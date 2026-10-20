@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title MAX Рассылки

echo.
echo ==========================================
echo       MAX Рассылки - запуск приложения
echo ==========================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare.ps1" -Start
if errorlevel 1 (
  echo.
  echo [ОШИБКА] Не удалось подготовить или запустить приложение.
  echo Подробности — в backend\logs, если backend успел запуститься.
  pause
  exit /b 1
)

echo.
echo Приложение запущено: http://127.0.0.1:8000
echo Для остановки используйте stop.bat.
echo.
pause
exit /b 0
