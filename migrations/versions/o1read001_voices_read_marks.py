"""staff_reads: which member of staff has opened which enquiry, review, report and match

The User voices badge counted rows nobody had *acted* on -- an enquiry stayed 'new' until
somebody changed its status, a review until it was approved -- so reading down the list never
moved the number. It now counts what *you* have not opened, which is per person: what a colleague
read is still new to you, and an agent who joins later starts with everything unread.

Everybody on staff today is given the rows already acted on as read, so their numbers after this
migration are the ones the badges showed before it, and only fall as they open what is left.

Revision ID: o1read001
Revises: n1seen001
Create Date: 2026-10-06
"""
from alembic import op
import sqlalchemy as sa

revision = 'o1read001'
down_revision = 'n1seen001'
branch_labels = None
depends_on = None

STAFF = "(u.role IN ('cs', 'admin') OR u.is_admin)"
HANDLED = (
    ('contact', 'contact_messages', 'COALESCE(x.handled_at, x.created_at)', "x.status <> 'new'"),
    ('feedback', 'feedbacks', 'x.created_at', 'x.is_approved'),
    ('report', 'match_reports', 'COALESCE(x.resolved_at, x.created_at)', "x.status <> 'open'"),
    # past 'suggested', or not in the queue at all
    ('match', 'matches', 'COALESCE(x.updated_at, x.created_at)',
     "(x.status <> 'suggested' OR x.needs_cs_attention IS NOT TRUE)"),
)


def upgrade():
    op.create_table(
        'staff_reads',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('kind', sa.String(10), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('read_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('user_id', 'kind', 'item_id', name='uq_staff_reads'),
    )
    op.create_index('ix_staff_reads_user_id', 'staff_reads', ['user_id'])
    for kind, table, when, done in HANDLED:
        op.execute(
            f"INSERT INTO staff_reads (user_id, kind, item_id, read_at) "
            f"SELECT u.id, '{kind}', x.id, COALESCE({when}, CURRENT_TIMESTAMP) "
            f"FROM users u CROSS JOIN {table} x WHERE {STAFF} AND {done}")


def downgrade():
    op.drop_index('ix_staff_reads_user_id', table_name='staff_reads')
    op.drop_table('staff_reads')
