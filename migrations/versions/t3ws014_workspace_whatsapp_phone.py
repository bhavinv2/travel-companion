"""Workspaces: the business WhatsApp number each one runs

workspaces.whatsapp_phone   E.164, entered in the "New workspace" flow and shown in the header switcher; NULL for
                            every existing workspace (the one linked to the WhatsApp CRM shows the CRM's number).

Revision ID: t3ws014
Revises: t2su013
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa

revision = 't3ws014'
down_revision = 't2su013'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('workspaces') as batch:
        batch.add_column(sa.Column('whatsapp_phone', sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table('workspaces') as batch:
        batch.drop_column('whatsapp_phone')
