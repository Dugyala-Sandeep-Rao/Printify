from urllib.parse import parse_qs, urlparse

import pytest

import config
from conftest import ADMIN_HEADERS


@pytest.fixture
def upi_shop(monkeypatch):
    monkeypatch.setattr(config, "UPI_ID", "printshop@okaxis")
    monkeypatch.setattr(config, "UPI_NAME", "Printify Shop")


def new_order(client, uploaded_pdf, **options):
    response = client.post("/api/orders", json={"upload_id": uploaded_pdf["upload_id"], **options})
    assert response.status_code == 200, response.text
    data = response.json()
    return data["order"]["id"], data["token"]


def test_config_reports_payment_mode(client, monkeypatch):
    assert client.get("/api/config").json()["payment"]["mode"] == "demo"

    monkeypatch.setattr(config, "UPI_ID", "printshop@okaxis")
    payment = client.get("/api/config").json()["payment"]
    assert payment == {"mode": "upi", "upi_name": config.UPI_NAME, "test_mode": False}


def test_upi_link_has_amount_and_payee(client, uploaded_pdf, upi_shop):
    order_id, token = new_order(client, uploaded_pdf, copies=2)  # 5 pages x 2 x Rs 2

    data = client.get(f"/api/orders/{order_id}/upi", params={"token": token}).json()

    link = urlparse(data["link"])
    params = {key: values[0] for key, values in parse_qs(link.query).items()}

    assert link.scheme == "upi" and link.netloc == "pay"
    assert params["pa"] == "printshop@okaxis"
    assert params["pn"] == "Printify Shop"
    assert params["am"] == "20.00"
    assert params["cu"] == "INR"
    assert params["tn"] == f"Printify order {order_id}"
    assert data["amount"] == 20


def test_upi_qr_code(client, uploaded_pdf, upi_shop):
    order_id, token = new_order(client, uploaded_pdf)

    response = client.get(f"/api/orders/{order_id}/upi-qr.png", params={"token": token})
    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG")

    wrong = client.get(f"/api/orders/{order_id}/upi-qr.png", params={"token": "nope"})
    assert wrong.status_code == 404


def test_upi_not_available_without_upi_id(client, uploaded_pdf):
    order_id, token = new_order(client, uploaded_pdf)
    assert client.get(f"/api/orders/{order_id}/upi", params={"token": token}).status_code == 404


def test_demo_payment_disabled_when_upi_is_set(client, uploaded_pdf, upi_shop):
    order_id, token = new_order(client, uploaded_pdf)
    response = client.post(f"/api/orders/{order_id}/pay", json={"token": token, "method": "upi"})
    assert response.status_code == 403


def test_full_upi_flow(client, uploaded_pdf, upi_shop):
    order_id, token = new_order(client, uploaded_pdf)

    # Customer submits the UTR (spaces allowed)
    response = client.post(
        f"/api/orders/{order_id}/upi-paid", json={"token": token, "utr": "4123 4567 8901"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["order"]["status"] == "verifying"

    # Not printed yet, and the QR is no longer offered
    assert client.get(f"/api/orders/{order_id}/upi", params={"token": token}).status_code == 409

    listed = client.get("/api/admin/orders", headers=ADMIN_HEADERS).json()
    row = next(o for o in listed["orders"] if o["id"] == order_id)
    assert row["payment_ref"] == "UTR 412345678901"
    assert listed["summary"]["verifying"] >= 1

    # Shop confirms: the order joins the print queue
    confirmed = client.post(
        f"/api/admin/orders/{order_id}/confirm-payment", headers=ADMIN_HEADERS
    ).json()["order"]
    assert confirmed["status"] == "queued"
    assert confirmed["paid_at"] is not None


def test_rejected_payment_can_be_paid_again(client, uploaded_pdf, upi_shop):
    order_id, token = new_order(client, uploaded_pdf)
    client.post(f"/api/orders/{order_id}/upi-paid", json={"token": token, "utr": "111122223333"})

    rejected = client.post(
        f"/api/admin/orders/{order_id}/reject-payment", headers=ADMIN_HEADERS
    ).json()["order"]
    assert rejected["status"] == "awaiting_payment"
    assert "111122223333" in rejected["error"]

    # Customer pays again with the right UTR
    again = client.post(f"/api/orders/{order_id}/upi-paid", json={"token": token, "utr": "111122224444"})
    assert again.json()["order"]["status"] == "verifying"


def test_utr_must_be_12_digits(client, uploaded_pdf, upi_shop):
    order_id, token = new_order(client, uploaded_pdf)
    for utr in ("12345", "abcdefghijkl", "1234567890123"):
        response = client.post(f"/api/orders/{order_id}/upi-paid", json={"token": token, "utr": utr})
        assert response.status_code == 422


def test_utr_cannot_be_reused(client, uploaded_pdf, upi_shop):
    first, first_token = new_order(client, uploaded_pdf)
    second, second_token = new_order(client, uploaded_pdf)

    client.post(f"/api/orders/{first}/upi-paid", json={"token": first_token, "utr": "999988887777"})
    response = client.post(f"/api/orders/{second}/upi-paid", json={"token": second_token, "utr": "999988887777"})
    assert response.status_code == 409


def test_unconfirmed_order_cannot_be_printed_or_completed(client, uploaded_pdf, upi_shop):
    import agent

    order_id, token = new_order(client, uploaded_pdf)
    client.post(f"/api/orders/{order_id}/upi-paid", json={"token": token, "utr": "555566667777"})

    assert client.post(f"/api/admin/orders/{order_id}/complete", headers=ADMIN_HEADERS).status_code == 409

    claimed = agent.claim_next_order()
    assert claimed is None or claimed["id"] != order_id


def test_customer_can_cancel_while_payment_is_checked(client, uploaded_pdf, upi_shop):
    order_id, token = new_order(client, uploaded_pdf)
    client.post(f"/api/orders/{order_id}/upi-paid", json={"token": token, "utr": "123123123123"})

    response = client.post(f"/api/orders/{order_id}/cancel", json={"token": token})
    assert response.json()["order"]["status"] == "cancelled"
