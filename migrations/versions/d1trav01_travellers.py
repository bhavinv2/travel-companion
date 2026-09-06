"""per-person travellers JSON

Revision ID: d1trav01
Revises: c9ret001
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa

revision = 'd1trav01'
down_revision = 'c9ret001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('companion_requests') as batch:
        batch.add_column(sa.Column('travellers', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('companion_requests') as batch:
        batch.drop_column('travellers')
