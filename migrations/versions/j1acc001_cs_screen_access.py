"""Per-agent CS console access.

One nullable JSON column. NULL means unrestricted, which is what every existing agent has and
what every new one gets, so this migration changes nobody's access on the day it runs.

Revision ID: j1acc001
Revises: i1sav001
Create Date: 2026-09-27
"""
import sqlalchemy as sa
from alembic import op

revision = 'j1acc001'
down_revision = 'i1sav001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('cs_access', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('users', 'cs_access')
