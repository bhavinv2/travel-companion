"""Sales CRM 2.0, activities and control (run 3b): who sees which leads, history, recycle bin,
assignment rules, what a stage needs

workspace_roles    crm_scope (NULL = everyone's leads)
crm_audit          new table: the history of every change
crm_leads          deleted_at, deleted_by_id (the recycle bin)
crm_sources        assign_mode, rr_last_user_id
workspace_members  away_until
crm_stages         requires (JSON list of field keys)

Revision ID: u4crm020
Revises: u3crm019
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = 'u4crm020'
down_revision = 'u3crm019'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('workspace_roles') as batch:
        batch.add_column(sa.Column('crm_scope', sa.String(8), nullable=True))
    op.create_table(
        'crm_audit',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('at', sa.DateTime(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('record_type', sa.String(12), nullable=False),
        sa.Column('record_id', sa.Integer(), nullable=False),
        sa.Column('field', sa.String(40), nullable=False),
        sa.Column('old', sa.Text(), nullable=True),
        sa.Column('new', sa.Text(), nullable=True),
    )
    op.create_index('ix_crm_audit_record', 'crm_audit', ['record_type', 'record_id'])
    with op.batch_alter_table('crm_leads') as batch:
        batch.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('deleted_by_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_crm_leads_deleted_by', 'users', ['deleted_by_id'], ['id'])
        batch.create_index('ix_crm_leads_deleted_at', ['deleted_at'])
    with op.batch_alter_table('crm_sources') as batch:
        batch.add_column(sa.Column('assign_mode', sa.String(12), nullable=True))
        batch.add_column(sa.Column('rr_last_user_id', sa.Integer(), nullable=True))
    with op.batch_alter_table('workspace_members') as batch:
        batch.add_column(sa.Column('away_until', sa.DateTime(), nullable=True))
    with op.batch_alter_table('crm_stages') as batch:
        batch.add_column(sa.Column('requires', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('crm_stages') as batch:
        batch.drop_column('requires')
    with op.batch_alter_table('workspace_members') as batch:
        batch.drop_column('away_until')
    with op.batch_alter_table('crm_sources') as batch:
        batch.drop_column('rr_last_user_id')
        batch.drop_column('assign_mode')
    with op.batch_alter_table('crm_leads') as batch:
        batch.drop_index('ix_crm_leads_deleted_at')
        batch.drop_constraint('fk_crm_leads_deleted_by', type_='foreignkey')
        batch.drop_column('deleted_by_id')
        batch.drop_column('deleted_at')
    op.drop_index('ix_crm_audit_record', table_name='crm_audit')
    op.drop_table('crm_audit')
    with op.batch_alter_table('workspace_roles') as batch:
        batch.drop_column('crm_scope')
