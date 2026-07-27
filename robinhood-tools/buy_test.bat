@echo off
REM ===========================================================
REM  Robinhood BUY TEST - buys 1 SPY $739 Call exp 2026-07-24
REM  Usage:  buy_test.bat            (limit = current ask)
REM          buy_test.bat --price 2.50
REM  WARNING: places a REAL order (queued while market closed).
REM ===========================================================
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Run balance_check.bat once first to set it up.
    pause
    exit /b 1
)

echo.
".venv\Scripts\python.exe" buy_test.py %*
echo.
pause
