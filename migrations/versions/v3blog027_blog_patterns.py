"""Blog: reusable blocks

blog_patterns   blocks saved once, by name, to add to any post; synced ones are kept the same in every post
                that holds them (inside <div class="blog-ref" data-ref="<id>">)

Revision ID: v3blog027
Revises: v2blog026
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa

revision = 'v3blog027'
down_revision = 'v2blog026'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'blog_patterns',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('content', sa.Text(), nullable=False, server_default=''),
        sa.Column('synced', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table('blog_patterns')
