"""feedback: is_featured flag - CS/admin hand-pick which approved reviews show on the home page

Revision ID: b7feat001
Revises: f1c72a904e33
"""
from alembic import op
import sqlalchemy as sa

revision = 'b7feat001'
down_revision = 'f1c72a904e33'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('feedbacks', sa.Column('is_featured', sa.Boolean(), nullable=True))
    op.execute("UPDATE feedbacks SET is_featured = false WHERE is_featured IS NULL")


def downgrade():
    op.drop_column('feedbacks', 'is_featured')
