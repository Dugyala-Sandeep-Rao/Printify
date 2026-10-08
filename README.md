# Printify – Online Printing

Customers upload a document from their phone or laptop, choose print options,
pay, and the shop's printer prints it automatically. The shop owner watches
the queue on an admin page.

```
 Customer browser ──► FastAPI backend ──► SQLite (orders)
   (website/)          (backend/)             │
                                              ▼
                              Print agent (printer_agent/) ──► Windows printer
```

## Features

- **Upload** PDF, Word, PowerPoint, Excel, OpenDocument, TXT, JPG and PNG
  (click or drag and drop, up to 50 MB). Office files are converted to PDF with
  LibreOffice, and images are placed on a page of the chosen paper size.
- **Live print preview** of every page: B&W or colour, paper shape,
  double-sided sheets you can flip, a stack showing the copies, thumbnails and zoom.
- **3D animation** (Three.js, bundled in `website/vendor/`): "Printy", a toon-style
  printer in the hero that prints pages, follows the mouse, spins when dragged and
  prints a burst when tapped. 3D paper tumbles in the background, and the printer on
  the order-tracking card acts out each status. Falls back to CSS animation without
  WebGL or with reduced motion.
- **Exact page count and price**, calculated on the server. The browser cannot change the price.
- **Print options:** B&W or colour, 1–100 copies, A4/A3/Letter, single or double-sided.
  Options the shop printer can't do (for example A3 on the Epson L4360) are disabled automatically.
- **Payment step** (demo mode, see below) and **live order tracking**: queue
  position, printing, ready to collect. Tracking survives a page reload.
- **Print agent** prints paid orders in order through the Windows printer
  driver. It applies colour, paper, duplex and copies, and reports printer
  problems such as "out of paper" on the order.
- **Admin page** (`/admin.html`): printer status, queue, revenue, retry failed
  jobs, reprint, mark as done, cancel. For privacy the admin cannot open or
  download customers' documents.

## Setup (Windows)

1. Install [Python 3.10+](https://www.python.org/downloads/) and
   [LibreOffice](https://www.libreoffice.org/) (LibreOffice is only needed for Word/PowerPoint/Excel/TXT).
2. Double-click **`setup.bat`**, or run:

   ```
   python -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   ```

## Running

1. **`start_server.bat`** starts the website and API on port 8000.
   - On this PC: <http://127.0.0.1:8000>
   - Customers on the same Wi-Fi: `http://<this PC's IP>:8000` (allow Python
     through Windows Firewall when asked).
   - The **admin token** is printed in the server window and saved in
     `database/admin_token.txt`.
2. **`start_printer_agent.bat`** prints paid orders on the Windows default printer.

Check which printers can be used, or print a test page:

```
.venv\Scripts\python tools\check_printer.py
.venv\Scripts\python tools\check_printer.py --test-page "EPSON L4360 Series"
```

To try everything without using paper, print to files:

```
.venv\Scripts\python printer_agent\agent.py --printer "Microsoft Print to PDF" --output-dir prints
```

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `PRINTIFY_RAZORPAY_KEY_ID`, `PRINTIFY_RAZORPAY_KEY_SECRET` | read from `database/razorpay_key.csv` | Razorpay payment gateway (empty = off) |
| `PRINTIFY_UPI_ID`, `PRINTIFY_UPI_NAME` | empty, `Printify` | Shop UPI ID for real payments (empty = demo mode) |
| `PRINTIFY_PRINTER` | Windows default printer | Printer used by the agent and for the capability checks |
| `PRINTIFY_ADMIN_TOKEN` | generated, saved in `database/admin_token.txt` | Admin page password |
| `PRINTIFY_LIBREOFFICE` | auto-detected | Path to `soffice.exe` |
| `PRINTIFY_MAX_UPLOAD_MB` | `50` | Upload size limit |
| `PRINTIFY_KEEP_DAYS` | `7` | The agent deletes uploaded files after this many days unless an open order needs them (`0` = never) |
| `PRINTIFY_CORS_ORIGINS` | `*` | Allowed origins when the site is hosted elsewhere |
| `PRINTIFY_DB`, `PRINTIFY_UPLOAD_DIR` | `database/printify.db`, `uploads/` | Storage locations |

## Pricing

Defined in `backend/pricing.py`:

| | B&W | Colour |
|---|---|---|
| Single-sided (per page) | ₹2 | ₹5 |
| Double-sided (per sheet) | ₹3 | ₹8 |
| A3 extra (per sheet) | +₹2 | +₹2 |

## Payments (Razorpay)

With Razorpay keys set up, customers pay in a Razorpay Checkout popup with UPI,
cards, netbanking or wallets. The server creates the Razorpay order with the
price it calculated, checks Razorpay's payment signature, and only then puts
the order in the print queue. No manual confirmation is needed.

1. In the Razorpay dashboard go to **Settings → API Keys** and generate a key.
   It downloads as a CSV file (`key_id,key_secret`).
2. Save that file as **`database/razorpay_key.csv`** (it is in `.gitignore`), or set
   `PRINTIFY_RAZORPAY_KEY_ID` and `PRINTIFY_RAZORPAY_KEY_SECRET`.
3. Restart the server.

Keys starting with `rzp_test_` are **test mode**: nothing is charged. Pay with
UPI ID `success@razorpay` or card `4100 2800 0000 1007` (any future expiry, any
CVV). Switch to live keys (`rzp_live_`) once Razorpay has activated the account.
The shop name in the popup comes from `PRINTIFY_UPI_NAME`.

If the customer's browser closes after paying, clicking *Pay now* again finds
the payment on Razorpay and queues the order instead of charging twice.

Razorpay takes priority over the UPI and demo modes below.

## Payments (UPI)

Set the shop's UPI ID in `start_server.bat`:

```
set PRINTIFY_UPI_ID=yourshop@okaxis
set PRINTIFY_UPI_NAME=Your Shop Name
```

At checkout the customer then gets:

- **on a phone**: an *Open UPI app* button. It opens GPay, PhonePe, Paytm, BHIM
  or any other UPI app with your UPI ID, the amount and "Printify order N" already filled in;
- **on a laptop**: a QR code of the same payment to scan with their phone.

After paying, the customer types the 12-digit **UTR / UPI reference number**
from their receipt. The order shows as **Check payment** on the admin page (the
browser tab shows a counter too). Find that UTR and amount in your UPI app's
history, then click **Confirm payment**. The order joins the print queue.
**Reject** asks the customer to pay again. A UTR can't be used for two orders,
and nothing prints before you confirm.

UPI links can't report back automatically. Automatic confirmation needs a
payment gateway (Razorpay, Cashfree, PhonePe PG) and its webhook.

Some UPI apps limit link or QR payments to personal UPI IDs. A merchant/business
UPI ID (GPay for Business, PhonePe Business, Paytm for Business) works best.

With no UPI ID set, checkout runs in **demo mode**: "Pay now" marks the order
as paid without charging anything.

## Order statuses

`awaiting_payment` → (`verifying` while the shop checks a UPI payment) → `queued` → `printing` → `completed`.
Orders can also end as `failed` (the admin can retry) or `cancelled`.
If the agent is stopped mid-print, the order is marked `failed` on restart so
the staff can check the output before retrying.

## API

| Method | Path | |
|---|---|---|
| GET | `/api/config` | Prices, supported files, printer status |
| POST | `/api/upload` | Multipart `file` (+ `paper_size`); returns `upload_id`, `pages` |
| POST | `/api/quote` | `{pages, color, copies, paper, sides}` → price |
| POST | `/api/orders` | `{upload_id, color, copies, paper, sides}` → order + access `token` |
| POST | `/api/orders/{id}/razorpay` | `{token}` → Razorpay order for the checkout popup |
| POST | `/api/orders/{id}/razorpay/verify` | `{token, razorpay_order_id, razorpay_payment_id, razorpay_signature}` → status `queued` |
| POST | `/api/orders/{id}/pay` | Demo payment `{token, method}` (only without a UPI ID) |
| GET | `/api/orders/{id}/upi?token=` | UPI link, amount, payee |
| GET | `/api/orders/{id}/upi-qr.png?token=` | QR code of the UPI link |
| POST | `/api/orders/{id}/upi-paid` | `{token, utr}` → status `verifying` |
| GET | `/api/orders/{id}?token=` | Order status and queue position |
| POST | `/api/orders/{id}/cancel` | `{token}` |
| GET | `/api/admin/orders` | Header `X-Admin-Token`; optional `?status=` |
| POST | `/api/admin/orders/{id}/confirm-payment` · `/reject-payment` | Check UPI payments |
| POST | `/api/admin/orders/{id}/retry` · `/complete` · `/cancel` | Admin actions |

Interactive docs: <http://127.0.0.1:8000/docs>

## Tests

```
.venv\Scripts\python -m pytest
```

The tests use a temporary database. One test really prints to
"Microsoft Print to PDF" and checks the output file, and one converts a text
file with LibreOffice (skipped if LibreOffice isn't installed).

## Project layout

```
backend/
  main.py         API routes, serves the website
  config.py       settings
  database.py     SQLite schema and migrations
  documents.py    conversion to PDF, page counting
  pricing.py      prices
  razorpay_gateway.py  Razorpay orders and payment signatures
  printing.py     Windows printer status and printing
printer_agent/
  agent.py        prints queued orders
website/          customer site (index.html) and admin page (admin.html)
tests/            pytest suite
tools/            printer check; early printer experiments
```

## Privacy

**Printed documents are not kept.** As soon as an order has printed (or the
admin clicks *Mark done*), its file and page previews are deleted and its name
is replaced by "Deleted after printing". Only the order number, print options,
price and payment reference stay, for your accounts. Completed orders can't be
reprinted for the same reason: the customer uploads the file again. Failed
orders keep their file so they can be retried.


Uploaded files stay in `uploads/` on the shop PC. They often contain personal
documents such as résumés and ID cards. The print agent deletes them after
`PRINTIFY_KEEP_DAYS` days. Never commit `uploads/` or `database/` (both are in `.gitignore`).

## Complete end-to-end browser test (no printer or payment needed)

For a safe local test of the complete flow, run `start_test.bat` after `setup.bat`.
It starts two windows:

- FastAPI + customer website at http://127.0.0.1:8000/
- simulated print agent that never touches a physical printer

Test pages:

- Customer: http://127.0.0.1:8000/
- Admin: http://127.0.0.1:8000/admin.html
- API docs: http://127.0.0.1:8000/docs
- Admin token: `test-admin-token`
- Simulated print files: `test_prints/`

The test flow is: upload → preview → choose options → server quote → create order → demo payment → queued → simulated printing → completed.

The test mode uses a separate `database/test-printify.db` and `test_uploads/`, so it does not use the shop's real database or uploaded documents.
