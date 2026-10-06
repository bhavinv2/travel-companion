"""users: when each staff member last looked at each "what's new" list

The floating "what's new" widget counts two kinds of thing. Most have a status that already says
whether anybody has acted on them -- a contact enquiry is 'new' until somebody opens it, a Sahayak
booking is 'new' until it is assigned -- and those need nothing stored here.

Two do not. An insurance quote request's status only records whether the partner priced it, and
a companion post has no "somebody has looked at this" state at all. For those, "new" can only
honestly mean "since you last opened that list", which is per person: the admin who checked the
quotes this morning should not be shown the same six again just because a colleague has not.

One JSON column of {list key: ISO timestamp} rather than a table, because nothing queries across
people -- it is read and written only for the person signed in -- and a list added later is a new
key, not a new migration. Nullable, no default: an empty mark means "never looked", which the
widget treats as the last 48 hours, the CS console's own definition of a new post.

Revision ID: n1seen001
Revises: m1num001
Create Date: 2026-10-06
"""
from alembic import op
import sqlalchemy as sa

revision = 'n1seen001'
down_revision = 'm1num001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('seen_marks', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('users', 'seen_marks')
