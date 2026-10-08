@echo off
rem Prints paid orders on the Windows default printer.
rem Use a specific printer with:  set PRINTIFY_PRINTER=EPSON L4360 Series
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" printer_agent\agent.py %*
pause
