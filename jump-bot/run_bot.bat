@echo off
cd /d %~dp0
echo === Mode-B bot: on-demand session (exits after market close) ===
venv\Scripts\python.exe modeb_bot.py
pause
