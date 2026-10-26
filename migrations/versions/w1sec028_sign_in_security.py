"""Sign-in security: two-step sign-in, the sessions a person has open, and signing everybody out

users.session_version   raised to sign every device out at once (a password change, "sign out everywhere")
users.totp_secret       the authenticator app's key (base32) once two-step sign-in is on; NULL while off
users.totp_on_at        when two-step sign-in was turned on
users.backup_codes      hashes of the one-time backup codes still unused
user_sessions           one row per signed-in browser: where, when last seen, ended by whom and why

Revision ID: w1sec028
Revises: v3blog027
Create Date: 2026-10-26
"""
from alembic import op
import sqlalchemy as sa

revision = 'w1sec028'
down_revision = 'v3blog027'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users') as b:
        b.add_column(sa.Column('session_version', sa.Integer(), nullable=False, server_default='0'))
        b.add_column(sa.Column('totp_secret', sa.String(length=64), nullable=True))
        b.add_column(sa.Column('totp_on_at', sa.DateTime(), nullable=True))
        b.add_column(sa.Column('backup_codes', sa.JSON(), nullable=True))
    op.create_table(
        'user_sessions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('how', sa.String(length=20), nullable=True),
        sa.Column('ip', sa.String(length=64), nullable=True),
        sa.Column('user_agent', sa.String(length=300), nullable=True),
        sa.Column('two_step', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(), nullable=False),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.Column('ended_reason', sa.String(length=30), nullable=True),
        sa.Column('ended_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    )
    op.create_index('ix_user_sessions_user_id', 'user_sessions', ['user_id'])
    op.create_index('ix_user_sessions_token_hash', 'user_sessions', ['token_hash'], unique=True)
    op.create_index('ix_user_sessions_ended_at', 'user_sessions', ['ended_at'])


def downgrade():
    op.drop_index('ix_user_sessions_ended_at', table_name='user_sessions')
    op.drop_index('ix_user_sessions_token_hash', table_name='user_sessions')
    op.drop_index('ix_user_sessions_user_id', table_name='user_sessions')
    op.drop_table('user_sessions')
    with op.batch_alter_table('users') as b:
        b.drop_column('backup_codes')
        b.drop_column('totp_on_at')
        b.drop_column('totp_secret')
        b.drop_column('session_version')
