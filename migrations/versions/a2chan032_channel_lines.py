"""WhatsApp numbers the portal talks to itself, through Meta's Cloud API (Set-up > Channels)

crm_channel_lines        one WhatsApp number per row, beside the WhatsApp CRM's own: Meta's ids for it (phone number id,
                         WhatsApp Business Account id), its token and app secret sealed (services/secretbox), the verify
                         token Meta's address check echoes, the lead source its newcomers come in under, the number
                         prefixes it writes first to, its state, and the templates Meta last listed for its account
crm_touchpoints.line_id  the number a WhatsApp message went through; NULL = the WhatsApp CRM's
crm_people.wa_line_id    the number this person last wrote to (NULL = the WhatsApp CRM's, or never)

Revision ID: a2chan032
Revises: z1fav031
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa

revision = 'a2chan032'
down_revision = 'z1fav031'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'crm_channel_lines',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('workspace_id', sa.Integer(), sa.ForeignKey('workspaces.id', ondelete='SET NULL'), nullable=True),
        sa.Column('key', sa.String(length=30), nullable=False),
        sa.Column('label', sa.String(length=60), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False, server_default='meta'),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('phone_number_id', sa.String(length=40), nullable=False),
        sa.Column('waba_id', sa.String(length=40), nullable=True),
        sa.Column('secrets', sa.Text(), nullable=True),
        sa.Column('verify_token', sa.String(length=64), nullable=False),
        sa.Column('source_key', sa.String(length=60), nullable=True),
        sa.Column('prefixes', sa.JSON(), nullable=True),
        sa.Column('also_on', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=12), nullable=False, server_default='new'),
        sa.Column('last_error', sa.String(length=300), nullable=True),
        sa.Column('connected_at', sa.DateTime(), nullable=True),
        sa.Column('last_in_at', sa.DateTime(), nullable=True),
        sa.Column('last_out_at', sa.DateTime(), nullable=True),
        sa.Column('templates', sa.JSON(), nullable=True),
        sa.Column('templates_at', sa.DateTime(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('key', name='uq_crm_channel_lines_key'),
        sa.UniqueConstraint('phone_number_id', name='uq_crm_channel_lines_pnid'),
    )
    op.create_index('ix_crm_channel_lines_workspace_id', 'crm_channel_lines', ['workspace_id'])
    with op.batch_alter_table('crm_touchpoints') as b:
        b.add_column(sa.Column('line_id', sa.Integer(), nullable=True))
        b.create_foreign_key('fk_crm_touchpoints_line', 'crm_channel_lines', ['line_id'], ['id'], ondelete='SET NULL')
        b.create_index('ix_crm_touchpoints_line_id', ['line_id'])
    with op.batch_alter_table('crm_people') as b:
        b.add_column(sa.Column('wa_line_id', sa.Integer(), nullable=True))
        b.create_foreign_key('fk_crm_people_wa_line', 'crm_channel_lines', ['wa_line_id'], ['id'], ondelete='SET NULL')


def downgrade():
    with op.batch_alter_table('crm_people') as b:
        b.drop_constraint('fk_crm_people_wa_line', type_='foreignkey')
        b.drop_column('wa_line_id')
    with op.batch_alter_table('crm_touchpoints') as b:
        b.drop_index('ix_crm_touchpoints_line_id')
        b.drop_constraint('fk_crm_touchpoints_line', type_='foreignkey')
        b.drop_column('line_id')
    op.drop_index('ix_crm_channel_lines_workspace_id', table_name='crm_channel_lines')
    op.drop_table('crm_channel_lines')
