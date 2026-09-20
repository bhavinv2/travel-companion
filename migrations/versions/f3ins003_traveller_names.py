"""per-traveller name + age on insurance quotes (replaces the comma-separated ages)

Revision ID: f3ins003
Revises: f2ins002
Create Date: 2026-09-20
"""
from alembic import op
import sqlalchemy as sa

revision = 'f3ins003'
down_revision = 'f2ins002'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('insurance_quotes', sa.Column('travellers', sa.JSON(), nullable=True))
    # Existing rows only ever captured ages, so carry those over with an empty name each.
    op.execute("""
        UPDATE insurance_quotes SET travellers = COALESCE((
            SELECT json_agg(json_build_object('name', '', 'age', trim(part)))
            FROM unnest(string_to_array(ages, ',')) AS part
            WHERE trim(part) <> ''
        ), '[]'::json)
    """)
    op.alter_column('insurance_quotes', 'travellers', nullable=False)
    op.drop_column('insurance_quotes', 'ages')


def downgrade():
    op.add_column('insurance_quotes', sa.Column('ages', sa.String(length=80), nullable=True))
    op.execute("""
        UPDATE insurance_quotes SET ages = COALESCE((
            SELECT string_agg(elem->>'age', ',')
            FROM json_array_elements(travellers::json) AS elem
        ), '')
    """)
    op.alter_column('insurance_quotes', 'ages', nullable=False)
    op.drop_column('insurance_quotes', 'travellers')
