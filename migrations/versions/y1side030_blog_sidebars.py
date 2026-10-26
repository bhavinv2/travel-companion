"""Blog: a thumbnail of its own for each post, and the sidebars beside a post (flyers, ads, links)

blogs.thumb_url      the picture on the blog's list, Read next and More stories; empty: the cover
blog_side_cards      one card in the left or right sidebar of a post: a flyer, an ad, links, the post's own
                     headings, more stories or a reusable block -- on every post, the posts of some categories or
                     some posts; its look (theme, height, how the picture fits, phones) in `look`

Revision ID: y1side030
Revises: x1rights029
Create Date: 2026-10-27
"""
from alembic import op
import sqlalchemy as sa

revision = 'y1side030'
down_revision = 'x1rights029'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('blogs') as b:
        b.add_column(sa.Column('thumb_url', sa.String(length=500), nullable=True))
    op.create_table(
        'blog_side_cards',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('side', sa.String(length=8), nullable=False, server_default='right'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_on', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('title', sa.String(length=120), nullable=True),
        sa.Column('body', sa.String(length=600), nullable=True),
        sa.Column('image_url', sa.String(length=500), nullable=True),
        sa.Column('image_alt', sa.String(length=300), nullable=True),
        sa.Column('link_url', sa.String(length=500), nullable=True),
        sa.Column('link_label', sa.String(length=60), nullable=True),
        sa.Column('new_tab', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('links', sa.JSON(), nullable=True),
        sa.Column('pattern_id', sa.Integer(), sa.ForeignKey('blog_patterns.id', ondelete='SET NULL'), nullable=True),
        sa.Column('look', sa.JSON(), nullable=True),
        sa.Column('show_on', sa.String(length=8), nullable=False, server_default='all'),
        sa.Column('term_ids', sa.JSON(), nullable=True),
        sa.Column('post_ids', sa.JSON(), nullable=True),
        sa.Column('starts_at', sa.DateTime(), nullable=True),
        sa.Column('ends_at', sa.DateTime(), nullable=True),
        sa.Column('clicks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_blog_side_cards_side', 'blog_side_cards', ['side', 'sort_order'])


def downgrade():
    op.drop_index('ix_blog_side_cards_side', table_name='blog_side_cards')
    op.drop_table('blog_side_cards')
    with op.batch_alter_table('blogs') as b:
        b.drop_column('thumb_url')
