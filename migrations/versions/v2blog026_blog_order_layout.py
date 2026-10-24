"""Blog: the order posts stand in on the public blog, and each post's layout

blogs.sort_order   where the post stands on the public blog (1 first); NULL: after the ordered ones, newest first
blogs.layout       the post's width, text size and spacing (JSON); NULL: the standard layout

Revision ID: v2blog026
Revises: v1blog025
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa

revision = 'v2blog026'
down_revision = 'v1blog025'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('blogs') as batch:
        batch.add_column(sa.Column('sort_order', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('layout', sa.JSON(), nullable=True))
        batch.create_index('ix_blogs_sort_order', ['sort_order'])


def downgrade():
    with op.batch_alter_table('blogs') as batch:
        batch.drop_index('ix_blogs_sort_order')
        batch.drop_column('layout')
        batch.drop_column('sort_order')
