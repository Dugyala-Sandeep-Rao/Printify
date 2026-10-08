@echo off
setlocal
cd /d "%~dp0"
set PRINTIFY_ADMIN_TOKEN=test-admin-token
set PRINTIFY_DB=%~dp0database\test-printify.db
set PRINTIFY_UPLOAD_DIR=%~dp0test_uploads
set PRINTIFY_KEEP_DAYS=0
if not exist test_prints mkdir test_prints
"%~dp0.venv\Scripts\python.exe" printer_agent\agent.py --simulate --output-dir "%~dp0test_prints"
endlocal
