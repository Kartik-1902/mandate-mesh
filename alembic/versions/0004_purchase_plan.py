"""PurchasePlan and MandateRecord.plan_id mapping (Milestone M7 / ADR-012).

Revision ID: 0004_purchase_plan
Revises: 0003_canonical_products
Create Date: 2026-09-03 21:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004_purchase_plan'
down_revision: Union[str, None] = '0003_canonical_products'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create purchase_plans table
    op.create_table(
        'purchase_plans',
        sa.Column('plan_id', sa.Uuid(), nullable=False),
        sa.Column('intent_id', sa.String(length=36), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='CONFIRMED', nullable=False),
        sa.Column('total_authorized_paise', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('plan_id'),
        sa.UniqueConstraint('intent_id', name='uq_purchase_plans_intent_id'),
    )
    op.create_index(op.f('ix_purchase_plans_intent_id'), 'purchase_plans', ['intent_id'], unique=True)

    # 2. Add nullable plan_id FK to mandate_records
    with op.batch_alter_table('mandate_records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('plan_id', sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            'fk_mandate_records_plan_id',
            'purchase_plans',
            ['plan_id'],
            ['plan_id'],
        )
        batch_op.create_index('ix_mandate_records_plan_id', ['plan_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('mandate_records', schema=None) as batch_op:
        batch_op.drop_index('ix_mandate_records_plan_id')
        batch_op.drop_constraint('fk_mandate_records_plan_id', type_='foreignkey')
        batch_op.drop_column('plan_id')

    op.drop_index(op.f('ix_purchase_plans_intent_id'), table_name='purchase_plans')
    op.drop_table('purchase_plans')
