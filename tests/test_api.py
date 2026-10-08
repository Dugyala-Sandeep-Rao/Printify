import io
import sqlite3

import pytest
from PIL import Image

import config
from conftest import ADMIN_HEADERS, make_pdf


def create_order(client, upload_id, **options):
    body = {"upload_id": upload_id, "color": "bw", "copies": 1, "paper": "a4", "sides": "single"}
    body.update(options)
    response = client.post("/api/orders", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def pay(client, order):
    response = client.post(
        f"/api/orders/{order['order']['id']}/pay",
        json={"token": order["token"], "method": "upi"},
    )
    assert response.status_code == 200, response.text
    return response.json()


# ==========================================
# WEBSITE
# ==========================================

def test_website_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Printify" in response.text

    assert client.get("/admin.html").status_code == 200
    assert client.get("/script.js").status_code == 200


def test_config(client):
    data = client.get("/api/config").json()
    assert data["prices"]["single"]["bw"] == 2
    assert ".pdf" in data["extensions"]
    assert data["printer"]["name"] == "Test printer"


# ==========================================
# UPLOADS
# ==========================================

def test_upload_pdf_counts_pages(uploaded_pdf):
    assert uploaded_pdf["pages"] == 5
    assert uploaded_pdf["kind"] == "pdf"
    assert uploaded_pdf["filename"] == "notes.pdf"


def test_upload_keeps_files_with_the_same_name_apart(client, tmp_path):
    ids = []
    for pages in (1, 2):
        path = make_pdf(tmp_path / f"doc{pages}.pdf", pages=pages)
        with open(path, "rb") as file:
            response = client.post("/api/upload", files={"file": ("same.pdf", file)})
        ids.append(response.json()["upload_id"])

    assert ids[0] != ids[1]
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        pages = [
            connection.execute("SELECT pages FROM uploads WHERE id = ?", (i,)).fetchone()[0]
            for i in ids
        ]
    assert pages == [1, 2]


def test_upload_filename_cannot_escape_upload_folder(client, tmp_path):
    path = make_pdf(tmp_path / "evil.pdf", pages=1)
    with open(path, "rb") as file:
        response = client.post("/api/upload", files={"file": ("../../evil.pdf", file)})

    assert response.status_code == 200
    assert response.json()["filename"] == "evil.pdf"
    assert not (config.UPLOAD_FOLDER.parent / "evil.pdf").exists()


def test_upload_image_becomes_one_page(client):
    buffer = io.BytesIO()
    Image.new("RGBA", (400, 300), (255, 0, 0, 128)).save(buffer, "PNG")
    buffer.seek(0)

    response = client.post(
        "/api/upload",
        files={"file": ("photo.png", buffer, "image/png")},
        data={"paper_size": "a4"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["pages"] == 1
    assert response.json()["kind"] == "image"


def test_upload_unsupported_type(client):
    response = client.post("/api/upload", files={"file": ("virus.exe", b"MZ...")})
    assert response.status_code == 400


def test_upload_damaged_pdf(client):
    response = client.post("/api/upload", files={"file": ("broken.pdf", b"not a pdf at all")})
    assert response.status_code == 422
    assert "could not be read" in response.json()["detail"]


def test_upload_fake_image(client):
    response = client.post("/api/upload", files={"file": ("fake.jpg", b"not an image")})
    assert response.status_code == 422


def test_upload_empty_file(client):
    response = client.post("/api/upload", files={"file": ("empty.pdf", b"")})
    assert response.status_code == 400


def test_upload_too_large(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_MB", 0)
    response = client.post("/api/upload", files={"file": ("big.pdf", b"x" * 10)})
    assert response.status_code == 413


@pytest.mark.skipif(not config.LIBREOFFICE_PATH, reason="LibreOffice not installed")
def test_upload_text_file_is_converted(client):
    response = client.post(
        "/api/upload",
        files={"file": ("notes.txt", "Hello\n" * 5, "text/plain")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["kind"] == "office"
    assert response.json()["pages"] == 1


# ==========================================
# QUOTES & ORDERS
# ==========================================

def test_quote(client):
    response = client.post(
        "/api/quote",
        json={"pages": 5, "color": "color", "copies": 2, "paper": "a4", "sides": "double"},
    )
    assert response.json()["total"] == 3 * 8 * 2


def test_quote_rejects_bad_options(client):
    assert client.post("/api/quote", json={"pages": 5, "copies": 0}).status_code == 422
    assert client.post("/api/quote", json={"pages": 5, "copies": 1000}).status_code == 422
    assert client.post("/api/quote", json={"pages": 5, "color": "gold"}).status_code == 422


def test_order_price_is_calculated_by_server(client, uploaded_pdf):
    # Extra fields such as a client-side total are ignored
    response = client.post(
        "/api/orders",
        json={"upload_id": uploaded_pdf["upload_id"], "copies": 2, "total_price": 1},
    )
    assert response.status_code == 200
    assert response.json()["order"]["total_price"] == 5 * 2 * 2
    assert response.json()["order"]["status"] == "awaiting_payment"


def test_order_for_unknown_upload(client):
    response = client.post("/api/orders", json={"upload_id": "missing"})
    assert response.status_code == 404


def test_order_rejects_options_printer_cannot_do(client, uploaded_pdf, monkeypatch):
    import printing

    monkeypatch.setattr(
        printing,
        "printer_info",
        lambda name=None: {
            "available": True, "name": "Small printer", "ready": True, "message": "",
            "papers": ["a4"], "duplex": False, "color": True, "jobs": 0,
        },
    )

    upload_id = uploaded_pdf["upload_id"]
    assert client.post("/api/orders", json={"upload_id": upload_id, "paper": "a3"}).status_code == 400
    assert client.post("/api/orders", json={"upload_id": upload_id, "sides": "double"}).status_code == 400
    assert client.post("/api/orders", json={"upload_id": upload_id}).status_code == 200


def test_image_order_is_laid_out_for_chosen_paper(client):
    buffer = io.BytesIO()
    Image.new("RGB", (300, 400), "blue").save(buffer, "JPEG")
    buffer.seek(0)
    upload = client.post(
        "/api/upload", files={"file": ("pic.jpg", buffer)}, data={"paper_size": "a4"}
    ).json()

    order = create_order(client, upload["upload_id"], paper="a3")

    with sqlite3.connect(config.DATABASE_PATH) as connection:
        pdf_path = connection.execute(
            "SELECT pdf_path FROM orders WHERE id = ?", (order["order"]["id"],)
        ).fetchone()[0]

    import pypdfium2 as pdfium
    document = pdfium.PdfDocument(pdf_path)
    width, height = document[0].get_size()
    document.close()
    assert round(width) == 842 and round(height) == 1191  # A3 portrait


def test_payment_and_tracking(client, uploaded_pdf):
    order = create_order(client, uploaded_pdf["upload_id"])
    order_id = order["order"]["id"]

    paid = pay(client, order)
    assert paid["order"]["status"] == "queued"
    assert paid["payment_ref"].startswith("DEMO-UPI-")

    tracked = client.get(f"/api/orders/{order_id}", params={"token": order["token"]}).json()
    assert tracked["status"] == "queued"
    assert tracked["queue_position"] >= 1

    # Paying twice is refused
    second = client.post(
        f"/api/orders/{order_id}/pay", json={"token": order["token"], "method": "card"}
    )
    assert second.status_code == 409


def test_order_needs_its_token(client, uploaded_pdf):
    order = create_order(client, uploaded_pdf["upload_id"])
    order_id = order["order"]["id"]

    assert client.get(f"/api/orders/{order_id}", params={"token": "wrong"}).status_code == 404
    assert client.post(
        f"/api/orders/{order_id}/pay", json={"token": "wrong", "method": "upi"}
    ).status_code == 404


def test_customer_can_cancel_queued_order(client, uploaded_pdf):
    order = create_order(client, uploaded_pdf["upload_id"])
    pay(client, order)

    response = client.post(
        f"/api/orders/{order['order']['id']}/cancel", json={"token": order["token"]}
    )
    assert response.json()["order"]["status"] == "cancelled"


# ==========================================
# ADMIN
# ==========================================

def test_admin_requires_token(client):
    assert client.get("/api/admin/orders").status_code == 401
    assert client.get("/api/admin/orders", headers={"X-Admin-Token": "nope"}).status_code == 401


def test_admin_order_management(client, uploaded_pdf):
    order = create_order(client, uploaded_pdf["upload_id"])
    order_id = order["order"]["id"]
    pay(client, order)

    data = client.get("/api/admin/orders", headers=ADMIN_HEADERS).json()
    listed = next(o for o in data["orders"] if o["id"] == order_id)
    assert listed["has_file"] is True
    assert listed["payment_ref"].startswith("DEMO-")
    assert data["summary"]["in_queue"] >= 1

    queued = client.get(
        "/api/admin/orders", params={"status": "queued"}, headers=ADMIN_HEADERS
    ).json()["orders"]
    assert all(o["status"] == "queued" for o in queued)

    # Privacy: the admin cannot open the customer's document
    file = client.get(f"/api/admin/orders/{order_id}/file", headers=ADMIN_HEADERS)
    assert file.status_code == 404
    assert not file.content.startswith(b"%PDF")

    # Queued orders cannot be "retried"
    assert client.post(f"/api/admin/orders/{order_id}/retry", headers=ADMIN_HEADERS).status_code == 409

    cancelled = client.post(f"/api/admin/orders/{order_id}/cancel", headers=ADMIN_HEADERS).json()
    assert cancelled["order"]["status"] == "cancelled"


def test_marking_done_deletes_the_document(client, uploaded_pdf):
    upload_id = uploaded_pdf["upload_id"]
    order = create_order(client, upload_id)
    order_id = order["order"]["id"]
    pay(client, order)

    done = client.post(f"/api/admin/orders/{order_id}/complete", headers=ADMIN_HEADERS).json()["order"]
    assert done["status"] == "completed"
    assert done["filename"] == "Deleted after printing"
    assert done["has_file"] is False

    # File, previews and upload record are gone
    assert not (config.UPLOAD_FOLDER / upload_id).exists()
    assert client.get(f"/api/uploads/{upload_id}/pages/1").status_code == 404
    assert client.get(f"/api/admin/orders/{order_id}/file", headers=ADMIN_HEADERS).status_code == 404
    with sqlite3.connect(config.DATABASE_PATH) as connection:
        row = connection.execute(
            "SELECT filename, pdf_path, upload_id, total_price, payment_ref FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
    assert row[:3] == ("Deleted after printing", None, None)
    assert row[3] == 10 and row[4].startswith("DEMO-")  # accounts are kept

    # Nothing left to reprint
    assert client.post(f"/api/admin/orders/{order_id}/retry", headers=ADMIN_HEADERS).status_code == 409

    # The customer sees the generic name too
    tracked = client.get(f"/api/orders/{order_id}", params={"token": order["token"]}).json()
    assert tracked["filename"] == "Deleted after printing"


def test_shared_upload_kept_while_another_order_needs_it(client, uploaded_pdf):
    upload_id = uploaded_pdf["upload_id"]
    first = create_order(client, upload_id)
    second = create_order(client, upload_id)
    pay(client, first)

    client.post(f"/api/admin/orders/{first['order']['id']}/complete", headers=ADMIN_HEADERS)

    # The second order still needs the file
    assert (config.UPLOAD_FOLDER / upload_id).exists()
    assert client.post(f"/api/orders/{second['order']['id']}/pay",
                       json={"token": second["token"], "method": "upi"}).status_code == 200


def test_unpaid_order_cannot_be_completed(client, uploaded_pdf):
    order = create_order(client, uploaded_pdf["upload_id"])
    response = client.post(
        f"/api/admin/orders/{order['order']['id']}/complete", headers=ADMIN_HEADERS
    )
    assert response.status_code == 409


def test_page_previews(client, uploaded_pdf):
    upload_id = uploaded_pdf["upload_id"]

    small = client.get(f"/api/uploads/{upload_id}/pages/1")
    assert small.status_code == 200
    assert small.headers["content-type"] == "image/jpeg"

    large = client.get(f"/api/uploads/{upload_id}/pages/5", params={"size": "large"})
    assert large.status_code == 200
    assert len(large.content) > len(small.content)

    # Served from the cache the second time
    assert client.get(f"/api/uploads/{upload_id}/pages/1").content == small.content

    assert client.get(f"/api/uploads/{upload_id}/pages/0").status_code == 404
    assert client.get(f"/api/uploads/{upload_id}/pages/6").status_code == 404
    assert client.get("/api/uploads/nope/pages/1").status_code == 404
    assert client.get(f"/api/uploads/{upload_id}/pages/1", params={"size": "huge"}).status_code == 422


def test_office_upload_without_libreoffice(client, monkeypatch):
    monkeypatch.setattr(config, "LIBREOFFICE_PATH", r"C:\missing\soffice.exe")
    monkeypatch.setattr(config, "find_libreoffice", lambda: None)

    response = client.post("/api/upload", files={"file": ("essay.docx", b"PK fake docx")})
    assert response.status_code == 422
    assert "LibreOffice is not installed" in response.json()["detail"]