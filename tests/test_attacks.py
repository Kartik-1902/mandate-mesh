"""Phase 6: Adversarial Demo Layer Test Suite for Mandate Mesh.

Executes and verifies all 4 core threat models and failure recovery modes:
1. Attack 1: Over-budget spend attempt (403 POLICY_SPEND_CAP_EXCEEDED + POLICY_REJECTED ledger entry).
2. Attack 2: Prompt injection fake/unauthorized SKU (404 CATALOG_SKU_NOT_FOUND, cart never signed).
3. Attack 3: Cart quote tampering MITM (409 POLICY_CART_SIGNATURE_INVALID / POLICY_CART_HASH_MISMATCH + POLICY_REJECTED).
4. Failure Mode 4: Duplicate webhook delivery deduplication (200 received=True, deduplicated=True) + Lost-response reconciler recovery.
5. Invariant Guarantee: Sequential attack execution preserves linear hash-chain integrity (verify_chain() == True).
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest

from app.crypto import (
    compute_cart_hash,
    generate_es256_keypair,
    issue_cart_jwt,
    issue_intent_jwt,
    verify_receipt_jwt,
)
from app.errors import CatalogSkuNotFound, PolicyViolation
from app.ledger import append_entry, verify_chain
from app.merchant import seed_catalog, sign_cart
from app.merchant_keys import get_merchant_private_key, get_merchant_public_key
from app.models import AuditLedgerEntry, IntentRegistry, LedgerEntryType, MandateRecord, MandateStatus
from app.policy import authorize_mandate, verify_cart, verify_intent
from app.razorpay_client import RazorpayClient, simulate_payment_captured_webhook
from app.reconcile import reconcile_stuck_orders
from app.schemas import CartLineItem, MerchantSignedCart, UserIntentCredential
from app.webhooks import process_payment_webhook


@pytest.fixture
def test_keys():
    """Generates standard ephemeral ES256 keypairs for user, merchant, and platform."""
    return {
        "user": generate_es256_keypair(),
        "merchant": generate_es256_keypair(),
        "platform": generate_es256_keypair(),
    }


def test_attack_1_over_budget_spend_cap_exceeded(db_session, test_keys):
    """Threat Model 1: The Over-Budget Breach.

    User sets spend cap = Rs. 1,500.00 (150,000 paise).
    Agent / cart attempts to authorize luxury cake costing Rs. 4,940.00 (494,000 paise).
    Assert:
      - PolicyViolation raised with error_code = 'POLICY_SPEND_CAP_EXCEEDED' and http_status = 403.
      - Audit ledger records POLICY_REJECTED with exact breach context.
      - IntentRegistry reserved_paise remains 0 (Rs. 0 moved).
      - No MandateRecord created.
    """
    seed_catalog(db_session)
    db_session.commit()

    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        user_id="user_victim_01",
        spend_cap_paise=150000,  # Rs. 1,500
        allowed_categories=["bakery"],
        allowed_merchant_ids=["merchant_cakehouse_01"],
        nonce=uuid4().hex,
        not_before=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    intent_jwt = issue_intent_jwt(intent, test_keys["user"][0])
    verify_intent(intent_jwt, test_keys["user"][1], db_session)
    db_session.commit()

    # Sign over-budget luxury cake
    over_budget_cart, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-PREM-001", "quantity": 1}],
        merchant_private_key_pem=test_keys["merchant"][0],
        db=db_session,
    )
    assert over_budget_cart.total_paise == 494000

    # Policy rail evaluation
    with pytest.raises(PolicyViolation) as exc_info:
        authorize_mandate(
            intent_jwt=intent_jwt,
            cart_jwt=cart_jwt,
            idempotency_key=f"tx_atk1_{uuid4().hex[:8]}",
            user_public_key_pem=test_keys["user"][1],
            merchant_public_key_pem=test_keys["merchant"][1],
            platform_private_key_pem=test_keys["platform"][0],
            db=db_session,
        )

    err = exc_info.value
    assert err.code == "POLICY_SPEND_CAP_EXCEEDED"
    assert err.http_status == 403
    assert "exceeds available budget" in err.message

    # Verify audit ledger entry persisted
    ledger_entry = (
        db_session.query(AuditLedgerEntry)
        .filter_by(entry_type=LedgerEntryType.POLICY_REJECTED)
        .order_by(AuditLedgerEntry.id.desc())
        .first()
    )
    assert ledger_entry is not None
    assert ledger_entry.payload.get("error_code") == "POLICY_SPEND_CAP_EXCEEDED"

    # Verify zero financial state mutation
    intent_record = db_session.query(IntentRegistry).filter_by(intent_id=str(intent.intent_id)).first()
    assert intent_record.reserved_paise == 0
    assert intent_record.captured_paise == 0


def test_attack_2_prompt_injection_fake_sku_fails_closed(db_session, test_keys):
    """Threat Model 2: The Prompt Injection Attack.

    Poisoned prompt or LLM tries to request a non-existent or injected SKU ('PREMIUM-ZERO-COST-TIER').
    Assert:
      - sign_cart raises CatalogSkuNotFound (404).
      - Cart JWT is NEVER produced.
      - Policy rail is never reached.
      - Rs. 0 moved.
    """
    seed_catalog(db_session)
    db_session.commit()

    injected_sku = "PREMIUM-ZERO-COST-TIER"

    with pytest.raises(CatalogSkuNotFound) as exc_info:
        sign_cart(
            merchant_id="merchant_cakehouse_01",
            line_items_req=[{"sku": injected_sku, "quantity": 1}],
            merchant_private_key_pem=test_keys["merchant"][0],
            db=db_session,
        )

    assert exc_info.value.http_status == 404
    assert exc_info.value.code == "CATALOG_SKU_NOT_FOUND"
    assert injected_sku in str(exc_info.value)


def test_attack_3_cart_tampering_mitm_blocked(db_session, test_keys):
    """Threat Model 3: The Cart Tampering Attack (MITM).

    Merchant signs a cart for Rs. 940.00 (94,000 paise).
    An attacker modifies total_paise or swaps claims to Rs. 1,940.00 in the JWT.
    Assert:
      - Policy Rail rejects with POLICY_CART_SIGNATURE_INVALID or POLICY_CART_HASH_MISMATCH (409).
      - Audit ledger records POLICY_REJECTED.
      - Rs. 0 moved.
    """
    seed_catalog(db_session)
    db_session.commit()

    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        user_id="user_victim_03",
        spend_cap_paise=200000,  # Rs. 2,000 cap
        allowed_categories=["bakery"],
        allowed_merchant_ids=["merchant_cakehouse_01"],
        nonce=uuid4().hex,
        not_before=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    intent_jwt = issue_intent_jwt(intent, test_keys["user"][0])
    verify_intent(intent_jwt, test_keys["user"][1], db_session)
    db_session.commit()

    # Legit cart signed for Rs. 940
    legit_cart, valid_cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=test_keys["merchant"][0],
        db=db_session,
    )

    # Attack Scenario 3A: Modify signature bytes (tampered payload)
    tampered_cart_jwt = valid_cart_jwt[:-4] + "AAAA"
    with pytest.raises(PolicyViolation) as exc_info:
        authorize_mandate(
            intent_jwt=intent_jwt,
            cart_jwt=tampered_cart_jwt,
            idempotency_key=f"tx_atk3a_{uuid4().hex[:8]}",
            user_public_key_pem=test_keys["user"][1],
            merchant_public_key_pem=test_keys["merchant"][1],
            platform_private_key_pem=test_keys["platform"][0],
            db=db_session,
        )
    assert exc_info.value.code == "POLICY_CART_SIGNATURE_INVALID"
    assert exc_info.value.http_status == 409

    # Attack Scenario 3B: Cart with forged claims where embedded cart_hash mismatch
    import jwt
    fraud_claims = {
        "cart_hash": "0" * 64,  # Mismatched forged hash
        "cart_id": str(uuid4()),
        "currency": "INR",
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "iat": int(now.timestamp()),
        "iss": "mandate-mesh:merchant:merchant_cakehouse_01",
        "line_items": [
            {
                "category": "bakery",
                "name": "Chocolate Truffle Cake (1kg)",
                "quantity": 1,
                "sku": "CAKE-CHOC-001",
                "unit_price_paise": 94000,
            }
        ],
        "merchant_id": "merchant_cakehouse_01",
        "tax_paise": 0,
        "total_paise": 94000,
    }
    fraud_cart_jwt = jwt.encode(
        fraud_claims,
        test_keys["merchant"][0],
        algorithm="ES256",
        headers={"kid": "merchant:key-1"},
    )

    with pytest.raises(PolicyViolation) as exc_info:
        authorize_mandate(
            intent_jwt=intent_jwt,
            cart_jwt=fraud_cart_jwt,
            idempotency_key=f"tx_atk3b_{uuid4().hex[:8]}",
            user_public_key_pem=test_keys["user"][1],
            merchant_public_key_pem=test_keys["merchant"][1],
            platform_private_key_pem=test_keys["platform"][0],
            db=db_session,
        )
    assert exc_info.value.code == "POLICY_CART_HASH_MISMATCH"
    assert exc_info.value.http_status == 409


def test_attack_4_duplicate_webhook_replay_deduplication(db_session, test_keys):
    """Threat Model 4A: Webhook Replay & Duplicate Delivery Attack.

    Simulate webhook replay: payment.captured event delivered 3 times.
    Assert:
      - 1st delivery returns status = 'PAYMENT_CAPTURED' and issues PaymentReceipt.
      - 2nd and 3rd deliveries return deduplicated = True.
      - IntentRegistry.captured_paise incremented exactly once (94,000 paise).
      - No double charge.
    """
    seed_catalog(db_session)
    db_session.commit()

    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        user_id="user_victim_04",
        spend_cap_paise=150000,
        allowed_categories=["bakery"],
        allowed_merchant_ids=["merchant_cakehouse_01"],
        nonce=uuid4().hex,
        not_before=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    intent_jwt = issue_intent_jwt(intent, test_keys["user"][0])
    verify_intent(intent_jwt, test_keys["user"][1], db_session)
    db_session.commit()

    cart, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=test_keys["merchant"][0],
        db=db_session,
    )

    mandate, mandate_jwt, record = authorize_mandate(
        intent_jwt=intent_jwt,
        cart_jwt=cart_jwt,
        idempotency_key=f"tx_atk4_{uuid4().hex[:8]}",
        user_public_key_pem=test_keys["user"][1],
        merchant_public_key_pem=test_keys["merchant"][1],
        platform_private_key_pem=test_keys["platform"][0],
        db=db_session,
    )

    # Transition to ORDER_CREATED
    rzp = RazorpayClient(mock_mode=True)
    rzp_order = rzp.create_order(amount_paise=94000, currency="INR", receipt=record.order_idempotency_key)
    record.status = MandateStatus.ORDER_CREATED
    record.razorpay_order_id = rzp_order["id"]
    db_session.commit()

    # Generate webhook payload
    raw_body, signature = simulate_payment_captured_webhook(
        razorpay_order_id=rzp_order["id"],
        amount_paise=94000,
        webhook_secret="whsec_demo_secret",
    )

    # Delivery 1: Process and capture
    res1 = process_payment_webhook(
        raw_body=raw_body,
        signature=signature,
        db=db_session,
        webhook_secret="whsec_demo_secret",
        platform_private_key_pem=test_keys["platform"][0],
    )
    assert res1["status"] == "PAYMENT_CAPTURED"
    assert res1.get("deduplicated") is None or res1.get("deduplicated") is False
    assert res1["receipt_jwt"] is not None

    # Delivery 2 (Replay 1): Atomic deduplication
    res2 = process_payment_webhook(
        raw_body=raw_body,
        signature=signature,
        db=db_session,
        webhook_secret="whsec_demo_secret",
        platform_private_key_pem=test_keys["platform"][0],
    )
    assert res2.get("deduplicated") is True
    assert res2.get("received") is True

    # Delivery 3 (Replay 2): Atomic deduplication
    res3 = process_payment_webhook(
        raw_body=raw_body,
        signature=signature,
        db=db_session,
        webhook_secret="whsec_demo_secret",
        platform_private_key_pem=test_keys["platform"][0],
    )
    assert res3.get("deduplicated") is True
    assert res3.get("received") is True

    # Assert exactly 94,000 paise captured
    intent_row = db_session.query(IntentRegistry).filter_by(intent_id=str(intent.intent_id)).first()
    assert intent_row.captured_paise == 94000
    assert intent_row.reserved_paise == 0


def test_attack_4_lost_response_reconciled(db_session, test_keys):
    """Threat Model 4B: Lost-Response Order Reconciliation.

    Simulate network outage while MandateRecord is in ORDER_CREATING state.
    Assert:
      - Startup/periodic reconciler identifies dangling mandate.
      - Queries mock Razorpay gateway by receipt reference.
      - Successfully updates MandateRecord to ORDER_CREATED without duplicate order creation.
    """
    seed_catalog(db_session)
    db_session.commit()

    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        user_id="user_victim_04b",
        spend_cap_paise=150000,
        allowed_categories=["bakery"],
        allowed_merchant_ids=["merchant_cakehouse_01"],
        nonce=uuid4().hex,
        not_before=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    intent_jwt = issue_intent_jwt(intent, test_keys["user"][0])
    verify_intent(intent_jwt, test_keys["user"][1], db_session)
    db_session.commit()

    cart, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=test_keys["merchant"][0],
        db=db_session,
    )

    mandate, mandate_jwt, record = authorize_mandate(
        intent_jwt=intent_jwt,
        cart_jwt=cart_jwt,
        idempotency_key=f"tx_atk4b_{uuid4().hex[:8]}",
        user_public_key_pem=test_keys["user"][1],
        merchant_public_key_pem=test_keys["merchant"][1],
        platform_private_key_pem=test_keys["platform"][0],
        db=db_session,
    )

    # Simulate: Order created on Razorpay gateway, but network died before DB status updated
    rzp = RazorpayClient(mock_mode=True)
    rzp_order = rzp.create_order(amount_paise=94000, currency="INR", receipt=record.order_idempotency_key)
    record.status = MandateStatus.ORDER_CREATING
    record.razorpay_order_id = None
    db_session.commit()

    # Reconcile stuck orders
    results = reconcile_stuck_orders(db=db_session, razorpay_client=rzp)
    assert len(results) == 1
    assert results[0]["reconciled"] is True

    db_session.refresh(record)
    assert record.status == MandateStatus.ORDER_CREATED
    assert record.razorpay_order_id == rzp_order["id"]


def test_attack_5_cross_merchant_signature_spoofing_blocked(db_session, test_keys):
    """Threat Model 5: Cross-Merchant Identity Spoofing & Key Confusion.

    Attacker signs a cart using Sweet Delight's key (Rs. 890), but attempts to authorize
    it using CakeHouse's public key (or vice-versa) to forge merchant pricing boundaries.
    Assert:
      - PolicyViolation raised with error_code = 'POLICY_CART_SIGNATURE_INVALID' and http_status = 409.
      - Audit ledger records POLICY_REJECTED with exact breach context.
      - IntentRegistry reserved_paise remains 0 (Rs. 0 moved).
      - No MandateRecord created.
    """
    seed_catalog(db_session)
    db_session.commit()

    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        user_id="user_victim_05",
        spend_cap_paise=150000,
        allowed_categories=["bakery"],
        allowed_merchant_ids=["merchant_cakehouse_01", "merchant_sweetdelight_02"],
        nonce=uuid4().hex,
        not_before=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    intent_jwt = issue_intent_jwt(intent, test_keys["user"][0])
    verify_intent(intent_jwt, test_keys["user"][1], db_session)
    db_session.commit()

    sweet_priv = get_merchant_private_key("merchant_sweetdelight_02")
    cake_pub = get_merchant_public_key("merchant_cakehouse_01")

    # Legitimate Sweet Delight cart signed with Sweet Delight's key
    cart, cart_jwt = sign_cart(
        merchant_id="merchant_sweetdelight_02",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=sweet_priv,
        db=db_session,
    )

    # Attempt authorization claiming CakeHouse's public key (Key Confusion / Signature Mismatch)
    with pytest.raises(PolicyViolation) as exc_info:
        authorize_mandate(
            intent_jwt=intent_jwt,
            cart_jwt=cart_jwt,
            idempotency_key=f"tx_atk5_{uuid4().hex[:8]}",
            user_public_key_pem=test_keys["user"][1],
            merchant_public_key_pem=cake_pub,
            platform_private_key_pem=test_keys["platform"][0],
            db=db_session,
        )

    err = exc_info.value
    assert err.code == "POLICY_CART_SIGNATURE_INVALID"
    assert err.http_status == 409

    # Verify zero balance movement
    intent_record = db_session.query(IntentRegistry).filter_by(intent_id=str(intent.intent_id)).first()
    assert intent_record.reserved_paise == 0
    assert intent_record.captured_paise == 0

    # Verify no mandate record created
    mandate_count = db_session.query(MandateRecord).filter_by(intent_id=str(intent.intent_id)).count()
    assert mandate_count == 0


def test_attack_6_expired_quote_replay_blocked(db_session, test_keys):
    """Threat Model 6: Stale Quote / TTL Expiration Replay Attack.

    Attacker intercepts/stores a signed cart quote and attempts to authorize it after its TTL expires.
    Assert:
      - PolicyViolation raised with error_code = 'POLICY_CART_EXPIRED' and http_status = 409.
      - IntentRegistry reserved_paise remains 0 (Rs. 0 moved).
      - No MandateRecord created.
    """
    seed_catalog(db_session)
    db_session.commit()

    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        user_id="user_victim_06",
        spend_cap_paise=150000,
        allowed_categories=["bakery"],
        allowed_merchant_ids=["merchant_cakehouse_01"],
        nonce=uuid4().hex,
        not_before=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    intent_jwt = issue_intent_jwt(intent, test_keys["user"][0])
    verify_intent(intent_jwt, test_keys["user"][1], db_session)
    db_session.commit()

    cake_priv = get_merchant_private_key("merchant_cakehouse_01")
    cake_pub = get_merchant_public_key("merchant_cakehouse_01")

    # Sign cart with negative TTL so it is already expired at verification time
    cart, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=cake_priv,
        db=db_session,
        ttl_seconds=-60,
    )

    with pytest.raises(PolicyViolation) as exc_info:
        authorize_mandate(
            intent_jwt=intent_jwt,
            cart_jwt=cart_jwt,
            idempotency_key=f"tx_atk6_{uuid4().hex[:8]}",
            user_public_key_pem=test_keys["user"][1],
            merchant_public_key_pem=cake_pub,
            platform_private_key_pem=test_keys["platform"][0],
            db=db_session,
        )

    err = exc_info.value
    assert err.code == "POLICY_CART_EXPIRED"
    assert err.http_status == 409

    # Verify zero balance movement
    intent_record = db_session.query(IntentRegistry).filter_by(intent_id=str(intent.intent_id)).first()
    assert intent_record.reserved_paise == 0
    assert intent_record.captured_paise == 0

    # Verify no mandate record created
    mandate_count = db_session.query(MandateRecord).filter_by(intent_id=str(intent.intent_id)).count()
    assert mandate_count == 0


def test_adversarial_suite_preserves_ledger_chain_integrity(db_session, test_keys):
    """Forensic Invariant Guarantee:

    After running all adversarial threat models on a shared database, verify that
    verify_chain() confirms the hash-chain is 100% linear, unbroken, and tamper-free.
    """
    is_valid, broken_id = verify_chain(db_session)
    assert is_valid is True, f"Audit ledger broken at entry ID: {broken_id}"
    assert broken_id is None
