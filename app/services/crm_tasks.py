"""Tasks, calls and meetings anyone can add (Sales CRM 2.0, run 3a), and what the Calendar shows.

A CrmTask has always been "the next step of a lead" (kind 'step': made by a pipeline, a call-back or an
import). People can now also add their own: a to-do, a call or a meeting, on a lead or only on a person.
Those never plan a next step, never change the lead's "next step", and are not skipped when the lead moves.

Times are typed and shown in India time and stored in UTC like everything else here.
"""
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from app import db
from app.models import ActivityEvent, CrmLead, CrmPerson, CrmTask, User

IST = timedelta(hours=5, minutes=30)

KINDS = {'todo': 'To-do', 'call': 'Call', 'meeting': 'Meeting'}
KIND_ICONS = {'todo': 'fa-list-check', 'call': 'fa-phone', 'meeting': 'fa-handshake', 'step': 'fa-bolt',
              'departure': 'fa-plane-departure', 'cover_end': 'fa-shield-halved'}
PRIORITIES = {'low': 'Low', 'normal': 'Normal', 'high': 'High'}
PRIORITY_RANK = {'high': 0, 'normal': 1, None: 1, 'low': 2}

TITLE_NEEDED = 'Give the task a title.'
BAD_TIME = 'The date or time did not look right.'
END_BEFORE_START = 'A meeting cannot end before it starts.'
NOT_STAFF = 'Choose someone from the list.'
NOT_YOURS = 'Only the person it is for, the person who made it, or an admin can change this.'
BELL = '%s gave you a %s'


# ------------------------------------------------------------------------------------------ time

def to_utc(ist_dt):
    return ist_dt - IST


def from_utc(dt):
    return dt + IST if dt else None


def default_due(now=None):
    """Tomorrow 10:00 India time, as UTC."""
    today = ((now or datetime.utcnow()) + IST).date()
    return to_utc(datetime.combine(today + timedelta(days=1), time(10, 0)))


def parse_when(text):
    """'2026-10-22T10:00' (or 'YYYY-MM-DD HH:MM', or just a date: 10:00) typed in India time -> UTC; None if
    it does not look like one."""
    text = (text or '').strip().replace(' ', 'T')
    if not text:
        return None
    for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S'):
        try:
            return to_utc(datetime.strptime(text, fmt))
        except ValueError:
            pass
    try:
        return to_utc(datetime.combine(datetime.strptime(text, '%Y-%m-%d').date(), time(10, 0)))
    except ValueError:
        return None


def input_value(dt):
    """For <input type=datetime-local>: the stored UTC time as India time."""
    return from_utc(dt).strftime('%Y-%m-%dT%H:%M') if dt else ''


def end_of_today(now=None):
    """The end of today in India time, as UTC."""
    today = ((now or datetime.utcnow()) + IST).date()
    return to_utc(datetime.combine(today, time.max))


# ------------------------------------------------------------------------------------------ who

def staff():
    """The people a task can be given to: the sales staff."""
    from app.services import crm_scope, cs_access
    return crm_scope.in_workspace(cs_access.recipients('crm_board', limit=None))


def can_change(user, task):
    """Edit, done and delete: the person it is for, the person who made it, or an admin."""
    if user is None or not getattr(user, 'is_authenticated', True):
        return False
    return bool(user.is_admin or task.owner_id == user.id or task.created_by_id == user.id)


def _staff_ids():
    return {u.id for u in staff()}


# ------------------------------------------------------------------------------------------ write

def _fields(data, task=None, user=None):
    """Read and check the form. (values dict, error text or None). A blank field keeps the task's own."""
    out = {}
    title = (data.get('title') or '').strip()[:160] if 'title' in data or task is None else task.title
    if not title:
        return None, TITLE_NEEDED
    out['title'] = title
    kind = data.get('kind') or (task.kind if task is not None else 'todo')
    if kind not in KINDS:
        kind = 'todo'
    out['kind'] = kind
    out['channel'] = kind
    if data.get('due') or task is None or 'due' in data:
        due = parse_when(data.get('due'))
        if due is None:
            if (data.get('due') or '').strip():
                return None, BAD_TIME
            due = task.due_at if task is not None else default_due()
        out['due_at'] = due
    due = out.get('due_at') or task.due_at
    ends = None
    if kind == 'meeting' and (data.get('ends') or '').strip():
        ends = parse_when(data.get('ends'))
        if ends is None:
            return None, BAD_TIME
        if ends < due:
            return None, END_BEFORE_START
    out['ends_at'] = ends
    out['location'] = (data.get('location') or '').strip()[:200] or None
    out['notes'] = (data.get('notes') or '').strip()[:4000] or None
    prio = data.get('priority') or (task.priority if task is not None else None) or 'normal'
    out['priority'] = prio if prio in PRIORITIES else 'normal'
    owner = data.get('owner_id')
    if str(owner or '').isdigit():
        if int(owner) not in _staff_ids() and not (task is not None and int(owner) == task.owner_id):
            return None, NOT_STAFF
        out['owner_id'] = int(owner)
    elif task is None:
        out['owner_id'] = getattr(user, 'id', None)
    return out, None


def _link(task):
    from app.services import crm
    if task.lead_id:
        return crm._lead_link(task.lead) if task.lead is not None else None
    try:
        from flask import url_for
        return url_for('crm.contact', person_id=task.person_id)
    except Exception:          # noqa: BLE001 -- outside a request
        return '/cs/crm/contact/%d' % task.person_id


def _bell(task, giver):
    """A bell for whoever was given the task, when somebody else gave it."""
    from app.services import notify
    if not task.owner_id or task.owner_id == getattr(giver, 'id', None):
        return
    notify.push(task.owner_id, 'crm_task', title=BELL % (getattr(giver, 'first_name', None) or 'Someone',
                                                          KINDS.get(task.kind, 'task').lower()),
                body='%s · %s' % (task.title, _when_text(task.due_at)), link=_link(task))


def _when_text(due):
    d = from_utc(due)
    return '%s %d %s, %s' % (d.strftime('%a'), d.day, d.strftime('%b'), d.strftime('%H:%M'))


def create(user, data, lead=None, person=None):
    """Add a task, call or meeting. (task, None) or (None, error). No commit."""
    if lead is not None:
        person = lead.person
    if person is None:
        return None, 'Choose who it is about.'
    values, err = _fields(data, None, user)
    if err:
        return None, err
    task = CrmTask(lead_id=lead.id if lead is not None else None, person_id=person.id, created_by_id=user.id,
                   status='open', auto=False, code=None, **values)
    db.session.add(task)
    db.session.flush()
    _bell(task, user)
    ActivityEvent.log('crm_task_added', actor=user, task=task.id, kind=task.kind)
    return task, None


def update(user, task, data):
    """Change one. (True, None) or (False, error). No commit."""
    if not task.is_step and not can_change(user, task):
        return False, NOT_YOURS
    values, err = _fields(data, task, user)
    if err:
        return False, err
    old_owner = task.owner_id
    for k, v in values.items():
        setattr(task, k, v)
    if task.owner_id != old_owner:
        _bell(task, user)
    ActivityEvent.log('crm_task_edited', actor=user, task=task.id)
    return True, None


def delete(user, task):
    if not can_change(user, task):
        return False, NOT_YOURS
    ActivityEvent.log('crm_task_deleted', actor=user, task=task.id)
    db.session.delete(task)
    return True, None


# ------------------------------------------------------------------------------------------ read

def manual():
    """Only the tasks people add by hand."""
    return CrmTask.kind != 'step'


def for_record(lead=None, person=None):
    """Open tasks, calls and meetings on this lead, and on its person with no lead: soonest first."""
    conds = []
    if lead is not None:
        conds.append(CrmTask.lead_id == lead.id)
        person = person or lead.person
    if person is not None:
        conds.append(CrmTask.person_id == person.id)
    if not conds:
        return []
    return (CrmTask.query.options(joinedload(CrmTask.owner))
            .filter(manual(), CrmTask.status == 'open', or_(*conds))
            .order_by(CrmTask.due_at, CrmTask.id).all())


def sort_key(t):
    return (t.due_at, PRIORITY_RANK.get(t.priority, 1), t.id or 0)


def my_open(user, until, everybody=False):
    """Manual tasks due by `until` (late ones included): for My day. Soonest first, high first inside one time."""
    q = (CrmTask.query.options(joinedload(CrmTask.lead).joinedload(CrmLead.person), joinedload(CrmTask.person),
                               joinedload(CrmTask.owner))
         .filter(manual(), CrmTask.status == 'open', CrmTask.due_at <= until))
    if not everybody:
        q = q.filter(CrmTask.owner_id == user.id)
    return sorted(q.limit(300).all(), key=sort_key)


def person_of(task):
    return task.lead.person if task.lead is not None else task.person


def label_of(task):
    p = person_of(task)
    return p.display_name if p is not None else ''


def href_of(task):
    return _link(task)


# ------------------------------------------------------------------------------------------ who is shown

def teammates(user):
    """The ids of everyone in the viewer's teams, the viewer included."""
    from app.services import access
    ids = {user.id}
    ws = access.current_workspace(user)
    member = next((m for m in access.memberships(user) if ws is not None and m.workspace_id == ws.id), None)
    if member is not None:
        ids |= {u.id for t in access.teams_of(member) for u in t.users}
    return ids


def sees_everyone(user):
    from app.services import access
    return bool(user.is_admin or access.can(user, 'ws_members') or access.can(user, 'crm_tracker')
                or access.can(user, 'crm_insights'))


def who_options(user):
    """[(key, label)] the viewer may pick."""
    out = [('mine', 'Mine'), ('team', 'My team')]
    if sees_everyone(user):
        out.append(('all', 'Everyone'))
    return out


def owner_scope(user, who):
    """(who actually used, owner ids or None for all). "Everyone" and "My team" never go beyond whose leads
    the viewer's role may see (services/crm_access)."""
    from app.services import crm_access
    seen = crm_access.visible_owner_ids(user)            # None: no limit
    if who == 'all' and sees_everyone(user):
        return 'all', (None if seen is None else sorted(seen))
    if who == 'team':
        ids = teammates(user)
        return 'team', sorted(ids if seen is None else ids & seen)
    return 'mine', [user.id]


# ------------------------------------------------------------------------------------------ the list

def open_list(user, who='mine', kind=None, priority=None, now=None):
    """Open tasks, calls and meetings the viewer may see, in four groups: late, today, this week, later.
    {'groups': [(key, label, [task])], 'who', 'total'}."""
    now = now or datetime.utcnow()
    who, owners = owner_scope(user, who)
    q = (CrmTask.query.options(joinedload(CrmTask.lead).joinedload(CrmLead.person), joinedload(CrmTask.person),
                               joinedload(CrmTask.owner))
         .filter(manual(), CrmTask.status == 'open'))
    if owners is not None:
        q = q.filter(CrmTask.owner_id.in_(owners))
    if kind in KINDS:
        q = q.filter(CrmTask.kind == kind)
    if priority in PRIORITIES:
        q = q.filter(CrmTask.priority == priority)
    tasks = sorted(q.limit(1000).all(), key=sort_key)
    today_end = end_of_today(now)
    week_end = today_end + timedelta(days=6)
    groups = [('late', 'Late', []), ('today', 'Today', []), ('week', 'This week', []), ('later', 'Later', [])]
    for t in tasks:
        if t.due_at < now:
            groups[0][2].append(t)
        elif t.due_at <= today_end:
            groups[1][2].append(t)
        elif t.due_at <= week_end:
            groups[2][2].append(t)
        else:
            groups[3][2].append(t)
    return {'groups': groups, 'who': who, 'total': len(tasks)}


# ------------------------------------------------------------------------------------------ the calendar

def month_grid(day):
    """The weeks (Monday first) that show the month of `day`: [[date x 7]]."""
    first = day.replace(day=1)
    start = first - timedelta(days=first.weekday())
    last = first.replace(day=monthrange(day.year, day.month)[1])
    end = last + timedelta(days=6 - last.weekday())
    weeks, d = [], start
    while d <= end:
        weeks.append([d + timedelta(days=i) for i in range(7)])
        d += timedelta(days=7)
    return weeks


def week_days(day):
    start = day - timedelta(days=day.weekday())
    return [start + timedelta(days=i) for i in range(7)]


def calendar_items(user, first, last, who='mine'):
    """Everything on the calendar between the India dates `first` and `last` (both included):
    {date: [item]}, items in time order, all-day items first. An item: {kind, title, who, time, end, href,
    task_id, done, priority, can_done, all_day}."""
    who, owners = owner_scope(user, who)
    lo = to_utc(datetime.combine(first, time.min))
    hi = to_utc(datetime.combine(last + timedelta(days=1), time.min))
    out = defaultdict(list)

    q = (CrmTask.query.options(joinedload(CrmTask.lead).joinedload(CrmLead.person), joinedload(CrmTask.person))
         .filter(CrmTask.due_at >= lo, CrmTask.due_at < hi, CrmTask.status.in_(('open', 'done'))))
    if owners is not None:
        q = q.filter(CrmTask.owner_id.in_(owners))
    for t in q.order_by(CrmTask.due_at).limit(2000):
        d = from_utc(t.due_at)
        step = t.is_step
        out[d.date()].append({
            'kind': t.kind or 'step', 'title': t.title, 'who': label_of(t), 'all_day': False,
            'time': d.strftime('%H:%M'),
            'end': from_utc(t.ends_at).strftime('%H:%M') if t.ends_at else None,
            'href': href_of(t) if (t.lead_id or t.person_id) else None, 'task_id': t.id,
            'done': t.status == 'done', 'priority': t.priority, 'sort': (1, d.strftime('%H:%M')),
            'can_done': (not step and t.status == 'open' and can_change(user, t)),
            'place': t.location})

    lq = (CrmLead.query.options(joinedload(CrmLead.person))
          .filter(CrmLead.status == 'open',
                  or_(CrmLead.departure_date.between(first, last), CrmLead.ends_on.between(first, last))))
    if owners is not None:
        lq = lq.filter(CrmLead.owner_id.in_(owners))
    from flask import url_for
    for l in lq.limit(2000):
        href = None
        try:
            href = url_for('crm.lead', lead_id=l.id)
        except Exception:          # noqa: BLE001 -- outside a request
            href = '/cs/crm/lead/%d' % l.id
        for field, kind, text in (('departure_date', 'departure', 'Travels'), ('ends_on', 'cover_end', 'Cover ends')):
            v = getattr(l, field)
            if v is not None and first <= v <= last:
                out[v].append({'kind': kind, 'title': text, 'who': l.person.display_name, 'all_day': True,
                               'time': None, 'end': None, 'href': href, 'task_id': None, 'done': False,
                               'priority': None, 'sort': (0, ''), 'can_done': False, 'place': None})
    for d in out:
        out[d].sort(key=lambda i: i['sort'])
    return out


def clamp_day(text, today):
    try:
        return datetime.strptime(text or '', '%Y-%m-%d').date()
    except ValueError:
        return today


def shift_month(day, n):
    m = day.month - 1 + n
    y, m = day.year + m // 12, m % 12 + 1
    return date(y, m, 1)
