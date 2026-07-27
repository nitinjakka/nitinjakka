@echo off
REM ===========================================================
REM  Robinhood balance checker - one-click runner (Windows)
REM  Usage:  balance_check.bat   (no arguments)
REM  First run: creates a .venv here and installs dependencies.
REM  Later runs: just runs the script.
REM ===========================================================
cd /d "%~dp0"

REM --- make sure Python is available ---
where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] Python was not found on your PATH.
    echo Install Python 3 from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during setup, then try again.
    echo.
    pause
    exit /b 1
)

REM --- create the virtual environment on first run ---
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment in "%cd%\.venv" ...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create the virtual environment.
        pause
        exit /b 1
    )
    echo Installing dependencies ^(this only happens once^) ...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency install failed. Check your internet connection.
        pause
        exit /b 1
    )
)

REM --- warn if credentials still look like placeholders ---
findstr /C:"your_robinhood_email@example.com" .env >nul 2>&1
if not errorlevel 1 (
    echo.
    echo [!] It looks like you haven't filled in .env yet.
    echo     Open .env in Notepad and set RH_USERNAME and RH_PASSWORD.
    echo.
    pause
    exit /b 1
)

echo.
".venv\Scripts\python.exe" robinhood_balance.py
echo.
pause
