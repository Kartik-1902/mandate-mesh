"""Merchant-scoped SKU unique constraint for multi-merchant catalogs (Milestone M2 / ADR-008).

Revision ID: 0002_merchant_scoped_sku
Revises: 0001_initial_schema
Create Date: 2026-08-29 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002_merchant_scoped_sku'
down_revision: Union[str, None] = '0001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use batch_alter_table for universal compatibility across SQLite and PostgreSQL
    with op.batch_alter_table('catalog_items', schema=None) as batch_op:
        # Create composite unique constraint on (merchant_id, sku)
        batch_op.create_unique_constraint('uq_merchant_sku', ['merchant_id', 'sku'])


def downgrade() -> None:
    with op.batch_alter_table('catalog_items', schema=None) as batch_op:
        batch_op.drop_constraint('uq_merchant_sku', type_='unique')
        batch_op.create_unique_constraint('uq_catalog_items_sku', ['sku'])
