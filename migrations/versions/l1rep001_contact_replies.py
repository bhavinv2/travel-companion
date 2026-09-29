"""contact messages: what we actually replied

The Reply button was a mailto: link. On a machine with no mail client configured it does nothing
at all, and even when it works the reply happens in somebody's personal mailbox -- so the console
shows an enquiry with no answer beside it, and the next agent to open it cannot tell whether it
was handled, by whom, or what was said.

A reply is a business record: who wrote it, when, what it said, and whether it reached the mail
provider. That does not fit in the free-text internal note, which is for something else and would
lose all four.

Revision ID: l1rep001
Revises: k1rev001
Create Date: 2026-09-29
"""
from alembic import op
import sqlalchemy as sa

revision = 'l1rep001'
down_revision = 'k1rev001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'contact_replies',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('message_id', sa.Integer(),
                  sa.ForeignKey('contact_messages.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('author_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('body', sa.Text(), nullable=False),
        # False when the mail provider refused it or the address is opted out. The reply is kept
        # either way: an agent needs to see what was written even when it did not go out.
        sa.Column('delivered', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.func.now(), index=True),
    )


def downgrade():
    op.drop_table('contact_replies')
