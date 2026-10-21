"""Sales CRM 2.0, Phase 4 run 4b: quotes and payments, saved views, saved reports

crm_quotes         a quote on a lead (amount, currency, valid until, status, approval)
crm_payments       a payment link / transfer on a lead (status, provider, reference)
crm_products       max_discount_pct (the biggest discount an agent may quote without approval)
crm_views          saved views of Leads and Contacts (a small table of their own: SavedFilter is bound to the
                   post listings' filter engine)
crm_saved_reports  reports built on the report builder

Revision ID: u6crm022
Revises: u5crm021
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = 'u6crm022'
down_revision = 'u5crm021'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'crm_quotes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('lead_id', sa.Integer(), sa.ForeignKey('crm_leads.id'), nullable=False),
        sa.Column('title', sa.String(160), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('currency', sa.String(3), nullable=True),
        sa.Column('valid_until', sa.Date(), nullable=True),
        sa.Column('status', sa.String(10), nullable=False, server_default='draft'),
        sa.Column('needs_approval', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('sent_touch_id', sa.Integer(), nullable=True),
    )
    op.create_index('ix_crm_quotes_lead_id', 'crm_quotes', ['lead_id'])
    op.create_table(
        'crm_payments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('lead_id', sa.Integer(), sa.ForeignKey('crm_leads.id'), nullable=False),
        sa.Column('quote_id', sa.Integer(), sa.ForeignKey('crm_quotes.id'), nullable=True),
        sa.Column('amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('currency', sa.String(3), nullable=True),
        sa.Column('link_url', sa.String(500), nullable=True),
        sa.Column('provider', sa.String(30), nullable=True),
        sa.Column('reference', sa.String(80), nullable=True),
        sa.Column('status', sa.String(10), nullable=False, server_default='pending'),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('link_touch_id', sa.Integer(), nullable=True),
    )
    op.create_index('ix_crm_payments_lead_id', 'crm_payments', ['lead_id'])
    op.create_index('ix_crm_payments_reference', 'crm_payments', ['reference'])
    with op.batch_alter_table('crm_products') as batch:
        batch.add_column(sa.Column('max_discount_pct', sa.Numeric(5, 2), nullable=True))
    op.create_table(
        'crm_views',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('scope', sa.String(20), nullable=False, server_default='crm_leads'),
        sa.Column('name', sa.String(60), nullable=False),
        sa.Column('params', sa.JSON(), nullable=False),
        sa.Column('shared', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_crm_views_owner_id', 'crm_views', ['owner_id'])
    op.create_table(
        'crm_saved_reports',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('shared', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('pinned', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_crm_saved_reports_owner_id', 'crm_saved_reports', ['owner_id'])


def downgrade():
    op.drop_index('ix_crm_saved_reports_owner_id', table_name='crm_saved_reports')
    op.drop_table('crm_saved_reports')
    op.drop_index('ix_crm_views_owner_id', table_name='crm_views')
    op.drop_table('crm_views')
    with op.batch_alter_table('crm_products') as batch:
        batch.drop_column('max_discount_pct')
    op.drop_index('ix_crm_payments_reference', table_name='crm_payments')
    op.drop_index('ix_crm_payments_lead_id', table_name='crm_payments')
    op.drop_table('crm_payments')
    op.drop_index('ix_crm_quotes_lead_id', table_name='crm_quotes')
    op.drop_table('crm_quotes')
