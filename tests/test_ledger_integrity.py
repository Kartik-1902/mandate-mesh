"""Phase 4: Audit Ledger Integrity & Failure Injection Test Suite for Mandate Mesh.

Verifies:
- Linear hash chain mathematical consistency.
- Failure injection: payload tampering detection, broken prev_hash detection, modified entry_hash detection.
- Middle row deletion forensic detection.
- Genesis hash invariant (64 zeros).
- Startup & background order reconciliation (ADR-005).
"""

from uuid import uuid4
from app.ledger import append_entry, verify_chain
from app.models import AuditLedgerEntry, LedgerEntryType, MandateRecord, MandateStatus
from app.razorpay_client import RazorpayClient
from app.reconcile import reconcile_stuck_orders


def test_ledger_happy_path_validity(db_session):
    """Happy path: 5 sequentially appended ledger entries produce a valid hash chain."""
    for i in range(5):
        append_entry(
            db=db_session,
            entry_type=LedgerEntryType.ORDER_CREATED,
            payload={"sequence": i, "data": f"valid_entry_{i}"},
            actor="system:test",
        )
    db_session.commit()

    is_valid, broken_id = verify_chain(db_session)
    assert is_valid is True
    assert broken_id is None


def test_ledger_tampered_payload_detected(db_session):
    """Forensic detection: Altering payload of entry 2 corrupts chain at entry 2."""
    for i in range(4):
        append_entry(
            db=db_session,
            entry_type=LedgerEntryType.ORDER_CREATED,
            payload={"sequence": i},
            actor="system:test",
        )
    db_session.commit()

    # Tamper payload of entry 2 directly in DB
    entry2 = db_session.query(AuditLedgerEntry).filter_by(id=2).first()
    entry2.payload = {"sequence": 2, "injected": "malicious_tamper"}
    db_session.commit()

    is_valid, broken_id = verify_chain(db_session)
    assert is_valid is False
    assert broken_id == 2


def test_ledger_tampered_prev_hash_detected(db_session):
    """Forensic detection: Altering prev_hash of entry 3 corrupts chain at entry 3."""
    for i in range(4):
        append_entry(
            db=db_session,
            entry_type=LedgerEntryType.ORDER_CREATED,
            payload={"sequence": i},
            actor="system:test",
        )
    db_session.commit()

    # Tamper prev_hash of entry 3
    entry3 = db_session.query(AuditLedgerEntry).filter_by(id=3).first()
    entry3.prev_hash = "f" * 64
    db_session.commit()

    is_valid, broken_id = verify_chain(db_session)
    assert is_valid is False
    assert broken_id == 3


def test_ledger_tampered_entry_hash_detected(db_session):
    """Forensic detection: Altering entry_hash of entry 1 corrupts chain at entry 1."""
    for i in range(3):
        append_entry(
            db=db_session,
            entry_type=LedgerEntryType.ORDER_CREATED,
            payload={"sequence": i},
            actor="system:test",
        )
    db_session.commit()

    entry1 = db_session.query(AuditLedgerEntry).filter_by(id=1).first()
    entry1.entry_hash = "a" * 64
    db_session.commit()

    is_valid, broken_id = verify_chain(db_session)
    assert is_valid is False
    assert broken_id == 1


def test_ledger_middle_row_deletion_detected(db_session):
    """Forensic detection: Deleting entry 2 breaks prev_hash link at entry 3."""
    for i in range(5):
        append_entry(
            db=db_session,
            entry_type=LedgerEntryType.ORDER_CREATED,
            payload={"sequence": i},
            actor="system:test",
        )
    db_session.commit()

    # Delete entry 2 from database
    entry2 = db_session.query(AuditLedgerEntry).filter_by(id=2).first()
    db_session.delete(entry2)
    db_session.commit()

    is_valid, broken_id = verify_chain(db_session)
    assert is_valid is False
    # Entry 3 points to entry 2's hash, but previous row is now entry 1
    assert broken_id == 3


def test_ledger_genesis_hash_invariant(db_session):
    """Genesis entry must link to 64 zeros as its previous hash."""
    entry = append_entry(
        db=db_session,
        entry_type=LedgerEntryType.INTENT_ISSUED,
        payload={"genesis": True},
        actor="system:test",
    )
    db_session.commit()

    assert entry.prev_hash == "0" * 64


def test_reconciliation_startup_hook_recovers_stuck_orders(db_session):
    """Startup Reconciler Test: Recovers multiple stuck ORDER_CREATING mandates.

    - Order 1 & Order 2 exist at Razorpay -> recovered to ORDER_CREATED.
    - Order 3 was dropped before reaching Razorpay -> reset to RESERVED.
    """
    rzp = RazorpayClient(mock_mode=True)

    # 1. Create Order 1 (at Razorpay)
    m1_id = str(uuid4())
    key1 = f"mm_{m1_id.replace('-', '')}"
    rzp_order1 = rzp.create_order(amount_paise=94000, receipt=key1)
    rec1 = MandateRecord(
        mandate_id=m1_id,
        intent_id="intent_rec_01",
        idempotency_key="tx_rec_01",
        merchant_id="merchant_cakehouse_01",
        cart_hash="hash_01",
        authorized_amount_paise=94000,
        reserved_paise=94000,
        status=MandateStatus.ORDER_CREATING,
        order_idempotency_key=key1,
        mandate_jwt="dummy_jwt_1",
    )

    # 2. Create Order 2 (at Razorpay)
    m2_id = str(uuid4())
    key2 = f"mm_{m2_id.replace('-', '')}"
    rzp_order2 = rzp.create_order(amount_paise=85000, receipt=key2)
    rec2 = MandateRecord(
        mandate_id=m2_id,
        intent_id="intent_rec_02",
        idempotency_key="tx_rec_02",
        merchant_id="merchant_cakehouse_01",
        cart_hash="hash_02",
        authorized_amount_paise=85000,
        reserved_paise=85000,
        status=MandateStatus.ORDER_CREATING,
        order_idempotency_key=key2,
        mandate_jwt="dummy_jwt_2",
    )

    # 3. Create Order 3 (network dropped before reaching Razorpay)
    m3_id = str(uuid4())
    key3 = f"mm_{m3_id.replace('-', '')}"
    rec3 = MandateRecord(
        mandate_id=m3_id,
        intent_id="intent_rec_03",
        idempotency_key="tx_rec_03",
        merchant_id="merchant_cakehouse_01",
        cart_hash="hash_03",
        authorized_amount_paise=25000,
        reserved_paise=25000,
        status=MandateStatus.ORDER_CREATING,
        order_idempotency_key=key3,
        mandate_jwt="dummy_jwt_3",
    )

    db_session.add_all([rec1, rec2, rec3])
    db_session.commit()

    # Run reconciler
    summary = reconcile_stuck_orders(db=db_session, razorpay_client=rzp)
    assert len(summary) == 3

    # Check Order 1 -> ORDER_CREATED with order ID
    assert rec1.status == MandateStatus.ORDER_CREATED
    assert rec1.razorpay_order_id == rzp_order1["id"]

    # Check Order 2 -> ORDER_CREATED with order ID
    assert rec2.status == MandateStatus.ORDER_CREATED
    assert rec2.razorpay_order_id == rzp_order2["id"]

    # Check Order 3 -> RESERVED for retry
    assert rec3.status == MandateStatus.RESERVED
    assert rec3.razorpay_order_id is None
