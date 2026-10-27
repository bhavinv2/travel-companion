"""Favourites, saved views of any staff page shared with one's team only, and the tour guide

staff_favourites     a person's own shortcuts: a staff page with its filters (endpoint, its path words `args`, the
                     query string `params`), or one of the saved views they can open (view_id); in their order
crm_views            the saved views of Leads and Contacts become the saved views of every staff page: `endpoint` and
                     `args` say which page for a view not of Leads or Contacts; `team_id` the ONE team it is shared
                     with (sharing is with the owner's team only; `shared` stays true while it is)
saved_filters        the trip lists' saved filters are shared the same way: `team_id`
users.tour_state     the tour guide: {'ask': 'never' once somebody said "Don't ask again", 'asked_at': when the
                     question was last shown, 'done': [tour keys finished]}

Views and filters that were shared with everybody before this revision go to the owner's first team (by id) in the
same workspace; one whose owner is in no team becomes the owner's own again.

Revision ID: z1fav031
Revises: y1side030
Create Date: 2026-10-27
"""
from alembic import op
import sqlalchemy as sa

revision = 'z1fav031'
down_revision = 'y1side030'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users') as b:
        b.add_column(sa.Column('tour_state', sa.JSON(), nullable=True))
    with op.batch_alter_table('crm_views') as b:
        b.add_column(sa.Column('endpoint', sa.String(length=80), nullable=True))
        b.add_column(sa.Column('args', sa.JSON(), nullable=True))
        b.add_column(sa.Column('team_id', sa.Integer(), nullable=True))
        b.create_foreign_key('fk_crm_views_team', 'workspace_teams', ['team_id'], ['id'], ondelete='SET NULL')
        b.create_index('ix_crm_views_team_id', ['team_id'])
    with op.batch_alter_table('saved_filters') as b:
        b.add_column(sa.Column('team_id', sa.Integer(), nullable=True))
        b.create_foreign_key('fk_saved_filters_team', 'workspace_teams', ['team_id'], ['id'], ondelete='SET NULL')
        b.create_index('ix_saved_filters_team_id', ['team_id'])
    op.create_table(
        'staff_favourites',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('key', sa.String(length=40), nullable=False),
        sa.Column('label', sa.String(length=80), nullable=True),
        sa.Column('endpoint', sa.String(length=80), nullable=False),
        sa.Column('args', sa.JSON(), nullable=True),
        sa.Column('params', sa.JSON(), nullable=True),
        sa.Column('view_id', sa.Integer(), sa.ForeignKey('crm_views.id', ondelete='CASCADE'), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('user_id', 'key', name='uq_staff_favourite_key'),
    )
    op.create_index('ix_staff_favourites_user_id', 'staff_favourites', ['user_id'])

    # what was shared with everybody: the owner's first team in that workspace, else the owner's own again
    bind = op.get_bind()
    first_ws = bind.execute(sa.text('SELECT MIN(id) FROM workspaces')).scalar()
    team_of = sa.text('SELECT MIN(t.id) FROM workspace_teams t JOIN workspace_team_members m ON m.team_id = t.id '
                      'WHERE m.user_id = :u AND t.workspace_id = :w')
    any_team = sa.text('SELECT MIN(t.id) FROM workspace_teams t JOIN workspace_team_members m ON m.team_id = t.id '
                       'WHERE m.user_id = :u')
    for vid, owner, ws in bind.execute(sa.text('SELECT id, owner_id, workspace_id FROM crm_views WHERE shared = :t'),
                                       {'t': True}).fetchall():
        team = bind.execute(team_of, {'u': owner, 'w': ws or first_ws}).scalar()
        bind.execute(sa.text('UPDATE crm_views SET team_id = :team, shared = :s WHERE id = :id'),
                     {'team': team, 's': team is not None, 'id': vid})
    for fid, owner in bind.execute(sa.text('SELECT id, owner_id FROM saved_filters WHERE shared = :t'),
                                   {'t': True}).fetchall():
        team = bind.execute(any_team, {'u': owner}).scalar()
        bind.execute(sa.text('UPDATE saved_filters SET team_id = :team, shared = :s WHERE id = :id'),
                     {'team': team, 's': team is not None, 'id': fid})


def downgrade():
    op.drop_index('ix_staff_favourites_user_id', table_name='staff_favourites')
    op.drop_table('staff_favourites')
    with op.batch_alter_table('saved_filters') as b:
        b.drop_index('ix_saved_filters_team_id')
        b.drop_constraint('fk_saved_filters_team', type_='foreignkey')
        b.drop_column('team_id')
    with op.batch_alter_table('crm_views') as b:
        b.drop_index('ix_crm_views_team_id')
        b.drop_constraint('fk_crm_views_team', type_='foreignkey')
        b.drop_column('team_id')
        b.drop_column('args')
        b.drop_column('endpoint')
    with op.batch_alter_table('users') as b:
        b.drop_column('tour_state')
