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
        # Prefer widely supported versions. Probe each installed version without
        # letting PowerShell turn the launcher's "not installed" message into a stop.
        foreach ($version in @('3.13', '3.12', '3.11', '3.10', '3.14', '3.15')) {
            $candidates += [pscustomobject]@{ FilePath = $launcher.Source; Prefix = @('-' + $version) }
        }
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
        $versionArguments = @($candidate.Prefix) + @('-c', 'import sys; print(sys.version_info[0]); print(sys.version_info[1]); print(sys.executable)')
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $runtimeInfo = @(& $candidate.FilePath @versionArguments 2>$null)
        $runtimeExitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousErrorActionPreference
        if ($runtimeExitCode -ne 0 -or $runtimeInfo.Count -lt 3) { continue }

        $major = [int]$runtimeInfo[0]
        $minor = [int]$runtimeInfo[1]
        if ($major -ne 3 -or $minor -lt 10) { continue }

        $script:Python = [string]$runtimeInfo[2]
        $script:PythonPrefix = @()
        $script:PythonVersion = "$major.$minor"
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
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    Invoke-Python -Arguments @('-c', 'import fastapi, openpyxl, playwright, sqlalchemy, uvicorn; from pydantic import BaseModel; from pydantic_settings import BaseSettings') *> $null
    $dependencyExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    return $dependencyExitCode -eq 0
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
    $backendStdout = Join-Path $script:RuntimeDir 'backend.stdout.log'
    $backendStderr = Join-Path $script:RuntimeDir 'backend.stderr.log'
    $process = Start-Process -FilePath $script:Python `
        -ArgumentList $startArguments `
        -WorkingDirectory (Join-Path $script:Root 'backend') `
        -RedirectStandardOutput $backendStdout `
        -RedirectStandardError $backendStderr `
        -PassThru

    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        Start-Sleep -Seconds 1
        if ($process.HasExited) {
            $errorDetails = if (Test-Path -LiteralPath $backendStderr) {
                (Get-Content -LiteralPath $backendStderr -Tail 30 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
            } else { '' }
            throw "Backend завершился во время запуска (код $($process.ExitCode)). Вывод backend: $backendStderr`n$errorDetails"
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

