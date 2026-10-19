"""Accounts: Super admin -- the only people who delete for good

users.roles   the owner of every workspace gets 'superadmin' (and 'admin'), keeping their other roles, so that
              somebody can still delete after this release. Administrators who are not owners stop being able to
              delete until a Super admin ticks "Super admin" for them on the Users screen.

Revision ID: t2su013
Revises: t1ws012
Create Date: 2026-10-19
"""
import json

from alembic import op
import sqlalchemy as sa

revision = 't2su013'
down_revision = 't1ws012'
branch_labels = None
depends_on = None

users = sa.table('users', sa.column('id', sa.Integer), sa.column('roles', sa.JSON),
                 sa.column('role', sa.String), sa.column('is_admin', sa.Boolean))


def _keys(roles, role, is_admin):
    if isinstance(roles, str):
        roles = json.loads(roles or 'null')
    keys = list(roles or [])
    if not keys:
        keys = [role or 'user'] + (['admin'] if is_admin and role != 'admin' else [])
    return keys


def upgrade():
    conn = op.get_bind()
    # no DISTINCT: Postgres has no equality for a json column; somebody owning two workspaces is just seen twice
    rows = conn.execute(sa.text(
        'SELECT u.id, u.roles, u.role, u.is_admin FROM users u '
        'JOIN workspace_members m ON m.user_id = u.id WHERE m.is_owner')).fetchall()
    done = set()
    for uid, roles, role, is_admin in rows:
        if uid in done:
            continue
        done.add(uid)
        keys = _keys(roles, role, is_admin)
        for k in ('admin', 'superadmin'):
            if k not in keys:
                keys.append(k)
        conn.execute(users.update().where(users.c.id == uid).values(roles=keys, role='admin', is_admin=True))


def downgrade():
    conn = op.get_bind()
    for uid, roles, role, is_admin in conn.execute(sa.text('SELECT id, roles, role, is_admin FROM users')).fetchall():
        keys = _keys(roles, role, is_admin)
        if 'superadmin' in keys:
            conn.execute(users.update().where(users.c.id == uid).values(roles=[k for k in keys if k != 'superadmin']))
