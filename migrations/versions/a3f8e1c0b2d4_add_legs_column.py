"""add legs column for multi-destination trips

Revision ID: a3f8e1c0b2d4
Revises: 62148d13d6ed
Create Date: 2026-05-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'a3f8e1c0b2d4'
down_revision = '62148d13d6ed'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('companion_requests', schema=None) as batch_op:
        batch_op.add_column(sa.Column('legs', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('companion_requests', schema=None) as batch_op:
        batch_op.drop_column('legs')
