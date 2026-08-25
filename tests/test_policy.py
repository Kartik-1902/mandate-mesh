"""Phase 2: Unit tests for Deterministic Policy Rail & Invariants (app/policy.py)."""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from sqlalchemy.orm import sessionmaker

from app.crypto import (
    compute_cart_hash,
    generate_es256_keypair,
    issue_cart_jwt,
    issue_intent_jwt,
)
from app.errors import (
    PolicyCartExpired,
    PolicyCartHashMismatch,
    PolicyCategoryNotAllowed,
    PolicyIntentExpired,
    PolicyMerchantNotAllowed,
    PolicyReplayDetected,
    PolicySpendCapExceeded,
    PolicyTransactionLimitReached,
    PolicyViolation,
)
from app.merchant import seed_catalog, sign_cart
from app.models import IntentRegistry, IntentStatus, MandateRecord, MandateStatus
from app.policy import authorize_mandate, verify_cart, verify_intent
from app.schemas import CartLineItem, MerchantSignedCart, UserIntentCredential


@pytest.fixture
def user_keys():
    return generate_es256_keypair()


@pytest.fixture
def merchant_keys():
    return generate_es256_keypair()


@pytest.fixture
def platform_keys():
    return generate_es256_keypair()


def build_test_intent_jwt(
    user_keys,
    spend_cap_paise=150000,
    max_transactions=1,
    nonce=None,
    allowed_categories=None,
    allowed_merchants=None,
    is_expired=False,
):
    priv, _ = user_keys
    now = datetime.now(timezone.utc)
    if is_expired:
        not_before = now - timedelta(hours=2)
        expires_at = now - timedelta(hours=1)
    else:
        not_before = now - timedelta(minutes=1)
        expires_at = now + timedelta(hours=1)

    intent = UserIntentCredential(
        user_id="user_test_01",
        spend_cap_paise=spend_cap_paise,
        allowed_categories=allowed_categories or ["bakery", "gifting"],
        allowed_merchant_ids=allowed_merchants or ["merchant_cakehouse_01"],
        max_transactions=max_transactions,
        nonce=nonce or uuid4().hex,
        not_before=not_before,
        expires_at=expires_at,
    )
    return intent, issue_intent_jwt(intent, priv)


def test_policy_within_budget_authorized(db_session, user_keys, merchant_keys, platform_keys):
    """Happy path: Cart under budget is authorized and budget is reserved in IntentRegistry."""
    u_priv, u_pub = user_keys
    m_priv, m_pub = merchant_keys
    p_priv, _ = platform_keys

    seed_catalog(db_session)
    intent, intent_jwt = build_test_intent_jwt(user_keys, spend_cap_paise=150000)

    # Price cart for ₹940 (94000 paise)
    cart_model, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=m_priv,
        db=db_session,
    )

    mandate, mandate_jwt, record = authorize_mandate(
        intent_jwt=intent_jwt,
        cart_jwt=cart_jwt,
        idempotency_key="tx_idemp_001",
        user_public_key_pem=u_pub,
        merchant_public_key_pem=m_pub,
        platform_private_key_pem=p_priv,
        db=db_session,
    )

    assert mandate.authorized_amount_paise == 94000
    assert record.status == MandateStatus.RESERVED
    assert record.reserved_paise == 94000

    # Verify IntentRegistry state
    reg = db_session.query(IntentRegistry).filter_by(intent_id=str(intent.intent_id)).first()
    assert reg.reserved_paise == 94000
    assert reg.available_paise == 56000  # 150000 - 94000
    assert reg.transactions_consumed == 1
    assert reg.status == IntentStatus.EXHAUSTED  # max_transactions=1 reached


def test_policy_exactly_at_budget_authorized(db_session, user_keys, merchant_keys, platform_keys):
    """Boundary condition: Cart exactly matching spend cap (₹940.00 == ₹940.00) is authorized."""
    u_priv, u_pub = user_keys
    m_priv, m_pub = merchant_keys
    p_priv, _ = platform_keys

    seed_catalog(db_session)
    intent, intent_jwt = build_test_intent_jwt(user_keys, spend_cap_paise=94000)

    cart_model, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=m_priv,
        db=db_session,
    )

    mandate, _, _ = authorize_mandate(
        intent_jwt=intent_jwt,
        cart_jwt=cart_jwt,
        idempotency_key="tx_idemp_exact",
        user_public_key_pem=u_pub,
        merchant_public_key_pem=m_pub,
        platform_private_key_pem=p_priv,
        db=db_session,
    )
    assert mandate.authorized_amount_paise == 94000

    reg = db_session.query(IntentRegistry).filter_by(intent_id=str(intent.intent_id)).first()
    assert reg.available_paise == 0


def test_policy_over_budget_blocked(db_session, user_keys, merchant_keys, platform_keys):
    """Attack 1: Cart exceeds user spend cap (₹4,940.00 vs ₹1,500.00 cap) and is blocked."""
    u_priv, u_pub = user_keys
    m_priv, m_pub = merchant_keys
    p_priv, _ = platform_keys

    seed_catalog(db_session)
    intent, intent_jwt = build_test_intent_jwt(user_keys, spend_cap_paise=150000)

    # Price luxury cake costing ₹4,940 (494000 paise)
    cart_model, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-PREM-001", "quantity": 1}],
        merchant_private_key_pem=m_priv,
        db=db_session,
    )

    with pytest.raises(PolicySpendCapExceeded, match="exceeds available budget"):
        authorize_mandate(
            intent_jwt=intent_jwt,
            cart_jwt=cart_jwt,
            idempotency_key="tx_idemp_over",
            user_public_key_pem=u_pub,
            merchant_public_key_pem=m_pub,
            platform_private_key_pem=p_priv,
            db=db_session,
        )

    # Invariant: Zero funds reserved, zero mandate records persisted
    reg = db_session.query(IntentRegistry).filter_by(intent_id=str(intent.intent_id)).first()
    assert reg.reserved_paise == 0
    assert reg.transactions_consumed == 0
    assert db_session.query(MandateRecord).count() == 0


def test_policy_nonce_is_checked_per_intent_registration(db_session, user_keys):
    """Intent replay protection: Attempting to register two different intent IDs with identical nonce fails."""
    _, u_pub = user_keys
    nonce = "fixed_nonce_123"

    _, jwt1 = build_test_intent_jwt(user_keys, nonce=nonce)
    _, jwt2 = build_test_intent_jwt(user_keys, nonce=nonce)

    # First registration succeeds
    verify_intent(jwt1, u_pub, db_session)

    # Second registration with different intent_id but same nonce is rejected
    with pytest.raises(PolicyReplayDetected, match="nonce 'fixed_nonce_123' has already been used"):
        verify_intent(jwt2, u_pub, db_session)


def test_same_intent_allows_multiple_distinct_mandates(db_session, user_keys, merchant_keys, platform_keys):
    """Multi-transaction intent: An intent with max_transactions=2 allows two separate mandates."""
    u_priv, u_pub = user_keys
    m_priv, m_pub = merchant_keys
    p_priv, _ = platform_keys

    seed_catalog(db_session)
    intent, intent_jwt = build_test_intent_jwt(user_keys, spend_cap_paise=200000, max_transactions=2)

    # Tx 1: ₹940
    _, cart1_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=m_priv,
        db=db_session,
    )
    authorize_mandate(intent_jwt, cart1_jwt, "idemp_tx_1", u_pub, m_pub, p_priv, db_session)

    # Tx 2: ₹850
    _, cart2_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-VAN-001", "quantity": 1}],
        merchant_private_key_pem=m_priv,
        db=db_session,
    )
    authorize_mandate(intent_jwt, cart2_jwt, "idemp_tx_2", u_pub, m_pub, p_priv, db_session)

    reg = db_session.query(IntentRegistry).filter_by(intent_id=str(intent.intent_id)).first()
    assert reg.reserved_paise == 179000  # 94000 + 85000
    assert reg.transactions_consumed == 2
    assert reg.status == IntentStatus.EXHAUSTED

    # Tx 3: Attempt third transaction -> rejected
    with pytest.raises(PolicyTransactionLimitReached):
        authorize_mandate(intent_jwt, cart1_jwt, "idemp_tx_3", u_pub, m_pub, p_priv, db_session)


def test_same_transaction_identity_is_replay(db_session, user_keys, merchant_keys, platform_keys):
    """Replay attack: Re-submitting the same idempotency_key for the same intent fails with PolicyReplayDetected."""
    u_priv, u_pub = user_keys
    m_priv, m_pub = merchant_keys
    p_priv, _ = platform_keys

    seed_catalog(db_session)
    intent, intent_jwt = build_test_intent_jwt(user_keys, spend_cap_paise=200000, max_transactions=2)

    _, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=m_priv,
        db=db_session,
    )

    authorize_mandate(intent_jwt, cart_jwt, "duplicate_idemp_key", u_pub, m_pub, p_priv, db_session)

    # Same (intent_id, idempotency_key) attempt is rejected
    with pytest.raises(PolicyReplayDetected, match="Transaction replay detected"):
        authorize_mandate(intent_jwt, cart_jwt, "duplicate_idemp_key", u_pub, m_pub, p_priv, db_session)


def test_policy_wrong_category_blocked(db_session, user_keys, merchant_keys, platform_keys):
    """Category constraint: Buying items in disallowed category ('electronics') is blocked."""
    u_priv, u_pub = user_keys
    m_priv, m_pub = merchant_keys
    p_priv, _ = platform_keys

    seed_catalog(db_session)
    intent, intent_jwt = build_test_intent_jwt(user_keys, allowed_categories=["bakery"])

    # Electronics item in cart
    _, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "ELEC-HEAD-001", "quantity": 1}],
        merchant_private_key_pem=m_priv,
        db=db_session,
    )

    with pytest.raises(PolicyCategoryNotAllowed, match="category 'electronics' is not in authorized categories"):
        authorize_mandate(intent_jwt, cart_jwt, "tx_wrong_cat", u_pub, m_pub, p_priv, db_session)


def test_policy_wrong_merchant_blocked(db_session, user_keys, merchant_keys, platform_keys):
    """Merchant constraint: Purchasing from unauthorized merchant is blocked."""
    u_priv, u_pub = user_keys
    m_priv, m_pub = merchant_keys
    p_priv, _ = platform_keys

    seed_catalog(db_session)
    intent, intent_jwt = build_test_intent_jwt(user_keys, allowed_merchants=["merchant_cakehouse_01"])

    # Signed with unauthorized merchant ID
    item = CartLineItem(sku="SKU-1", name="Cake", category="bakery", unit_price_paise=94000, quantity=1)
    unauthorized_cart = MerchantSignedCart(
        merchant_id="merchant_rogue_99",
        line_items=[item],
        tax_paise=0,
        currency="INR",
        cart_hash="",
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    unauthorized_cart.cart_hash = compute_cart_hash(unauthorized_cart)
    cart_jwt = issue_cart_jwt(unauthorized_cart, m_priv)

    with pytest.raises(PolicyMerchantNotAllowed, match="Merchant 'merchant_rogue_99' is not in authorized merchants"):
        authorize_mandate(intent_jwt, cart_jwt, "tx_wrong_merch", u_pub, m_pub, p_priv, db_session)


def test_policy_expired_intent_blocked(db_session, user_keys, merchant_keys, platform_keys):
    """Expired intent: Intent expired in the past is rejected."""
    _, u_pub = user_keys
    m_priv, m_pub = merchant_keys
    p_priv, _ = platform_keys

    seed_catalog(db_session)
    _, intent_jwt = build_test_intent_jwt(user_keys, is_expired=True)

    _, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=m_priv,
        db=db_session,
    )

    with pytest.raises(PolicyIntentExpired):
        authorize_mandate(intent_jwt, cart_jwt, "tx_exp_intent", u_pub, m_pub, p_priv, db_session)


def test_policy_expired_cart_blocked(db_session, user_keys, merchant_keys, platform_keys):
    """Expired cart: Cart quote with expired 5-minute TTL is rejected."""
    _, u_pub = user_keys
    m_priv, m_pub = merchant_keys
    p_priv, _ = platform_keys

    seed_catalog(db_session)
    _, intent_jwt = build_test_intent_jwt(user_keys)

    # Cart with negative TTL (expired in past)
    _, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=m_priv,
        db=db_session,
        ttl_seconds=-10,
    )

    with pytest.raises(PolicyCartExpired):
        authorize_mandate(intent_jwt, cart_jwt, "tx_exp_cart", u_pub, m_pub, p_priv, db_session)


def test_policy_cart_hash_mismatch_blocked(db_session, user_keys, merchant_keys, platform_keys):
    """Attack 3: MITM tampering with cart line items or total causes cart_hash mismatch failure."""
    _, u_pub = user_keys
    m_priv, m_pub = merchant_keys
    p_priv, _ = platform_keys

    seed_catalog(db_session)
    _, intent_jwt = build_test_intent_jwt(user_keys)

    # Legitimate cart signed by merchant
    _, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=m_priv,
        db=db_session,
    )

    # Attacker alters total_paise or line item without resigning or with altered cart_hash
    header_b64, payload_b64, sig_b64 = cart_jwt.split(".")
    import base64
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "==").decode("utf-8"))
    payload["total_paise"] = 1000  # Attacker attempts to forge price
    tampered_payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
    tampered_cart_jwt = f"{header_b64}.{tampered_payload_b64}.{sig_b64}"

    with pytest.raises(PolicyViolation):
        authorize_mandate(intent_jwt, tampered_cart_jwt, "tx_tamper", u_pub, m_pub, p_priv, db_session)


def test_concurrent_reservations_cannot_overspend(db_session, engine, user_keys, merchant_keys, platform_keys):
    """Multi-threaded concurrency test: Two concurrent ₹940 reservations against a ₹1,500 cap.
    Guarantees exactly ONE succeeds and ONE fails (never overspends the cap)."""
    import concurrent.futures
    SessionLocal = sessionmaker(bind=engine)

    init_session = SessionLocal()
    seed_catalog(init_session)
    intent, intent_jwt = build_test_intent_jwt(user_keys, spend_cap_paise=150000, max_transactions=2)
    verify_intent(intent_jwt, user_keys[1], init_session)
    init_session.commit()
    init_session.close()

    m_priv, m_pub = merchant_keys
    u_priv, u_pub = user_keys
    p_priv, _ = platform_keys

    # Price cart for ₹940
    cart_session = SessionLocal()
    _, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=m_priv,
        db=cart_session,
    )
    cart_session.close()

    results = []

    def try_reserve(tx_id: str):
        session = SessionLocal()
        try:
            mandate, _, _ = authorize_mandate(
                intent_jwt=intent_jwt,
                cart_jwt=cart_jwt,
                idempotency_key=tx_id,
                user_public_key_pem=u_pub,
                merchant_public_key_pem=m_pub,
                platform_private_key_pem=p_priv,
                db=session,
            )
            return "SUCCESS", mandate.authorized_amount_paise
        except PolicySpendCapExceeded:
            return "REJECTED_OVERSPEND", 0
        finally:
            session.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(try_reserve, "concurrent_tx_1")
        f2 = executor.submit(try_reserve, "concurrent_tx_2")
        results = [f1.result(), f2.result()]

    statuses = [r[0] for r in results]
    assert "SUCCESS" in statuses
    assert "REJECTED_OVERSPEND" in statuses

    # Verify final registry state
    verify_session = SessionLocal()
    reg = verify_session.query(IntentRegistry).filter_by(intent_id=str(intent.intent_id)).first()
    assert reg.reserved_paise == 94000  # Exactly 1 reservation succeeded, NOT 188000
    assert reg.available_paise == 56000
    verify_session.close()
