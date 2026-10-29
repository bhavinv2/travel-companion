"""Promotion dashboards a Marketing head designs (Reports > Dashboard designer)

mkt_dashboards   one dashboard per row: its boxes as the designer left them (draft) and as everybody sees them
                 (published, copied on Publish), who may see it, the dates it opens on and its place among the tabs

Revision ID: b1mkt033
Revises: a2chan032
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa

revision = 'b1mkt033'
down_revision = 'a2chan032'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'mkt_dashboards',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('description', sa.String(length=300), nullable=True),
        sa.Column('icon', sa.String(length=40), nullable=True),
        sa.Column('draft', sa.JSON(), nullable=False),
        sa.Column('published', sa.JSON(), nullable=True),
        sa.Column('audience', sa.String(length=12), nullable=False, server_default='all'),
        sa.Column('range_key', sa.String(length=20), nullable=False, server_default='last_30'),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('published_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('published_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table('mkt_dashboards')
