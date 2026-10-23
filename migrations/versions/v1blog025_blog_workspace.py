"""Blog workspace: categories and tags, revisions, the picture library, scheduled and featured posts

blogs.seo_title        the title Google shows (NULL: the post's title)
blogs.focus_keyword    the words the post should be found by; the checks look for them
blogs.is_featured      kept at the top of the blog
blogs.trashed_at       in the Trash: off the site, back with Restore (NULL: not in the Trash)
blogs.notified_at      "went live" was handled: everybody told (or not, if the post said so). A post
                       scheduled for later is told about by the jobs when its time comes. Posts live
                       today are marked handled, so nobody is told about them again.
blog_terms             categories and tags (kind), each with its own address
blog_post_terms        which post is in which category / has which tag
blog_revisions         every saved version of a post, to compare and bring back
blog_media             every picture uploaded for the blog (editor, library, Word import)

Revision ID: v1blog025
Revises: u8crm024
Create Date: 2026-10-23
"""
from alembic import op
import sqlalchemy as sa

revision = 'v1blog025'
down_revision = 'u8crm024'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('blogs') as batch:
        batch.add_column(sa.Column('seo_title', sa.String(length=300), nullable=True))
        batch.add_column(sa.Column('focus_keyword', sa.String(length=100), nullable=True))
        batch.add_column(sa.Column('is_featured', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('trashed_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('notified_at', sa.DateTime(), nullable=True))
    op.execute(sa.text('UPDATE blogs SET notified_at = COALESCE(published_at, updated_at, created_at) '
                       'WHERE is_published = :yes').bindparams(yes=True))

    op.create_table(
        'blog_terms',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('slug', sa.String(length=90), nullable=False),
        sa.Column('description', sa.String(length=300), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('kind', 'slug', name='uq_blog_terms_kind_slug'),
    )
    op.create_table(
        'blog_post_terms',
        sa.Column('blog_id', sa.Integer(), sa.ForeignKey('blogs.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('term_id', sa.Integer(), sa.ForeignKey('blog_terms.id', ondelete='CASCADE'), primary_key=True),
    )
    op.create_index('ix_blog_post_terms_term_id', 'blog_post_terms', ['term_id'])
    op.create_table(
        'blog_revisions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('blog_id', sa.Integer(), sa.ForeignKey('blogs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('summary', sa.String(length=300), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('note', sa.String(length=120), nullable=True),
        sa.Column('saved_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('saved_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_blog_revisions_blog_id', 'blog_revisions', ['blog_id'])
    op.create_table(
        'blog_media',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('url', sa.String(length=500), nullable=False, unique=True),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('bytes', sa.Integer(), nullable=True),
        sa.Column('alt', sa.String(length=300), nullable=True),
        sa.Column('uploaded_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table('blog_media')
    op.drop_index('ix_blog_revisions_blog_id', table_name='blog_revisions')
    op.drop_table('blog_revisions')
    op.drop_index('ix_blog_post_terms_term_id', table_name='blog_post_terms')
    op.drop_table('blog_post_terms')
    op.drop_table('blog_terms')
    with op.batch_alter_table('blogs') as batch:
        batch.drop_column('notified_at')
        batch.drop_column('trashed_at')
        batch.drop_column('is_featured')
        batch.drop_column('focus_keyword')
        batch.drop_column('seo_title')
