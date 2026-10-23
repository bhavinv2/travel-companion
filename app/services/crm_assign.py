"""Who a new lead goes to (Sales CRM 2.0, run 3b).

A source shares its new leads one of three ways (CrmSource.assign_mode):
  NULL            nobody: the lead waits, not given to anyone, until somebody takes it or is given it. The
                  default since 2026-10-23 (it used to mean 'fewest')
  'fewest'        whoever holds the fewest open leads
  'round_robin'   in turn: the next person after the one who got the last lead (CrmSource.rr_last_user_id)
People can be away (WorkspaceMember.away_until): they get no new leads in either sharing mode. When everybody
who could take it is away, the normal rule runs over all of them and the lead says so.
"""
from datetime import datetime, timedelta

from sqlalchemy import func

from app import db
from app.models import CrmLead, WorkspaceMember

MODES = (('none', 'Nobody: it waits, not given to anyone, until someone takes it'),
         ('fewest', 'Whoever has the fewest open leads'), ('round_robin', 'In turn (round robin)'))
ALL_AWAY = 'Everyone who could take this lead was away, so it went to %s as usual.'
IST = timedelta(hours=5, minutes=30)


DEFAULT = 'none'           # a source with nothing set gives its new leads to nobody


def mode_of(src):
    mode = src.assign_mode if src is not None else None
    return mode if mode in ('fewest', 'round_robin') else DEFAULT


def away_ids(user_ids, now=None):
    """The ids among `user_ids` who are away just now (in any workspace)."""
    ids = [i for i in user_ids if i]
    if not ids:
        return set()
    now = now or datetime.utcnow()
    rows = (db.session.query(WorkspaceMember.user_id)
            .filter(WorkspaceMember.user_id.in_(ids), WorkspaceMember.away_until.isnot(None),
                    WorkspaceMember.away_until > now).all())
    return {r[0] for r in rows}


def away_until(user, now=None):
    """When this person is back (UTC), or None when they are not away."""
    if user is None or not getattr(user, 'id', None):
        return None
    now = now or datetime.utcnow()
    rows = (db.session.query(func.max(WorkspaceMember.away_until))
            .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.away_until > now).scalar())
    return rows


def parse_until(text, today=None):
    """'2026-11-03' -> the moment they are back: that morning, India time, as UTC. None when it is not a day
    in the future."""
    try:
        day = datetime.strptime((text or '').strip(), '%Y-%m-%d')
    except ValueError:
        return None
    until = day - IST
    return until if until > (today or datetime.utcnow()) else None


def set_away(user, until=None):
    """Away until `until` (UTC datetime), or back now (None). Every workspace they are in. No commit.
    How many memberships changed."""
    rows = WorkspaceMember.query.filter_by(user_id=user.id).all()
    for m in rows:
        m.away_until = until
    return len(rows)


def choose(src, now=None, mode=None):
    """(user or None, note or None): the owner for a new lead from `src`, and what to say on the lead when
    the usual rule could not be followed. Remembers the round-robin turn (no commit). `mode` says it outright
    instead of the source (the Add lead form's "Whoever is least busy" is 'fewest' whatever the source does)."""
    mode = mode or mode_of(src)
    if mode == 'none':
        return None, None
    from app.services import crm
    users = crm._owner_candidates(src)
    if not users:
        return None, None
    now = now or datetime.utcnow()
    away = away_ids([u.id for u in users], now)
    here = [u for u in users if u.id not in away]
    note = None
    if not here:
        here = users
        note = 'all_away'
    owner = _round_robin(src, here) if mode == 'round_robin' else _fewest(here)
    if note:
        note = ALL_AWAY % (owner.full_name if owner is not None else 'nobody')
    return owner, note


def _fewest(users):
    ids = [u.id for u in users]
    loads = dict(db.session.query(CrmLead.owner_id, func.count(CrmLead.id))
                 .filter(CrmLead.owner_id.in_(ids), CrmLead.status == 'open')
                 .group_by(CrmLead.owner_id).all())
    return min(users, key=lambda u: (loads.get(u.id, 0), u.id))


def _round_robin(src, users):
    ordered = sorted(users, key=lambda u: u.id)
    last = src.rr_last_user_id or 0
    nxt = next((u for u in ordered if u.id > last), ordered[0])
    if src is not None and src.id is not None:
        src.rr_last_user_id = nxt.id
    return nxt


# ------------------------------------------------------------------------------------ automation rules (run 5b)

def source_turn(src, now=None):
    """A rule's "give it to the next person in turn" through a lead source: the source's people (its team, else
    sales), nobody who is away (unless everybody is), in turn after the source's last one. Remembers the turn on the
    source (no commit). None when nobody can take it."""
    from app.services import crm
    users = crm._owner_candidates(src)
    if not users:
        return None
    away = away_ids([u.id for u in users], now or datetime.utcnow())
    here = [u for u in users if u.id not in away] or users
    if src is None:
        return sorted(here, key=lambda u: u.id)[0]
    return _round_robin(src, here)


def team_turn(team, last_id=None, now=None):
    """The same through a workspace team: its active members who work in its workspace, nobody away (unless
    everybody is), the next one after `last_id`. None when the team has nobody."""
    from app.services import crm_scope
    users = [u for u in crm_scope.in_workspace(team.users, team.workspace_id) if u.is_active]
    if not users:
        return None
    away = away_ids([u.id for u in users], now or datetime.utcnow())
    here = sorted([u for u in users if u.id not in away] or users, key=lambda u: u.id)
    last = int(last_id or 0)
    return next((u for u in here if u.id > last), here[0])
