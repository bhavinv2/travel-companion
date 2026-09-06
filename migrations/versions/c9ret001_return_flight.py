"""round-trip return airline/flight number

Revision ID: c9ret001
Revises: b7feat001
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa

revision = 'c9ret001'
down_revision = 'b7feat001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('companion_requests') as batch:
        batch.add_column(sa.Column('return_airline', sa.String(length=200), nullable=True))
        batch.add_column(sa.Column('return_flight_number', sa.String(length=30), nullable=True))


def downgrade():
    with op.batch_alter_table('companion_requests') as batch:
        batch.drop_column('return_flight_number')
        batch.drop_column('return_airline')
