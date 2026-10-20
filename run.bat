@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "ROOT=%~dp0"
cd /d "%ROOT%"
title MAX Рассылки

echo.
echo ==========================================
echo       MAX Рассылки - запуск приложения
echo ==========================================
echo.

set "PYTHON_EXE="
for /f "delims=" %%P in ('py -3.12 -c "import sys; print(sys.executable)" 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
if not defined PYTHON_EXE for /f "delims=" %%P in ('py -3.13 -c "import sys; print(sys.executable)" 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
if not defined PYTHON_EXE for /f "delims=" %%P in ('py -3.14 -c "import sys; print(sys.executable)" 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
if not defined PYTHON_EXE for /f "delims=" %%P in ('py -3.11 -c "import sys; print(sys.executable)" 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
if not defined PYTHON_EXE for /f "delims=" %%P in ('py -3.10 -c "import sys; print(sys.executable)" 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
if not defined PYTHON_EXE for /f "delims=" %%P in ('python -c "import sys; print(sys.executable if sys.version_info >= (3,10) else '')" 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
if not defined PYTHON_EXE for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable if sys.version_info >= (3,10) else '')" 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
if not defined PYTHON_EXE (
  echo [ОШИБКА] Python 3.10 или новее не найден.
  echo Установите Python с https://www.python.org/downloads/
  echo При установке включите опцию "Add Python to PATH".
  pause
  exit /b 1
)
echo Найден Python: %PYTHON_EXE%
for /f "delims=" %%V in ('"%PYTHON_EXE%" -c "import sys; print(str(sys.version_info[0])+'.'+str(sys.version_info[1]))"') do set "PYTHON_VERSION=%%V"
echo Версия Python: %PYTHON_VERSION%

if exist ".venv\Scripts\python.exe" (
  for /f "delims=" %%V in ('.venv\Scripts\python.exe -c "import sys; print(str(sys.version_info[0])+'.'+str(sys.version_info[1]))"') do set "VENV_VERSION=%%V"
  if not "%VENV_VERSION%"=="%PYTHON_VERSION%" (
    echo Виртуальное окружение создано для Python %VENV_VERSION%, требуется %PYTHON_VERSION%. Пересоздаю...
    rmdir /s /q ".venv"
  )
)
if not exist ".venv\Scripts\python.exe" (
  echo [1/2] Создание виртуального окружения...
  "%PYTHON_EXE%" -m venv ".venv"
  if errorlevel 1 (
    echo [ОШИБКА] Не удалось создать виртуальное окружение.
    pause
    exit /b 1
  )
)

echo [2/2] Проверка Python-зависимостей...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --prefer-binary -r backend\requirements.txt
if errorlevel 1 (
  echo [ОШИБКА] Не удалось установить Python-зависимости.
  pause
  exit /b 1
)

echo Проверка браузера Playwright Chromium...
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 (
  echo [ОШИБКА] Не удалось установить браузер Chromium для Playwright.
  echo Проверьте подключение к интернету и повторите запуск.
  pause
  exit /b 1
)

echo Запуск локального приложения...
start "MAX backend" /min /D "%ROOT%backend" "%ROOT%.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
echo Ожидание запуска локального сайта...
set "READY="
for /l %%I in (1,1,30) do (
  if not defined READY (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } } catch {} ; exit 1" >nul 2>&1
    if not errorlevel 1 set "READY=1"
    if not defined READY timeout /t 1 /nobreak >nul
  )
)
if not defined READY (
  echo [ОШИБКА] Backend не запустился за 30 секунд.
  echo Проверьте окно "MAX backend" и файл backend\logs\session.log.
  pause
  exit /b 1
)
start "" "http://127.0.0.1:8000"
echo.
echo Приложение запущено: http://127.0.0.1:8000
echo Node.js/npm не требуются.
echo Для остановки закройте окно MAX backend.
echo.
pause
