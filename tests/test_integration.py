"""Phase 3: End-to-End Integration Tests for Mandate Mesh REST API & Payment Lifecycle."""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from app.api.deps import (
    get_db,
    get_merchant_private_key_pem,
    get_merchant_public_key_pem,
    get_platform_private_key_pem,
    get_platform_public_key_pem,
    get_razorpay_client,
    get_user_public_key_pem,
    get_webhook_secret,
)
from app.crypto import generate_es256_keypair, issue_intent_jwt, verify_receipt_jwt
from app.main import app
from app.merchant import seed_catalog
from app.models import MandateRecord, MandateStatus
from app.razorpay_client import RazorpayClient, simulate_payment_captured_webhook
from app.schemas import UserIntentCredential


@pytest.fixture
def test_keys():
    return {
        "user": generate_es256_keypair(),
        "merchant": generate_es256_keypair(),
        "platform": generate_es256_keypair(),
    }


@pytest.fixture
def mock_rzp():
    return RazorpayClient(mock_mode=True)


@pytest.fixture
def client(db_session, test_keys, mock_rzp):
    """Configures FastAPI TestClient with test database, keys, and mock Razorpay client."""
    seed_catalog(db_session)
    db_session.commit()

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_user_public_key_pem] = lambda: test_keys["user"][1]
    app.dependency_overrides[get_merchant_public_key_pem] = lambda: test_keys["merchant"][1]
    app.dependency_overrides[get_merchant_private_key_pem] = lambda: test_keys["merchant"][0]
    app.dependency_overrides[get_platform_private_key_pem] = lambda: test_keys["platform"][0]
    app.dependency_overrides[get_platform_public_key_pem] = lambda: test_keys["platform"][1]
    app.dependency_overrides[get_razorpay_client] = lambda: mock_rzp
    app.dependency_overrides[get_webhook_secret] = lambda: "whsec_test_secret_123"

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def build_user_intent_jwt(test_keys, spend_cap_paise=150000, allowed_categories=None, allowed_merchants=None):
    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        user_id="user_e2e_test",
        spend_cap_paise=spend_cap_paise,
        allowed_categories=allowed_categories or ["bakery", "gifting"],
        allowed_merchant_ids=allowed_merchants or ["merchant_cakehouse_01"],
        max_transactions=2,
        nonce=uuid4().hex,
        not_before=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    return intent, issue_intent_jwt(intent, test_keys["user"][0])


def test_e2e_happy_path(client, test_keys, mock_rzp):
    """Full End-to-End Payment Lifecycle: Intent -> Catalog -> Cart -> Mandate -> Razorpay Order -> Webhook -> Receipt."""
    # 1. Authorize User Intent (Cap: ₹1,500.00)
    intent, intent_jwt = build_user_intent_jwt(test_keys, spend_cap_paise=150000)
    res_intent = client.post("/api/v1/intent/authorize", json={"intent_jwt": intent_jwt})
    assert res_intent.status_code == 201

    # 2. Agent browses catalog
    res_catalog = client.get("/catalog.json")
    assert res_catalog.status_code == 200
    skus = [item["sku"] for item in res_catalog.json()]
    assert "CAKE-CHOC-001" in skus

    # 3. Agent requests signed cart quote for 1kg cake (₹940.00)
    res_cart = client.post(
        "/checkout/sign-cart",
        json={
            "merchant_id": "merchant_cakehouse_01",
            "line_items": [{"sku": "CAKE-CHOC-001", "quantity": 1}],
            "tax_paise": 0,
        },
    )
    assert res_cart.status_code == 200
    cart_jwt = res_cart.json()["cart_jwt"]
    assert res_cart.json()["cart"]["total_paise"] == 94000

    # 4. Policy Rail authorizes mandate and creates Razorpay Order
    idemp_key = f"tx_e2e_{uuid4().hex[:10]}"
    res_mandate = client.post(
        "/api/v1/mandate/authorize",
        json={
            "intent_jwt": intent_jwt,
            "cart_jwt": cart_jwt,
            "idempotency_key": idemp_key,
        },
    )
    assert res_mandate.status_code == 201
    mandate_data = res_mandate.json()
    assert mandate_data["mandate"]["authorized_amount_paise"] == 94000
    assert mandate_data["status"] == "ORDER_CREATED"
    razorpay_order_id = mandate_data["razorpay_order_id"]
    assert razorpay_order_id.startswith("order_mock_")

    # 5. Ingest payment.captured webhook
    raw_wh_bytes, wh_sig = simulate_payment_captured_webhook(
        razorpay_order_id=razorpay_order_id,
        amount_paise=94000,
        webhook_secret="whsec_test_secret_123",
    )

    res_wh = client.post(
        "/api/v1/webhooks/razorpay",
        content=raw_wh_bytes,
        headers={"X-Razorpay-Signature": wh_sig, "Content-Type": "application/json"},
    )
    assert res_wh.status_code == 200
    wh_data = res_wh.json()
    assert wh_data["status"] == "PAYMENT_CAPTURED"
    receipt_jwt = wh_data["receipt_jwt"]

    # 6. Verify signed PaymentReceipt
    receipt = verify_receipt_jwt(receipt_jwt, test_keys["platform"][1])
    assert receipt.amount_captured_paise == 94000
    assert receipt.razorpay_order_id == razorpay_order_id

    # 7. Forensically verify audit ledger chain endpoint
    res_ledger = client.get("/api/v1/ledger/verify-chain")
    assert res_ledger.status_code == 200
    assert res_ledger.json()["valid"] is True


def test_e2e_attack_1_over_budget(client, test_keys):
    """Attack 1: Agent tries to buy luxury cake (₹4,940.00) against ₹1,500.00 spend cap -> HTTP 403."""
    _, intent_jwt = build_user_intent_jwt(test_keys, spend_cap_paise=150000)
    client.post("/api/v1/intent/authorize", json={"intent_jwt": intent_jwt})

    res_cart = client.post(
        "/checkout/sign-cart",
        json={
            "merchant_id": "merchant_cakehouse_01",
            "line_items": [{"sku": "CAKE-PREM-001", "quantity": 1}],
            "tax_paise": 0,
        },
    )
    assert res_cart.status_code == 200
    cart_jwt = res_cart.json()["cart_jwt"]

    res_mandate = client.post(
        "/api/v1/mandate/authorize",
        json={
            "intent_jwt": intent_jwt,
            "cart_jwt": cart_jwt,
            "idempotency_key": "tx_atk_1",
        },
    )
    assert res_mandate.status_code == 403
    assert res_mandate.json()["error"]["code"] == "POLICY_SPEND_CAP_EXCEEDED"


def test_e2e_attack_2_prompt_injection(client, test_keys):
    """Attack 2: Agent attempts to purchase fake/hallucinated SKU -> HTTP 404."""
    res_cart = client.post(
        "/checkout/sign-cart",
        json={
            "merchant_id": "merchant_cakehouse_01",
            "line_items": [{"sku": "FAKE-GOLD-COIN-001", "quantity": 1}],
        },
    )
    assert res_cart.status_code == 404
    assert res_cart.json()["error"]["code"] == "CATALOG_SKU_NOT_FOUND"


def test_e2e_attack_3_cart_tampering(client, test_keys):
    """Attack 3: MITM attacker modifies cart JWT payload -> HTTP 409."""
    _, intent_jwt = build_user_intent_jwt(test_keys)
    client.post("/api/v1/intent/authorize", json={"intent_jwt": intent_jwt})

    res_cart = client.post(
        "/checkout/sign-cart",
        json={
            "merchant_id": "merchant_cakehouse_01",
            "line_items": [{"sku": "CAKE-CHOC-001", "quantity": 1}],
        },
    )
    cart_jwt = res_cart.json()["cart_jwt"]

    # Tamper payload
    header_b64, payload_b64, sig_b64 = cart_jwt.split(".")
    import base64
    payload_dict = json.loads(base64.urlsafe_b64decode(payload_b64 + "==").decode("utf-8"))
    payload_dict["total_paise"] = 1000
    tampered_b64 = base64.urlsafe_b64encode(json.dumps(payload_dict).encode("utf-8")).decode("utf-8").rstrip("=")
    tampered_jwt = f"{header_b64}.{tampered_b64}.{sig_b64}"

    res_mandate = client.post(
        "/api/v1/mandate/authorize",
        json={
            "intent_jwt": intent_jwt,
            "cart_jwt": tampered_jwt,
            "idempotency_key": "tx_atk_3",
        },
    )
    assert res_mandate.status_code == 409
    assert res_mandate.json()["error"]["code"] == "POLICY_CART_SIGNATURE_INVALID"


def test_e2e_failure_4_duplicate_webhook(client, test_keys, mock_rzp):
    """Webhook Deduplication: Duplicate webhook delivery is handled idempotently without double capture."""
    _, intent_jwt = build_user_intent_jwt(test_keys)
    client.post("/api/v1/intent/authorize", json={"intent_jwt": intent_jwt})

    res_cart = client.post(
        "/checkout/sign-cart",
        json={
            "merchant_id": "merchant_cakehouse_01",
            "line_items": [{"sku": "CAKE-CHOC-001", "quantity": 1}],
        },
    )
    cart_jwt = res_cart.json()["cart_jwt"]

    res_mandate = client.post(
        "/api/v1/mandate/authorize",
        json={
            "intent_jwt": intent_jwt,
            "cart_jwt": cart_jwt,
            "idempotency_key": "tx_dup_wh",
        },
    )
    rzp_order_id = res_mandate.json()["razorpay_order_id"]

    raw_wh_bytes, wh_sig = simulate_payment_captured_webhook(
        razorpay_order_id=rzp_order_id,
        amount_paise=94000,
        event_id="evt_fixed_duplicate_123",
    )

    # First delivery -> Captured
    res1 = client.post(
        "/api/v1/webhooks/razorpay",
        content=raw_wh_bytes,
        headers={"X-Razorpay-Signature": wh_sig, "Content-Type": "application/json"},
    )
    assert res1.status_code == 200
    assert res1.json()["status"] == "PAYMENT_CAPTURED"

    # Second delivery -> Deduplicated (200 OK)
    res2 = client.post(
        "/api/v1/webhooks/razorpay",
        content=raw_wh_bytes,
        headers={"X-Razorpay-Signature": wh_sig, "Content-Type": "application/json"},
    )
    assert res2.status_code == 200
    assert res2.json()["deduplicated"] is True


def test_razorpay_order_creation_lost_response_reconciled(client, db_session, test_keys, mock_rzp):
    """Reconciliation Test: Recovers mandate stuck in ORDER_CREATING via receipt lookup."""
    _, intent_jwt = build_user_intent_jwt(test_keys)
    client.post("/api/v1/intent/authorize", json={"intent_jwt": intent_jwt})

    res_cart = client.post(
        "/checkout/sign-cart",
        json={
            "merchant_id": "merchant_cakehouse_01",
            "line_items": [{"sku": "CAKE-CHOC-001", "quantity": 1}],
        },
    )
    cart_jwt = res_cart.json()["cart_jwt"]

    res_mandate = client.post(
        "/api/v1/mandate/authorize",
        json={
            "intent_jwt": intent_jwt,
            "cart_jwt": cart_jwt,
            "idempotency_key": "tx_reconcile_test",
        },
    )
    mandate_id = res_mandate.json()["mandate"]["mandate_id"]
    order_idemp_key = res_mandate.json()["order_idempotency_key"]

    # Artificially set status back to ORDER_CREATING to simulate dropped network response
    record = db_session.query(MandateRecord).filter_by(mandate_id=mandate_id).first()
    record.status = MandateStatus.ORDER_CREATING
    record.razorpay_order_id = None
    db_session.commit()

    # Create order at Razorpay with matching receipt
    mock_rzp.create_order(amount_paise=94000, receipt=order_idemp_key)

    # Call reconciliation endpoint
    res_rec = client.post(f"/api/v1/mandate/reconcile/{mandate_id}")
    assert res_rec.status_code == 200
    rec_data = res_rec.json()
    assert rec_data["reconciled"] is True
    assert rec_data["status"] == "ORDER_CREATED"
    assert rec_data["razorpay_order_id"] is not None


def test_razorpay_lost_response_reconciled_via_receipt(client, db_session, test_keys, mock_rzp):
    """Reconciliation Test: If no order was created at Razorpay, resets status back to RESERVED for retry."""
    _, intent_jwt = build_user_intent_jwt(test_keys)
    client.post("/api/v1/intent/authorize", json={"intent_jwt": intent_jwt})

    res_cart = client.post(
        "/checkout/sign-cart",
        json={
            "merchant_id": "merchant_cakehouse_01",
            "line_items": [{"sku": "CAKE-CHOC-001", "quantity": 1}],
        },
    )
    cart_jwt = res_cart.json()["cart_jwt"]

    res_mandate = client.post(
        "/api/v1/mandate/authorize",
        json={
            "intent_jwt": intent_jwt,
            "cart_jwt": cart_jwt,
            "idempotency_key": "tx_reconcile_retry_test",
        },
    )
    mandate_id = res_mandate.json()["mandate"]["mandate_id"]

    # Simulate dropped network before order reached Razorpay (clear from mock gateway)
    record = db_session.query(MandateRecord).filter_by(mandate_id=mandate_id).first()
    record.status = MandateStatus.ORDER_CREATING
    record.razorpay_order_id = None
    mock_rzp._mock_orders_by_receipt.pop(record.order_idempotency_key, None)
    db_session.commit()

    # Reconcile -> No order found at Razorpay -> Reset to RESERVED
    res_rec = client.post(f"/api/v1/mandate/reconcile/{mandate_id}")
    assert res_rec.status_code == 200
    rec_data = res_rec.json()
    assert rec_data["reconciled"] is False
    assert rec_data["status"] == "RESERVED"
    assert rec_data["razorpay_order_id"] is None


def test_ledger_verify_chain_endpoint(client):
    """Verify GET /api/v1/ledger/verify-chain returns valid audit status."""
    res = client.get("/api/v1/ledger/verify-chain")
    assert res.status_code == 200
    assert res.json()["valid"] is True


def test_ledger_entries_list_endpoint(client, test_keys):
    """Verify GET /api/v1/ledger/entries returns recent ledger records."""
    # Create an intent to generate an audit entry
    _, intent_jwt = build_user_intent_jwt(test_keys)
    client.post("/api/v1/intent/authorize", json={"intent_jwt": intent_jwt})

    res = client.get("/api/v1/ledger/entries?limit=10")
    assert res.status_code == 200
    entries = res.json()
    assert isinstance(entries, list)
    assert len(entries) >= 1

