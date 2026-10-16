"""One menu: role page keys renamed, "Customer service" becomes "Sales & service", a Team lead role

The staff menu was regrouped (services/access.py SECTIONS). Page keys changed with it, so every
stored role list is rewritten the way access.expand_page_keys reads it:
  wa_contacts -> crm_people, wa_quick -> crm_quick, wa_overview -> (dropped),
  crm_setup -> its five pages, and wa_settings also grants wa_tags.
The role "Customer service" is renamed "Sales & service" (unless the workspace already has one),
and each workspace gets a "Team lead" role (Sales & service plus Team today, Results and Broadcasts)
because an existing workspace never runs ensure_defaults again.

Data only, so it does not import app code. Downgrade reverses the key renames and the role name.

Revision ID: s2crm006
Revises: s1crm005
Create Date: 2026-10-16
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = 's2crm006'
down_revision = 's1crm005'
branch_labels = None
depends_on = None

roles = sa.table('workspace_roles', sa.column('id', sa.Integer), sa.column('workspace_id', sa.Integer),
                 sa.column('name', sa.String), sa.column('description', sa.String), sa.column('pages', sa.JSON),
                 sa.column('system_key', sa.String), sa.column('created_at', sa.DateTime))

RENAMES = {'wa_contacts': ['crm_people'], 'wa_quick': ['crm_quick'],
           'crm_setup': ['crm_pipelines', 'crm_sources', 'crm_connection', 'crm_data', 'crm_export'],
           'wa_overview': []}
BACK = {'crm_people': ['wa_contacts'], 'crm_quick': ['wa_quick'], 'crm_pipelines': ['crm_setup'],
        'crm_sources': ['crm_setup'], 'crm_connection': ['crm_setup'], 'crm_data': ['crm_setup'],
        'crm_export': ['crm_setup'], 'wa_tags': [], 'crm_auto': []}
# access.CS_ROLE_PAGES as of this revision
SALES_AND_SERVICE = ['crm_add', 'crm_board', 'crm_checks', 'crm_people', 'crm_process', 'crm_quick', 'crm_today',
                     'home', 'import', 'insurance', 'matches', 'metrics', 'new', 'notifications', 'posts',
                     'sahayak', 'voices_contact', 'voices_feedback', 'voices_general', 'voices_insurance',
                     'voices_report', 'voices_sahayak', 'wa_inbox']
TEAM_LEAD_EXTRA = ['crm_auto', 'crm_insights', 'crm_tracker', 'wa_broadcasts']
TEAM_LEAD_NOTE = 'Sales & service, plus Team today, Results and Broadcasts.'


def _map(keys, table):
    """The list with each key swapped for what the table says; order kept, no duplicates."""
    out = []
    for k in keys or []:
        for n in table.get(k, [k]):
            if n not in out:
                out.append(n)
    return out


def _up(keys):
    out = _map(keys, RENAMES)
    if 'wa_settings' in out and 'wa_tags' not in out:
        out.append('wa_tags')
    return out


def _down(keys):
    return _map(keys, BACK)


def _rewrite(conn, fn):
    for row in conn.execute(sa.select(roles.c.id, roles.c.pages)).fetchall():
        old = list(row.pages or [])
        new = fn(old)
        if new != old:
            conn.execute(roles.update().where(roles.c.id == row.id).values(pages=new))


def _rename(conn, system_key, old, new):
    """Rename that role in each workspace that has no role by the new name already."""
    taken = {(r.workspace_id, r.name) for r in conn.execute(sa.select(roles.c.workspace_id, roles.c.name))}
    for row in conn.execute(sa.select(roles.c.id, roles.c.workspace_id, roles.c.name, roles.c.system_key)).fetchall():
        if row.name != old or (system_key and row.system_key != system_key):
            continue
        if (row.workspace_id, new) in taken:
            continue
        conn.execute(roles.update().where(roles.c.id == row.id).values(name=new))
        taken.add((row.workspace_id, new))


def upgrade():
    conn = op.get_bind()
    _rewrite(conn, _up)
    _rename(conn, None, 'Customer service', 'Sales & service')
    rows = conn.execute(sa.select(roles.c.workspace_id, roles.c.name, roles.c.system_key, roles.c.pages)).fetchall()
    for ws_id in sorted({r.workspace_id for r in rows}):
        mine = [r for r in rows if r.workspace_id == ws_id]
        if any((r.name or '').lower() == 'team lead' for r in mine):
            continue
        cs = next((r for r in mine if r.system_key == 'cs'), None)
        pages = sorted(set((cs.pages if cs is not None and cs.pages else None) or SALES_AND_SERVICE) | set(TEAM_LEAD_EXTRA))
        conn.execute(roles.insert().values(workspace_id=ws_id, name='Team lead', description=TEAM_LEAD_NOTE,
                                           pages=pages, system_key=None, created_at=datetime.utcnow()))


def downgrade():
    conn = op.get_bind()
    _rewrite(conn, _down)
    _rename(conn, 'cs', 'Sales & service', 'Customer service')
