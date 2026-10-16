"""Sales CRM: keeping each person's WhatsApp CRM contact in step, in the background

A change to a person or their leads only marks them due (wacrm_sync_due_at); straight after the
save a background thread, and every jobs run after that, brings the WhatsApp CRM into step and
clears the mark. wacrm_assign_due: the owner changed here, so their chat goes to the owner too.
wa_sync_error is the last problem, wa_synced_at the last success, wa_opt_out_at when they asked
for no more WhatsApp messages.

Revision ID: r1crm003
Revises: q1ws001
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa

revision = 'r1crm003'
down_revision = 'q1ws001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('crm_people', sa.Column('wacrm_sync_due_at', sa.DateTime(), nullable=True))
    op.add_column('crm_people', sa.Column('wacrm_assign_due', sa.Boolean(), nullable=True, server_default=sa.false()))
    op.add_column('crm_people', sa.Column('wa_sync_error', sa.String(300), nullable=True))
    op.add_column('crm_people', sa.Column('wa_synced_at', sa.DateTime(), nullable=True))
    op.add_column('crm_people', sa.Column('wa_opt_out_at', sa.DateTime(), nullable=True))
    op.create_index('ix_crm_people_wacrm_sync_due_at', 'crm_people', ['wacrm_sync_due_at'])


def downgrade():
    op.drop_index('ix_crm_people_wacrm_sync_due_at', table_name='crm_people')
    with op.batch_alter_table('crm_people') as b:
        for name in ('wa_opt_out_at', 'wa_synced_at', 'wa_sync_error', 'wacrm_assign_due', 'wacrm_sync_due_at'):
            b.drop_column(name)
