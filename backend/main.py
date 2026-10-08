import io
import re
import secrets
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import quote as url_quote

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import config
import documents
import pricing
import printing
import razorpay_gateway
from database import connect, forget_document, init_db, set_order_status


ADMIN_TOKEN = config.get_admin_token()

# Statuses the customer or admin may still cancel from
CANCELLABLE = ("awaiting_payment", "verifying", "queued", "failed")

# UPI transaction reference (UTR): 12 digits
UTR_PATTERN = re.compile(r"^\d{12}$")


def upi_enabled():
    return bool(config.UPI_ID)


def payment_mode():
    if razorpay_gateway.enabled():
        return "razorpay"
    return "upi" if upi_enabled() else "demo"


@asynccontextmanager
async def lifespan(app):
    config.UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    init_db()
    print(f"Printify admin token: {ADMIN_TOKEN}")
    yield


app = FastAPI(title="Printify", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================
# MODELS
# ==========================================

Color = Literal["bw", "color"]
Paper = Literal["a4", "a3", "letter"]
Sides = Literal["single", "double"]


class PrintOptions(BaseModel):
    color: Color = "bw"
    copies: int = Field(1, ge=1, le=config.MAX_COPIES)
    paper: Paper = "a4"
    sides: Sides = "single"


class QuoteRequest(PrintOptions):
    pages: int = Field(..., ge=1)


class OrderRequest(PrintOptions):
    upload_id: str


class PaymentRequest(BaseModel):
    token: str
    method: Literal["upi", "card"]


class TokenRequest(BaseModel):
    token: str


class UpiPaidRequest(BaseModel):
    token: str
    utr: str


class RazorpayVerifyRequest(BaseModel):
    token: str
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


# ==========================================
# HELPERS
# ==========================================

def require_admin(x_admin_token: str = Header("")):
    if not secrets.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise HTTPException(401, "Invalid admin token")


def check_printer_supports(options):
    """Reject options the shop printer cannot do."""

    info = printing.printer_info(config.PRINTER_NAME or None)
    if not info["available"]:
        return

    if options.paper not in info["papers"]:
        raise HTTPException(400, f"The printer does not support {options.paper.upper()} paper.")
    if options.sides == "double" and not info["duplex"]:
        raise HTTPException(400, "The printer cannot print double-sided.")
    if options.color == "color" and not info["color"]:
        raise HTTPException(400, "The printer cannot print in colour.")


def get_order_row(connection, order_id):
    order = connection.execute(
        "SELECT * FROM orders WHERE id = ?", (order_id,)
    ).fetchone()
    if order is None:
        raise HTTPException(404, "Order not found")
    return order


def get_customer_order(connection, order_id, token):
    order = get_order_row(connection, order_id)
    if not order["access_token"] or not secrets.compare_digest(order["access_token"], token):
        raise HTTPException(404, "Order not found")
    return order


def order_to_dict(order, admin=False):
    data = {
        "id": order["id"],
        "filename": order["filename"],
        "pages": order["pages"],
        "color": order["color"],
        "copies": order["copies"],
        "paper": order["paper"],
        "sides": order["sides"],
        "total_price": order["total_price"],
        "status": order["status"],
        "error": order["error"],
        "created_at": order["created_at"],
        "paid_at": order["paid_at"],
        "printed_at": order["printed_at"],
    }
    if admin:
        data["payment_ref"] = order["payment_ref"]
        data["has_file"] = bool(order["pdf_path"]) and Path(order["pdf_path"]).exists()
    return data


async def save_upload(file, destination):
    """Stream the upload to disk, enforcing the size limit."""

    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    size = 0

    with open(destination, "wb") as buffer:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise HTTPException(413, f"File is larger than {config.MAX_UPLOAD_MB} MB.")
            buffer.write(chunk)

    if size == 0:
        raise HTTPException(400, "The file is empty.")


# ==========================================
# PUBLIC API
# ==========================================

@app.get("/api/health")
def health():
    return {"message": "Printify Backend is running!"}


@app.get("/api/config")
def get_config():
    return {
        "prices": pricing.PRICES,
        "max_copies": config.MAX_COPIES,
        "max_upload_mb": config.MAX_UPLOAD_MB,
        "extensions": sorted(documents.SUPPORTED_EXTENSIONS),
        "office_conversion": bool(config.find_libreoffice()),
        "payment": {
            "mode": payment_mode(),
            "upi_name": config.UPI_NAME if payment_mode() == "upi" else None,
            "test_mode": razorpay_gateway.test_mode() if payment_mode() == "razorpay" else False,
        },
        "printer": printing.printer_info(config.PRINTER_NAME or None),
    }


@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    paper_size: Paper = Form("a4"),
):
    original_name = Path(file.filename or "document").name[:200]
    extension = Path(original_name).suffix.lower()
    kind = documents.file_kind(extension)

    if kind is None:
        raise HTTPException(
            400,
            "This file type is not supported. Please upload a PDF, Word, "
            "PowerPoint, Excel, text or image file.",
        )

    # Each upload gets its own folder, so names never clash
    upload_id = uuid.uuid4().hex
    upload_dir = config.UPLOAD_FOLDER / upload_id
    upload_dir.mkdir(parents=True)
    source_path = upload_dir / f"document{extension}"

    try:
        await save_upload(file, source_path)

        # Conversion is slow and blocking, so keep it off the event loop
        pdf_path, pages = await run_in_threadpool(
            documents.prepare_document, source_path, kind, paper_size
        )

    except documents.DocumentError as error:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(422, str(error))

    except BaseException:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise

    with connect() as connection:
        connection.execute(
            """
            INSERT INTO uploads (id, original_name, kind, source_path, pdf_path, pages)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (upload_id, original_name, kind, str(source_path), str(pdf_path), pages),
        )

    return {
        "status": "success",
        "upload_id": upload_id,
        "filename": original_name,
        "kind": kind,
        "pages": pages,
        "message": "File uploaded and processed successfully!",
    }


@app.get("/api/uploads/{upload_id}/pages/{page_number}")
def page_preview(upload_id: str, page_number: int, size: Literal["small", "large"] = "small"):
    """Picture of one page (numbered from 1) for the print preview."""

    with connect() as connection:
        upload = connection.execute(
            "SELECT * FROM uploads WHERE id = ?", (upload_id,)
        ).fetchone()

    if upload is None or not Path(upload["pdf_path"]).exists():
        raise HTTPException(404, "Upload not found")
    if not 1 <= page_number <= upload["pages"]:
        raise HTTPException(404, "Page not found")

    preview = documents.render_preview(
        upload["pdf_path"], page_number - 1, size, Path(upload["pdf_path"]).parent
    )

    return FileResponse(
        preview,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@app.post("/api/quote")
def quote(request: QuoteRequest):
    return pricing.calculate_price(
        request.pages, request.color, request.copies, request.paper, request.sides
    )


@app.post("/api/orders")
def create_order(request: OrderRequest):
    check_printer_supports(request)

    with connect() as connection:
        upload = connection.execute(
            "SELECT * FROM uploads WHERE id = ?", (request.upload_id,)
        ).fetchone()

    if upload is None:
        raise HTTPException(404, "Upload not found. Please upload the file again.")

    pdf_path = Path(upload["pdf_path"])

    # Images are laid out for one paper size; redo the page if it changed
    if upload["kind"] == "image":
        pdf_path = pdf_path.with_name(f"document-{request.paper}.pdf")
        if not pdf_path.exists():
            documents.image_to_pdf(upload["source_path"], request.paper, pdf_path)

    if not pdf_path.exists():
        raise HTTPException(410, "The uploaded file is no longer available. Please upload it again.")

    price = pricing.calculate_price(
        upload["pages"], request.color, request.copies, request.paper, request.sides
    )

    access_token = secrets.token_urlsafe(16)

    with connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO orders (
                filename, pages, color, copies, paper, sides, total_price,
                status, upload_id, pdf_path, access_token, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'awaiting_payment', ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                upload["original_name"],
                upload["pages"],
                request.color,
                request.copies,
                request.paper,
                request.sides,
                price["total"],
                upload["id"],
                str(pdf_path),
                access_token,
            ),
        )
        order = get_order_row(connection, cursor.lastrowid)

    return {
        "status": "success",
        "order": order_to_dict(order),
        "token": access_token,
        "price": price,
        "message": "Order created successfully!",
    }


@app.get("/api/orders/{order_id}")
def get_order(order_id: int, token: str):
    with connect() as connection:
        order = get_customer_order(connection, order_id, token)

        queue_position = None
        if order["status"] == "queued":
            queue_position = connection.execute(
                """
                SELECT COUNT(*) FROM orders
                WHERE status IN ('queued', 'printing') AND (paid_at < ? OR (paid_at = ? AND id <= ?))
                """,
                (order["paid_at"], order["paid_at"], order["id"]),
            ).fetchone()[0]

    return {**order_to_dict(order), "queue_position": queue_position}


@app.post("/api/orders/{order_id}/pay")
def pay_order(order_id: int, request: PaymentRequest):
    """Demo payment: marks the order as paid and puts it in the print queue.

    Only available while no payment gateway or shop UPI ID is configured.
    """

    if payment_mode() != "demo":
        raise HTTPException(403, "Demo payments are turned off. Please pay online.")

    with connect() as connection:
        order = get_customer_order(connection, order_id, request.token)

        if order["status"] != "awaiting_payment":
            raise HTTPException(409, "This order has already been paid or cancelled.")

        payment_ref = f"DEMO-{request.method.upper()}-{secrets.token_hex(4).upper()}"

        set_order_status(
            connection,
            order_id,
            "queued",
            payment_ref=payment_ref,
            paid_at=_now(connection),
            error=None,
        )
        order = get_order_row(connection, order_id)

    return {
        "status": "success",
        "payment_ref": payment_ref,
        "order": order_to_dict(order),
    }


# ==========================================
# UPI PAYMENTS
# ==========================================

def upi_link(order):
    """upi:// link that opens the customer's UPI app with the amount filled in."""

    params = {
        "pa": config.UPI_ID,
        "pn": config.UPI_NAME,
        "am": f"{order['total_price']:.2f}",
        "cu": "INR",
        "tn": f"Printify order {order['id']}",
    }
    return "upi://pay?" + "&".join(f"{key}={url_quote(value, safe='@')}" for key, value in params.items())


def get_unpaid_upi_order(connection, order_id, token):
    if payment_mode() != "upi":
        raise HTTPException(404, "UPI payments are not set up for this shop.")

    order = get_customer_order(connection, order_id, token)
    if order["status"] != "awaiting_payment":
        raise HTTPException(409, "This order has already been paid or cancelled.")
    return order


@app.get("/api/orders/{order_id}/upi")
def upi_details(order_id: int, token: str):
    with connect() as connection:
        order = get_unpaid_upi_order(connection, order_id, token)

    return {
        "link": upi_link(order),
        "amount": order["total_price"],
        "upi_id": config.UPI_ID,
        "name": config.UPI_NAME,
        "note": f"Printify order {order['id']}",
    }


@app.get("/api/orders/{order_id}/upi-qr.png")
def upi_qr(order_id: int, token: str):
    import qrcode

    with connect() as connection:
        order = get_unpaid_upi_order(connection, order_id, token)

    image = qrcode.make(upi_link(order), box_size=8, border=2)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")

    return Response(buffer.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/orders/{order_id}/upi-paid")
def upi_paid(order_id: int, request: UpiPaidRequest):
    """The customer says they paid; the shop checks the UTR before printing."""

    utr = re.sub(r"\s+", "", request.utr)
    if not UTR_PATTERN.match(utr):
        raise HTTPException(422, "The UTR / UPI reference number has 12 digits.")

    payment_ref = f"UTR {utr}"

    with connect() as connection:
        order = get_unpaid_upi_order(connection, order_id, request.token)

        used = connection.execute(
            "SELECT id FROM orders WHERE payment_ref = ? AND id != ? AND status != 'cancelled'",
            (payment_ref, order_id),
        ).fetchone()
        if used:
            raise HTTPException(409, "This UTR has already been used for another order.")

        set_order_status(connection, order_id, "verifying", payment_ref=payment_ref, error=None)
        order = get_order_row(connection, order_id)

    return {"status": "success", "order": order_to_dict(order)}


# ==========================================
# RAZORPAY PAYMENTS
# ==========================================

def get_unpaid_razorpay_order(connection, order_id, token):
    if payment_mode() != "razorpay":
        raise HTTPException(404, "Online payments are not set up for this shop.")

    order = get_customer_order(connection, order_id, token)
    if order["status"] != "awaiting_payment":
        raise HTTPException(409, "This order has already been paid or cancelled.")
    return order


def mark_razorpay_paid(connection, order_id, payment_id):
    set_order_status(
        connection,
        order_id,
        "queued",
        payment_ref=f"Razorpay {payment_id}",
        paid_at=_now(connection),
        error=None,
    )


@app.post("/api/orders/{order_id}/razorpay")
def razorpay_checkout(order_id: int, request: TokenRequest):
    """Razorpay order for the checkout popup. The amount comes from the server."""

    with connect() as connection:
        order = get_unpaid_razorpay_order(connection, order_id, request.token)

    gateway_order_id = order["gateway_order_id"]

    try:
        if gateway_order_id:
            # Paid before, but the browser closed before telling us?
            payment = razorpay_gateway.paid_payment(gateway_order_id)
            if payment:
                with connect() as connection:
                    mark_razorpay_paid(connection, order_id, payment["id"])
                    order = get_order_row(connection, order_id)
                return {"status": "paid", "order": order_to_dict(order)}
        else:
            gateway_order = razorpay_gateway.create_order(
                order["total_price"],
                receipt=f"printify-{order_id}",
                notes={"printify_order": str(order_id)},
            )
            gateway_order_id = gateway_order["id"]
            with connect() as connection:
                connection.execute(
                    "UPDATE orders SET gateway_order_id = ? WHERE id = ?",
                    (gateway_order_id, order_id),
                )

    except razorpay_gateway.RazorpayError as error:
        raise HTTPException(502, str(error))

    return {
        "status": "pending",
        "key_id": config.RAZORPAY_KEY_ID,
        "razorpay_order_id": gateway_order_id,
        "amount": round(order["total_price"] * 100),
        "currency": "INR",
        "name": config.UPI_NAME,
        "description": f"Printify order {order_id}",
        "test_mode": razorpay_gateway.test_mode(),
    }


@app.post("/api/orders/{order_id}/razorpay/verify")
def razorpay_verify(order_id: int, request: RazorpayVerifyRequest):
    """Checkout succeeded: check Razorpay's signature, then queue the order."""

    with connect() as connection:
        order = get_customer_order(connection, order_id, request.token)

        if order["status"] != "awaiting_payment":
            if order["payment_ref"] == f"Razorpay {request.razorpay_payment_id}":
                return {"status": "success", "order": order_to_dict(order)}
            raise HTTPException(409, "This order has already been paid or cancelled.")

        if (
            not order["gateway_order_id"]
            or request.razorpay_order_id != order["gateway_order_id"]
            or not razorpay_gateway.signature_valid(
                request.razorpay_order_id,
                request.razorpay_payment_id,
                request.razorpay_signature,
            )
        ):
            raise HTTPException(400, "The payment could not be verified.")

        mark_razorpay_paid(connection, order_id, request.razorpay_payment_id)
        order = get_order_row(connection, order_id)

    return {"status": "success", "order": order_to_dict(order)}


@app.post("/api/orders/{order_id}/cancel")
def cancel_order(order_id: int, request: TokenRequest):
    with connect() as connection:
        order = get_customer_order(connection, order_id, request.token)

        if order["status"] not in ("awaiting_payment", "verifying", "queued"):
            raise HTTPException(409, "This order can no longer be cancelled.")

        set_order_status(connection, order_id, "cancelled")
        order = get_order_row(connection, order_id)

    return {"status": "success", "order": order_to_dict(order)}


def _now(connection):
    return connection.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]


# ==========================================
# ADMIN API
# ==========================================

@app.get("/api/admin/orders", dependencies=[Depends(require_admin)])
def admin_orders(status: str | None = None, limit: int = 100):
    query = "SELECT * FROM orders"
    params = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(min(max(limit, 1), 500))

    with connect() as connection:
        orders = connection.execute(query, params).fetchall()

        summary = connection.execute(
            """
            SELECT
                COUNT(*) AS orders,
                COALESCE(SUM(CASE WHEN paid_at IS NOT NULL AND status != 'cancelled'
                             THEN total_price END), 0) AS revenue,
                COALESCE(SUM(status IN ('queued', 'printing')), 0) AS in_queue,
                COALESCE(SUM(status = 'failed'), 0) AS failed,
                COALESCE(SUM(status = 'verifying'), 0) AS verifying
            FROM orders
            """
        ).fetchone()

    return {
        "orders": [order_to_dict(order, admin=True) for order in orders],
        "summary": dict(summary),
        "printer": printing.printer_info(config.PRINTER_NAME or None),
    }


@app.post("/api/admin/orders/{order_id}/confirm-payment", dependencies=[Depends(require_admin)])
def admin_confirm_payment(order_id: int):
    """The UTR was found in the shop's UPI app: queue the order for printing."""

    with connect() as connection:
        order = get_order_row(connection, order_id)
        if order["status"] != "verifying":
            raise HTTPException(409, "This order is not waiting for payment confirmation.")
        set_order_status(connection, order_id, "queued", paid_at=_now(connection), error=None)
        order = get_order_row(connection, order_id)
    return {"status": "success", "order": order_to_dict(order, admin=True)}


@app.post("/api/admin/orders/{order_id}/reject-payment", dependencies=[Depends(require_admin)])
def admin_reject_payment(order_id: int):
    """No matching payment arrived: ask the customer to pay again."""

    with connect() as connection:
        order = get_order_row(connection, order_id)
        if order["status"] != "verifying":
            raise HTTPException(409, "This order is not waiting for payment confirmation.")
        set_order_status(
            connection, order_id, "awaiting_payment",
            error=f"No payment was found for {order['payment_ref']}.",
            payment_ref=None,
        )
        order = get_order_row(connection, order_id)
    return {"status": "success", "order": order_to_dict(order, admin=True)}


@app.post("/api/admin/orders/{order_id}/retry", dependencies=[Depends(require_admin)])
def admin_retry(order_id: int):
    with connect() as connection:
        order = get_order_row(connection, order_id)
        if order["status"] not in ("failed", "completed"):
            raise HTTPException(409, "Only failed or completed orders can be printed again.")
        if not order["pdf_path"] or not Path(order["pdf_path"]).exists():
            raise HTTPException(409, "The document was deleted after printing, so it can't be printed again.")
        if not order["paid_at"]:
            raise HTTPException(409, "This order has not been paid.")
        set_order_status(connection, order_id, "queued", error=None)
        order = get_order_row(connection, order_id)
    return {"status": "success", "order": order_to_dict(order, admin=True)}


@app.post("/api/admin/orders/{order_id}/cancel", dependencies=[Depends(require_admin)])
def admin_cancel(order_id: int):
    with connect() as connection:
        order = get_order_row(connection, order_id)
        if order["status"] not in CANCELLABLE:
            raise HTTPException(409, "This order can no longer be cancelled.")
        set_order_status(connection, order_id, "cancelled")
        order = get_order_row(connection, order_id)
    return {"status": "success", "order": order_to_dict(order, admin=True)}


@app.post("/api/admin/orders/{order_id}/complete", dependencies=[Depends(require_admin)])
def admin_complete(order_id: int):
    """Mark an order as handed over, e.g. after printing it manually."""

    with connect() as connection:
        order = get_order_row(connection, order_id)
        if order["status"] in ("awaiting_payment", "verifying", "cancelled", "completed"):
            raise HTTPException(409, "Only paid orders can be marked as completed.")
        set_order_status(
            connection, order_id, "completed", error=None, printed_at=_now(connection)
        )
        # Printed: the customer's document is not kept
        forget_document(connection, order_id)
        order = get_order_row(connection, order_id)
    return {"status": "success", "order": order_to_dict(order, admin=True)}


# Privacy: there is deliberately no admin route to open or download a
# customer's document. The print agent reads the file straight from disk.


# ==========================================
# WEBSITE
# ==========================================

# Mounted last so the API routes above take priority
app.mount("/", StaticFiles(directory=config.WEBSITE_DIR, html=True), name="website")
