"""contact messages: which service the enquiry is about

The travel-insurance page writes its "talk to an expert" enquiries into the same inbox as every
other contact message, rather than standing up a second system CS would have to remember to
check. `topic` is what lets the consoles tell them apart and filter.

Existing rows predate the insurance page, so they are all companion enquiries.

Revision ID: g1ins005
Revises: f4ins004
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa

revision = 'g1ins005'
down_revision = 'f4ins004'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('contact_messages', sa.Column('topic', sa.String(length=20),
                                                nullable=False, server_default='companion'))
    op.create_index('ix_contact_messages_topic', 'contact_messages', ['topic'])


def downgrade():
    op.drop_index('ix_contact_messages_topic', table_name='contact_messages')
    op.drop_column('contact_messages', 'topic')
