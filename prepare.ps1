[CmdletBinding()]
param(
    [switch]$Start,
    [switch]$Package
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$script:Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$script:RuntimeDir = Join-Path $script:Root '.runtime'
$script:Python = $null
$script:PythonPrefix = @()
$script:PythonVersion = $null
$script:Packages = Join-Path $script:RuntimeDir 'packages'
$script:BrowserPath = Join-Path $script:RuntimeDir 'ms-playwright'
$script:Requirements = Join-Path $script:Root 'backend\requirements.txt'
$script:BrowserStamp = Join-Path $script:RuntimeDir 'chromium-installed.txt'

$env:PYTHONPATH = $script:Packages
$env:PLAYWRIGHT_BROWSERS_PATH = $script:BrowserPath
$script:PackageMode = $Package

function Resolve-Python {
    $candidates = @()
    $launcher = Get-Command 'py.exe' -ErrorAction SilentlyContinue
    if ($launcher) {
        # Let the Python launcher select the installed default instead of requiring
        # a particular minor release (which may not exist on the target PC).
        $candidates += [pscustomobject]@{ FilePath = $launcher.Source; Prefix = @('-3') }
    }

    $pythonCommand = Get-Command 'python.exe' -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $candidates += [pscustomobject]@{ FilePath = $pythonCommand.Source; Prefix = @() }
    }
    if (-not $pythonCommand) {
        $pythonCommand = Get-Command 'python' -ErrorAction SilentlyContinue
        if ($pythonCommand) {
            $candidates += [pscustomobject]@{ FilePath = $pythonCommand.Source; Prefix = @() }
        }
    }

    # The newer Python install manager uses `py` rather than `py.exe` on PATH.
    if (-not $launcher) {
        $launcher = Get-Command 'py' -ErrorAction SilentlyContinue
        if ($launcher) {
            $candidates += [pscustomobject]@{ FilePath = $launcher.Source; Prefix = @('-3') }
        }
    }

    foreach ($candidate in $candidates) {
        $versionArguments = @($candidate.Prefix) + @('-c', 'import sys; print(str(sys.version_info[0]) + chr(46) + str(sys.version_info[1]))')
        $versionOutput = & $candidate.FilePath @versionArguments 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $versionOutput) { continue }

        $versionParts = ([string]$versionOutput | Select-Object -Last 1) -split '\.'
        if ($versionParts.Count -ne 2 -or [int]$versionParts[0] -ne 3 -or [int]$versionParts[1] -lt 10) { continue }

        $script:Python = $candidate.FilePath
        $script:PythonPrefix = @($candidate.Prefix)
        $script:PythonVersion = [string]$versionOutput
        Write-Host "Используется установленный Python $($script:PythonVersion): $($script:Python)"
        return
    }

    throw 'Не найден установленный Python 3.10 или новее. Установите Python обычным способом и убедитесь, что доступен py launcher либо python в PATH.'
}

function Invoke-Python {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $invokeArguments = @($script:PythonPrefix) + $Arguments
    & $script:Python @invokeArguments | Out-Host
    return $LASTEXITCODE
}

function Test-Dependencies {
    if (-not (Test-Path -LiteralPath $script:Packages)) { return $false }
    Invoke-Python -Arguments @('-c', 'import fastapi, openpyxl, playwright, sqlalchemy, uvicorn') *> $null
    return $LASTEXITCODE -eq 0
}

function Initialize-Runtime {
    Resolve-Python
    New-Item -ItemType Directory -Force -Path $script:RuntimeDir | Out-Null

    Invoke-Python -Arguments @('-m', 'pip', '--version') *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "В установленном Python $($script:PythonVersion) отсутствует pip. Установите/включите pip для этого Python обычным способом."
    }

    if (-not (Test-Dependencies)) {
        if (Test-Path -LiteralPath $script:Packages) {
            Remove-Item -LiteralPath $script:Packages -Recurse -Force
        }
        New-Item -ItemType Directory -Force -Path $script:Packages | Out-Null
        Write-Host 'Установка зависимостей приложения...'
        Invoke-Python -Arguments @('-m', 'pip', 'install', '--disable-pip-version-check', '--prefer-binary', '--target', $script:Packages, '-r', $script:Requirements) | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить зависимости. Проверьте Интернет и повторите запуск.' }
    }

    $browser = Get-ChildItem -LiteralPath $script:BrowserPath -Directory -Filter 'chromium-*' -ErrorAction SilentlyContinue | Select-Object -First 1
    $chromiumInstalled = -not $script:PackageMode -and
        (Test-Path -LiteralPath $script:BrowserStamp) -and [bool]$browser
    if (-not $chromiumInstalled) {
        Write-Host 'Установка браузера Chromium для работы с MAX...'
        Invoke-Python -Arguments @('-m', 'playwright', 'install', 'chromium') | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Не удалось загрузить Chromium. Проверьте Интернет и повторите запуск.' }
        if (-not $script:PackageMode) {
            Set-Content -LiteralPath $script:BrowserStamp -Value 'installed' -Encoding ascii
        }
    }
}

function Start-Application {
    $healthUrl = 'http://127.0.0.1:8000/api/health'
    $appUrl = 'http://127.0.0.1:8000/'
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            Write-Host 'Приложение уже запущено: http://127.0.0.1:8000'
            Start-Process $appUrl
            return
        }
    }
    catch {
        # No server is running on the application port yet.
    }

    Write-Host 'Запуск локального приложения...'
    $startArguments = @($script:PythonPrefix) + @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000')
    $process = Start-Process -FilePath $script:Python `
        -ArgumentList $startArguments `
        -WorkingDirectory (Join-Path $script:Root 'backend') `
        -PassThru

    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        Start-Sleep -Seconds 1
        if ($process.HasExited) {
            throw "Backend завершился во время запуска (код $($process.ExitCode)). См. backend\logs\session.log."
        }
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                Set-Content -LiteralPath (Join-Path $script:Root '.runtime\backend.pid') `
                    -Value $process.Id -Encoding ascii
                Start-Process $appUrl
                return
            }
        }
        catch {
            # The server is still starting.
        }
    }

    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    throw 'Backend не ответил за 45 секунд. Проверьте backend\logs\session.log.'
}

try {
    Initialize-Runtime
    if ($Start) { Start-Application }
    exit 0
}
catch {
    Write-Error $_
    exit 1
}

