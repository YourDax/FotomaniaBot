@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
echo Остановка MAX Рассылок...
if exist ".runtime\backend.pid" (
  set /p BACKEND_PID=<".runtime\backend.pid"
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$p=Get-CimInstance Win32_Process -Filter 'ProcessId=!BACKEND_PID!' -ErrorAction SilentlyContinue; if ($p -and $p.CommandLine -like '*uvicorn app.main:app*') { & taskkill.exe /PID !BACKEND_PID! /T /F | Out-Null }"
  del ".runtime\backend.pid" >nul 2>&1
)
echo Готово.
pause
