"""Sales CRM: quick replies -- one title each

crm_answers   a title another quick reply already has (ignoring case and spaces around it) gets " (2)",
              " (3)" ... added; the oldest keeps its own. From now on Quick replies refuses a second one in
              code: WhatsApp matches quick replies by title, so two with one title would overwrite each
              other there.

Revision ID: s7crm011
Revises: s6crm010
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa

revision = 's7crm011'
down_revision = 's6crm010'
branch_labels = None
depends_on = None
MAX = 160


def upgrade():
    conn = op.get_bind()
    rows = conn.execute(sa.text('SELECT id, title FROM crm_answers ORDER BY id')).fetchall()
    taken = {(t or '').strip().lower() for _, t in rows}
    seen = set()
    for rid, title in rows:
        base = (title or '').strip()
        key = base.lower()
        if key not in seen:
            seen.add(key)
            continue
        n = 2
        while True:
            suffix = ' (%d)' % n
            new = base[:MAX - len(suffix)] + suffix
            if new.lower() not in taken:
                break
            n += 1
        conn.execute(sa.text('UPDATE crm_answers SET title = :t WHERE id = :i'), {'t': new, 'i': rid})
        taken.add(new.lower())
        seen.add(new.lower())


def downgrade():
    pass        # data only: the old duplicate titles are not brought back
