"""Sales CRM 2.0, money: prices, deal values, forecast categories, exchange rates and targets

crm_products   price, revenue_kind, revenue_value, close_days
crm_stages     forecast, probability              (NULL = automatic)
crm_leads      amount, currency, revenue, close_date, forecast
crm_currency_rates (new)   code -> rate into the reporting currency
crm_targets (new)          month targets per person / team: amount, deals, new leads

Revision ID: u1crm017
Revises: t5bl016
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = 'u1crm017'
down_revision = 't5bl016'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('crm_products') as batch:
        batch.add_column(sa.Column('price', sa.Numeric(12, 2), nullable=True))
        batch.add_column(sa.Column('revenue_kind', sa.String(8), nullable=True))
        batch.add_column(sa.Column('revenue_value', sa.Numeric(12, 2), nullable=True))
        batch.add_column(sa.Column('close_days', sa.Integer(), nullable=True))
    with op.batch_alter_table('crm_stages') as batch:
        batch.add_column(sa.Column('forecast', sa.String(10), nullable=True))
        batch.add_column(sa.Column('probability', sa.Integer(), nullable=True))
    with op.batch_alter_table('crm_leads') as batch:
        batch.add_column(sa.Column('amount', sa.Numeric(12, 2), nullable=True))
        batch.add_column(sa.Column('currency', sa.String(3), nullable=True))
        batch.add_column(sa.Column('revenue', sa.Numeric(12, 2), nullable=True))
        batch.add_column(sa.Column('close_date', sa.Date(), nullable=True))
        batch.add_column(sa.Column('forecast', sa.String(10), nullable=True))
    op.create_table(
        'crm_currency_rates',
        sa.Column('code', sa.String(3), primary_key=True),
        sa.Column('rate', sa.Numeric(14, 6), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
    )
    op.create_table(
        'crm_targets',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('period', sa.String(7), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('workspace_teams.id', ondelete='CASCADE'), nullable=True),
        sa.Column('pipeline_id', sa.Integer(), sa.ForeignKey('crm_pipelines.id'), nullable=True),
        sa.Column('amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('deals', sa.Integer(), nullable=True),
        sa.Column('leads', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
    )
    op.create_index('ix_crm_targets_period', 'crm_targets', ['period'])
    op.create_index('ix_crm_targets_user_id', 'crm_targets', ['user_id'])
    op.create_index('ix_crm_targets_team_id', 'crm_targets', ['team_id'])


def downgrade():
    op.drop_index('ix_crm_targets_team_id', table_name='crm_targets')
    op.drop_index('ix_crm_targets_user_id', table_name='crm_targets')
    op.drop_index('ix_crm_targets_period', table_name='crm_targets')
    op.drop_table('crm_targets')
    op.drop_table('crm_currency_rates')
    with op.batch_alter_table('crm_leads') as batch:
        for c in ('forecast', 'close_date', 'revenue', 'currency', 'amount'):
            batch.drop_column(c)
    with op.batch_alter_table('crm_stages') as batch:
        batch.drop_column('probability')
        batch.drop_column('forecast')
    with op.batch_alter_table('crm_products') as batch:
        for c in ('close_days', 'revenue_value', 'revenue_kind', 'price'):
            batch.drop_column(c)
