import hashlib
import hmac

import pytest

import config
import razorpay_gateway


KEY_SECRET = "test_secret_123"


@pytest.fixture
def razorpay_shop(monkeypatch):
    monkeypatch.setattr(config, "RAZORPAY_KEY_ID", "rzp_test_abc123")
    monkeypatch.setattr(config, "RAZORPAY_KEY_SECRET", KEY_SECRET)

    calls = []

    def fake_request(method, path, body=None):
        calls.append((method, path, body))
        if method == "POST" and path == "/orders":
            return {"id": f"order_rzp{len(calls)}", "amount": body["amount"]}
        if method == "GET" and path.endswith("/payments"):
            return {"items": fake_request.payments}
        raise AssertionError(path)

    fake_request.payments = []
    monkeypatch.setattr(razorpay_gateway, "request", fake_request)
    return fake_request, calls


def sign(gateway_order_id, payment_id):
    return hmac.new(
        KEY_SECRET.encode(), f"{gateway_order_id}|{payment_id}".encode(), hashlib.sha256
    ).hexdigest()


def new_order(client, uploaded_pdf, **options):
    response = client.post("/api/orders", json={"upload_id": uploaded_pdf["upload_id"], **options})
    assert response.status_code == 200, response.text
    data = response.json()
    return data["order"]["id"], data["token"]


def start_checkout(client, order_id, token):
    response = client.post(f"/api/orders/{order_id}/razorpay", json={"token": token})
    assert response.status_code == 200, response.text
    return response.json()


def test_config_reports_razorpay(client, razorpay_shop, monkeypatch):
    monkeypatch.setattr(config, "UPI_ID", "printshop@okaxis")  # Razorpay wins over UPI
    payment = client.get("/api/config").json()["payment"]
    assert payment["mode"] == "razorpay"
    assert payment["test_mode"] is True


def test_checkout_uses_server_price(client, uploaded_pdf, razorpay_shop):
    fake_request, calls = razorpay_shop
    order_id, token = new_order(client, uploaded_pdf, copies=2, color="color")  # 5 x 2 x Rs 5

    data = start_checkout(client, order_id, token)

    assert data["status"] == "pending"
    assert data["key_id"] == "rzp_test_abc123"
    assert data["amount"] == 5000
    assert calls[0][2]["amount"] == 5000
    assert calls[0][2]["currency"] == "INR"
    assert "secret" not in str(data).lower()

    # Opening the checkout again reuses the same Razorpay order
    again = start_checkout(client, order_id, token)
    assert again["razorpay_order_id"] == data["razorpay_order_id"]
    assert [call for call in calls if call[0] == "POST"] == calls[:1]


def test_verified_payment_queues_order(client, uploaded_pdf, razorpay_shop):
    order_id, token = new_order(client, uploaded_pdf)
    gateway_order_id = start_checkout(client, order_id, token)["razorpay_order_id"]

    response = client.post(f"/api/orders/{order_id}/razorpay/verify", json={
        "token": token,
        "razorpay_order_id": gateway_order_id,
        "razorpay_payment_id": "pay_ABC",
        "razorpay_signature": sign(gateway_order_id, "pay_ABC"),
    })

    assert response.status_code == 200, response.text
    order = response.json()["order"]
    assert order["status"] == "queued"
    assert order["paid_at"]


def test_bad_signature_is_rejected(client, uploaded_pdf, razorpay_shop):
    order_id, token = new_order(client, uploaded_pdf)
    gateway_order_id = start_checkout(client, order_id, token)["razorpay_order_id"]

    for body in (
        {"razorpay_order_id": gateway_order_id, "razorpay_signature": "0" * 64},
        # Valid signature, but for another Razorpay order
        {"razorpay_order_id": "order_other", "razorpay_signature": sign("order_other", "pay_ABC")},
    ):
        response = client.post(f"/api/orders/{order_id}/razorpay/verify", json={
            "token": token, "razorpay_payment_id": "pay_ABC", **body,
        })
        assert response.status_code == 400

    status = client.get(f"/api/orders/{order_id}", params={"token": token}).json()["status"]
    assert status == "awaiting_payment"


def test_payment_found_when_browser_closed(client, uploaded_pdf, razorpay_shop):
    fake_request, _ = razorpay_shop
    order_id, token = new_order(client, uploaded_pdf)
    start_checkout(client, order_id, token)

    fake_request.payments = [{"id": "pay_LATE", "status": "captured"}]

    data = start_checkout(client, order_id, token)
    assert data["status"] == "paid"
    assert data["order"]["status"] == "queued"


def test_demo_and_upi_payments_off_with_razorpay(client, uploaded_pdf, razorpay_shop):
    order_id, token = new_order(client, uploaded_pdf)
    assert client.post(f"/api/orders/{order_id}/pay", json={"token": token, "method": "upi"}).status_code == 403
    assert client.get(f"/api/orders/{order_id}/upi", params={"token": token}).status_code == 404


def test_razorpay_off_without_keys(client, uploaded_pdf, monkeypatch):
    monkeypatch.setattr(config, "RAZORPAY_KEY_ID", "")
    monkeypatch.setattr(config, "RAZORPAY_KEY_SECRET", "")
    order_id, token = new_order(client, uploaded_pdf)
    assert client.post(f"/api/orders/{order_id}/razorpay", json={"token": token}).status_code == 404


def test_keys_read_from_dashboard_csv(tmp_path, monkeypatch):
    key_file = tmp_path / "rzp-key.csv"
    key_file.write_text("key_id,key_secret\nrzp_test_file,file_secret\n", encoding="utf-8")

    monkeypatch.delenv("PRINTIFY_RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("PRINTIFY_RAZORPAY_KEY_SECRET", raising=False)
    monkeypatch.setenv("PRINTIFY_RAZORPAY_KEY_FILE", str(key_file))

    assert config.load_razorpay_keys() == ("rzp_test_file", "file_secret")
