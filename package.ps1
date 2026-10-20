[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$prepareScript = Join-Path $root 'prepare.ps1'
$outputDir = Join-Path $root 'releases'
$archive = Join-Path $outputDir 'MAX-Rassylki-portable.zip'
$stage = Join-Path ([System.IO.Path]::GetTempPath()) ('MAX-Rassylki-' + [guid]::NewGuid().ToString('N'))
$runtime = Join-Path $root '.runtime'

try {
    Write-Host 'Подготовка зависимостей и Chromium для установленного в Windows Python. Требуется Интернет.'
    & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $prepareScript -Package
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось подготовить runtime приложения.' }
    $env:PYTHONPATH = Join-Path $runtime 'packages'
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $runtime 'ms-playwright'

    if (-not (Test-Path -LiteralPath (Join-Path $runtime 'packages\fastapi')) -or
        -not (Get-ChildItem -LiteralPath (Join-Path $runtime 'ms-playwright') -Directory -Filter 'chromium-*' -ErrorAction SilentlyContinue | Select-Object -First 1)) {
        throw 'Runtime неполный: не найдены зависимости или Chromium.'
    }
    Set-Content -LiteralPath (Join-Path $runtime 'chromium-installed.txt') -Value 'installed' -Encoding ascii

    New-Item -ItemType Directory -Force -Path $stage, $outputDir | Out-Null
    Write-Host 'Копирование файлов приложения (без базы, профиля браузера и тестовых данных)...'
    $excludedDirectories = @(
        '.git', '.venv', 'venv', '__pycache__', '.pytest_cache', '.ruff_cache',
        '.mypy_cache', 'node_modules', '.max-browser-profile', 'logs', 'releases'
    )
    $excludedFiles = @('*.db', '*.db-*', '*.log', '*.xlsx', '.env')
    & robocopy.exe $root $stage /E /COPY:DAT /R:1 /W:1 /XD $excludedDirectories /XF $excludedFiles /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -ge 8) { throw "Не удалось скопировать файлы приложения (robocopy: $LASTEXITCODE)." }
    Copy-Item -LiteralPath (Join-Path $root 'package.bat') -Destination $stage

    Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
    Write-Host 'Создание ZIP-архива...'
    Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $archive -CompressionLevel Optimal
    $result = Get-Item -LiteralPath $archive
    Write-Host "Готово: $($result.FullName)"
    Write-Host ('Размер архива: {0:N0} МБ' -f ($result.Length / 1MB))
    Write-Host 'Архив включает зависимости и браузер. Для запуска на целевом ПК требуется установленный Python 3.10+ с py launcher или python в PATH.'
}
catch {
    Write-Error $_
    exit 1
}
finally {
    if (Test-Path -LiteralPath $stage) {
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    }
}
