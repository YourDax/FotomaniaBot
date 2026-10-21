@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
echo Остановка MAX Рассылок...

rem Каталог данных тот же, что в prepare.ps1; pid в .runtime — от старых версий.
set "DATA_DIR=%USERPROFILE%\.max-rassylki"
if defined LOCALAPPDATA set "DATA_DIR=%LOCALAPPDATA%\MAX-Rassylki"
if defined MAX_DATA_DIR set "DATA_DIR=%MAX_DATA_DIR%"

for %%F in ("!DATA_DIR!\backend.pid" ".runtime\backend.pid") do (
  if exist "%%~F" (
    set "BACKEND_PID="
    set /p BACKEND_PID=<"%%~F"
    if defined BACKEND_PID (
      powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$p=Get-CimInstance Win32_Process -Filter 'ProcessId=!BACKEND_PID!' -ErrorAction SilentlyContinue; if ($p -and $p.CommandLine -like '*uvicorn app.main:app*') { & taskkill.exe /PID !BACKEND_PID! /T /F | Out-Null }"
    )
    del "%%~F" >nul 2>&1
  )
)
echo Готово.
pause
