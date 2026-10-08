"""Razorpay payment gateway: orders API and payment signature checks.

Uses Razorpay's REST API directly, so no extra package is needed.
https://razorpay.com/docs/api/orders/
"""

import base64
import hashlib
import hmac
import json
import urllib.error
import urllib.request

import config


API_BASE = "https://api.razorpay.com/v1"


class RazorpayError(Exception):
    pass


def enabled():
    return bool(config.RAZORPAY_KEY_ID and config.RAZORPAY_KEY_SECRET)


def test_mode():
    return config.RAZORPAY_KEY_ID.startswith("rzp_test_")


def request(method, path, body=None):
    credentials = f"{config.RAZORPAY_KEY_ID}:{config.RAZORPAY_KEY_SECRET}".encode()
    headers = {"Authorization": "Basic " + base64.b64encode(credentials).decode()}

    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(API_BASE + path, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.load(response)

    except urllib.error.HTTPError as error:
        try:
            message = json.load(error)["error"]["description"]
        except Exception:
            message = f"HTTP {error.code}"
        raise RazorpayError(f"Razorpay: {message}") from error

    except (urllib.error.URLError, TimeoutError) as error:
        raise RazorpayError("Could not reach Razorpay. Check the internet connection.") from error


def create_order(amount_rupees, receipt, notes):
    """Razorpay order for the amount; the checkout can only charge this amount."""

    return request("POST", "/orders", {
        "amount": round(amount_rupees * 100),  # paise
        "currency": "INR",
        "receipt": receipt,
        "notes": notes,
    })


def paid_payment(gateway_order_id):
    """The successful payment for a Razorpay order, or None."""

    payments = request("GET", f"/orders/{gateway_order_id}/payments")
    for payment in payments.get("items", []):
        if payment.get("status") in ("captured", "authorized"):
            return payment
    return None


def signature_valid(gateway_order_id, payment_id, signature):
    """Checkout's success signature: HMAC-SHA256 of "order_id|payment_id"."""

    expected = hmac.new(
        config.RAZORPAY_KEY_SECRET.encode(),
        f"{gateway_order_id}|{payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")
