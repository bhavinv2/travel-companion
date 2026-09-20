"""destination country on insurance quotes (Travel Medical prices per destination)

Revision ID: f2ins002
Revises: f1ins001
Create Date: 2026-09-20
"""
from alembic import op
import sqlalchemy as sa

revision = 'f2ins002'
down_revision = 'f1ins001'
branch_labels = None
depends_on = None


def upgrade():
    # Nullable: only Travel Medical takes a destination — visitors implies the USA and
    # schengen implies the Schengen area, so existing rows correctly have none.
    op.add_column('insurance_quotes', sa.Column('destination', sa.String(length=3), nullable=True))


def downgrade():
    op.drop_column('insurance_quotes', 'destination')
