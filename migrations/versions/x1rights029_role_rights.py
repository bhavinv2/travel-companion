"""What a role may do on the pages it opens (Staff Console 2.0): look-only pages, removing leads, masked contacts

workspace_roles.rights   {'profile': the ready-made profile it started from, 'view': [page keys opened to look
                         only], 'remove': may send leads to the Recycle bin, 'mask': phone numbers and e-mails of
                         people whose leads they do not look after are hidden until "Show"}. NULL: as before
                         this revision (nothing look-only, removing allowed, nothing hidden).

Revision ID: x1rights029
Revises: w1sec028
Create Date: 2026-10-26
"""
from alembic import op
import sqlalchemy as sa

revision = 'x1rights029'
down_revision = 'w1sec028'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('workspace_roles') as b:
        b.add_column(sa.Column('rights', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('workspace_roles') as b:
        b.drop_column('rights')
