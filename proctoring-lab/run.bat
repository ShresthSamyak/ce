@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Local environment missing. Run setup.bat first.
    exit /b 1
)
echo Open http://127.0.0.1:8000 in this computer's browser.
".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
