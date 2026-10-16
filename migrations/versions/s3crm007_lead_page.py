"""Sales CRM: the lead page as one screen

wa_history_at       when a person's older WhatsApp messages were brought onto the lead page (once)
wa_opt_in_due       an admin opted them back in; their next push takes the "opted-out" tag off
fail_reason         why WhatsApp did not deliver a message, kept for the timeline

Revision ID: s3crm007
Revises: s2crm006
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa

revision = 's3crm007'
down_revision = 's2crm006'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('crm_people', sa.Column('wa_history_at', sa.DateTime(), nullable=True))
    op.add_column('crm_people', sa.Column('wa_opt_in_due', sa.Boolean(), nullable=True,
                                          server_default=sa.false()))
    op.add_column('crm_touchpoints', sa.Column('fail_reason', sa.String(300), nullable=True))


def downgrade():
    with op.batch_alter_table('crm_touchpoints') as b:
        b.drop_column('fail_reason')
    with op.batch_alter_table('crm_people') as b:
        b.drop_column('wa_opt_in_due')
        b.drop_column('wa_history_at')
