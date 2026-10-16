"""Sales CRM: a WhatsApp chat goes to the lead's owner only when nobody has it

Somebody already in the Sales CRM writes from a chat we had not seen: after the save their chat
is given to the owner of their lead, unless somebody in the WhatsApp CRM already has it
(wacrm_assign_if_free). An owner change made here still moves the chat (wacrm_assign_due).

Revision ID: r2crm004
Revises: r1crm003
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa

revision = 'r2crm004'
down_revision = 'r1crm003'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('crm_people', sa.Column('wacrm_assign_if_free', sa.Boolean(), nullable=True,
                                          server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('crm_people') as b:
        b.drop_column('wacrm_assign_if_free')
