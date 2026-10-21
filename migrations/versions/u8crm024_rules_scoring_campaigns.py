"""Sales CRM 2.0, Phase 5 run 5b: automation rules, lead scoring, campaigns, offers consent, AI summaries

crm_rules          automation rules (When / If / Then), per workspace
crm_rule_runs      a rule ran for a lead on one triggering event (unique: never twice)
crm_score_rules    lead scoring lines (signal + points), per workspace
crm_campaigns      marketing activities and campaigns (moved from the 'crm' setting's "channels" list into a table:
                   costs are money -- Numeric(12,2) with a currency -- and each workspace keeps its own)
crm_leads          score, likelihood_manual (a person picked the rating), ai_cache (the lead page's summary)
crm_people         consent_marketing_at / _how / _by_id ("OK to send offers": when and how it was given)

The marketing activities saved in the 'crm' app setting are copied into crm_campaigns for the first workspace (the
setting itself is left as it was, so a downgrade loses nothing that was there before).

Revision ID: u8crm024
Revises: u7crm023
Create Date: 2026-10-21
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = 'u8crm024'
down_revision = 'u7crm023'
branch_labels = None
depends_on = None


def _first_workspace(conn):
    return conn.execute(sa.text('SELECT MIN(id) FROM workspaces')).scalar()


def _saved_channels(conn):
    """The marketing activities kept in the 'crm' setting: [[platform, activity, who, status]] or []."""
    settings = sa.table('app_settings', sa.column('key', sa.String), sa.column('value', sa.JSON))
    try:
        value = conn.execute(sa.select(settings.c.value).where(settings.c.key == 'crm')).scalar()
    except Exception:          # noqa: BLE001 -- no settings table (a bare database): nothing to copy
        return []
    rows = (value or {}).get('channels') if isinstance(value, dict) else None
    out = []
    for row in rows or []:
        if isinstance(row, (list, tuple)):
            cells = [str(c or '').strip()[:200] for c in list(row)[:4]] + [''] * 4
            if cells[0] or cells[1]:
                out.append(cells[:4])
    return out[:80]


def upgrade():
    op.create_table(
        'crm_rules',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspaces.id'), nullable=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('trigger', sa.String(20), nullable=False),
        sa.Column('trigger_args', sa.JSON(), nullable=True),
        sa.Column('conditions', sa.JSON(), nullable=True),
        sa.Column('actions', sa.JSON(), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('last_run_at', sa.DateTime(), nullable=True),
        sa.Column('run_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_error', sa.String(300), nullable=True),
        sa.Column('last_error_at', sa.DateTime(), nullable=True),
        sa.Column('conflict', sa.String(300), nullable=True),
    )
    op.create_index('ix_crm_rules_workspace_id', 'crm_rules', ['workspace_id'])
    op.create_table(
        'crm_rule_runs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('rule_id', sa.Integer(), sa.ForeignKey('crm_rules.id'), nullable=False),
        sa.Column('lead_id', sa.Integer(), sa.ForeignKey('crm_leads.id'), nullable=False),
        sa.Column('event_key', sa.String(120), nullable=False),
        sa.Column('ok', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('rule_id', 'lead_id', 'event_key', name='uq_crm_rule_runs'),
    )
    op.create_index('ix_crm_rule_runs_rule_id', 'crm_rule_runs', ['rule_id'])
    op.create_index('ix_crm_rule_runs_lead_id', 'crm_rule_runs', ['lead_id'])
    op.create_table(
        'crm_score_rules',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspaces.id'), nullable=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('points', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('signal', sa.String(30), nullable=False),
        sa.Column('args', sa.JSON(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_crm_score_rules_workspace_id', 'crm_score_rules', ['workspace_id'])
    op.create_table(
        'crm_campaigns',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspaces.id'), nullable=True),
        sa.Column('platform', sa.String(200), nullable=True),
        sa.Column('name', sa.String(200), nullable=True),
        sa.Column('who', sa.String(200), nullable=True),
        sa.Column('status', sa.String(200), nullable=True),
        sa.Column('utm_campaign', sa.String(120), nullable=True),
        sa.Column('source_id', sa.Integer(), sa.ForeignKey('crm_sources.id'), nullable=True),
        sa.Column('starts_on', sa.Date(), nullable=True),
        sa.Column('ends_on', sa.Date(), nullable=True),
        sa.Column('cost', sa.Numeric(12, 2), nullable=True),
        sa.Column('currency', sa.String(3), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_crm_campaigns_workspace_id', 'crm_campaigns', ['workspace_id'])
    op.create_index('ix_crm_campaigns_utm_campaign', 'crm_campaigns', ['utm_campaign'])
    with op.batch_alter_table('crm_leads') as batch:
        batch.add_column(sa.Column('score', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('likelihood_manual', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('ai_cache', sa.JSON(), nullable=True))
    with op.batch_alter_table('crm_people') as batch:
        batch.add_column(sa.Column('consent_marketing_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('consent_marketing_how', sa.String(120), nullable=True))
        batch.add_column(sa.Column('consent_marketing_by_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_crm_people_consent_marketing_by', 'users', ['consent_marketing_by_id'], ['id'])

    # a rating somebody already picked stays theirs: the score never changes it
    conn = op.get_bind()
    leads = sa.table('crm_leads', sa.column('likelihood', sa.String), sa.column('likelihood_manual', sa.Boolean))
    conn.execute(leads.update().where(leads.c.likelihood.isnot(None)).values(likelihood_manual=True))

    # the marketing activities saved so far become the first workspace's rows
    rows = _saved_channels(conn)
    if rows:
        ws = _first_workspace(conn)
        camp = sa.table('crm_campaigns', sa.column('workspace_id', sa.Integer), sa.column('platform', sa.String),
                        sa.column('name', sa.String), sa.column('who', sa.String), sa.column('status', sa.String),
                        sa.column('position', sa.Integer), sa.column('created_at', sa.DateTime),
                        sa.column('updated_at', sa.DateTime))
        now = datetime.utcnow()
        conn.execute(camp.insert(), [{'workspace_id': ws, 'platform': p or None, 'name': a or None, 'who': w or None,
                                      'status': s or None, 'position': n, 'created_at': now, 'updated_at': now}
                                     for n, (p, a, w, s) in enumerate(rows)])


def downgrade():
    with op.batch_alter_table('crm_people') as batch:
        batch.drop_constraint('fk_crm_people_consent_marketing_by', type_='foreignkey')
        batch.drop_column('consent_marketing_by_id')
        batch.drop_column('consent_marketing_how')
        batch.drop_column('consent_marketing_at')
    with op.batch_alter_table('crm_leads') as batch:
        batch.drop_column('ai_cache')
        batch.drop_column('likelihood_manual')
        batch.drop_column('score')
    op.drop_index('ix_crm_campaigns_utm_campaign', table_name='crm_campaigns')
    op.drop_index('ix_crm_campaigns_workspace_id', table_name='crm_campaigns')
    op.drop_table('crm_campaigns')
    op.drop_index('ix_crm_score_rules_workspace_id', table_name='crm_score_rules')
    op.drop_table('crm_score_rules')
    op.drop_index('ix_crm_rule_runs_lead_id', table_name='crm_rule_runs')
    op.drop_index('ix_crm_rule_runs_rule_id', table_name='crm_rule_runs')
    op.drop_table('crm_rule_runs')
    op.drop_index('ix_crm_rules_workspace_id', table_name='crm_rules')
    op.drop_table('crm_rules')
