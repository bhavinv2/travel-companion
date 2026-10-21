"""Sales CRM 2.0, People 360 (run 4a): families and files

crm_households   a family: name, notes
crm_people       household_id (nullable, index), household_role
crm_files        documents kept on a person / enquiry (the bytes are on disk, not here)

Revision ID: u5crm021
Revises: u4crm020
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = 'u5crm021'
down_revision = 'u4crm020'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'crm_households',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
    )
    with op.batch_alter_table('crm_people') as batch:
        batch.add_column(sa.Column('household_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('household_role', sa.String(10), nullable=True))
        batch.create_foreign_key('fk_crm_people_household', 'crm_households', ['household_id'], ['id'])
        batch.create_index('ix_crm_people_household_id', ['household_id'])
    op.create_table(
        'crm_files',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('person_id', sa.Integer(), sa.ForeignKey('crm_people.id'), nullable=False),
        sa.Column('lead_id', sa.Integer(), sa.ForeignKey('crm_leads.id'), nullable=True),
        sa.Column('filename', sa.String(200), nullable=False),
        sa.Column('stored_name', sa.String(80), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('content_type', sa.String(100), nullable=True),
        sa.Column('uploaded_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('stored_name', name='uq_crm_files_stored_name'),
    )
    op.create_index('ix_crm_files_person_id', 'crm_files', ['person_id'])
    op.create_index('ix_crm_files_lead_id', 'crm_files', ['lead_id'])


def downgrade():
    op.drop_index('ix_crm_files_lead_id', table_name='crm_files')
    op.drop_index('ix_crm_files_person_id', table_name='crm_files')
    op.drop_table('crm_files')
    with op.batch_alter_table('crm_people') as batch:
        batch.drop_index('ix_crm_people_household_id')
        batch.drop_constraint('fk_crm_people_household', type_='foreignkey')
        batch.drop_column('household_role')
        batch.drop_column('household_id')
    op.drop_table('crm_households')
