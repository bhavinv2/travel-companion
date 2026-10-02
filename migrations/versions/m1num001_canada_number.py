"""publish the Canada support line on an install still using the two-field shape

Adding a number is a row on Admin -> Landing page now, so this would normally not be a migration
at all. But an install that has not opened that screen since it changed still has only the old
whatsapp_in / whatsapp_us pair in app_settings, and services/offices reads those when
contact_numbers is unset -- which means a third country has nowhere to live and simply never
appears. Writing the list once converts that install to the new shape with Canada in it; from
then on the screen owns it and this migration never touches anything again.

Deliberately conservative: it runs only when contact_numbers is unset, it keeps whatever numbers
were actually configured (a cleared one stays cleared), and it leaves the row alone entirely if
nobody ever set a number, because the shipped defaults already cover that case.

Revision ID: m1num001
Revises: l1rep001
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = 'm1num001'
down_revision = 'l1rep001'
branch_labels = None
depends_on = None

CANADA = {'label': 'Canada', 'iso': 'CA', 'number': '+1 (647) 770-2288',
          'whatsapp': False, 'sites': []}

settings = sa.table('app_settings',
                    sa.column('key', sa.String),
                    sa.column('value', sa.JSON))


def _landing(conn):
    """The stored landing settings as a dict, or None when there is no row to change."""
    import json
    row = conn.execute(sa.select(settings.c.value)
                       .where(settings.c.key == 'landing')).first()
    if row is None:
        return None
    value = row[0]
    if isinstance(value, (str, bytes)):           # SQLite hands JSON back as text
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def upgrade():
    conn = op.get_bind()
    cur = _landing(conn)
    if cur is None or cur.get('contact_numbers') is not None:
        return                                    # already on the new shape, or nothing to convert

    rows = []
    if (cur.get('whatsapp_in') or '').strip():
        rows.append({'label': 'India', 'iso': 'IN', 'number': cur['whatsapp_in'].strip(),
                     'whatsapp': True, 'sites': []})
    if (cur.get('whatsapp_us') or '').strip():
        rows.append({'label': 'USA', 'iso': 'US', 'number': cur['whatsapp_us'].strip(),
                     'whatsapp': False, 'sites': []})
    if not rows:
        return                                    # the shipped defaults already include Canada

    rows.append(CANADA)
    cur['contact_numbers'] = rows
    conn.execute(settings.update().where(settings.c.key == 'landing').values(value=cur))


def downgrade():
    """Take the Canada row back out, leaving the rest of the list as staff have it."""
    conn = op.get_bind()
    cur = _landing(conn)
    if cur is None or not isinstance(cur.get('contact_numbers'), list):
        return
    kept = [r for r in cur['contact_numbers']
            if not (isinstance(r, dict) and (r.get('iso') or '').upper() == 'CA')]
    if len(kept) == len(cur['contact_numbers']):
        return
    cur['contact_numbers'] = kept
    conn.execute(settings.update().where(settings.c.key == 'landing').values(value=cur))
