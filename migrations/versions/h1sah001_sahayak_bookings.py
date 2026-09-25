"""sahayak bookings: requests for a home healthcare visit

A request, not a dispatch: staff assign somebody by hand in the CS console, so there are no
Sahayak accounts here yet and the assignee is recorded by name.

Revision ID: h1sah001
Revises: g1ins005
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa

revision = 'h1sah001'
down_revision = 'g1ins005'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'sahayak_bookings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('service_key', sa.String(length=40), nullable=False),
        sa.Column('service_name', sa.String(length=80), nullable=False),
        sa.Column('quoted_price', sa.String(length=12), nullable=True),
        sa.Column('patient_name', sa.String(length=120), nullable=False),
        sa.Column('patient_age', sa.Integer(), nullable=True),
        sa.Column('contact_name', sa.String(length=120), nullable=True),
        sa.Column('phone', sa.String(length=30), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('address', sa.Text(), nullable=False),
        sa.Column('landmark', sa.String(length=200), nullable=True),
        sa.Column('pincode', sa.String(length=12), nullable=True),
        sa.Column('access_notes', sa.String(length=300), nullable=True),
        sa.Column('when_type', sa.String(length=12), nullable=False, server_default='asap'),
        sa.Column('scheduled_for', sa.DateTime(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=15), nullable=False, server_default='new'),
        sa.Column('assigned_to_name', sa.String(length=120), nullable=True),
        sa.Column('assigned_by_id', sa.Integer(), nullable=True),
        sa.Column('assigned_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_reason', sa.String(length=200), nullable=True),
        sa.Column('cs_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['assigned_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_sahayak_bookings_user_id', 'sahayak_bookings', ['user_id'])
    op.create_index('ix_sahayak_bookings_service_key', 'sahayak_bookings', ['service_key'])
    op.create_index('ix_sahayak_bookings_email', 'sahayak_bookings', ['email'])
    op.create_index('ix_sahayak_bookings_pincode', 'sahayak_bookings', ['pincode'])
    op.create_index('ix_sahayak_bookings_status', 'sahayak_bookings', ['status'])
    op.create_index('ix_sahayak_bookings_created_at', 'sahayak_bookings', ['created_at'])


def downgrade():
    op.drop_table('sahayak_bookings')
