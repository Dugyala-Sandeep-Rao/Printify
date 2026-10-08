import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Point the app at a throwaway database and upload folder before it is imported
_TEMP = Path(tempfile.mkdtemp(prefix="printify-tests-"))
os.environ["PRINTIFY_DB"] = str(_TEMP / "test.db")
os.environ["PRINTIFY_UPLOAD_DIR"] = str(_TEMP / "uploads")
os.environ["PRINTIFY_ADMIN_TOKEN"] = "test-admin-token"

sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "printer_agent"))

from reportlab.pdfgen import canvas  # noqa: E402


ADMIN_HEADERS = {"X-Admin-Token": "test-admin-token"}


def make_pdf(path, pages=3, landscape_last=False):
    pdf = canvas.Canvas(str(path))
    for number in range(1, pages + 1):
        if landscape_last and number == pages:
            pdf.setPageSize((842, 595))
        pdf.setFont("Helvetica", 40)
        pdf.drawString(100, 500, f"Page {number}")
        pdf.showPage()
    pdf.save()
    return path


@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    import main
    import printing

    # Behave as if the shop printer supports everything
    monkeypatch.setattr(
        printing,
        "printer_info",
        lambda name=None: {
            "available": True,
            "name": "Test printer",
            "ready": True,
            "message": "Printer ready",
            "papers": ["a4", "a3", "letter"],
            "duplex": True,
            "color": True,
            "jobs": 0,
        },
    )

    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def uploaded_pdf(client, tmp_path):
    path = make_pdf(tmp_path / "notes.pdf", pages=5)
    with open(path, "rb") as file:
        response = client.post("/api/upload", files={"file": ("notes.pdf", file, "application/pdf")})
    assert response.status_code == 200, response.text
    return response.json()
