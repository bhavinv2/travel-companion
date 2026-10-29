"""Canada quotes: our own quotes page for super visa and visitors to Canada cover

insurance_quotes.token   the unguessable part of the quotes page's address (/travel-insurance/canada/quotes/<token>)
insurance_quotes.extra   what the Canada flow needs beside the trip: the cover chosen, the days, the options the
                         customer picked with the price they were shown, and their call-back request

Revision ID: d1can035
Revises: c1chat034
Create Date: 2026-10-30
"""
from alembic import op
import sqlalchemy as sa

revision = 'd1can035'
down_revision = 'c1chat034'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('insurance_quotes', sa.Column('token', sa.String(length=32), nullable=True))
    op.add_column('insurance_quotes', sa.Column('extra', sa.JSON(), nullable=True))
    op.create_index('ix_insurance_quotes_token', 'insurance_quotes', ['token'], unique=True)


def downgrade():
    op.drop_index('ix_insurance_quotes_token', table_name='insurance_quotes')
    op.drop_column('insurance_quotes', 'extra')
    op.drop_column('insurance_quotes', 'token')
