@echo off
rem One-time setup: creates the virtual environment and installs packages.
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv || goto :error
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
".venv\Scripts\python.exe" backend\database.py || goto :error
echo.
echo Setup complete. Run start_server.bat and start_printer_agent.bat.
pause
exit /b 0

:error
echo Setup failed.
pause
exit /b 1
