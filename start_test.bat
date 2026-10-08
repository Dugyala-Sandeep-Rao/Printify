@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Please run setup.bat first.
  pause
  exit /b 1
)
if not exist test_uploads mkdir test_uploads
if not exist test_prints mkdir test_prints
start "Printify Server" cmd /k "%~dp0start_test_server.bat"
timeout /t 3 /nobreak >nul
start "Printify Test Printer" cmd /k "%~dp0start_test_agent.bat"
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8000/
echo.
echo ================================================
echo Printify end-to-end TEST MODE is starting
echo ================================================
echo Website: http://127.0.0.1:8000/
echo Admin:   http://127.0.0.1:8000/admin.html
echo API:     http://127.0.0.1:8000/docs
echo Token:   test-admin-token
echo Output:  %~dp0test_prints
echo.
echo No real payment and no physical printer are used.
echo Keep the two server windows open while testing.
pause
endlocal
