"""Sales CRM: lead sources, pipelines and stages, people, leads, tasks, touchpoints, answers

Every enquiry the site takes in (trip posts, insurance quotes, Sahayak bookings and sign-ups,
contact forms, Instagram and Facebook messages, and any landing page added later) becomes a lead on
a pipeline, with the next message or call of the sales playbook on somebody's list. Also the
half-hourly inbox check of the sales sheet (crm_channel_checks). The starting pipelines, playbook steps,
answers and built-in sources are written by services/crm.ensure_defaults() the first time the CRM
is opened, so this migration only makes the tables.

Revision ID: p1crm001
Revises: o1read001
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa

revision = 'p1crm001'
down_revision = 'o1read001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'crm_pipelines',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('key', sa.String(40), nullable=False, unique=True),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('product', sa.String(4), nullable=False, server_default='GEN'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('fallout_reasons', sa.JSON()),
        sa.Column('created_at', sa.DateTime()),
    )
    op.create_table(
        'crm_stages',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('pipeline_id', sa.Integer(), sa.ForeignKey('crm_pipelines.id'), nullable=False),
        sa.Column('key', sa.String(40), nullable=False),
        sa.Column('name', sa.String(60), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('kind', sa.String(8), nullable=False, server_default='open'),
        sa.Column('on_reply', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('sla_hours', sa.Integer()),
        sa.Column('auto_kind', sa.String(10)),
        sa.Column('auto_days', sa.Integer()),
        sa.Column('auto_to_id', sa.Integer(), sa.ForeignKey('crm_stages.id', name='fk_crm_stage_auto_to'),
                  nullable=True),
        sa.Column('auto_reason', sa.String(80)),
        sa.UniqueConstraint('pipeline_id', 'key', name='uq_crm_stage_key'),
    )
    op.create_index('ix_crm_stages_pipeline_id', 'crm_stages', ['pipeline_id'])
    op.create_table(
        'crm_sources',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('key', sa.String(60), nullable=False, unique=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('kind', sa.String(10), nullable=False, server_default='form'),
        sa.Column('product', sa.String(4), nullable=False, server_default='GEN'),
        sa.Column('pages', sa.JSON()),
        sa.Column('pipeline_id', sa.Integer(), sa.ForeignKey('crm_pipelines.id'), nullable=True),
        sa.Column('status', sa.String(10), nullable=False, server_default='live'),
        sa.Column('team', sa.JSON()),
        sa.Column('crm_tags', sa.JSON()),
        sa.Column('dedupe_days', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('built_in', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('lead_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_lead_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
    )
    op.create_table(
        'crm_people',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('phone', sa.String(20), nullable=True, unique=True),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('name', sa.String(120)),
        sa.Column('country', sa.String(2)),
        sa.Column('consent_whatsapp', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('consent_marketing', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('wacrm_contact_id', sa.String(64), nullable=True),
        sa.Column('wacrm_conversation_id', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
    )
    op.create_index('ix_crm_people_email', 'crm_people', ['email'])
    op.create_index('ix_crm_people_wacrm_contact_id', 'crm_people', ['wacrm_contact_id'])
    op.create_table(
        'crm_leads',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('person_id', sa.Integer(), sa.ForeignKey('crm_people.id'), nullable=False),
        sa.Column('product', sa.String(4), nullable=False, server_default='GEN'),
        sa.Column('source_id', sa.Integer(), sa.ForeignKey('crm_sources.id'), nullable=True),
        sa.Column('pipeline_id', sa.Integer(), sa.ForeignKey('crm_pipelines.id'), nullable=True),
        sa.Column('stage_id', sa.Integer(), sa.ForeignKey('crm_stages.id'), nullable=True),
        sa.Column('status', sa.String(6), nullable=False, server_default='open'),
        sa.Column('temperature', sa.String(3)),
        sa.Column('likelihood', sa.String(4)),
        sa.Column('imported', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('fallout_reason', sa.String(80)),
        sa.Column('details', sa.JSON()),
        sa.Column('utm', sa.JSON()),
        sa.Column('ref_type', sa.String(30)),
        sa.Column('ref_id', sa.Integer()),
        sa.Column('departure_date', sa.Date()),
        sa.Column('ends_on', sa.Date()),
        sa.Column('entered_stage_at', sa.DateTime()),
        sa.Column('sla_alerted_at', sa.DateTime()),
        sa.Column('last_activity_at', sa.DateTime()),
        sa.Column('closed_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
    )
    for col in ('person_id', 'source_id', 'pipeline_id', 'stage_id', 'owner_id',
                'last_activity_at', 'created_at'):
        op.create_index('ix_crm_leads_%s' % col, 'crm_leads', [col])
    op.create_index('ix_crm_leads_ref', 'crm_leads', ['ref_type', 'ref_id'])
    op.create_table(
        'crm_playbook_steps',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('stage_id', sa.Integer(), sa.ForeignKey('crm_stages.id'), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('code', sa.String(20), nullable=False),
        sa.Column('title', sa.String(160), nullable=False),
        sa.Column('channel', sa.String(10), nullable=False, server_default='whatsapp'),
        sa.Column('body', sa.Text()),
        sa.Column('trigger', sa.String(24), nullable=False, server_default='after_hours'),
        sa.Column('trigger_value', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('auto', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('wa_template', sa.String(80)),
    )
    op.create_index('ix_crm_playbook_steps_stage_id', 'crm_playbook_steps', ['stage_id'])
    op.create_table(
        'crm_touchpoints',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('lead_id', sa.Integer(), sa.ForeignKey('crm_leads.id'), nullable=True),
        sa.Column('person_id', sa.Integer(), sa.ForeignKey('crm_people.id'), nullable=False),
        sa.Column('channel', sa.String(10), nullable=False, server_default='note'),
        sa.Column('direction', sa.String(4), nullable=False, server_default='none'),
        sa.Column('code', sa.String(20)),
        sa.Column('outcome', sa.String(20)),
        sa.Column('body', sa.Text()),
        sa.Column('status', sa.String(12)),
        sa.Column('agent_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('external_id', sa.String(120)),
        sa.Column('created_at', sa.DateTime()),
    )
    for col in ('lead_id', 'person_id', 'external_id', 'created_at'):
        op.create_index('ix_crm_touchpoints_%s' % col, 'crm_touchpoints', [col])
    op.create_table(
        'crm_tasks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('lead_id', sa.Integer(), sa.ForeignKey('crm_leads.id'), nullable=False),
        sa.Column('step_id', sa.Integer(), sa.ForeignKey('crm_playbook_steps.id'), nullable=True),
        sa.Column('code', sa.String(20)),
        sa.Column('title', sa.String(160), nullable=False),
        sa.Column('channel', sa.String(10), nullable=False, server_default='whatsapp'),
        sa.Column('auto', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('due_at', sa.DateTime(), nullable=False),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('status', sa.String(8), nullable=False, server_default='open'),
        sa.Column('done_at', sa.DateTime()),
        sa.Column('done_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('note', sa.String(200)),
        sa.Column('created_at', sa.DateTime()),
    )
    for col in ('lead_id', 'due_at', 'owner_id'):
        op.create_index('ix_crm_tasks_%s' % col, 'crm_tasks', [col])
    op.create_table(
        'crm_stage_changes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('lead_id', sa.Integer(), sa.ForeignKey('crm_leads.id'), nullable=False),
        sa.Column('from_stage_id', sa.Integer(), sa.ForeignKey('crm_stages.id'), nullable=True),
        sa.Column('to_stage_id', sa.Integer(), sa.ForeignKey('crm_stages.id'), nullable=False),
        sa.Column('by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('reason', sa.String(160)),
        sa.Column('created_at', sa.DateTime()),
    )
    op.create_index('ix_crm_stage_changes_lead_id', 'crm_stage_changes', ['lead_id'])
    op.create_index('ix_crm_stage_changes_created_at', 'crm_stage_changes', ['created_at'])
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
    op.create_table(
        'crm_answers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(160), nullable=False),
        sa.Column('keywords', sa.String(400)),
        sa.Column('code', sa.String(20)),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('product', sa.String(4), nullable=False, server_default='GEN'),
        sa.Column('use_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
    )


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
    for table in ('crm_activities', 'crm_answers', 'crm_channel_checks', 'crm_identities', 'crm_stage_changes', 'crm_tasks', 'crm_touchpoints',
                  'crm_playbook_steps', 'crm_leads', 'crm_people', 'crm_sources', 'crm_stages',
                  'crm_pipelines'):
        # IF EXISTS: a database upgraded by an earlier draft of this revision lacks the newer tables
        op.execute('DROP TABLE IF EXISTS %s' % table)
