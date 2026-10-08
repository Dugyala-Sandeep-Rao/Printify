@echo off
setlocal
cd /d "%~dp0"
set PRINTIFY_ADMIN_TOKEN=test-admin-token
set PRINTIFY_DB=%~dp0database\test-printify.db
set PRINTIFY_UPLOAD_DIR=%~dp0test_uploads
set PRINTIFY_KEEP_DAYS=0
set PRINTIFY_UPI_ID=
set PRINTIFY_UPI_NAME=Printify Test Shop
set PRINTIFY_RAZORPAY_KEY_ID=
set PRINTIFY_RAZORPAY_KEY_SECRET=
if not exist test_uploads mkdir test_uploads
if not exist test_prints mkdir test_prints
cd /d "%~dp0backend"
"%~dp0.venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000
endlocal
