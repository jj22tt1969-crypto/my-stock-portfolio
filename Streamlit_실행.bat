@echo off
chcp 65001 > nul
cd /d "%~dp0"
set PYTHONPATH=%~dp0

echo ==================================================
echo   AI Stock Portfolio - Streamlit Server Starting...
echo   Dashboard : http://localhost:8501/
echo   Press Ctrl+C to stop the server.
echo ==================================================
echo.

"C:\Users\SKB.0439\AppData\Local\Programs\Python\Python311\python.exe" -m streamlit run streamlit_app.py --server.port 8501

pause
