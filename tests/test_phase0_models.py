"""Phase 0: Tests for SQLAlchemy ORM models, constraints, and enums."""

from datetime import datetime, timezone
import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    AuditLedgerEntry,
    CatalogItem,
    IntentRegistry,
    IntentStatus,
    LedgerEntryType,
    MandateRecord,
    MandateStatus,
    WebhookEvent,
    WebhookEventStatus,
)


def test_intent_registry_crud_and_uniqueness(db_session):
    now = datetime.now(timezone.utc)
    intent = IntentRegistry(
        intent_id="intent_001",
        user_id="user_abc",
        nonce="nonce_unique_1",
        spend_cap_paise=150000,
        reserved_paise=50000,
        captured_paise=0,
        max_transactions=3,
        status=IntentStatus.ACTIVE,
        expires_at=now,
    )
    db_session.add(intent)
    db_session.commit()

    assert intent.available_paise == 100000

    # Duplicate nonce must fail
    duplicate_intent = IntentRegistry(
        intent_id="intent_002",
        user_id="user_xyz",
        nonce="nonce_unique_1",  # Duplicate nonce
        spend_cap_paise=100000,
        max_transactions=1,
        status=IntentStatus.ACTIVE,
        expires_at=now,
    )
    db_session.add(duplicate_intent)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_mandate_record_idempotency_constraint(db_session):
    now = datetime.now(timezone.utc)
    mandate1 = MandateRecord(
        mandate_id="mandate_001",
        intent_id="intent_001",
        idempotency_key="tx_attempt_1",
        merchant_id="merchant_cakehouse_01",
        cart_hash="cart_hash_1",
        authorized_amount_paise=94000,
        status=MandateStatus.RESERVED,
        order_idempotency_key="mm_mandate001",
        mandate_jwt="jwt_dummy_string",
    )
    db_session.add(mandate1)
    db_session.commit()

    # Same intent_id + same idempotency_key must raise IntegrityError
    duplicate_mandate = MandateRecord(
        mandate_id="mandate_002",
        intent_id="intent_001",
        idempotency_key="tx_attempt_1",  # Replay of same transaction identity
        merchant_id="merchant_cakehouse_01",
        cart_hash="cart_hash_1",
        authorized_amount_paise=94000,
        status=MandateStatus.RESERVED,
        order_idempotency_key="mm_mandate002",
        mandate_jwt="jwt_dummy_string",
    )
    db_session.add(duplicate_mandate)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_webhook_event_dedup_constraint(db_session):
    event1 = WebhookEvent(
        razorpay_event_id="evt_12345",
        event_type="payment.captured",
        raw_payload={"id": "evt_12345", "event": "payment.captured"},
        status=WebhookEventStatus.RECEIVED,
    )
    db_session.add(event1)
    db_session.commit()

    # Same (event_id, event_type) must fail unique constraint
    duplicate_event = WebhookEvent(
        razorpay_event_id="evt_12345",
        event_type="payment.captured",
        raw_payload={"id": "evt_12345", "event": "payment.captured"},
        status=WebhookEventStatus.RECEIVED,
    )
    db_session.add(duplicate_event)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_catalog_item_creation_and_uniqueness(db_session):
    item = CatalogItem(
        merchant_id="merchant_cakehouse_01",
        sku="CAKE-CHOC-001",
        name="Chocolate Truffle Cake (1kg)",
        description="Rich dark chocolate sponge with truffle ganache",
        category="bakery",
        price_paise=94000,
        in_stock=True,
    )
    db_session.add(item)
    db_session.commit()

    assert item.id is not None
    assert item.price_paise == 94000

    # Duplicate SKU must fail
    duplicate_item = CatalogItem(
        merchant_id="merchant_cakehouse_01",
        sku="CAKE-CHOC-001",
        name="Different Cake",
        description="Description",
        category="bakery",
        price_paise=50000,
    )
    db_session.add(duplicate_item)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_audit_ledger_entry_creation(db_session):
    now = datetime.now(timezone.utc)
    entry = AuditLedgerEntry(
        entry_type=LedgerEntryType.INTENT_ISSUED,
        actor="user:user_123",
        payload={"intent_id": "intent_001", "spend_cap_paise": 150000},
        payload_hash="payload_hash_abc",
        prev_hash="0" * 64,
        entry_hash="entry_hash_def",
        created_at=now,
    )
    db_session.add(entry)
    db_session.commit()

    assert entry.id is not None
    assert entry.entry_type == LedgerEntryType.INTENT_ISSUED
