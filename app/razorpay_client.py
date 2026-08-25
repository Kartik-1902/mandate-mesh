"""Razorpay gateway client for Mandate Mesh.

Provides:
- `RazorpayClient`: Dual-mode (Live API / Mock in-memory) client for order creation
  and deterministic receipt-based reconciliation.
- `verify_webhook_signature`: Constant-time HMAC-SHA256 signature verification over raw bytes.
- `simulate_payment_captured_webhook`: Test & CLI utility for authentic webhook simulation.

NOTE: Per ADR-005, orders are created with `receipt = f"mm_{mandate_id.hex}"`
(35 chars <= 40-char Razorpay limit) enabling application-level reconciliation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from uuid import uuid4

import razorpay


def verify_webhook_signature(
    raw_body: bytes,
    signature_header: str,
    webhook_secret: str,
) -> bool:
    """Verifies Razorpay HMAC-SHA256 signature over raw request bytes using constant-time comparison."""
    if not signature_header or not webhook_secret:
        return False
    expected = hmac.new(
        webhook_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


class RazorpayClient:
    """Gateway client supporting both live Razorpay API and mock in-memory execution."""

    def __init__(
        self,
        key_id: str | None = None,
        key_secret: str | None = None,
        mock_mode: bool = False,
    ) -> None:
        self.key_id = key_id or "rzp_test_mock_key"
        self.key_secret = key_secret or "rzp_test_mock_secret"
        self.mock_mode = mock_mode or self.key_id.startswith("rzp_test_mock")

        # Mock order storage: {order_id: order_dict} and {receipt: order_dict}
        self._mock_orders_by_id: dict[str, dict[str, Any]] = {}
        self._mock_orders_by_receipt: dict[str, dict[str, Any]] = {}

        if not self.mock_mode:
            self._client = razorpay.Client(auth=(self.key_id, self.key_secret))
        else:
            self._client = None

    def create_order(
        self,
        amount_paise: int,
        currency: str = "INR",
        receipt: str = "",
        notes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Creates an order at Razorpay with deterministic receipt reference."""
        if self.mock_mode:
            order_id = f"order_mock_{uuid4().hex[:14]}"
            order_data = {
                "id": order_id,
                "entity": "order",
                "amount": amount_paise,
                "amount_paid": 0,
                "amount_due": amount_paise,
                "currency": currency,
                "receipt": receipt,
                "status": "created",
                "attempts": 0,
                "notes": notes or {},
                "created_at": int(time.time()),
            }
            self._mock_orders_by_id[order_id] = order_data
            if receipt:
                self._mock_orders_by_receipt[receipt] = order_data
            return order_data

        return self._client.order.create(
            data={
                "amount": amount_paise,
                "currency": currency,
                "receipt": receipt,
                "notes": notes or {},
            }
        )

    def reconcile_order(self, order_idempotency_key: str) -> dict[str, Any] | None:
        """Reconciles an order by querying Razorpay using the deterministic receipt key.

        Returns matching order dict if found, else None.
        """
        if self.mock_mode:
            return self._mock_orders_by_receipt.get(order_idempotency_key)

        try:
            # Query Razorpay for orders matching receipt
            orders = self._client.order.all({"receipt": order_idempotency_key})
            items = orders.get("items", [])
            if items:
                return items[0]
            return None
        except Exception:
            return None

    def get_order(self, order_id: str) -> dict[str, Any] | None:
        """Fetches an order by Razorpay order ID."""
        if self.mock_mode:
            return self._mock_orders_by_id.get(order_id)
        try:
            return self._client.order.fetch(order_id)
        except Exception:
            return None


def simulate_payment_captured_webhook(
    razorpay_order_id: str,
    amount_paise: int,
    currency: str = "INR",
    webhook_secret: str = "whsec_test_secret_123",
    event_id: str | None = None,
    payment_id: str | None = None,
) -> tuple[bytes, str]:
    """Builds a canonical Razorpay `payment.captured` webhook payload and computes its HMAC signature.

    Returns:
        tuple[bytes, str]: (raw_json_bytes, hmac_signature_header)
    """
    event_id = event_id or f"evt_mock_{uuid4().hex[:14]}"
    payment_id = payment_id or f"pay_mock_{uuid4().hex[:14]}"
    now_ts = int(time.time())

    payload = {
        "entity": "event",
        "account_id": "acc_mock_001",
        "event": "payment.captured",
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "entity": "payment",
                    "amount": amount_paise,
                    "currency": currency,
                    "status": "captured",
                    "order_id": razorpay_order_id,
                    "invoice_id": None,
                    "international": False,
                    "method": "upi",
                    "amount_refunded": 0,
                    "refund_status": None,
                    "captured": True,
                    "description": "Mandate Mesh payment capture",
                    "card_id": None,
                    "bank": None,
                    "wallet": None,
                    "vpa": "user@upi",
                    "email": "user@example.com",
                    "contact": "+919999999999",
                    "fee": 0,
                    "tax": 0,
                    "error_code": None,
                    "error_description": None,
                    "created_at": now_ts,
                }
            }
        },
        "created_at": now_ts,
        "event_id": event_id,
    }

    raw_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(
        webhook_secret.encode("utf-8"),
        raw_bytes,
        hashlib.sha256,
    ).hexdigest()

    return raw_bytes, signature
