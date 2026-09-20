"""insurance quote requests (leads from the travel-insurance form)

Revision ID: f1ins001
Revises: e1rep001
Create Date: 2026-09-20
"""
from alembic import op
import sqlalchemy as sa

revision = 'f1ins001'
down_revision = 'e1rep001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'insurance_quotes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('phone', sa.String(length=30), nullable=True),
        sa.Column('insurance_type', sa.String(length=20), nullable=False),
        sa.Column('citizenship', sa.String(length=3), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('ages', sa.String(length=80), nullable=False),
        sa.Column('status', sa.String(length=15), nullable=True),
        sa.Column('quote_url', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_insurance_quotes_user_id', 'insurance_quotes', ['user_id'])
    op.create_index('ix_insurance_quotes_email', 'insurance_quotes', ['email'])
    op.create_index('ix_insurance_quotes_insurance_type', 'insurance_quotes', ['insurance_type'])
    op.create_index('ix_insurance_quotes_status', 'insurance_quotes', ['status'])
    op.create_index('ix_insurance_quotes_created_at', 'insurance_quotes', ['created_at'])


def downgrade():
    op.drop_index('ix_insurance_quotes_created_at', table_name='insurance_quotes')
    op.drop_index('ix_insurance_quotes_status', table_name='insurance_quotes')
    op.drop_index('ix_insurance_quotes_insurance_type', table_name='insurance_quotes')
    op.drop_index('ix_insurance_quotes_email', table_name='insurance_quotes')
    op.drop_index('ix_insurance_quotes_user_id', table_name='insurance_quotes')
    op.drop_table('insurance_quotes')
