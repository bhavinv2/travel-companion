"""Sharing with one's team, and only with them (2026-10-27).

A saved view (crm_views: Leads, Contacts and every other staff page) and a trip list's saved filter (saved_filters)
are shared with ONE team: a team of the current workspace (Set-up › People › Teams) that the owner is in. Who sees a
shared one: its owner, and the people in that team -- while the owner still is. Somebody who moves to another team
stops seeing the old team's views, and theirs stop showing there; nothing is deleted, and joining again brings them
back. Seeing a view is never more than a link to a screen with some filters: the screen still shows each person
only what their role lets them see.

    teams(user)                the teams of the current workspace this person is in, by name: "Who sees it" offers these
    pick(user, value)          the team a form chose, or None ('' / 'me' / anything not one of theirs)
    team_ids(user)             every team this person is in, any workspace
    shared_with(user, rows)    of rows not theirs (owner_id, team_id), the ones shared with them
    sees(user, row)            their own, or shared with them
"""
from sqlalchemy import select

from app import db
from app.models import WorkspaceTeam, workspace_team_members
from app.services import access

NOBODY = 'me'


def teams(user):
    if not access._authed(user):
        return []
    c = access._cache()
    key = ('share_teams', user.id)
    if key not in c:
        ws = access.current_workspace(user)
        c[key] = [] if ws is None else (
            WorkspaceTeam.query.join(workspace_team_members, workspace_team_members.c.team_id == WorkspaceTeam.id)
            .filter(WorkspaceTeam.workspace_id == ws.id, workspace_team_members.c.user_id == user.id)
            .order_by(WorkspaceTeam.name).all())
    return c[key]


def pick(user, value):
    value = str(value or '').strip()
    if not value.isdigit():
        return None
    return next((t for t in teams(user) if t.id == int(value)), None)


def team_ids(user):
    if not access._authed(user):
        return set()
    c = access._cache()
    key = ('share_team_ids', user.id)
    if key not in c:
        c[key] = set(db.session.execute(select(workspace_team_members.c.team_id)
                                        .where(workspace_team_members.c.user_id == user.id)).scalars())
    return c[key]


def _members(ids):
    out = {i: set() for i in ids}
    if ids:
        for t, u in db.session.execute(select(workspace_team_members.c.team_id, workspace_team_members.c.user_id)
                                       .where(workspace_team_members.c.team_id.in_(ids))):
            out[t].add(u)
    return out


def shared_with(user, rows):
    mine = team_ids(user)
    maybe = [r for r in rows if r.owner_id != user.id and r.team_id in mine]
    members = _members({r.team_id for r in maybe})
    return [r for r in maybe if r.owner_id in members.get(r.team_id, ())]


def sees(user, row):
    return row is not None and (row.owner_id == user.id or bool(shared_with(user, [row])))


def team_name(row):
    """The name of the team a row is shared with, or None."""
    return row.team.name if row is not None and row.team_id and row.team is not None else None
