"""match reports table (user-reported problems with a match)

Revision ID: e1rep001
Revises: d1trav01
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa

revision = 'e1rep001'
down_revision = 'd1trav01'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'match_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('match_id', sa.Integer(), nullable=True),
        sa.Column('party_id', sa.Integer(), nullable=True),
        sa.Column('trip_id', sa.Integer(), nullable=True),
        sa.Column('reporter_id', sa.Integer(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('cs_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('resolved_by_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['match_id'], ['matches.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['party_id'], ['match_parties.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['trip_id'], ['companion_requests.id']),
        sa.ForeignKeyConstraint(['reporter_id'], ['users.id']),
        sa.ForeignKeyConstraint(['resolved_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_match_reports_match_id', 'match_reports', ['match_id'])
    op.create_index('ix_match_reports_status', 'match_reports', ['status'])
    op.create_index('ix_match_reports_created_at', 'match_reports', ['created_at'])


def downgrade():
    op.drop_index('ix_match_reports_created_at', table_name='match_reports')
    op.drop_index('ix_match_reports_status', table_name='match_reports')
    op.drop_index('ix_match_reports_match_id', table_name='match_reports')
    op.drop_table('match_reports')
