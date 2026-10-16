"""Sales CRM: the daily work -- Leads, My day, Team today, bells and hand-over

snoozed_until       "Remind me in 1 hour" on a waiting customer: My day and the waiting bell hold it till then
waiting_alerted_at  the waiting bell went for this wait; our next message to them clears it
via                 who sent an outbound message: person / auto / automation / flow / ai / broadcast / import

Revision ID: s4crm008
Revises: s3crm007
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa

revision = 's4crm008'
down_revision = 's3crm007'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('crm_leads', sa.Column('snoozed_until', sa.DateTime(), nullable=True))
    op.add_column('crm_leads', sa.Column('waiting_alerted_at', sa.DateTime(), nullable=True))
    op.add_column('crm_touchpoints', sa.Column('via', sa.String(12), nullable=True))


def downgrade():
    with op.batch_alter_table('crm_touchpoints') as b:
        b.drop_column('via')
    with op.batch_alter_table('crm_leads') as b:
        b.drop_column('waiting_alerted_at')
        b.drop_column('snoozed_until')
