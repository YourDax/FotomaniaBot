@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title MAX Rassylki

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare.ps1" -Start
if errorlevel 1 (
  echo.
  echo [ERROR] Could not prepare or start the application.
  echo Check backend\logs for details if the backend started.
  pause
  exit /b 1
)

echo.
echo Application is running: http://127.0.0.1:8000
echo Use stop.bat to stop it.
echo.
pause
exit /b 0
