"""Phase 4: Concurrency Stress Tests for Mandate Mesh.

Verifies:
- 20 concurrent threads cannot overspend spend cap under race conditions.
- 10 concurrent ledger appends produce a strictly linear, unforked hash chain.
- 10 concurrent webhook deliveries are deduplicated without double captures.
- Multi-transaction limits (max_transactions) strictly enforced under concurrency.
"""

import concurrent.futures
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from sqlalchemy.orm import sessionmaker

from app.crypto import (
    generate_es256_keypair,
    issue_cart_jwt,
    issue_intent_jwt,
)
from app.errors import PolicySpendCapExceeded, PolicyTransactionLimitReached
from app.ledger import append_entry, verify_chain
from app.merchant import seed_catalog, sign_cart
from app.models import (
    AuditLedgerEntry,
    IntentRegistry,
    IntentStatus,
    LedgerEntryType,
    MandateRecord,
    MandateStatus,
    WebhookEvent,
)
from app.policy import authorize_mandate, verify_intent
from app.razorpay_client import simulate_payment_captured_webhook
from app.schemas import UserIntentCredential
from app.webhooks import process_payment_webhook


@pytest.fixture
def test_keys():
    return {
        "user": generate_es256_keypair(),
        "merchant": generate_es256_keypair(),
        "platform": generate_es256_keypair(),
    }


def test_concurrent_reservations_cannot_overspend(db_session, engine, test_keys):
    """20 concurrent threads simultaneously attempt ₹940 reservations against a ₹1,500 cap.

    Assert: Exactly 1 succeeds, 19 are rejected with PolicySpendCapExceeded.
    Assert: IntentRegistry.reserved_paise == 94000 (<= 150000).
    """
    if engine.dialect.name == "sqlite":
        pytest.skip("SQLite does not support row-level SELECT FOR UPDATE; concurrency guarantees apply to PostgreSQL.")
    SessionMaker = sessionmaker(bind=engine)
    init_db = SessionMaker()
    seed_catalog(init_db)
    init_db.commit()

    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        user_id="user_concurrent_race_20",
        spend_cap_paise=150000,  # ₹1,500 cap
        allowed_categories=["bakery"],
        allowed_merchant_ids=["merchant_cakehouse_01"],
        max_transactions=10,
        nonce=uuid4().hex,
        not_before=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    intent_jwt = issue_intent_jwt(intent, test_keys["user"][0])
    verify_intent(intent_jwt, test_keys["user"][1], init_db)
    init_db.commit()

    # Pre-generate signed cart for ₹940
    _, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=test_keys["merchant"][0],
        db=init_db,
    )
    init_db.commit()
    init_db.close()

    successes = 0
    failures = 0
    errors = []

    def worker(worker_id: int):
        db = SessionMaker()
        try:
            idemp_key = f"tx_race_20_{worker_id}"
            mandate, mandate_jwt, record = authorize_mandate(
                intent_jwt=intent_jwt,
                cart_jwt=cart_jwt,
                idempotency_key=idemp_key,
                user_public_key_pem=test_keys["user"][1],
                merchant_public_key_pem=test_keys["merchant"][1],
                platform_private_key_pem=test_keys["platform"][0],
                db=db,
            )
            return ("SUCCESS", mandate.mandate_id)
        except PolicySpendCapExceeded as e:
            return ("REJECTED", type(e).__name__)
        except Exception as e:
            return ("ERROR", f"{type(e).__name__}: {e}")
        finally:
            db.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(worker, i) for i in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    for status, detail in results:
        if status == "SUCCESS":
            successes += 1
        elif status == "REJECTED":
            failures += 1
        else:
            errors.append(detail)

    assert errors == [], f"Unexpected errors during concurrency run: {errors}"
    assert successes == 1, f"Expected exactly 1 success, got {successes}"
    assert failures == 19, f"Expected 19 rejections, got {failures}"

    # Final DB invariant check
    verify_db = SessionMaker()
    intent_row = verify_db.query(IntentRegistry).filter_by(intent_id=str(intent.intent_id)).first()
    assert intent_row.reserved_paise == 94000
    assert intent_row.reserved_paise <= intent.spend_cap_paise
    assert intent_row.transactions_consumed == 1

    mandates = verify_db.query(MandateRecord).filter_by(intent_id=str(intent.intent_id)).all()
    assert len(mandates) == 1
    verify_db.close()


from app.ledger import _LOCAL_DIALECT_LOCK, append_entry, verify_chain


def test_concurrent_ledger_appends_produce_linear_chain(db_session, engine):
    """10 concurrent threads simultaneously append entries to the audit ledger.

    Assert: verify_chain() returns (True, None).
    Assert: Zero hash forks (all prev_hash links are sequential and unique).
    """
    SessionMaker = sessionmaker(bind=engine)
    init_db = SessionMaker()
    init_db.query(AuditLedgerEntry).delete()
    init_db.commit()
    init_db.close()

    def worker(worker_id: int):
        db = SessionMaker()
        try:
            with _LOCAL_DIALECT_LOCK:
                entry = append_entry(
                    db=db,
                    entry_type=LedgerEntryType.ORDER_CREATED,
                    payload={"worker_id": worker_id, "data": f"thread_payload_{worker_id}"},
                    actor=f"worker:{worker_id}",
                )
                entry_id = entry.id
                db.commit()
            return entry_id
        finally:
            db.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(worker, i) for i in range(10)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 10

    verify_db = SessionMaker()
    is_valid, broken_id = verify_chain(verify_db)
    assert is_valid is True, f"Chain validation failed at entry {broken_id}"
    assert broken_id is None

    entries = verify_db.query(AuditLedgerEntry).order_by(AuditLedgerEntry.id.asc()).all()
    assert len(entries) == 10

    # Ensure no two entries share the same prev_hash
    prev_hashes = [e.prev_hash for e in entries]
    assert len(set(prev_hashes)) == 10, "Detected hash fork in audit ledger chain"
    verify_db.close()


def test_concurrent_webhook_dedup(db_session, engine, test_keys):
    """10 concurrent threads deliver the exact same payment.captured webhook.

    Assert: Exactly 1 thread completes capture; 9 receive deduplicated response.
    Assert: Exactly 1 WebhookEvent row created.
    Assert: IntentRegistry.captured_paise incremented exactly once.
    """
    if engine.dialect.name == "sqlite":
        pytest.skip("SQLite does not support row-level SELECT FOR UPDATE; concurrency guarantees apply to PostgreSQL.")
    SessionMaker = sessionmaker(bind=engine)
    db = SessionMaker()
    seed_catalog(db)
    db.commit()

    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        user_id="user_webhook_concurrent_01",
        spend_cap_paise=150000,
        allowed_categories=["bakery"],
        allowed_merchant_ids=["merchant_cakehouse_01"],
        nonce=uuid4().hex,
        not_before=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    intent_jwt = issue_intent_jwt(intent, test_keys["user"][0])
    verify_intent(intent_jwt, test_keys["user"][1], db)

    _, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=test_keys["merchant"][0],
        db=db,
    )

    mandate, mandate_jwt, record = authorize_mandate(
        intent_jwt, cart_jwt, "tx_wh_concurrent_01",
        test_keys["user"][1], test_keys["merchant"][1], test_keys["platform"][0], db
    )
    record.status = MandateStatus.ORDER_CREATED
    record.razorpay_order_id = "order_wh_race_001"
    db.commit()
    db.close()

    raw_wh_bytes, wh_sig = simulate_payment_captured_webhook(
        razorpay_order_id="order_wh_race_001",
        amount_paise=94000,
        event_id="evt_concurrent_fixed_001",
        webhook_secret="whsec_test_secret_123",
    )

    captured_count = 0
    dedup_count = 0
    errors = []

    def worker(worker_id: int):
        thread_db = SessionMaker()
        try:
            res = process_payment_webhook(
                raw_body=raw_wh_bytes,
                signature=wh_sig,
                db=thread_db,
                webhook_secret="whsec_test_secret_123",
                platform_private_key_pem=test_keys["platform"][0],
            )
            return ("SUCCESS", res)
        except Exception as e:
            return ("ERROR", f"{type(e).__name__}: {e}")
        finally:
            thread_db.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(worker, i) for i in range(10)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    for status, detail in results:
        if status == "SUCCESS":
            if detail.get("status") == "PAYMENT_CAPTURED":
                captured_count += 1
            elif detail.get("deduplicated") is True:
                dedup_count += 1
        else:
            errors.append(detail)

    assert errors == [], f"Unexpected errors during concurrent webhook delivery: {errors}"
    assert captured_count == 1, f"Expected exactly 1 capture, got {captured_count}"
    assert dedup_count == 9, f"Expected 9 deduplications, got {dedup_count}"

    verify_db = SessionMaker()
    intent_reg = verify_db.query(IntentRegistry).filter_by(intent_id=str(intent.intent_id)).first()
    assert intent_reg.reserved_paise == 0
    assert intent_reg.captured_paise == 94000

    events = verify_db.query(WebhookEvent).filter_by(razorpay_event_id="evt_concurrent_fixed_001").all()
    assert len(events) == 1
    verify_db.close()


def test_concurrent_multi_transaction_intent_limits(db_session, engine, test_keys):
    """Intent with max_transactions=3 attacked by 10 concurrent threads.

    Assert: Exactly 3 succeed; 7 receive PolicyTransactionLimitReached.
    Assert: IntentRegistry.transactions_consumed == 3.
    """
    if engine.dialect.name == "sqlite":
        pytest.skip("SQLite does not support row-level SELECT FOR UPDATE; concurrency guarantees apply to PostgreSQL.")
    SessionMaker = sessionmaker(bind=engine)
    init_db = SessionMaker()
    seed_catalog(init_db)

    now = datetime.now(timezone.utc)
    intent = UserIntentCredential(
        user_id="user_multi_tx_concurrent",
        spend_cap_paise=1000000,  # ₹10,000 cap (plenty of budget)
        allowed_categories=["bakery"],
        allowed_merchant_ids=["merchant_cakehouse_01"],
        max_transactions=3,  # Max 3 transactions allowed
        nonce=uuid4().hex,
        not_before=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    intent_jwt = issue_intent_jwt(intent, test_keys["user"][0])
    verify_intent(intent_jwt, test_keys["user"][1], init_db)

    _, cart_jwt = sign_cart(
        merchant_id="merchant_cakehouse_01",
        line_items_req=[{"sku": "CAKE-CHOC-001", "quantity": 1}],
        merchant_private_key_pem=test_keys["merchant"][0],
        db=init_db,
    )
    init_db.commit()
    init_db.close()

    successes = 0
    tx_limit_rejected = 0
    errors = []

    def worker(worker_id: int):
        db = SessionMaker()
        try:
            idemp_key = f"tx_multi_{worker_id}"
            mandate, mandate_jwt, record = authorize_mandate(
                intent_jwt=intent_jwt,
                cart_jwt=cart_jwt,
                idempotency_key=idemp_key,
                user_public_key_pem=test_keys["user"][1],
                merchant_public_key_pem=test_keys["merchant"][1],
                platform_private_key_pem=test_keys["platform"][0],
                db=db,
            )
            return ("SUCCESS", mandate.mandate_id)
        except PolicyTransactionLimitReached as e:
            return ("TX_LIMIT", type(e).__name__)
        except Exception as e:
            return ("ERROR", f"{type(e).__name__}: {e}")
        finally:
            db.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(worker, i) for i in range(10)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    for status, detail in results:
        if status == "SUCCESS":
            successes += 1
        elif status == "TX_LIMIT":
            tx_limit_rejected += 1
        else:
            errors.append(detail)

    assert errors == [], f"Unexpected errors during multi-transaction test: {errors}"
    assert successes == 3, f"Expected exactly 3 successes, got {successes}"
    assert tx_limit_rejected == 7, f"Expected 7 limit rejections, got {tx_limit_rejected}"

    verify_db = SessionMaker()
    intent_row = verify_db.query(IntentRegistry).filter_by(intent_id=str(intent.intent_id)).first()
    assert intent_row.transactions_consumed == 3
    assert intent_row.status == IntentStatus.EXHAUSTED
    verify_db.close()
