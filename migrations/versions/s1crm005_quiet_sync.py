"""Sales CRM: bulk pushes to the WhatsApp CRM are quiet

A person's next push to the WhatsApp CRM is quiet -- their tags are written without starting its
"tag added" automations (dispatch_tag_events false) -- only while every mark since their last
push was a bulk one: the backfill, a source's changed tags. Any other change makes it a normal
push. wacrm_quiet holds that, and the sync clears it.

Revision ID: s1crm005
Revises: r2crm004
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa

revision = 's1crm005'
down_revision = 'r2crm004'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('crm_people', sa.Column('wacrm_quiet', sa.Boolean(), nullable=True,
                                          server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('crm_people') as b:
        b.drop_column('wacrm_quiet')
