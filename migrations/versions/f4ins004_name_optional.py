"""insurance quotes: contact name becomes optional (the form asks for ages + email only)

Revision ID: f4ins004
Revises: f3ins003
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa

revision = 'f4ins004'
down_revision = 'f3ins003'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('insurance_quotes', 'name', existing_type=sa.String(length=120), nullable=True)


def downgrade():
    op.execute("UPDATE insurance_quotes SET name = '' WHERE name IS NULL")
    op.alter_column('insurance_quotes', 'name', existing_type=sa.String(length=120), nullable=False)
