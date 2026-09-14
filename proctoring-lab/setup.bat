@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3.12 --version >nul 2>nul
    if not errorlevel 1 (
        py -3.12 -m venv .venv
        if errorlevel 1 exit /b 1
        goto install
    )
)
where python >nul 2>nul
if errorlevel 1 (
    echo Python 3.12 was not found. Install it and add it to PATH.
    exit /b 1
)
python -c "import sys; sys.exit(sys.version_info[:2] != (3, 12))"
if errorlevel 1 (
    echo Python on PATH is not version 3.12.
    exit /b 1
)
python -m venv .venv
if errorlevel 1 exit /b 1
:install
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -r "backend\requirements.txt"
if errorlevel 1 exit /b 1
echo Setup complete. Run run.bat.
