"""Sales CRM: products and pipelines made on screen

crm_products         what a lead asks about (code, name, icon, offered, its pipeline, kpi row), seeded from the old lists
crm_fields           lead details asked per pipeline (none seeded: Travels on and Cover ends stay columns)
product              widened to 8 letters on pipelines, sources, leads and answers
crm_stages           means (new / talking / quoted / won / lost), button_label / button_code, auto_field
crm_pipelines        tag_mode / tag_label (the WhatsApp tag's first part), catch_all
crm_playbook_steps   kind, trigger_field, wa_params; "N days before they travel" becomes date_offset -N on a date
sources              ti-support, contact-companion and contact-sahayak point at the pipeline the catch-all rule
                     already passed their leads on to. No lead changes pipeline.

No network calls and no app imports: the rules are this file's own copies.

Revision ID: s5crm009
Revises: s4crm008
Create Date: 2026-10-16
"""
import re
from collections import defaultdict

from alembic import op
import sqlalchemy as sa

revision = 's5crm009'
down_revision = 's4crm008'
branch_labels = None
depends_on = None

# (code, name, icon, default pipeline key, kpi row)
PRODUCTS = [('TC', 'Travel Companion', 'fa-plane-departure', 'tc-companion', 'tc_posts'),
            ('TI', 'Travel Insurance', 'fa-shield-heart', 'ti-standard', None),
            ('SH', 'Sahayak', 'fa-house-medical', 'sahayak-visit', None),
            ('GH', 'Gift Health', 'fa-gift', 'general', None),
            ('VC', 'Virtual Consultation', 'fa-user-doctor', 'general', None),
            ('GEN', 'General', 'fa-comments', 'general', None)]
MILESTONES = {'quoted': ('I sent the quote', 'Q'), 'pipeline': ('I sent the payment link', 'PLS')}
KIND_PREFIXES = {'PI': 'reminder', 'CE': 'care', 'SH': 'care', 'BW': 'birthday', 'FM': 'festival',
                 'OM': 'festival', 'PM': 'promotion', 'ER': 'expiry', 'PF': 'after_lost'}
LEGACY = {'before_departure_days': 'departure_date', 'before_end_days': 'ends_on'}
WIDEN = ('crm_pipelines', 'crm_sources', 'crm_leads', 'crm_answers')

pipelines = sa.table('crm_pipelines', sa.column('id', sa.Integer), sa.column('key', sa.String),
                     sa.column('product', sa.String), sa.column('is_active', sa.Boolean),
                     sa.column('catch_all', sa.Boolean))
stages = sa.table('crm_stages', sa.column('id', sa.Integer), sa.column('pipeline_id', sa.Integer),
                  sa.column('position', sa.Integer), sa.column('kind', sa.String), sa.column('on_reply', sa.Boolean),
                  sa.column('key', sa.String), sa.column('means', sa.String),
                  sa.column('button_label', sa.String), sa.column('button_code', sa.String),
                  sa.column('auto_kind', sa.String), sa.column('auto_field', sa.String))
steps = sa.table('crm_playbook_steps', sa.column('id', sa.Integer), sa.column('code', sa.String),
                 sa.column('kind', sa.String), sa.column('trigger', sa.String),
                 sa.column('trigger_value', sa.Integer), sa.column('trigger_field', sa.String))
products = sa.table('crm_products', sa.column('id', sa.Integer), sa.column('code', sa.String),
                    sa.column('name', sa.String), sa.column('icon', sa.String), sa.column('offered', sa.Boolean),
                    sa.column('default_pipeline_id', sa.Integer), sa.column('currency', sa.String),
                    sa.column('kpi_row', sa.String), sa.column('position', sa.Integer))
sources = sa.table('crm_sources', sa.column('id', sa.Integer), sa.column('key', sa.String),
                   sa.column('product', sa.String), sa.column('pipeline_id', sa.Integer))
leads = sa.table('crm_leads', sa.column('product', sa.String))


def _step_kind(code, product_codes):
    m = re.match(r'^[A-Z]+', (code or '').strip().upper())
    prefix = m.group(0) if m else ''
    if prefix in KIND_PREFIXES:
        return KIND_PREFIXES[prefix]
    return 'first' if prefix in product_codes else 'other'


def upgrade():
    op.create_table(
        'crm_products',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code', sa.String(8), nullable=False),
        sa.Column('name', sa.String(60), nullable=False),
        sa.Column('icon', sa.String(40), nullable=False, server_default='fa-layer-group'),
        sa.Column('offered', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('default_pipeline_id', sa.Integer(), sa.ForeignKey('crm_pipelines.id'), nullable=True),
        sa.Column('currency', sa.String(3), nullable=False, server_default='INR'),
        sa.Column('kpi_row', sa.String(30), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.UniqueConstraint('code', name='uq_crm_product_code'),
    )
    op.create_table(
        'crm_fields',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('pipeline_id', sa.Integer(), sa.ForeignKey('crm_pipelines.id'), nullable=True),
        sa.Column('key', sa.String(40), nullable=False),
        sa.Column('label', sa.String(80), nullable=False),
        sa.Column('type', sa.String(10), nullable=False, server_default='text'),
        sa.Column('options', sa.JSON(), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('on_card', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('on_add', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('required', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint('pipeline_id', 'key', name='uq_crm_field_key'),
    )
    op.create_index('ix_crm_fields_pipeline_id', 'crm_fields', ['pipeline_id'])

    for t in WIDEN:
        with op.batch_alter_table(t) as b:
            b.alter_column('product', existing_type=sa.String(4), type_=sa.String(8), existing_nullable=False)

    op.add_column('crm_stages', sa.Column('means', sa.String(8), nullable=True))
    op.add_column('crm_stages', sa.Column('button_label', sa.String(60), nullable=True))
    op.add_column('crm_stages', sa.Column('button_code', sa.String(20), nullable=True))
    op.add_column('crm_stages', sa.Column('auto_field', sa.String(40), nullable=True))
    op.add_column('crm_pipelines', sa.Column('tag_mode', sa.String(8), nullable=False, server_default='product'))
    op.add_column('crm_pipelines', sa.Column('tag_label', sa.String(30), nullable=True))
    op.add_column('crm_pipelines', sa.Column('catch_all', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('crm_playbook_steps', sa.Column('kind', sa.String(16), nullable=True))
    op.add_column('crm_playbook_steps', sa.Column('trigger_field', sa.String(40), nullable=True))
    op.add_column('crm_playbook_steps', sa.Column('wa_params', sa.JSON(), nullable=True))

    conn = op.get_bind()

    # a. products, from the old lists (each only when its code is missing)
    pipe_ids = {k: i for i, k in conn.execute(sa.select(pipelines.c.id, pipelines.c.key))}
    have = {c for (c,) in conn.execute(sa.select(products.c.code))}
    for pos, (code, name, icon, pkey, kpi) in enumerate(PRODUCTS):
        if code not in have:
            conn.execute(products.insert().values(code=code, name=name, icon=icon, offered=True,
                                                  default_pipeline_id=pipe_ids.get(pkey), currency='INR',
                                                  kpi_row=kpi, position=pos))
            have.add(code)
    extra = set()
    for table in (pipelines, sources, leads):
        extra |= {c for (c,) in conn.execute(sa.select(table.c.product).distinct()) if c}
    for code in sorted(extra - have):
        conn.execute(products.insert().values(code=code, name=code, icon='fa-layer-group', offered=False,
                                              currency='INR', position=len(have)))
        have.add(code)

    # b. the catch-all
    conn.execute(pipelines.update().where(pipelines.c.key == 'general').values(catch_all=True))

    # c. stages: "this stage means" by the old rule (where the stage sits), buttons, 'departed'
    by_pipe = defaultdict(list)
    for row in conn.execute(sa.select(stages.c.id, stages.c.pipeline_id, stages.c.position, stages.c.kind,
                                      stages.c.on_reply, stages.c.key, stages.c.means, stages.c.button_label,
                                      stages.c.auto_kind)):
        by_pipe[row.pipeline_id].append(row)
    for rows in by_pipe.values():
        rows.sort(key=lambda r: (r.position, r.id))
        opens = [r for r in rows if r.kind == 'open']
        reply = next((r for r in rows if r.on_reply), None)
        for r in rows:
            values = {}
            if r.means is None:
                if r.kind == 'won':
                    values['means'] = 'won'
                elif r.kind == 'lost':
                    values['means'] = 'lost'
                elif opens and opens[0].id == r.id:
                    values['means'] = 'new'
                elif reply is not None and reply.id == r.id:
                    values['means'] = 'talking'
                elif reply is not None and r.position < reply.position:
                    values['means'] = 'new'
                else:
                    values['means'] = 'quoted'
            if r.button_label is None and r.key in MILESTONES:
                values['button_label'], values['button_code'] = MILESTONES[r.key]
            if r.auto_kind == 'departed':
                values['auto_kind'], values['auto_field'] = 'after_date', 'departure_date'
            if values:
                conn.execute(stages.update().where(stages.c.id == r.id).values(**values))

    # d. follow-up steps: kind from the code, "days before" as date_offset on a date
    codes = {c for (c,) in conn.execute(sa.select(products.c.code))}
    for row in conn.execute(sa.select(steps.c.id, steps.c.code, steps.c.kind, steps.c.trigger,
                                      steps.c.trigger_value)).fetchall():
        values = {}
        if row.kind is None:
            values['kind'] = _step_kind(row.code, codes)
        if row.trigger in LEGACY:
            values.update(trigger='date_offset', trigger_field=LEGACY[row.trigger],
                          trigger_value=-abs(row.trigger_value or 0))
        if values:
            conn.execute(steps.update().where(steps.c.id == row.id).values(**values))

    # e. sources whose leads the catch-all rule already passed on go to that pipeline themselves
    pipe_rows = {r.id: r for r in conn.execute(sa.select(pipelines.c.id, pipelines.c.product,
                                                         pipelines.c.is_active, pipelines.c.catch_all)
                                               .order_by(pipelines.c.id))}
    prods = {r.code: r for r in conn.execute(sa.select(products.c.code, products.c.default_pipeline_id))}
    for src in conn.execute(sa.select(sources.c.id, sources.c.product, sources.c.pipeline_id)).fetchall():
        c = pipe_rows.get(src.pipeline_id)
        if c is None or not c.catch_all or src.product == c.product:
            continue
        prod = prods.get(src.product)
        d = pipe_rows.get(prod.default_pipeline_id) if prod is not None else None
        if d is not None and d.is_active and not d.catch_all:
            target = d.id
        else:
            target = next((r.id for r in pipe_rows.values()
                           if r.product == src.product and r.is_active and not r.catch_all), None)
        if target:
            conn.execute(sources.update().where(sources.c.id == src.id).values(pipeline_id=target))


def downgrade():
    conn = op.get_bind()
    long_codes = [c for (c,) in conn.execute(sa.select(products.c.code)) if len(c or '') > 4]
    if long_codes:
        raise RuntimeError('Product codes longer than 4 letters exist (%s): shorten them before going back.'
                           % ', '.join(long_codes))
    for row in conn.execute(sa.select(steps.c.id, steps.c.trigger, steps.c.trigger_field,
                                      steps.c.trigger_value)).fetchall():
        if row.trigger != 'date_offset':
            continue
        v = row.trigger_value or 0
        if row.trigger_field == 'departure_date' and v <= 0:
            values = dict(trigger='before_departure_days', trigger_value=-v)
        elif row.trigger_field == 'ends_on' and v <= 0:
            values = dict(trigger='before_end_days', trigger_value=-v)
        else:
            values = dict(trigger='after_hours', trigger_value=24)
        conn.execute(steps.update().where(steps.c.id == row.id).values(**values))
    for row in conn.execute(sa.select(stages.c.id, stages.c.auto_kind, stages.c.auto_field)).fetchall():
        if row.auto_kind == 'after_date' and row.auto_field == 'departure_date':
            conn.execute(stages.update().where(stages.c.id == row.id).values(auto_kind='departed'))
        elif row.auto_kind in ('after_date', 'in_stage'):
            conn.execute(stages.update().where(stages.c.id == row.id).values(auto_kind=None))

    op.drop_index('ix_crm_fields_pipeline_id', table_name='crm_fields')
    op.drop_table('crm_fields')
    op.drop_table('crm_products')
    with op.batch_alter_table('crm_playbook_steps') as b:
        b.drop_column('wa_params')
        b.drop_column('trigger_field')
        b.drop_column('kind')
    with op.batch_alter_table('crm_pipelines') as b:
        b.drop_column('catch_all')
        b.drop_column('tag_label')
        b.drop_column('tag_mode')
    with op.batch_alter_table('crm_stages') as b:
        b.drop_column('auto_field')
        b.drop_column('button_code')
        b.drop_column('button_label')
        b.drop_column('means')
    for t in WIDEN:
        with op.batch_alter_table(t) as b:
            b.alter_column('product', existing_type=sa.String(8), type_=sa.String(4), existing_nullable=False)
