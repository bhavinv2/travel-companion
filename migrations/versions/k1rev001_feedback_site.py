"""reviews: which service the review is about

A review left after a flight and a review left about travel insurance are about different
products and belong on different pages. One table, one moderation queue, one column saying which
page it was written on -- the same shape `topic` already gives contact messages, so CS learns one
idea rather than two.

Every existing review was left on the companion app, which is the only place that has ever had a
review form, so the default is the truth for them rather than a guess.

Revision ID: k1rev001
Revises: j1acc001
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa

revision = 'k1rev001'
down_revision = 'j1acc001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('feedbacks', sa.Column('site', sa.String(length=20),
                                         nullable=False, server_default='companion'))
    op.create_index('ix_feedbacks_site', 'feedbacks', ['site'])


def downgrade():
    op.drop_index('ix_feedbacks_site', table_name='feedbacks')
    op.drop_column('feedbacks', 'site')
