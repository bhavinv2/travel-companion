"""Workspaces, roles, teams and members: who may open which screens

Revision ID: q1ws001
Revises: p2crm002
Create Date: 2026-10-13
"""
from alembic import op
import sqlalchemy as sa

revision = 'q1ws001'
down_revision = 'p2crm002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'workspaces',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('slug', sa.String(60), nullable=False, unique=True),
        sa.Column('description', sa.String(255)),
        sa.Column('modules', sa.JSON()),
        sa.Column('wacrm', sa.JSON()),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    )
    op.create_table(
        'workspace_roles',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('description', sa.String(255)),
        sa.Column('pages', sa.JSON()),
        sa.Column('system_key', sa.String(20)),
        sa.Column('created_at', sa.DateTime()),
        sa.UniqueConstraint('workspace_id', 'name', name='uq_workspace_role_name'),
    )
    op.create_index('ix_workspace_roles_workspace_id', 'workspace_roles', ['workspace_id'])
    op.create_table(
        'workspace_teams',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('description', sa.String(255)),
        sa.Column('role_id', sa.Integer(), sa.ForeignKey('workspace_roles.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime()),
        sa.UniqueConstraint('workspace_id', 'name', name='uq_workspace_team_name'),
    )
    op.create_index('ix_workspace_teams_workspace_id', 'workspace_teams', ['workspace_id'])
    op.create_table(
        'workspace_team_members',
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('workspace_teams.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    )
    op.create_table(
        'workspace_members',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role_id', sa.Integer(), sa.ForeignKey('workspace_roles.id', ondelete='SET NULL'), nullable=True),
        sa.Column('is_owner', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('added_at', sa.DateTime()),
        sa.Column('added_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('wacrm_role', sa.String(20)),
        sa.Column('wacrm_synced_at', sa.DateTime()),
        sa.Column('wacrm_error', sa.String(255)),
        sa.UniqueConstraint('workspace_id', 'user_id', name='uq_workspace_member'),
    )
    op.create_index('ix_workspace_members_workspace_id', 'workspace_members', ['workspace_id'])
    op.create_index('ix_workspace_members_user_id', 'workspace_members', ['user_id'])


def downgrade():
    op.execute('DROP TABLE IF EXISTS workspace_members')
    op.execute('DROP TABLE IF EXISTS workspace_team_members')
    op.execute('DROP TABLE IF EXISTS workspace_teams')
    op.execute('DROP TABLE IF EXISTS workspace_roles')
    op.execute('DROP TABLE IF EXISTS workspaces')
