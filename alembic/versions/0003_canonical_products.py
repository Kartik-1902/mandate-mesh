"""Canonical product identity and catalog product_id mapping (Milestone M4 / ADR-007).

Revision ID: 0003_canonical_products
Revises: 0002_merchant_scoped_sku
Create Date: 2026-09-02 20:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003_canonical_products'
down_revision: Union[str, None] = '0002_merchant_scoped_sku'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create canonical_products table
    op.create_table(
        'canonical_products',
        sa.Column('product_id', sa.Uuid(), nullable=False),
        sa.Column('canonical_name', sa.String(length=255), nullable=False),
        sa.Column('brand', sa.String(length=128), nullable=True),
        sa.Column('category', sa.String(length=64), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('product_id'),
    )
    op.create_index(op.f('ix_canonical_products_category'), 'canonical_products', ['category'], unique=False)

    # 2. Add nullable product_id FK to catalog_items
    with op.batch_alter_table('catalog_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('product_id', sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            'fk_catalog_items_product_id',
            'canonical_products',
            ['product_id'],
            ['product_id'],
        )
        batch_op.create_index('ix_catalog_items_product_id', ['product_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('catalog_items', schema=None) as batch_op:
        batch_op.drop_index('ix_catalog_items_product_id')
        batch_op.drop_constraint('fk_catalog_items_product_id', type_='foreignkey')
        batch_op.drop_column('product_id')

    op.drop_index(op.f('ix_canonical_products_category'), table_name='canonical_products')
    op.drop_table('canonical_products')
