@echo off
chcp 65001 > nul
cd /d "%~dp0"
set PYTHONPATH=%~dp0

echo ==================================================
echo   AI Stock Portfolio - Server Starting...
echo   Dashboard : http://localhost:8000/
echo   Browser will open automatically in 12 seconds.
echo   Press Ctrl+C to stop the server.
echo ==================================================
echo.

REM Clear any existing Python process occupying port 8000
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do taskkill /f /pid %%a >nul 2>&1

REM Open browser after 12 second delay (server needs time to fully initialize)
start /min "" cmd /c "timeout /t 12 /nobreak > nul && start http://localhost:8000/"

REM Run server in foreground (with hot-reload)
"C:\Users\SKB.0439\AppData\Local\Programs\Python\Python311\python.exe" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

pause
