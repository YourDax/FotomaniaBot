@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title MAX Рассылки — подготовка архива

echo.
echo ==========================================
echo    Подготовка переносимого ZIP-архива
echo ==========================================
echo.
echo Будут подготовлены зависимости приложения и браузер Chromium.
echo Требуется обычный установленный Python 3.10+ с pip и py launcher либо python в PATH.
echo Python не скачивается и не устанавливается.
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0package.ps1"
if errorlevel 1 (
  echo.
  echo [ОШИБКА] Архив не создан. Проверьте Интернет и свободное место.
  pause
  exit /b 1
)
echo.
echo Скопируйте ZIP из папки releases на другой ПК и распакуйте.
echo Запуск: двойной щелчок по run.bat.
echo.
pause
