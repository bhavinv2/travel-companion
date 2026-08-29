"""phase 2a: roles, contact points, claim tokens, activity events, post lifecycle

Revision ID: 262b3294a429
Revises: a3f8e1c0b2d4
Create Date: 2026-08-29 22:45:31.198193

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '262b3294a429'
down_revision = 'a3f8e1c0b2d4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('activity_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('trip_id', sa.Integer(), nullable=True),
    sa.Column('match_id', sa.Integer(), nullable=True),
    sa.Column('actor_type', sa.String(length=10), nullable=True),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('event', sa.String(length=40), nullable=False),
    sa.Column('meta', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['trip_id'], ['companion_requests.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('activity_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_activity_events_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_activity_events_event'), ['event'], unique=False)
        batch_op.create_index(batch_op.f('ix_activity_events_match_id'), ['match_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_activity_events_trip_id'), ['trip_id'], unique=False)

    op.create_table('claim_tokens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token', sa.String(length=64), nullable=False),
    sa.Column('trip_id', sa.Integer(), nullable=False),
    sa.Column('purpose', sa.String(length=30), nullable=True),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('used_at', sa.DateTime(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['trip_id'], ['companion_requests.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('claim_tokens', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_claim_tokens_token'), ['token'], unique=True)

    op.create_table('contact_points',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('trip_id', sa.Integer(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('value', sa.String(length=255), nullable=False),
    sa.Column('label', sa.String(length=100), nullable=True),
    sa.Column('is_preferred', sa.Boolean(), nullable=True),
    sa.Column('consent_to_share', sa.Boolean(), nullable=True),
    sa.Column('verified', sa.Boolean(), nullable=True),
    sa.Column('added_by', sa.String(length=10), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['trip_id'], ['companion_requests.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('contact_points', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_contact_points_trip_id'), ['trip_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_contact_points_user_id'), ['user_id'], unique=False)

    # Legacy masked-relay messages: only ever written by the removed /api/send-message endpoint.
    op.drop_table('messages')

    with op.batch_alter_table('companion_requests', schema=None) as batch_op:
        batch_op.add_column(sa.Column('origin_iata', sa.String(length=5), nullable=True))
        batch_op.add_column(sa.Column('origin_city', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('origin_metro', sa.String(length=60), nullable=True))
        batch_op.add_column(sa.Column('dest_iata', sa.String(length=5), nullable=True))
        batch_op.add_column(sa.Column('dest_city', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('dest_metro', sa.String(length=60), nullable=True))
        batch_op.add_column(sa.Column('ticket_attachment', sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column('source', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('source_url', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('import_key', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('created_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('poster_name', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('traveler_name', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('role', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('traveler_age_group', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('traveler_gender', sa.String(length=15), nullable=True))
        batch_op.add_column(sa.Column('pref_gender', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('pref_age_min', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('pref_age_max', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('status', sa.String(length=15), nullable=True))
        batch_op.add_column(sa.Column('closed_reason', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('closed_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('closed_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('claimed_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('cs_notes', sa.Text(), nullable=True))
        batch_op.alter_column('user_id', existing_type=sa.INTEGER(), nullable=True)
        batch_op.create_index(batch_op.f('ix_companion_requests_dest_iata'), ['dest_iata'], unique=False)
        batch_op.create_index(batch_op.f('ix_companion_requests_dest_metro'), ['dest_metro'], unique=False)
        batch_op.create_index(batch_op.f('ix_companion_requests_origin_iata'), ['origin_iata'], unique=False)
        batch_op.create_index(batch_op.f('ix_companion_requests_origin_metro'), ['origin_metro'], unique=False)
        batch_op.create_index(batch_op.f('ix_companion_requests_role'), ['role'], unique=False)
        batch_op.create_index(batch_op.f('ix_companion_requests_source'), ['source'], unique=False)
        batch_op.create_index(batch_op.f('ix_companion_requests_status'), ['status'], unique=False)
        batch_op.create_unique_constraint('uq_companion_requests_import_key', ['import_key'])
        batch_op.create_foreign_key('fk_companion_requests_created_by_id_users', 'users', ['created_by_id'], ['id'])
        batch_op.create_foreign_key('fk_companion_requests_closed_by_id_users', 'users', ['closed_by_id'], ['id'])

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('role', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('phone_verified', sa.Boolean(), nullable=True))

    # --- Data backfill for rows that existed before Phase 2 -------------------------------
    op.execute("UPDATE companion_requests SET status = CASE WHEN is_active THEN 'open' ELSE 'closed' END WHERE status IS NULL")
    op.execute("UPDATE companion_requests SET closed_reason = 'no_longer_required' WHERE status = 'closed' AND closed_reason IS NULL")
    op.execute("UPDATE companion_requests SET source = 'organic' WHERE source IS NULL")
    op.execute("UPDATE companion_requests SET role = 'seeking_help' WHERE role IS NULL")
    op.execute("UPDATE companion_requests SET pref_gender = 'any' WHERE pref_gender IS NULL")
    op.execute("UPDATE companion_requests SET claimed_at = created_at WHERE claimed_at IS NULL")
    op.execute("UPDATE users SET role = CASE WHEN is_admin THEN 'admin' ELSE 'user' END WHERE role IS NULL")
    op.execute("UPDATE users SET phone_verified = false WHERE phone_verified IS NULL")
    # origin_/dest_ iata/city/metro are filled by:  flask backfill-locations


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('phone_verified')
        batch_op.drop_column('role')

    with op.batch_alter_table('companion_requests', schema=None) as batch_op:
        batch_op.drop_constraint('fk_companion_requests_closed_by_id_users', type_='foreignkey')
        batch_op.drop_constraint('fk_companion_requests_created_by_id_users', type_='foreignkey')
        batch_op.drop_constraint('uq_companion_requests_import_key', type_='unique')
        batch_op.drop_index(batch_op.f('ix_companion_requests_status'))
        batch_op.drop_index(batch_op.f('ix_companion_requests_source'))
        batch_op.drop_index(batch_op.f('ix_companion_requests_role'))
        batch_op.drop_index(batch_op.f('ix_companion_requests_origin_metro'))
        batch_op.drop_index(batch_op.f('ix_companion_requests_origin_iata'))
        batch_op.drop_index(batch_op.f('ix_companion_requests_dest_metro'))
        batch_op.drop_index(batch_op.f('ix_companion_requests_dest_iata'))
        batch_op.alter_column('user_id', existing_type=sa.INTEGER(), nullable=False)
        batch_op.drop_column('cs_notes')
        batch_op.drop_column('claimed_at')
        batch_op.drop_column('closed_by_id')
        batch_op.drop_column('closed_at')
        batch_op.drop_column('closed_reason')
        batch_op.drop_column('status')
        batch_op.drop_column('pref_age_max')
        batch_op.drop_column('pref_age_min')
        batch_op.drop_column('pref_gender')
        batch_op.drop_column('traveler_gender')
        batch_op.drop_column('traveler_age_group')
        batch_op.drop_column('role')
        batch_op.drop_column('traveler_name')
        batch_op.drop_column('poster_name')
        batch_op.drop_column('created_by_id')
        batch_op.drop_column('import_key')
        batch_op.drop_column('source_url')
        batch_op.drop_column('source')
        batch_op.drop_column('ticket_attachment')
        batch_op.drop_column('dest_metro')
        batch_op.drop_column('dest_city')
        batch_op.drop_column('dest_iata')
        batch_op.drop_column('origin_metro')
        batch_op.drop_column('origin_city')
        batch_op.drop_column('origin_iata')

    op.create_table('messages',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('sender_id', sa.INTEGER(), nullable=False),
    sa.Column('recipient_id', sa.INTEGER(), nullable=False),
    sa.Column('trip_id', sa.INTEGER(), nullable=True),
    sa.Column('subject', sa.VARCHAR(length=255), nullable=True),
    sa.Column('body', sa.TEXT(), nullable=False),
    sa.Column('is_read', sa.BOOLEAN(), nullable=True),
    sa.Column('masked_relay', sa.BOOLEAN(), nullable=True),
    sa.Column('created_at', sa.DATETIME(), nullable=True),
    sa.ForeignKeyConstraint(['recipient_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['sender_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['trip_id'], ['companion_requests.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('contact_points', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_contact_points_user_id'))
        batch_op.drop_index(batch_op.f('ix_contact_points_trip_id'))
    op.drop_table('contact_points')

    with op.batch_alter_table('claim_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_claim_tokens_token'))
    op.drop_table('claim_tokens')

    with op.batch_alter_table('activity_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_activity_events_trip_id'))
        batch_op.drop_index(batch_op.f('ix_activity_events_match_id'))
        batch_op.drop_index(batch_op.f('ix_activity_events_event'))
        batch_op.drop_index(batch_op.f('ix_activity_events_created_at'))
    op.drop_table('activity_events')
