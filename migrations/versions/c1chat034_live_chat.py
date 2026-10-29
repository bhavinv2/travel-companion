"""Live chat: the portal's own chat bubble on our websites, answered in the portal (no tawk.to frame)

crm_live_chats             one chat a visitor started from the bubble: the secret their browser keeps, who they are
                           (the person and lead it made), the page they were on, when their browser last asked for news
                           and when one of us was last typing
crm_touchpoints.live_chat_id  which chat a message (channel 'webchat') belongs to: a visitor sees only their own chat's

Revision ID: c1chat034
Revises: b1mkt033
Create Date: 2026-10-30
"""
from alembic import op
import sqlalchemy as sa

revision = 'c1chat034'
down_revision = 'b1mkt033'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'crm_live_chats',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('person_id', sa.Integer(), sa.ForeignKey('crm_people.id', ondelete='CASCADE'), nullable=True),
        sa.Column('lead_id', sa.Integer(), sa.ForeignKey('crm_leads.id', ondelete='SET NULL'), nullable=True),
        sa.Column('agent_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('site', sa.String(length=120), nullable=True),
        sa.Column('page_url', sa.String(length=500), nullable=True),
        sa.Column('page_title', sa.String(length=200), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('seen_at', sa.DateTime(), nullable=True),
        sa.Column('read_upto', sa.Integer(), nullable=True),
        sa.Column('agent_typing_at', sa.DateTime(), nullable=True),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('token', name='uq_crm_live_chats_token'),
    )
    op.create_index('ix_crm_live_chats_person_id', 'crm_live_chats', ['person_id'])
    op.create_index('ix_crm_live_chats_started_at', 'crm_live_chats', ['started_at'])
    with op.batch_alter_table('crm_touchpoints') as b:
        b.add_column(sa.Column('live_chat_id', sa.Integer(), nullable=True))
        b.create_foreign_key('fk_crm_touchpoints_live_chat', 'crm_live_chats', ['live_chat_id'], ['id'],
                             ondelete='SET NULL')
        b.create_index('ix_crm_touchpoints_live_chat_id', ['live_chat_id'])


def downgrade():
    with op.batch_alter_table('crm_touchpoints') as b:
        b.drop_index('ix_crm_touchpoints_live_chat_id')
        b.drop_constraint('fk_crm_touchpoints_live_chat', type_='foreignkey')
        b.drop_column('live_chat_id')
    op.drop_index('ix_crm_live_chats_started_at', table_name='crm_live_chats')
    op.drop_index('ix_crm_live_chats_person_id', table_name='crm_live_chats')
    op.drop_table('crm_live_chats')
