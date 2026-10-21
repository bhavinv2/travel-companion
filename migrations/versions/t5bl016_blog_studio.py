"""Blog studio: posts imported from Word documents

blogs.summary       what Google, shares and the blog list show (NULL: the first lines of the post)
blogs.cover_alt     what the cover picture shows, for search engines and screen readers
blogs.source_file   the Word document a post was imported from (NULL: written in the editor)

Revision ID: t5bl016
Revises: t4su015
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = 't5bl016'
down_revision = 't4su015'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('blogs') as batch:
        batch.add_column(sa.Column('summary', sa.String(length=300), nullable=True))
        batch.add_column(sa.Column('cover_alt', sa.String(length=300), nullable=True))
        batch.add_column(sa.Column('source_file', sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table('blogs') as batch:
        batch.drop_column('source_file')
        batch.drop_column('cover_alt')
        batch.drop_column('summary')
