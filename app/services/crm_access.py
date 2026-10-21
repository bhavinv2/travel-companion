"""Who sees which leads in the Sales CRM (Sales CRM 2.0, run 3b).

A role says it with `crm_scope`:  NULL / 'all' = everyone's leads (what every role did before),
'team' = leads of anyone in my teams (me included), 'own' = leads I look after. Leads nobody looks
after yet are seen by everyone: somebody has to pick them up. Admins, Super admins and the
workspace owner always see everything; so does a person who belongs to no workspace (the old
setup). A person with several roles gets the most generous one; somebody "Working as" one of
their roles gets just that role's.

    lead_filter(user)      SQL criterion on CrmLead, or None = no limit
    person_filter(user)    the same for CrmPerson (a person is seen if any of their leads is, or
                           they have none)
    can_see_lead / can_see_person

Reading a page is limited by ONE mechanism: a `do_orm_execute` listener adds lead_filter to every
SELECT of CrmLead that a signed-in person's GET request makes (board, list, lead page, contact
page, My day, Calendar, Results, Forecast, exports, find, flow, the WhatsApp lead panel ...), the
way crm_bin hides removed leads. A statement can opt out with execution option `include_hidden=True`
(the duplicate check on Add a lead must see everybody's). What people DO (POST) is not filtered
this way -- a side effect like "tell the WhatsApp CRM their tags" must see every lead of the
person -- but the lead lookup of every action goes through can_see_lead (routes/crm._lead_or_404).
"""
import threading

from flask import g, has_request_context, request
from sqlalchemy import Select, event, exists, or_
from sqlalchemy.orm import with_loader_criteria

from app import db
from app.models import (CrmLead, CrmPayment, CrmPerson, CrmQuote, CrmStageChange, CrmTask, CrmTouchpoint, WorkspaceTeam,
                        workspace_team_members)

SCOPES = ('all', 'team', 'own')
SCOPE_LABELS = (('all', "Everyone's"), ('team', "Their team's"), ('own', 'Only their own'))
_RANK = {'all': 2, 'team': 1, 'own': 0}
OTHER_PERSON = 'Someone else looks after this person.'


def _authed(user):
    return bool(user is not None and getattr(user, 'is_authenticated', False))


def _cache():
    from app.services import access
    return access._cache()


def scope_of(user):
    """'all' | 'team' | 'own' for this person (see the module note)."""
    if not _authed(user):
        return 'all'
    if user.is_admin:
        return 'all'
    from app.services import access
    if access.is_super(user):
        return 'all'
    c = _cache()
    key = ('crm_scope', user.id)
    if key in c:
        return c[key]
    scope = _scope_uncached(user, access)
    c[key] = scope
    return scope


def _scope_uncached(user, access):
    act = access.acting_role(user)
    if act is not None:
        return _role_scope(act)
    ws = access.current_workspace(user)
    mems = access.memberships(user)
    if ws is None or not mems:
        return 'all'
    m = next((m for m in mems if m.workspace_id == ws.id), None)
    if m is None or m.is_owner:
        return 'all'
    roles = [m.role] if m.role is not None else []
    roles += [t.role for t in access._teams(m) if t.role is not None]
    if not roles:
        return 'all'
    return max((_role_scope(r) for r in roles), key=_RANK.get)


def _role_scope(role):
    if role is None or role.system_key == 'admin':
        return 'all'
    return role.crm_scope if role.crm_scope in SCOPES else 'all'


def team_user_ids(user):
    """Everyone in my teams (workspace teams I am in), me included."""
    c = _cache()
    key = ('crm_team_ids', user.id)
    if key not in c:
        from app.services import access
        ids = {user.id}
        ws = access.current_workspace(user)
        if ws is not None:
            mine = [t.id for t in WorkspaceTeam.query.join(
                workspace_team_members, workspace_team_members.c.team_id == WorkspaceTeam.id)
                .filter(WorkspaceTeam.workspace_id == ws.id, workspace_team_members.c.user_id == user.id)]
            if mine:
                rows = db.session.execute(db.select(workspace_team_members.c.user_id)
                                          .where(workspace_team_members.c.team_id.in_(mine))).all()
                ids |= {r[0] for r in rows}
        c[key] = ids
    return c[key]


def visible_owner_ids(user):
    """None = every owner; otherwise the user ids whose leads this person sees (plus unassigned)."""
    scope = scope_of(user)
    if scope == 'all':
        return None
    return {user.id} if scope == 'own' else set(team_user_ids(user))


def lead_filter(user):
    """A criterion on CrmLead for the leads this person may see, or None for all of them."""
    ids = visible_owner_ids(user)
    if ids is None:
        return None
    return or_(CrmLead.owner_id.in_(sorted(ids)), CrmLead.owner_id.is_(None))


def person_filter(user):
    """A criterion on CrmPerson, or None for everybody. Written on the table, not the model, so the
    sweep of removed leads and this listener leave the sub-select alone (it asks for itself)."""
    ids = visible_owner_ids(user)
    if ids is None:
        return None
    L = CrmLead.__table__.alias()
    mine = or_(L.c.owner_id.in_(sorted(ids)), L.c.owner_id.is_(None))
    has_any = exists().where(L.c.person_id == CrmPerson.id, L.c.deleted_at.is_(None)).correlate(CrmPerson)
    has_mine = exists().where(L.c.person_id == CrmPerson.id, L.c.deleted_at.is_(None), mine).correlate(CrmPerson)
    return or_(~has_any, has_mine)


def can_see_lead(user, lead):
    ids = visible_owner_ids(user)
    if ids is None or lead is None:
        return True
    return lead.owner_id is None or lead.owner_id in ids


def can_see_person(user, person):
    ids = visible_owner_ids(user)
    if ids is None or person is None or person.id is None:
        return True
    L = CrmLead.__table__
    rows = db.session.execute(db.select(L.c.owner_id).where(
        L.c.person_id == person.id, L.c.deleted_at.is_(None))).all()
    if not rows:
        return True
    return any(o is None or o in ids for (o,) in rows)


def someone_else_has(user, person):
    """True when the person has leads and none of them is seen by `user` (for the duplicate prompt)."""
    return not can_see_person(user, person)


def limit_users(user, users):
    """The staff a scoped person may pick from (owner filters, scope selectors): me and, with 'team', my
    team. Everybody for 'all'."""
    ids = visible_owner_ids(user)
    if ids is None:
        return list(users)
    return [u for u in users if u.id in ids]


# ----------------------------------------------------------------------------- the one mechanism

_registered = []


_busy = threading.local()


def _lead_is_hidden(cls, ids):
    L = CrmLead.__table__.alias()
    return ~exists().where(L.c.id == cls.lead_id, L.c.owner_id.isnot(None), L.c.owner_id.notin_(ids)).correlate(cls)


def _on_execute(state):
    if not state.is_select or state.is_column_load or state.execution_options.get('include_hidden'):
        return
    if getattr(_busy, 'on', False) or not isinstance(state.statement, Select):
        return
    if not has_request_context() or request.method not in ('GET', 'HEAD'):
        return
    user = g.get('_login_user')            # never start the sign-in lookup from in here
    if not _authed(user):
        return
    _busy.on = True
    try:
        crit = lead_filter(user)
    finally:
        _busy.on = False
    if crit is None:
        return
    # the criteria only act where CrmLead is really selected from (also inside sub-selects and count());
    # what hangs on a lead they may not see (tasks, touches, stage moves) goes with it
    ids = sorted(visible_owner_ids(user))
    opts = [with_loader_criteria(CrmLead, crit, include_aliases=True)]
    opts += [with_loader_criteria(child, _lead_is_hidden(child, ids), include_aliases=True)
             for child in (CrmTask, CrmTouchpoint, CrmStageChange, CrmQuote, CrmPayment)]
    state.statement = state.statement.options(*opts)


def register():
    if not _registered:
        event.listen(db.session, 'do_orm_execute', _on_execute)
        _registered.append(1)
