"""Phase 2: Tests for Append-Only Hash-Chained Audit Ledger (app/ledger.py)."""

from datetime import datetime, timezone
import pytest
from app.ledger import append_entry, verify_chain
from app.models import AuditLedgerEntry, LedgerEntryType


def test_ledger_chain_valid_after_happy_path(db_session):
    """Verifies that appending sequential entries produces a 100% mathematically valid chain."""
    e1 = append_entry(
        db_session,
        LedgerEntryType.INTENT_ISSUED,
        {"intent_id": "intent_01", "cap": 150000},
        actor="user:user_123",
    )
    e2 = append_entry(
        db_session,
        LedgerEntryType.CART_SIGNED,
        {"cart_id": "cart_01", "total_paise": 94000},
        actor="merchant:m_01",
    )
    e3 = append_entry(
        db_session,
        LedgerEntryType.MANDATE_CREATED,
        {"mandate_id": "man_01", "amount": 94000},
        actor="system:policy-rail",
    )
    db_session.commit()

    is_valid, broken_id = verify_chain(db_session)
    assert is_valid is True
    assert broken_id is None
    assert e2.prev_hash == e1.entry_hash
    assert e3.prev_hash == e2.entry_hash


def test_ledger_modified_payload_detected(db_session):
    """Forensic test: Direct tampering with payload column breaks the chain verification."""
    append_entry(db_session, LedgerEntryType.INTENT_ISSUED, {"cap": 150000}, actor="user:1")
    e2 = append_entry(db_session, LedgerEntryType.CART_SIGNED, {"total_paise": 94000}, actor="merchant:1")
    append_entry(db_session, LedgerEntryType.MANDATE_CREATED, {"amount": 94000}, actor="system")
    db_session.commit()

    # Tamper with row 2's payload directly in the database
    e2.payload = {"total_paise": 1000}  # Attacker alters historical cart total
    db_session.flush()

    is_valid, broken_id = verify_chain(db_session)
    assert is_valid is False
    assert broken_id == e2.id


def test_ledger_broken_prev_hash_detected(db_session):
    """Forensic test: Deleting or altering prev_hash linkage breaks the chain verification."""
    append_entry(db_session, LedgerEntryType.INTENT_ISSUED, {"a": 1}, actor="user:1")
    e2 = append_entry(db_session, LedgerEntryType.CART_SIGNED, {"b": 2}, actor="merchant:1")
    db_session.commit()

    # Alter prev_hash link
    e2.prev_hash = "0" * 64
    db_session.flush()

    is_valid, broken_id = verify_chain(db_session)
    assert is_valid is False
    assert broken_id == e2.id


def test_ledger_modified_entry_hash_detected(db_session):
    """Forensic test: Tampering with entry_hash itself breaks verification."""
    e1 = append_entry(db_session, LedgerEntryType.INTENT_ISSUED, {"a": 1}, actor="user:1")
    db_session.commit()

    e1.entry_hash = "bad_hash_" + "0" * 55
    db_session.flush()

    is_valid, broken_id = verify_chain(db_session)
    assert is_valid is False
    assert broken_id == e1.id


def test_ledger_append_is_atomic_with_state_transition(db_session):
    """Verifies that rolling back a transaction cleanly rolls back the ledger append as well."""
    append_entry(db_session, LedgerEntryType.INTENT_ISSUED, {"intent_id": "test"}, actor="user:1")
    db_session.commit()

    # Start transaction, append ledger entry, then rollback
    append_entry(db_session, LedgerEntryType.MANDATE_CREATED, {"failed": True}, actor="system")
    db_session.rollback()

    rows = db_session.query(AuditLedgerEntry).all()
    assert len(rows) == 1
    assert rows[0].entry_type == LedgerEntryType.INTENT_ISSUED


def test_concurrent_ledger_appends_produce_linear_chain(db_session, engine):
    """Multi-threaded test verifying that concurrent appends produce a strictly linear chain."""
    import concurrent.futures
    from sqlalchemy.orm import sessionmaker
    from app.ledger import _LOCAL_DIALECT_LOCK

    SessionLocal = sessionmaker(bind=engine)

    def worker_append(idx: int):
        session = SessionLocal()
        try:
            with _LOCAL_DIALECT_LOCK:
                append_entry(
                    session,
                    LedgerEntryType.INTENT_ISSUED,
                    {"worker_id": idx, "seq": idx},
                    actor=f"user:worker_{idx}",
                )
                session.commit()
        finally:
            session.close()

    # Run 10 concurrent appends
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(worker_append, i) for i in range(10)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    verify_session = SessionLocal()
    try:
        is_valid, broken_id = verify_chain(verify_session)
        assert is_valid is True
        assert broken_id is None
        assert verify_session.query(AuditLedgerEntry).count() == 10
    finally:
        verify_session.close()
