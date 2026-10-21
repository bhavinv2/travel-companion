"""CRM data per workspace (Sales CRM 2.0, run 5a): every workspace has its own leads, contacts, pipelines,
products, lead sources, ready answers, numbers and set-up.

Which rows belong where
    The top-level CRM tables carry `workspace_id` (SCOPED below). Child rows (stages, fields, follow-up steps,
    touches, tasks, stage moves, quotes, payments, files) follow their parent and have no column of their own.
    crm_identities keeps a copy of its person's workspace, only so the same Instagram handle can be a contact in
    two workspaces (its uniqueness is per workspace). A NULL workspace_id (rows from before this run on a site
    that had no workspace yet) means the DEFAULT workspace: the one with the lowest id (access.ensure_defaults).
    Global, not per workspace: exchange rates (crm_currency_rates), the do-not-contact list (an erasure is
    for the whole company) and the app settings `crm.*`.

ONE mechanism limits what is read (like crm_bin and crm_access): a `do_orm_execute` listener adds
`with_loader_criteria` for every scoped model -- and, through their parent, for the child models -- to every
SELECT and every ORM bulk UPDATE / DELETE. It is active
  * inside a request of a signed-in STAFF member, for every method (POST too: nobody acts on another
    workspace's record by its id): the workspace is access.current_workspace (the switcher; legacy staff
    without a workspace work in the default one);
  * inside `use(workspace_id)`: the jobs runner (once per workspace), a public capture (the SOURCE decides),
    the WhatsApp CRM webhook (the workspace linked to WhatsApp), seeding a new workspace.
A statement opts out with execution option `all_workspaces=True`; `use(None)` / `all_workspaces()` switches it
off for a block. While there is only ONE workspace (or none) nothing is added at all: there is nothing to
keep apart, and the site behaves exactly as before.

New rows get their workspace in a `before_flush` hook: a lead from its person (else its source / pipeline), an
identity from its person, a history row from its record, everything else from the current workspace (else the
default one). Code that knows better sets workspace_id itself.

Reading an object that is already in the session (session.get on the identity map) is not a SELECT, so the
lookups of the routes check `visible(obj)` as well (routes/crm._lead_or_404, the _person_or_404s ...).
"""
import logging
import threading
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar

from flask import g, has_request_context
from sqlalchemy import Delete, Select, Update, and_, event, exists, inspect, or_, select, true
from sqlalchemy.orm import object_session, with_loader_criteria

from app import db
from app.models import (CrmActivity, CrmAnswer, CrmAudit, CrmCampaign, CrmChannelCheck, CrmDailyStat, CrmField,
                        CrmFile, CrmHousehold, CrmIdentity, CrmLead, CrmPayment, CrmPerson, CrmPipeline,
                        CrmPlaybookStep, CrmProduct, CrmQuote, CrmRule, CrmSavedReport, CrmScoreRule, CrmSource,
                        CrmStage, CrmStageChange, CrmTarget, CrmTask, CrmTouchpoint, CrmView, Workspace,
                        request_cache)

log = logging.getLogger(__name__)

# the tables with a workspace_id column (crm_identities only for its uniqueness: it follows its person)
SCOPED = (CrmPipeline, CrmProduct, CrmSource, CrmHousehold, CrmPerson, CrmIdentity, CrmChannelCheck, CrmLead,
          CrmTarget, CrmDailyStat, CrmView, CrmSavedReport, CrmAudit, CrmAnswer, CrmActivity,
          # run 5b: automation rules, scoring lines and campaigns are per workspace from the start
          CrmRule, CrmScoreRule, CrmCampaign)
# the rows that follow a parent (no column): what they hang on
CHILDREN = {CrmTask: 'lead or person', CrmTouchpoint: 'person', CrmStageChange: 'lead', CrmQuote: 'lead',
            CrmPayment: 'lead', CrmFile: 'person', CrmStage: 'pipeline', CrmField: 'pipeline',
            CrmPlaybookStep: 'stage'}
GLOBAL = ('crm_currency_rates', 'crm_do_not_contact', 'app_settings crm.*')

_UNSET = object()
_forced = ContextVar('crm_workspace', default=_UNSET)
_busy = threading.local()
_registered = []


# ----------------------------------------------------------------------------------------- which workspace

def _authed(user):
    return bool(user is not None and getattr(user, 'is_authenticated', False))


def _quiet(fn):
    """Run a lookup of our own without this listener looking at its statements."""
    was = getattr(_busy, 'on', False)
    _busy.on = True
    try:
        return fn()
    finally:
        _busy.on = was


def _workspace_ids():
    """Every workspace id, oldest first (once per request)."""
    c = request_cache('crm_scope')
    if 'ids' not in c:
        c['ids'] = _quiet(lambda: [i for (i,) in db.session.execute(
            select(Workspace.__table__.c.id).order_by(Workspace.__table__.c.id)).all()])
    return c['ids']


def workspace_ids():
    return list(_workspace_ids())


def several():
    """True when there is more than one workspace: only then is anything kept apart."""
    return len(_workspace_ids()) > 1


def default_id():
    """The default workspace (lowest id), or None when there is none yet."""
    ids = _workspace_ids()
    return ids[0] if ids else None


def _request_id():
    """The workspace of this request's signed-in staff member, or None (nobody signed in, not staff, or only one
    workspace)."""
    if not has_request_context():
        return None
    user = g.get('_login_user')            # never start the sign-in lookup from in here
    if not _authed(user):
        return None
    from app.services import access
    c = access._cache()            # cleared when somebody switches workspace (access.set_current_workspace)
    key = ('crm_ws', user.id)
    if key not in c:
        c[key] = _quiet(lambda: _staff_workspace(user))
    return c[key]


def _staff_workspace(user):
    from app.services import access
    if not several() or not access.is_staff(user):
        return None
    ws = access.current_workspace(user)
    return ws.id if ws is not None else default_id()


def current_id():
    """The workspace whose CRM is being read or written just now, or None (every workspace: nothing is limited)."""
    f = _forced.get()
    if f is not _UNSET:
        return f[0]
    return _request_id()


def _current():
    """(workspace id, is it the default one) for the listener -- worked out once per use() block / request."""
    f = _forced.get()
    if f is not _UNSET:
        return f
    wid = _request_id()
    return (wid, is_default(wid)) if wid is not None else (None, False)


def active():
    """True when reads are limited to one workspace just now."""
    return current_id() is not None


def stamp_id():
    """The workspace a new row gets when nothing about it says otherwise: the current one, else the default."""
    wid = current_id()
    return wid if wid is not None else default_id()


def current_workspace():
    wid = stamp_id()
    return db.session.get(Workspace, wid) if wid is not None else None


@contextmanager
def use(workspace_id):
    """Read and write the CRM of one workspace inside this block (None: every workspace). Jobs, public captures,
    webhooks and seeding use it; it overrides the signed-in person's workspace. The request's cache of products is
    dropped on the way in and out (it belongs to one workspace)."""
    token = _forced.set((workspace_id, is_default(workspace_id) if workspace_id is not None else False))
    _forget_caches()
    try:
        yield workspace_id
    finally:
        _forced.reset(token)
        _forget_caches()


def all_workspaces():
    """Every workspace inside this block (super-admin tools, migrations, CLI clean-ups)."""
    return use(None)


def _forget_caches():
    request_cache('crm_products').clear()


def forget():
    """A workspace was made or linked in this request: ask again which there are."""
    request_cache('crm_scope').clear()


def is_default(workspace_id):
    return workspace_id is None or workspace_id == default_id()


def match(col, workspace_id):
    """SQL: the column `col` (a workspace_id) is this workspace -- NULL counts as the default one."""
    if workspace_id is None:
        return true()
    if is_default(workspace_id):
        return or_(col == workspace_id, col.is_(None))
    return col == workspace_id


def here(model, workspace_id=_UNSET):
    """SQL criterion: rows of `model` (a SCOPED model) in the current workspace -- or in `workspace_id`. Always
    true while nothing is limited. For the bulk writes that must stay in one workspace whoever runs them
    (forgetting saved days, renaming a product code)."""
    wid = current_id() if workspace_id is _UNSET else workspace_id
    if wid is None or (workspace_id is _UNSET and not several()):
        return true()
    return match(model.__table__.c.workspace_id, wid)


def of(obj):
    """The workspace id a CRM object belongs to (NULL read as the default one), or None when unknown."""
    if obj is None:
        return None
    wid = _own_ws(obj)
    if wid is _UNSET:
        return None
    return wid if wid is not None else default_id()


def _col(table, row_id):
    if row_id is None:
        return _UNSET
    row = _quiet(lambda: db.session.execute(select(table.c.workspace_id).where(table.c.id == row_id)).first())
    return row[0] if row is not None else _UNSET


def _own_ws(obj):
    """obj's workspace_id as stored (None = default), or _UNSET when it has no way to say."""
    if isinstance(obj, SCOPED):
        st = inspect(obj)
        if 'workspace_id' in st.dict or st.key is None:
            return obj.__dict__.get('workspace_id')
        return _col(type(obj).__table__, obj.id)
    if isinstance(obj, (CrmStageChange, CrmQuote, CrmPayment)):
        return _col(CrmLead.__table__, obj.lead_id)
    if isinstance(obj, CrmTask):
        if obj.lead_id is not None:
            return _col(CrmLead.__table__, obj.lead_id)
        return _col(CrmPerson.__table__, obj.person_id)
    if isinstance(obj, (CrmTouchpoint, CrmFile)):
        return _col(CrmPerson.__table__, obj.person_id)
    if isinstance(obj, (CrmStage, CrmField)):
        if obj.pipeline_id is None:
            return _UNSET
        return _col(CrmPipeline.__table__, obj.pipeline_id)
    if isinstance(obj, CrmPlaybookStep):
        st = db.session.get(CrmStage, obj.stage_id, execution_options={'all_workspaces': True})
        return _col(CrmPipeline.__table__, st.pipeline_id) if st is not None else _UNSET
    return _UNSET


def visible(obj, workspace_id=_UNSET):
    """True when `obj` belongs to the current workspace (or `workspace_id`), or nothing is limited. The lookups of
    the routes ask it as well as the SELECT filter: an object already in the session is not read again."""
    if obj is None:
        return False
    wid = current_id() if workspace_id is _UNSET else workspace_id
    if wid is None:
        return True
    own = _own_ws(obj)
    if own is _UNSET:
        return True
    if own is None:
        return is_default(wid)
    return own == wid


# ---------------------------------------------------------------------------------------- the one listener

def _ws_ok(col, wid, default):
    return or_(col == wid, col.is_(None)) if default else col == wid


def _top(model, wid, default):
    if default:
        return with_loader_criteria(model, lambda cls: or_(cls.workspace_id == wid, cls.workspace_id.is_(None)),
                                    include_aliases=True)
    return with_loader_criteria(model, lambda cls: cls.workspace_id == wid, include_aliases=True)


def _lead_ok(cls, col, wid, default):
    L = CrmLead.__table__.alias()
    return exists().where(L.c.id == col, _ws_ok(L.c.workspace_id, wid, default)).correlate(cls)


def _person_ok(cls, col, wid, default):
    P = CrmPerson.__table__.alias()
    return exists().where(P.c.id == col, _ws_ok(P.c.workspace_id, wid, default)).correlate(cls)


def _pipeline_ok(cls, col, wid, default):
    Pi = CrmPipeline.__table__.alias()
    return exists().where(Pi.c.id == col, _ws_ok(Pi.c.workspace_id, wid, default)).correlate(cls)


def _children(wid, default):
    """Criteria for the rows that follow a parent: written on table aliases, so the sweeps of the bin and of who
    sees which leads leave these sub-selects alone (they ask for themselves)."""
    S = CrmStage.__table__.alias()
    Pi = CrmPipeline.__table__.alias()
    step_ok = exists().where(S.c.id == CrmPlaybookStep.stage_id, Pi.c.id == S.c.pipeline_id,
                             _ws_ok(Pi.c.workspace_id, wid, default)).correlate(CrmPlaybookStep)
    crit = {
        CrmTask: or_(and_(CrmTask.lead_id.isnot(None), _lead_ok(CrmTask, CrmTask.lead_id, wid, default)),
                     and_(CrmTask.lead_id.is_(None), _person_ok(CrmTask, CrmTask.person_id, wid, default))),
        CrmTouchpoint: _person_ok(CrmTouchpoint, CrmTouchpoint.person_id, wid, default),
        CrmStageChange: _lead_ok(CrmStageChange, CrmStageChange.lead_id, wid, default),
        CrmQuote: _lead_ok(CrmQuote, CrmQuote.lead_id, wid, default),
        CrmPayment: _lead_ok(CrmPayment, CrmPayment.lead_id, wid, default),
        CrmFile: _person_ok(CrmFile, CrmFile.person_id, wid, default),
        CrmStage: _pipeline_ok(CrmStage, CrmStage.pipeline_id, wid, default),
        # a detail asked in every pipeline (no pipeline) is shared by every workspace
        CrmField: or_(CrmField.pipeline_id.is_(None), _pipeline_ok(CrmField, CrmField.pipeline_id, wid, default)),
        CrmPlaybookStep: step_ok,
    }
    return [with_loader_criteria(model, c, include_aliases=True) for model, c in crit.items()]


_OPTS = {}


def options(workspace_id, default=None):
    """The loader criteria for one workspace (built once per workspace and kind)."""
    if default is None:
        default = is_default(workspace_id)
    key = (workspace_id, default)
    if key not in _OPTS:
        _OPTS[key] = [_top(m, workspace_id, default) for m in SCOPED] + _children(workspace_id, default)
    return _OPTS[key]


def _on_execute(state):
    if state.is_column_load or state.execution_options.get('all_workspaces'):
        return
    if getattr(_busy, 'on', False):
        return
    stmt = state.statement
    if not isinstance(stmt, (Select, Update, Delete)):
        return
    if isinstance(stmt, Select) and not state.is_select:
        return
    wid, default = _quiet(_current)
    if wid is None:
        return
    state.statement = stmt.options(*options(wid, default))


# ---------------------------------------------------------------------------------------- new rows

_FIRST = (CrmPipeline, CrmSource, CrmProduct, CrmPerson, CrmHousehold)


def _parent_ws(sess, obj):
    """The workspace a new row takes from what it hangs on, or _UNSET."""
    if isinstance(obj, (CrmLead, CrmIdentity)):
        d = inspect(obj).dict
        person = d.get('person')
        if person is not None and person.workspace_id is not None:
            return person.workspace_id
        if obj.person_id is not None:
            got = _col(CrmPerson.__table__, obj.person_id)
            if got not in (_UNSET, None):
                return got
        if isinstance(obj, CrmLead):
            for rel, table, fk in (('source', CrmSource.__table__, 'source_id'),
                                   ('pipeline', CrmPipeline.__table__, 'pipeline_id')):
                parent = d.get(rel)
                if parent is not None and parent.workspace_id is not None:
                    return parent.workspace_id
                got = _col(table, getattr(obj, fk))
                if got not in (_UNSET, None):
                    return got
        return _UNSET
    if isinstance(obj, CrmAudit) and obj.record_type in ('lead', 'person'):
        table = CrmLead.__table__ if obj.record_type == 'lead' else CrmPerson.__table__
        got = _col(table, obj.record_id)
        return got if got not in (_UNSET, None) else _UNSET
    return _UNSET


def _before_flush(sess, flush_context, instances):
    new = [o for o in sess.new if isinstance(o, SCOPED) and o.workspace_id is None]
    if not new:
        return
    stamp = _quiet(stamp_id)
    sess.info['crm_ws_stamp'] = stamp
    new.sort(key=lambda o: 0 if isinstance(o, _FIRST) else 1)
    for obj in new:
        got = _parent_ws(sess, obj)
        wid = got if got is not _UNSET else stamp
        if wid is not None:
            obj.workspace_id = wid


def _before_insert(mapper, connection, target):
    """A row that reached the flush without a workspace (added by another flush hook): the stamp of this flush."""
    if target.workspace_id is None:
        sess = object_session(target)
        stamp = sess.info.get('crm_ws_stamp') if sess is not None else None
        if stamp is not None:
            target.workspace_id = stamp


def register():
    if not _registered:
        event.listen(db.session, 'do_orm_execute', _on_execute)
        event.listen(db.session, 'before_flush', _before_flush)
        for model in SCOPED:
            event.listen(model, 'before_insert', _before_insert)
        _registered.append(1)


# ---------------------------------------------------------------------------------------- deciding

def source_workspace(key):
    """The workspace a public capture with this lead-source key lands in: the one workspace that has the key, else
    the default one when several have it (the site's own forms are the first business's), else -- a key nobody
    has -- the default workspace (the source is made there, unrouted)."""
    key = (key or '').strip().lower()
    T = CrmSource.__table__
    ids = {r[0] for r in _quiet(lambda: db.session.execute(select(T.c.workspace_id).where(T.c.key == key)).all())}
    d = default_id()
    ids = {i if i is not None else d for i in ids}
    if len(ids) == 1:
        return next(iter(ids))
    if not ids or d in ids:
        return d
    return min(i for i in ids if i is not None)


def for_capture(source_key, person=None, workspace_id=None):
    """The block a capture runs in: an explicit workspace, else the person's, else the current one (staff, a job,
    a webhook), else the SOURCE decides (a public form has nobody signed in). Nothing while there is one workspace."""
    if workspace_id is not None:
        return use(workspace_id)
    if not several():
        return nullcontext()
    if person is not None:
        return use(of(person))
    if active():
        return nullcontext()
    return use(source_workspace(source_key))


def for_source(source_key):
    """A webhook that makes its own source before it captures (lead ads): the source's workspace for both."""
    if not several() or active():
        return nullcontext()
    return use(source_workspace(source_key))


# ---------------------------------------------------------------------------------------- WhatsApp

def whatsapp_id():
    """The workspace WhatsApp belongs to: the one linked to the WhatsApp CRM, else the default one."""
    c = request_cache('crm_scope')
    if 'wa' not in c:
        def find():
            T = Workspace.__table__
            for wid, info in db.session.execute(select(T.c.id, T.c.wacrm).order_by(T.c.id)).all():
                if isinstance(info, dict) and info.get('account_id'):
                    return wid
            return default_id()
        c['wa'] = _quiet(find)
    return c['wa']


def wa_here():
    """WhatsApp works in the current workspace (or nothing is limited). A second workspace's leads have WhatsApp
    off until it has a number of its own: the WhatsApp CRM is linked to one workspace."""
    wid = current_id()
    if wid is None:
        return True
    return wid == whatsapp_id()


def wa_person(person):
    """The person may be written to the WhatsApp CRM: they belong to the workspace WhatsApp is linked to."""
    if person is None or not several():
        return True
    return of(person) == whatsapp_id()


def whatsapp_elsewhere():
    """The workspace WhatsApp is linked to, when the current one is another (for "WhatsApp is linked to X"), or
    None."""
    if wa_here():
        return None
    wid = whatsapp_id()
    return db.session.get(Workspace, wid) if wid is not None else None


def in_whatsapp():
    """The block a WhatsApp CRM webhook or job runs in."""
    if not several():
        return nullcontext()
    return use(whatsapp_id())


# ---------------------------------------------------------------------------------------- people

def in_workspace(users, workspace_id=_UNSET):
    """The staff among `users` who work in the workspace (the current one by default): its members; in the default
    workspace also staff who belong to no workspace (the old set-up). Everyone while there is one workspace."""
    users = list(users)
    wid = current_id() if workspace_id is _UNSET else workspace_id
    if wid is None or not several():
        return users
    from app.models import WorkspaceMember
    rows = _quiet(lambda: db.session.query(WorkspaceMember.workspace_id, WorkspaceMember.user_id)
                  .filter(WorkspaceMember.user_id.in_([u.id for u in users] or [0])).all())
    member_of = {}
    for w, u in rows:
        member_of.setdefault(u, set()).add(w)
    default = is_default(wid)
    return [u for u in users if wid in member_of.get(u.id, ()) or (default and not member_of.get(u.id))]


# ---------------------------------------------------------------------------------------- jobs and seeding

def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _merge(out, got):
    """Add one workspace's report into the total: numbers add up, anything else keeps the last word said."""
    for k, v in (got or {}).items():
        if k in out and _number(v) and _number(out[k]):
            out[k] += v
        elif k not in out or v not in (None, '', [], {}):
            out[k] = v
    return out


def each_workspace(fn, *args, **kwargs):
    """Run a CRM job once per workspace (inside use()), adding up the numbers it reports. With one workspace (or
    none) it simply runs once, as before. A workspace that fails does not stop the others; the first failure is
    raised at the end, so the runner reports the step as failed."""
    ids = workspace_ids()
    if len(ids) <= 1:
        return fn(*args, **kwargs)
    out, failed = {}, None
    for wid in ids:
        try:
            with use(wid):
                got = fn(*args, **kwargs)
        except Exception as exc:          # noqa: BLE001 -- the next workspace still runs
            db.session.rollback()
            log.exception('CRM job %s failed for workspace %s', getattr(fn, '__name__', fn), wid)
            failed = failed or exc
            continue
        if isinstance(got, dict):
            _merge(out, got)
        else:
            out = got
    if failed is not None:
        raise failed
    return out


def in_whatsapp_workspace(fn, *args, **kwargs):
    """Run a WhatsApp job only for the workspace WhatsApp is linked to."""
    with in_whatsapp():
        return fn(*args, **kwargs)


def seed(workspace_id):
    """A new workspace gets its own copy of the starting pipelines, products, lead sources and ready answers."""
    from app.services import crm
    with use(workspace_id):
        crm.ensure_defaults()
