"""Sales CRM 2.0, one set of numbers: saved daily numbers

crm_daily_stats (new)   one row per India day, number, person (NULL = company) and pipeline (NULL = all):
                        what Results adds up for days before today

Revision ID: u2crm018
Revises: u1crm017
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = 'u2crm018'
down_revision = 'u1crm017'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'crm_daily_stats',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('metric', sa.String(40), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('pipeline_id', sa.Integer(), sa.ForeignKey('crm_pipelines.id'), nullable=True),
        sa.Column('value', sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('computed_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_crm_daily_stats_day_metric', 'crm_daily_stats', ['day', 'metric'])


def downgrade():
    op.drop_index('ix_crm_daily_stats_day_metric', table_name='crm_daily_stats')
    op.drop_table('crm_daily_stats')
