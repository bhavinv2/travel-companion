"""Sales CRM 2.0, activities and control (run 3a): tasks, calls and meetings anywhere

crm_tasks   lead_id may now be empty (a task on a person with no open lead); new: person_id, kind
            ('step' for every existing row), ends_at, location, notes, created_by_id, priority

Revision ID: u3crm019
Revises: u2crm018
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = 'u3crm019'
down_revision = 'u2crm018'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('crm_tasks') as batch:
        batch.add_column(sa.Column('person_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('kind', sa.String(10), nullable=False, server_default='step'))
        batch.add_column(sa.Column('ends_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('location', sa.String(200), nullable=True))
        batch.add_column(sa.Column('notes', sa.Text(), nullable=True))
        batch.add_column(sa.Column('created_by_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('priority', sa.String(8), nullable=True))
        batch.create_foreign_key('fk_crm_tasks_person', 'crm_people', ['person_id'], ['id'])
        batch.create_foreign_key('fk_crm_tasks_created_by', 'users', ['created_by_id'], ['id'])
        batch.create_index('ix_crm_tasks_person_id', ['person_id'])
        batch.alter_column('lead_id', existing_type=sa.Integer(), nullable=True)


def downgrade():
    # tasks with no lead cannot exist in the old shape: they are removed
    op.execute('DELETE FROM crm_tasks WHERE lead_id IS NULL')
    with op.batch_alter_table('crm_tasks') as batch:
        batch.alter_column('lead_id', existing_type=sa.Integer(), nullable=False)
        batch.drop_index('ix_crm_tasks_person_id')
        batch.drop_constraint('fk_crm_tasks_created_by', type_='foreignkey')
        batch.drop_constraint('fk_crm_tasks_person', type_='foreignkey')
        for c in ('priority', 'created_by_id', 'notes', 'location', 'ends_at', 'kind', 'person_id'):
            batch.drop_column(c)
