[CmdletBinding()]
param(
    [switch]$Start,
    [switch]$Package
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$script:Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$script:Python = $null
$script:PythonPrefix = @()
$script:PythonVersion = $null
$script:Requirements = Join-Path $script:Root 'backend\requirements.txt'
$script:PackageMode = $Package

# Каталог данных (база, журналы, профиль MAX) и общий кэш зависимостей лежат вне папки
# приложения, поэтому новая версия, распакованная в другую папку, их не пересоздаёт.
if ($env:MAX_DATA_DIR) { $script:DataDir = $env:MAX_DATA_DIR }
elseif ($env:LOCALAPPDATA) { $script:DataDir = Join-Path $env:LOCALAPPDATA 'MAX-Rassylki' }
else { $script:DataDir = Join-Path $env:USERPROFILE '.max-rassylki' }
$env:MAX_DATA_DIR = $script:DataDir
$script:PidFile = Join-Path $script:DataDir 'backend.pid'

# Заполняются в Initialize-Runtime после выбора Python.
$script:RuntimeDir = $null
$script:Packages = $null
$script:BrowserPath = $null
$script:DependencyStamp = $null

function Resolve-Python {
    $candidates = @()
    $launcher = Get-Command 'py.exe' -ErrorAction SilentlyContinue
    if ($launcher) {
        # Pinned backend dependencies (SQLAlchemy 2.0.36, pydantic-core) support Python 3.10-3.13.
        foreach ($version in @('3.13', '3.12', '3.11', '3.10')) {
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
        # Путь к интерпретатору кодируется в ASCII (unicode_escape), иначе кириллица в пути
        # (например, имя пользователя) искажается из-за кодировки консоли Windows (OEM 866).
        $versionArguments = @($candidate.Prefix) + @('-c', 'import sys; print(''PYINFO'', sys.version_info[0], sys.version_info[1], sys.executable.encode(''unicode_escape'').decode(''ascii''))')
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $runtimeOutput = @(& $candidate.FilePath @versionArguments 2>$null)
        $runtimeExitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousErrorActionPreference
        if ($runtimeExitCode -ne 0) { continue }

        # py.exe может печатать служебный вывод (например, "Downloading: ...") в stdout,
        # поэтому читаем только строку с маркером и не приводим произвольный текст к числу.
        $infoMatch = $null
        foreach ($outputLine in $runtimeOutput) {
            $match = [regex]::Match([string]$outputLine, 'PYINFO (\d+) (\d+) (.+?)\s*$')
            if ($match.Success) { $infoMatch = $match }
        }
        if (-not $infoMatch) { continue }

        $major = [int]$infoMatch.Groups[1].Value
        $minor = [int]$infoMatch.Groups[2].Value
        if ($major -ne 3 -or $minor -lt 10 -or $minor -gt 13) { continue }

        $script:Python = [regex]::Unescape($infoMatch.Groups[3].Value)
        if (-not (Test-Path -LiteralPath $script:Python -PathType Leaf)) { continue }
        $script:PythonPrefix = @()
        $script:PythonVersion = "$major.$minor"
        Write-Host "Используется установленный Python $($script:PythonVersion): $($script:Python)"
        return
    }

    throw 'Не найден подходящий Python 3.10-3.13. Установите Python 3.13 обычным способом (с py launcher) и повторите запуск. Python 3.14+ пока не поддерживается зависимостями проекта.'
}

function Invoke-Python {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $invokeArguments = @($script:PythonPrefix) + $Arguments
    & $script:Python @invokeArguments | Out-Host
    return $LASTEXITCODE
}

function Get-RequirementsHash {
    # Перенос строк не должен менять хэш: GitHub-архив и клон дают разные окончания строк.
    $text = (Get-Content -LiteralPath $script:Requirements -Raw) -replace "`r`n", "`n"
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($text))
    }
    finally {
        $sha.Dispose()
    }
    return (($bytes | ForEach-Object { $_.ToString('x2') }) -join '').Substring(0, 12)
}

function Get-PlaywrightVersion {
    $match = [regex]::Match((Get-Content -LiteralPath $script:Requirements -Raw), '(?im)^\s*playwright==([\w.]+)')
    if ($match.Success) { return $match.Groups[1].Value }
    return 'unknown'
}

function Initialize-RuntimePaths {
    $localRuntime = Join-Path $script:Root '.runtime'
    $hash = Get-RequirementsHash
    # Переносимый архив (package.bat) и старые установки держат runtime рядом с приложением;
    # во всех остальных случаях зависимости общие для всех версий с тем же requirements.txt.
    if ($script:PackageMode -or (Test-Path -LiteralPath (Join-Path $localRuntime 'packages'))) {
        $script:RuntimeDir = $localRuntime
        $script:BrowserPath = Join-Path $localRuntime 'ms-playwright'
    }
    else {
        $script:RuntimeDir = Join-Path $script:DataDir "runtime\py$($script:PythonVersion)-$hash"
        $script:BrowserPath = Join-Path $script:DataDir 'ms-playwright'
    }
    $script:Packages = Join-Path $script:RuntimeDir 'packages'
    $script:DependencyStamp = Join-Path $script:RuntimeDir 'packages-stamp.txt'
    $script:StampValue = "$($script:PythonVersion)|$hash"
    New-Item -ItemType Directory -Force -Path $script:DataDir, $script:RuntimeDir | Out-Null
    $env:PYTHONPATH = $script:Packages
    $env:PLAYWRIGHT_BROWSERS_PATH = $script:BrowserPath
}

function Test-Dependencies {
    if (-not (Test-Path -LiteralPath $script:Packages)) { return $false }
    if (-not (Test-Path -LiteralPath $script:DependencyStamp)) { return $false }
    if ((Get-Content -LiteralPath $script:DependencyStamp -Raw).Trim() -ne $script:StampValue) { return $false }
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    Invoke-Python -Arguments @('-c', 'import fastapi, openpyxl, playwright, sqlalchemy, uvicorn; from pydantic import BaseModel') *> $null
    $dependencyExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    return $dependencyExitCode -eq 0
}

function Remove-StaleRuntimes {
    # Оставляем две последние версии зависимостей (текущую и предыдущую для отката).
    $root = Join-Path $script:DataDir 'runtime'
    if ($script:RuntimeDir -notlike "$root*") { return }
    (Get-Item -LiteralPath $script:RuntimeDir).LastWriteTime = Get-Date
    $stale = Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -Skip 2
    foreach ($directory in $stale) {
        try { Remove-Item -LiteralPath $directory.FullName -Recurse -Force -ErrorAction Stop }
        catch { }  # папку может держать запущенная старая версия — удалим при следующем запуске
    }
}

function Initialize-Runtime {
    Resolve-Python
    Initialize-RuntimePaths

    if (Test-Dependencies) {
        Write-Host 'Зависимости приложения уже установлены.'
    }
    else {
        Invoke-Python -Arguments @('-m', 'pip', '--version') *> $null
        if ($LASTEXITCODE -ne 0) {
            throw "В установленном Python $($script:PythonVersion) отсутствует pip. Установите/включите pip для этого Python обычным способом."
        }
        if (Test-Path -LiteralPath $script:Packages) {
            Remove-Item -LiteralPath $script:Packages -Recurse -Force
        }
        Remove-Item -LiteralPath $script:DependencyStamp -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Force -Path $script:Packages | Out-Null
        Write-Host 'Установка зависимостей приложения (один раз для этой версии requirements.txt)...'
        Invoke-Python -Arguments @('-m', 'pip', 'install', '--disable-pip-version-check', '--prefer-binary', '--target', $script:Packages, '-r', $script:Requirements) | Out-Null
        if ($LASTEXITCODE -ne 0) {
            # Недоустановленный каталог не должен считаться готовым при следующем запуске.
            Remove-Item -LiteralPath $script:Packages -Recurse -Force -ErrorAction SilentlyContinue
            throw 'Не удалось установить зависимости. Проверьте Интернет и повторите запуск.'
        }
        Set-Content -LiteralPath $script:DependencyStamp -Value $script:StampValue -Encoding ascii
    }

    # Отметка ставится после успешной установки; при смене версии Playwright браузер докачивается.
    $browserStamp = Join-Path $script:BrowserPath ("chromium-$(Get-PlaywrightVersion).stamp")
    $browser = Get-ChildItem -LiteralPath $script:BrowserPath -Directory -Filter 'chromium-*' -ErrorAction SilentlyContinue | Select-Object -First 1
    $chromiumInstalled = -not $script:PackageMode -and (Test-Path -LiteralPath $browserStamp) -and [bool]$browser
    if ($chromiumInstalled) {
        Write-Host 'Браузер Chromium уже установлен.'
    }
    else {
        Write-Host 'Установка браузера Chromium для работы с MAX...'
        Invoke-Python -Arguments @('-m', 'playwright', 'install', 'chromium') | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Не удалось загрузить Chromium. Проверьте Интернет и повторите запуск.' }
        if (-not $script:PackageMode) {
            Set-Content -LiteralPath $browserStamp -Value 'installed' -Encoding ascii
        }
    }
    Remove-StaleRuntimes
}

function Get-Health {
    try {
        return Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 2
    }
    catch {
        return $null
    }
}

function Test-SameRoot {
    param([string]$Other)
    if (-not $Other) { return $false }
    $mine = [System.IO.Path]::GetFullPath($script:Root).TrimEnd('\')
    $theirs = [System.IO.Path]::GetFullPath($Other).TrimEnd('\')
    return $mine -ieq $theirs
}

function Stop-OtherBackend {
    # Порт 8000 занят копией приложения из другой папки (старая версия): останавливаем её,
    # иначе run.bat открыл бы старый интерфейс, а новая версия не запустилась.
    $backendPid = $null
    if (Test-Path -LiteralPath $script:PidFile) {
        $backendPid = (Get-Content -LiteralPath $script:PidFile -Raw).Trim()
    }
    $process = $null
    if ($backendPid -match '^\d+$') {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$backendPid" -ErrorAction SilentlyContinue
    }
    if (-not $process -or $process.CommandLine -notlike '*uvicorn app.main:app*') {
        throw 'На порту 8000 уже работает другая копия приложения. Остановите её (stop.bat в её папке или закройте окно backend) и повторите запуск.'
    }
    Write-Host 'Останавливаю запущенную копию приложения из другой папки...'
    & taskkill.exe /PID $backendPid /T /F | Out-Null
    Remove-Item -LiteralPath $script:PidFile -Force -ErrorAction SilentlyContinue
    for ($attempt = 0; $attempt -lt 10; $attempt++) {
        if (-not (Get-Health)) { return }
        Start-Sleep -Seconds 1
    }
    throw 'Не удалось остановить предыдущую копию приложения на порту 8000.'
}

function Start-Application {
    $appUrl = 'http://127.0.0.1:8000/'
    $health = Get-Health
    if ($health) {
        $runningRoot = ''
        if ($health.PSObject.Properties['root']) { $runningRoot = [string]$health.root }
        if (Test-SameRoot $runningRoot) {
            Write-Host 'Приложение уже запущено: http://127.0.0.1:8000'
            Start-Process $appUrl
            return
        }
        Stop-OtherBackend
    }

    Write-Host 'Запуск локального приложения...'
    $startArguments = @($script:PythonPrefix) + @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000')
    # Backend запускается в собственном окне консоли, чтобы сообщения о работе
    # (запуск, запросы, ошибки) были видны оператору; полный журнал также пишется
    # в session.log каталога данных. При аварийном завершении окно остаётся открытым.
    $quotedPython = '"' + $script:Python + '"'
    $commandLine = '/d /s /c "title MAX Rassylki - backend && ' + $quotedPython +
        ' ' + ($startArguments -join ' ') + ' || pause"'
    $process = Start-Process -FilePath 'cmd.exe' `
        -ArgumentList $commandLine `
        -WorkingDirectory (Join-Path $script:Root 'backend') `
        -PassThru

    $logHint = Join-Path $script:DataDir 'logs\session.log'
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        Start-Sleep -Seconds 1
        if ($process.HasExited) {
            throw "Backend завершился во время запуска (код $($process.ExitCode)). Подробности в окне backend и в $logHint."
        }
        if (Get-Health) {
            Set-Content -LiteralPath $script:PidFile -Value $process.Id -Encoding ascii
            Start-Process $appUrl
            return
        }
    }

    & taskkill.exe /PID $process.Id /T /F | Out-Null
    throw "Backend не ответил за 45 секунд. Смотрите сообщения в окне backend и в $logHint."
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
