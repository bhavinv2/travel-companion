"""Accounts: only sign-ups are asked to confirm their e-mail

users.signed_up   True for an account made on the sign-up page (from now on set there). For the accounts that
                  exist, the ones that would have been asked before -- not confirmed, no Google / Facebook, not
                  staff -- keep being asked, except accounts made by claiming a post (made within ten minutes of
                  the claim of a post they now own): those are never asked any more.

Revision ID: t4su015
Revises: t3ws014
Create Date: 2026-10-21
"""
from datetime import timedelta

from alembic import op
import sqlalchemy as sa

revision = 't4su015'
down_revision = 't3ws014'
branch_labels = None
depends_on = None

users = sa.table('users', sa.column('id', sa.Integer), sa.column('signed_up', sa.Boolean))


def upgrade():
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('signed_up', sa.Boolean(), nullable=False, server_default=sa.false()))
    conn = op.get_bind()
    asked = conn.execute(sa.text(
        "SELECT id, created_at FROM users WHERE (is_verified IS NULL OR NOT is_verified) AND oauth_provider IS NULL "
        "AND (is_admin IS NULL OR NOT is_admin) AND (role IS NULL OR role NOT IN ('cs', 'admin'))")).fetchall()
    claims = {}
    for uid, claimed_at in conn.execute(sa.text(
            'SELECT user_id, claimed_at FROM companion_requests WHERE user_id IS NOT NULL AND claimed_at IS NOT NULL')):
        claims.setdefault(uid, []).append(claimed_at)
    for uid, created in asked:
        by_claim = created is not None and any(c is not None and abs(c - created) <= timedelta(minutes=10)
                                               for c in claims.get(uid, []))
        if not by_claim:
            conn.execute(users.update().where(users.c.id == uid).values(signed_up=True))


def downgrade():
    with op.batch_alter_table('users') as batch:
        batch.drop_column('signed_up')
