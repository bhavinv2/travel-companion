"""Visitors: who is on our websites, recorded by our own chat bubble (tawk.to's Visitors list, kept by us)

crm_visitors                one browser: its random id, address and where that is (our own copy of DB-IP's free list),
                            browser and device, how it first found us, the page it is on, when it last spoke, the person
                            once it starts a chat
crm_visitor_pages           each page it opened and how long it stayed
crm_live_chats.visitor_id   the browser a chat was started from

Revision ID: e1vis036
Revises: d1can035
Create Date: 2026-10-30
"""
from alembic import op
import sqlalchemy as sa

revision = 'e1vis036'
down_revision = 'd1can035'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'crm_visitors',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('vid', sa.String(length=40), nullable=False),
        sa.Column('site', sa.String(length=120), nullable=True),
        sa.Column('first_at', sa.DateTime(), nullable=False),
        sa.Column('last_at', sa.DateTime(), nullable=False),
        sa.Column('visit_at', sa.DateTime(), nullable=True),
        sa.Column('gone_at', sa.DateTime(), nullable=True),
        sa.Column('visits', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('pages', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('ip', sa.String(length=64), nullable=True),
        sa.Column('country_code', sa.String(length=2), nullable=True),
        sa.Column('country', sa.String(length=80), nullable=True),
        sa.Column('region', sa.String(length=80), nullable=True),
        sa.Column('city', sa.String(length=80), nullable=True),
        sa.Column('tz', sa.String(length=64), nullable=True),
        sa.Column('lang', sa.String(length=20), nullable=True),
        sa.Column('browser', sa.String(length=40), nullable=True),
        sa.Column('os', sa.String(length=40), nullable=True),
        sa.Column('device', sa.String(length=10), nullable=True),
        sa.Column('source', sa.String(length=60), nullable=True),
        sa.Column('referrer', sa.String(length=500), nullable=True),
        sa.Column('campaign', sa.String(length=200), nullable=True),
        sa.Column('landing_url', sa.String(length=500), nullable=True),
        sa.Column('page_url', sa.String(length=500), nullable=True),
        sa.Column('page_title', sa.String(length=200), nullable=True),
        sa.Column('person_id', sa.Integer(), sa.ForeignKey('crm_people.id', ondelete='SET NULL'), nullable=True),
        sa.UniqueConstraint('vid', name='uq_crm_visitors_vid'),
    )
    op.create_index('ix_crm_visitors_last_at', 'crm_visitors', ['last_at'])
    op.create_index('ix_crm_visitors_country_code', 'crm_visitors', ['country_code'])
    op.create_index('ix_crm_visitors_source', 'crm_visitors', ['source'])
    op.create_index('ix_crm_visitors_person_id', 'crm_visitors', ['person_id'])
    op.create_table(
        'crm_visitor_pages',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('visitor_id', sa.Integer(), sa.ForeignKey('crm_visitors.id', ondelete='CASCADE'), nullable=False),
        sa.Column('at', sa.DateTime(), nullable=False),
        sa.Column('url', sa.String(length=500), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=True),
        sa.Column('visit', sa.Integer(), nullable=True),
        sa.Column('secs', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('came_from', sa.String(length=60), nullable=True),
    )
    op.create_index('ix_crm_visitor_pages_visitor_id', 'crm_visitor_pages', ['visitor_id'])
    op.create_index('ix_crm_visitor_pages_at', 'crm_visitor_pages', ['at'])
    with op.batch_alter_table('crm_live_chats') as b:
        b.add_column(sa.Column('visitor_id', sa.Integer(), nullable=True))
        b.create_foreign_key('fk_crm_live_chats_visitor', 'crm_visitors', ['visitor_id'], ['id'], ondelete='SET NULL')


def downgrade():
    with op.batch_alter_table('crm_live_chats') as b:
        b.drop_constraint('fk_crm_live_chats_visitor', type_='foreignkey')
        b.drop_column('visitor_id')
    op.drop_index('ix_crm_visitor_pages_at', table_name='crm_visitor_pages')
    op.drop_index('ix_crm_visitor_pages_visitor_id', table_name='crm_visitor_pages')
    op.drop_table('crm_visitor_pages')
    op.drop_index('ix_crm_visitors_person_id', table_name='crm_visitors')
    op.drop_index('ix_crm_visitors_source', table_name='crm_visitors')
    op.drop_index('ix_crm_visitors_country_code', table_name='crm_visitors')
    op.drop_index('ix_crm_visitors_last_at', table_name='crm_visitors')
    op.drop_table('crm_visitors')
