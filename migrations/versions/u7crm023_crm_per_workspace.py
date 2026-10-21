"""Sales CRM 2.0, Phase 5 run 5a: CRM data per workspace

workspace_id (FK workspaces, nullable, indexed) on the top-level CRM tables: crm_pipelines, crm_products, crm_sources,
crm_households, crm_people, crm_identities (a copy of its person's, for its uniqueness), crm_channel_checks,
crm_leads, crm_targets, crm_daily_stats, crm_views, crm_saved_reports, crm_audit, crm_answers, crm_activities.
Child tables (stages, fields, steps, touches, tasks, stage moves, quotes, payments, files) follow their parent.
Global: crm_currency_rates, crm_do_not_contact.

Every existing row goes to the first workspace (lowest id); with no workspace yet they stay NULL, which the code reads
as the default workspace. The backfill runs BEFORE the new unique constraints are made, so PostgreSQL never sees a
NULL workspace in them. Unique per workspace from now on:
    crm_people (phone)                     -> (workspace_id, phone)
    crm_pipelines (key)                    -> (workspace_id, key)
    crm_sources (key)                      -> (workspace_id, key)
    crm_products (code)                    -> (workspace_id, code)
    crm_identities (kind, value)           -> (workspace_id, kind, value)
    crm_channel_checks (day, slot, channel) -> (workspace_id, day, slot, channel)
crm_daily_stats, crm_targets and crm_views keep their uniqueness in code (no constraint before, none now).

Revision ID: u7crm023
Revises: u6crm022
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = 'u7crm023'
down_revision = 'u6crm022'
branch_labels = None
depends_on = None

TABLES = ('crm_pipelines', 'crm_products', 'crm_sources', 'crm_households', 'crm_people', 'crm_identities',
          'crm_channel_checks', 'crm_leads', 'crm_targets', 'crm_daily_stats', 'crm_views', 'crm_saved_reports',
          'crm_audit', 'crm_answers', 'crm_activities')

# table: (old columns, the old constraint's name as the earlier migrations made it on PostgreSQL, new name)
UNIQUES = {
    'crm_people': (['phone'], 'crm_people_phone_key', 'uq_crm_people_ws_phone'),
    'crm_pipelines': (['key'], 'crm_pipelines_key_key', 'uq_crm_pipelines_ws_key'),
    'crm_sources': (['key'], 'crm_sources_key_key', 'uq_crm_sources_ws_key'),
    'crm_products': (['code'], 'uq_crm_product_code', 'uq_crm_products_ws_code'),
    'crm_identities': (['kind', 'value'], 'uq_crm_identity', 'uq_crm_identities_ws'),
    'crm_channel_checks': (['day', 'slot', 'channel'], 'uq_crm_check', 'uq_crm_checks_ws'),
}

# SQLite keeps an inline UNIQUE without a name: in batch mode the reflected copy gets this one, so it can be dropped
NAMING = {'uq': 'uq_%(table_name)s_%(column_0_N_name)s'}


def _old_unique_name(table, cols, fallback):
    """The real name of the unique constraint on exactly `cols` (PostgreSQL: crm_people_phone_key ...); on SQLite an
    unnamed one is called by NAMING inside the batch."""
    insp = sa.inspect(op.get_bind())
    for uc in insp.get_unique_constraints(table):
        if list(uc.get('column_names') or []) == list(cols):
            if uc.get('name'):
                return uc['name']
            return NAMING['uq'] % {'table_name': table, 'column_0_N_name': '_'.join(cols)}
    return None if fallback is None else fallback


def upgrade():
    # 1. the column, its index and its foreign key
    for t in TABLES:
        with op.batch_alter_table(t) as batch:
            batch.add_column(sa.Column('workspace_id', sa.Integer(), nullable=True))
            batch.create_index('ix_%s_workspace_id' % t, ['workspace_id'])
            batch.create_foreign_key('fk_%s_workspace_id' % t, 'workspaces', ['workspace_id'], ['id'])

    # 2. every existing row -> the first workspace (none yet: they stay NULL = the default workspace)
    bind = op.get_bind()
    meta = sa.MetaData()
    ws = sa.Table('workspaces', meta, sa.Column('id', sa.Integer, primary_key=True))
    first = bind.execute(sa.select(sa.func.min(ws.c.id))).scalar()
    if first is not None:
        for t in TABLES:
            if t == 'crm_identities':
                continue
            tab = sa.Table(t, sa.MetaData(), sa.Column('id', sa.Integer, primary_key=True),
                           sa.Column('workspace_id', sa.Integer))
            bind.execute(sa.update(tab).where(tab.c.workspace_id.is_(None)).values(workspace_id=first))
        # an identity takes its person's workspace
        m2 = sa.MetaData()
        people = sa.Table('crm_people', m2, sa.Column('id', sa.Integer, primary_key=True),
                          sa.Column('workspace_id', sa.Integer))
        ident = sa.Table('crm_identities', m2, sa.Column('id', sa.Integer, primary_key=True),
                         sa.Column('person_id', sa.Integer), sa.Column('workspace_id', sa.Integer))
        bind.execute(sa.update(ident).where(ident.c.workspace_id.is_(None)).values(
            workspace_id=sa.select(people.c.workspace_id).where(people.c.id == ident.c.person_id).scalar_subquery()))
        bind.execute(sa.update(ident).where(ident.c.workspace_id.is_(None)).values(workspace_id=first))

    # 3. uniqueness per workspace (after the backfill)
    for t, (cols, old_name, new_name) in UNIQUES.items():
        old = _old_unique_name(t, cols, None)
        with op.batch_alter_table(t, naming_convention=NAMING) as batch:
            if old:
                batch.drop_constraint(old, type_='unique')
            batch.create_unique_constraint(new_name, ['workspace_id'] + cols)


def downgrade():
    # The old constraints come back with their old names. This fails if two workspaces really share a value (the same
    # phone number as a contact in two workspaces, the same pipeline key or source key, the same product code): merge
    # or rename those first -- the database cannot hold them under one global constraint.
    for t, (cols, old_name, new_name) in UNIQUES.items():
        with op.batch_alter_table(t, naming_convention=NAMING) as batch:
            batch.drop_constraint(new_name, type_='unique')
            batch.create_unique_constraint(old_name, cols)
    for t in reversed(TABLES):
        with op.batch_alter_table(t) as batch:
            batch.drop_constraint('fk_%s_workspace_id' % t, type_='foreignkey')
            batch.drop_index('ix_%s_workspace_id' % t)
            batch.drop_column('workspace_id')
