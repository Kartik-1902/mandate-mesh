"""Initial schema creation for Mandate Mesh

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-08-25 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Audit Ledger
    op.create_table(
        'audit_ledger',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('entry_type', sa.Enum('INTENT_ISSUED', 'CART_SIGNED', 'MANDATE_CREATED', 'POLICY_REJECTED', 'ORDER_CREATED', 'WEBHOOK_RECEIVED', 'PAYMENT_CAPTURED', 'RECEIPT_ISSUED', name='ledgerentrytype'), nullable=False),
        sa.Column('actor', sa.String(length=128), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('prev_hash', sa.String(length=64), nullable=False),
        sa.Column('entry_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('entry_hash')
    )

    # 2. Intent Registry
    op.create_table(
        'intent_registry',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('intent_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=128), nullable=False),
        sa.Column('nonce', sa.String(length=64), nullable=False),
        sa.Column('spend_cap_paise', sa.BigInteger(), nullable=False),
        sa.Column('reserved_paise', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('captured_paise', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('max_transactions', sa.Integer(), nullable=False),
        sa.Column('transactions_consumed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.Enum('ACTIVE', 'EXHAUSTED', 'EXPIRED', 'REVOKED', name='intentstatus'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('intent_id'),
        sa.UniqueConstraint('nonce')
    )

    # 3. Mandate Records
    op.create_table(
        'mandate_records',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('mandate_id', sa.String(length=36), nullable=False),
        sa.Column('intent_id', sa.String(length=36), nullable=False),
        sa.Column('idempotency_key', sa.String(length=128), nullable=False),
        sa.Column('merchant_id', sa.String(length=128), nullable=False),
        sa.Column('cart_hash', sa.String(length=64), nullable=False),
        sa.Column('authorized_amount_paise', sa.BigInteger(), nullable=False),
        sa.Column('reserved_paise', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('captured_paise', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('status', sa.Enum('RESERVED', 'ORDER_CREATING', 'ORDER_CREATED', 'PAYMENT_PENDING', 'PAYMENT_CAPTURED', 'PAYMENT_FAILED', 'EXPIRED', 'RELEASED', name='mandatestatus'), nullable=False),
        sa.Column('order_idempotency_key', sa.String(length=40), nullable=True),
        sa.Column('razorpay_order_id', sa.String(length=64), nullable=True),
        sa.Column('razorpay_payment_id', sa.String(length=64), nullable=True),
        sa.Column('mandate_jwt', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('mandate_id'),
        sa.UniqueConstraint('order_idempotency_key'),
        sa.UniqueConstraint('razorpay_order_id'),
        sa.UniqueConstraint('razorpay_payment_id'),
        sa.UniqueConstraint('intent_id', 'idempotency_key', name='uq_mandate_idempotency')
    )
    op.create_index(op.f('ix_mandate_records_intent_id'), 'mandate_records', ['intent_id'], unique=False)

    # 4. Webhook Events
    op.create_table(
        'webhook_events',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('razorpay_event_id', sa.String(length=64), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('razorpay_order_id', sa.String(length=64), nullable=True),
        sa.Column('razorpay_payment_id', sa.String(length=64), nullable=True),
        sa.Column('raw_payload', sa.JSON(), nullable=False),
        sa.Column('status', sa.Enum('RECEIVED', 'PROCESSING', 'PROCESSED', 'FAILED', name='webhookeventstatus'), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('razorpay_event_id', 'event_type', name='uq_webhook_event')
    )
    op.create_index(op.f('ix_webhook_events_razorpay_order_id'), 'webhook_events', ['razorpay_order_id'], unique=False)

    # 5. Catalog Items
    op.create_table(
        'catalog_items',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('merchant_id', sa.String(length=128), nullable=False),
        sa.Column('sku', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('category', sa.String(length=64), nullable=False),
        sa.Column('price_paise', sa.BigInteger(), nullable=False),
        sa.Column('in_stock', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sku')
    )
    op.create_index(op.f('ix_catalog_items_merchant_id'), 'catalog_items', ['merchant_id'], unique=False)
    op.create_index(op.f('ix_catalog_items_category'), 'catalog_items', ['category'], unique=False)


def downgrade() -> None:
    op.drop_table('catalog_items')
    op.drop_table('webhook_events')
    op.drop_table('mandate_records')
    op.drop_table('intent_registry')
    op.drop_table('audit_ledger')
