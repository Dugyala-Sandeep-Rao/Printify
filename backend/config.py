import csv
import os
import secrets
import shutil
from pathlib import Path


# Project folder
BASE_DIR = Path(__file__).resolve().parent.parent

WEBSITE_DIR = BASE_DIR / "website"

UPLOAD_FOLDER = Path(os.getenv("PRINTIFY_UPLOAD_DIR", BASE_DIR / "uploads"))

DATABASE_PATH = Path(os.getenv("PRINTIFY_DB", BASE_DIR / "database" / "printify.db"))

MAX_UPLOAD_MB = int(os.getenv("PRINTIFY_MAX_UPLOAD_MB", "50"))

MAX_COPIES = 100

# Uploaded files are deleted this many days after upload (0 = keep forever)
KEEP_UPLOADS_DAYS = float(os.getenv("PRINTIFY_KEEP_DAYS", "7"))

# Shop UPI ID for payments (e.g. myshop@okaxis). Empty = demo payments.
UPI_ID = os.getenv("PRINTIFY_UPI_ID", "").strip()
UPI_NAME = os.getenv("PRINTIFY_UPI_NAME", "Printify").strip() or "Printify"

def load_razorpay_keys():
    """Razorpay API keys from the environment, or from the key file the
    Razorpay dashboard downloads (key_id,key_secret) saved as
    database/razorpay_key.csv. Empty = Razorpay turned off."""

    key_id = os.getenv("PRINTIFY_RAZORPAY_KEY_ID", "").strip()
    key_secret = os.getenv("PRINTIFY_RAZORPAY_KEY_SECRET", "").strip()
    if key_id and key_secret:
        return key_id, key_secret

    key_file = Path(os.getenv("PRINTIFY_RAZORPAY_KEY_FILE", DATABASE_PATH.parent / "razorpay_key.csv"))
    if key_file.is_file():
        with open(key_file, newline="", encoding="utf-8-sig") as file:
            for row in csv.DictReader(file):
                key_id = (row.get("key_id") or "").strip()
                key_secret = (row.get("key_secret") or "").strip()
                if key_id and key_secret:
                    return key_id, key_secret

    return "", ""


# Razorpay payment gateway (cards, UPI, netbanking, wallets). Takes priority over UPI.
RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET = load_razorpay_keys()

# Printer used by the print agent. Empty = Windows default printer.
PRINTER_NAME = os.getenv("PRINTIFY_PRINTER", "")

# Origins allowed to call the API from another page (e.g. Live Server).
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("PRINTIFY_CORS_ORIGINS", "*").split(",")
    if origin.strip()
]


def find_libreoffice():
    configured = os.getenv("PRINTIFY_LIBREOFFICE")
    if configured:
        return configured

    for candidate in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ):
        if Path(candidate).exists():
            return candidate

    return shutil.which("soffice") or shutil.which("libreoffice")


LIBREOFFICE_PATH = find_libreoffice()


def get_admin_token():
    """Admin token from PRINTIFY_ADMIN_TOKEN, or one generated on first run."""

    token = os.getenv("PRINTIFY_ADMIN_TOKEN")
    if token:
        return token

    token_file = DATABASE_PATH.parent / "admin_token.txt"
    if token_file.exists():
        return token_file.read_text(encoding="utf-8").strip()

    token_file.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(16)
    token_file.write_text(token, encoding="utf-8")
    return token
