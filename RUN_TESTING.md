# Printify: complete local testing

## Fastest Windows test

1. Install Python 3.10+ and LibreOffice.
2. Run `setup.bat` once.
3. Run `start_test.bat`.
4. Open:
   - Customer website: http://127.0.0.1:8000/
   - Admin dashboard: http://127.0.0.1:8000/admin.html
   - API docs: http://127.0.0.1:8000/docs
5. Admin test token: `test-admin-token`

Test mode uses demo payment and a simulated printer. It never sends a job to a physical printer. When an order reaches `queued`, the test printer agent copies its prepared PDF into `test_prints/` and marks the order completed.

## Normal Windows shop mode

Use `start_server.bat` for the website/API and `start_printer_agent.bat` for the real Windows printer. Set `PRINTIFY_PRINTER` if you want a specific printer.

For real payments, configure Razorpay or UPI through environment variables. Do not put real secrets in source control or ZIP archives.
