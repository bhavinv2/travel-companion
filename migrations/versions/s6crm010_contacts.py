"""Sales CRM: contacts -- the do-not-contact list kept after "Erase this person"

crm_do_not_contact   somebody erased at their request: a salted sha256 of their E.164 phone and of
                     their lower-case e-mail (never the number or address), why, when and who.
                     Imports skip a match; an enquiry they make themselves clears it.

Revision ID: s6crm010
Revises: s5crm009
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa

revision = 's6crm010'
down_revision = 's5crm009'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'crm_do_not_contact',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('phone_hash', sa.String(64), nullable=True),
        sa.Column('email_hash', sa.String(64), nullable=True),
        sa.Column('reason', sa.String(40), nullable=False, server_default='erased'),
        sa.Column('at', sa.DateTime(), nullable=False),
        sa.Column('by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True))
    op.create_index('ix_crm_do_not_contact_phone_hash', 'crm_do_not_contact', ['phone_hash'])
    op.create_index('ix_crm_do_not_contact_email_hash', 'crm_do_not_contact', ['email_hash'])


def downgrade():
    op.drop_index('ix_crm_do_not_contact_email_hash', table_name='crm_do_not_contact')
    op.drop_index('ix_crm_do_not_contact_phone_hash', table_name='crm_do_not_contact')
    op.drop_table('crm_do_not_contact')
