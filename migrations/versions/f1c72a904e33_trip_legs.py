"""Per-leg matching: trip_legs table, and matches keyed by leg pair.

Every post is flattened into one row per flown segment so a round trip's return and each
hop of a multi-destination itinerary can be matched on their own. The existing matches are
left in place with null leg ids; app.cli's `backfill-legs` command rebuilds the legs and
recomputes them.

Revision ID: f1c72a904e33
Revises: e8b06d796c5f
"""
from alembic import op
import sqlalchemy as sa


revision = 'f1c72a904e33'
down_revision = 'e8b06d796c5f'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'trip_legs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trip_id', sa.Integer(), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('kind', sa.String(length=12), nullable=True),
        sa.Column('origin_text', sa.String(length=200), nullable=True),
        sa.Column('origin_iata', sa.String(length=5), nullable=True),
        sa.Column('origin_city', sa.String(length=120), nullable=True),
        sa.Column('origin_metro', sa.String(length=60), nullable=True),
        sa.Column('dest_text', sa.String(length=200), nullable=True),
        sa.Column('dest_iata', sa.String(length=5), nullable=True),
        sa.Column('dest_city', sa.String(length=120), nullable=True),
        sa.Column('dest_metro', sa.String(length=60), nullable=True),
        sa.Column('depart_date', sa.Date(), nullable=True),
        sa.Column('date_flexible', sa.Boolean(), nullable=True),
        sa.Column('airline', sa.String(length=200), nullable=True),
        sa.Column('flight_number', sa.String(length=30), nullable=True),
        sa.ForeignKeyConstraint(['trip_id'], ['companion_requests.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('trip_id', 'seq', name='uq_trip_legs_seq'),
    )
    with op.batch_alter_table('trip_legs') as b:
        b.create_index('ix_trip_legs_trip_id', ['trip_id'])
        b.create_index('ix_trip_legs_origin_iata', ['origin_iata'])
        b.create_index('ix_trip_legs_origin_metro', ['origin_metro'])
        b.create_index('ix_trip_legs_dest_iata', ['dest_iata'])
        b.create_index('ix_trip_legs_dest_metro', ['dest_metro'])
        b.create_index('ix_trip_legs_depart_date', ['depart_date'])
        b.create_index('ix_trip_legs_route', ['origin_metro', 'dest_metro', 'depart_date'])

    # A pair of posts may now match on more than one leg, so the pair alone is no longer
    # unique -- the leg ids are part of the key.
    with op.batch_alter_table('matches') as b:
        b.add_column(sa.Column('leg_a_id', sa.Integer(), nullable=True))
        b.add_column(sa.Column('leg_b_id', sa.Integer(), nullable=True))
        b.drop_constraint('uq_matches_pair', type_='unique')
        b.create_unique_constraint('uq_matches_pair',
                                   ['trip_a_id', 'trip_b_id', 'leg_a_id', 'leg_b_id'])
        b.create_foreign_key('fk_matches_leg_a', 'trip_legs', ['leg_a_id'], ['id'],
                             ondelete='CASCADE')
        b.create_foreign_key('fk_matches_leg_b', 'trip_legs', ['leg_b_id'], ['id'],
                             ondelete='CASCADE')
        b.create_index('ix_matches_leg_a_id', ['leg_a_id'])
        b.create_index('ix_matches_leg_b_id', ['leg_b_id'])


def downgrade():
    with op.batch_alter_table('matches') as b:
        b.drop_index('ix_matches_leg_b_id')
        b.drop_index('ix_matches_leg_a_id')
        b.drop_constraint('fk_matches_leg_b', type_='foreignkey')
        b.drop_constraint('fk_matches_leg_a', type_='foreignkey')
        b.drop_constraint('uq_matches_pair', type_='unique')
        b.create_unique_constraint('uq_matches_pair', ['trip_a_id', 'trip_b_id'])
        b.drop_column('leg_b_id')
        b.drop_column('leg_a_id')
    op.drop_table('trip_legs')
