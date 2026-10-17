"""Workspaces: the menu as arranged on Team -> Menu builder

workspaces.menu   {'sections', 'labels', 'hidden'} as saved by the builder; NULL (every existing workspace)
                  keeps the menu in code, so nothing changes for anybody until an admin saves one.

Revision ID: t1ws012
Revises: s7crm011
Create Date: 2026-10-17
"""
from alembic import op
import sqlalchemy as sa

revision = 't1ws012'
down_revision = 's7crm011'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('workspaces') as batch:
        batch.add_column(sa.Column('menu', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('workspaces') as batch:
        batch.drop_column('menu')
