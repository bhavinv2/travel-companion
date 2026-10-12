"""Sales CRM: bring a database migrated with an early draft of p1crm001 up to date

p1crm001 grew while the CRM was being built (Instagram / Facebook identities, the inbox check,
readiness, stage automations, ready messages, the dashboard's work log...). A database that ran
an early copy of it is marked p1crm001 but lacks the later tables and columns, and "upgrade"
would never revisit it. This adds whatever is missing and leaves alone whatever is there, so it
is a no-op on a database created from the final p1crm001.

Revision ID: p2crm002
Revises: p1crm001
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa

revision = 'p2crm002'
down_revision = 'p1crm001'
branch_labels = None
depends_on = None

COLUMNS = {
    'crm_stages': [
        ('auto_kind', lambda: sa.Column('auto_kind', sa.String(10))),
        ('auto_days', lambda: sa.Column('auto_days', sa.Integer())),
        ('auto_to_id', lambda: sa.Column('auto_to_id', sa.Integer(), nullable=True)),
        ('auto_reason', lambda: sa.Column('auto_reason', sa.String(80))),
    ],
    'crm_people': [
        ('wacrm_conversation_id', lambda: sa.Column('wacrm_conversation_id', sa.String(64), nullable=True)),
    ],
    'crm_leads': [
        ('likelihood', lambda: sa.Column('likelihood', sa.String(4))),
        ('imported', lambda: sa.Column('imported', sa.Boolean(), nullable=False, server_default=sa.false())),
        ('ends_on', lambda: sa.Column('ends_on', sa.Date())),
        ('sla_alerted_at', lambda: sa.Column('sla_alerted_at', sa.DateTime())),
        ('created_by_id', lambda: sa.Column('created_by_id', sa.Integer(), nullable=True)),
    ],
    'crm_answers': [
        ('code', lambda: sa.Column('code', sa.String(20))),
    ],
}


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    for table, cols in COLUMNS.items():
        have = {c['name'] for c in insp.get_columns(table)} if table in tables else set()
        for name, make in cols:
            if table in tables and name not in have:
                op.add_column(table, make())
                # the foreign keys the model declares; SQLite cannot add one after the fact
                if bind.dialect.name != 'sqlite':
                    if (table, name) == ('crm_stages', 'auto_to_id'):
                        op.create_foreign_key('fk_crm_stage_auto_to', 'crm_stages', 'crm_stages',
                                              ['auto_to_id'], ['id'])
                    elif (table, name) == ('crm_leads', 'created_by_id'):
                        op.create_foreign_key('fk_crm_leads_created_by', 'crm_leads', 'users',
                                              ['created_by_id'], ['id'])

    if 'crm_identities' not in tables:
        op.create_table(
            'crm_identities',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('person_id', sa.Integer(), sa.ForeignKey('crm_people.id'), nullable=False),
            sa.Column('kind', sa.String(20), nullable=False),
            sa.Column('value', sa.String(190), nullable=False),
            sa.Column('created_at', sa.DateTime()),
            sa.UniqueConstraint('kind', 'value', name='uq_crm_identity'),
        )
        op.create_index('ix_crm_identities_person_id', 'crm_identities', ['person_id'])
    if 'crm_channel_checks' not in tables:
        op.create_table(
            'crm_channel_checks',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('day', sa.Date(), nullable=False),
            sa.Column('slot', sa.SmallInteger(), nullable=False),
            sa.Column('channel', sa.String(40), nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('checked_at', sa.DateTime()),
            sa.UniqueConstraint('day', 'slot', 'channel', name='uq_crm_check'),
        )
        op.create_index('ix_crm_channel_checks_day', 'crm_channel_checks', ['day'])
    if 'crm_activities' not in tables:
        op.create_table(
            'crm_activities',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('day', sa.Date(), nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('metric', sa.String(30), nullable=False),
            sa.Column('count', sa.Float(), nullable=False, server_default='0'),
            sa.Column('source', sa.String(8), nullable=False, server_default='manual'),
            sa.Column('updated_at', sa.DateTime()),
        )
        op.create_index('ix_crm_activities_day', 'crm_activities', ['day'])
        op.create_index('ix_crm_activities_user_id', 'crm_activities', ['user_id'])


def downgrade():
    # Nothing to undo on its own: on an up-to-date database these belong to p1crm001, whose
    # downgrade drops the CRM tables.
    pass
