@echo off
rem Starts the Printify website and API on port 8000.
rem Customers on the same Wi-Fi can open http://<this-PC's-IP>:8000

rem ---- UPI payments -------------------------------------------------
rem Put the shop's UPI ID here to take real UPI payments.
rem Leave it empty to use demo payments (nothing is charged).
if not defined PRINTIFY_UPI_ID set PRINTIFY_UPI_ID=
if not defined PRINTIFY_UPI_NAME set PRINTIFY_UPI_NAME=Printify
rem ------------------------------------------------------------------

cd /d "%~dp0backend"
"%~dp0.venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000
pause
