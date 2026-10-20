@echo off
chcp 65001 >nul
echo Остановка MAX Рассылок...
for /f "tokens=2" %%P in ('tasklist /v /fo csv ^| findstr /i "\"MAX backend\""') do taskkill /PID %%~P /T /F >nul 2>&1
echo Готово.
pause
