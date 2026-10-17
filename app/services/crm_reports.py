"""The two sheets of "Sales Process 1.5" that are about the team rather than the customers.

KPI (HB KPI, AP KPI, HK KPI): per person, per day -- leads they were given or added, replies,
messages and calls, follow-ups done, stage moves, won and lost, how fast the first message went out.
Counted from what the CRM already records, so nobody fills a sheet in.

Checker: every half hour from 07:00 to midnight (India time) somebody confirms each inbox was
looked at -- Tawk, Messenger, Instagram, comments, both WhatsApp numbers, e-mail, calls, Telegram,
the website. One click ticks them all for the current half hour.
"""
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median

from sqlalchemy import func

from app import db
from app.models import (CrmChannelCheck, CrmLead, CrmStage, CrmStageChange, CrmTask, CrmTouchpoint,
                        CRM_CHECK_HOURS)

IST = timedelta(hours=5, minutes=30)

METRICS = [
    ('leads', 'New leads given to them'),
    ('added', 'Leads they added'),
    ('replies', 'Replies from their leads'),
    ('messages', 'Messages sent'),
    ('calls', 'Calls made'),
    ('talked', 'Calls answered'),
    ('done', 'Follow-ups done'),
    ('moved', 'Leads moved on'),
    ('won', 'Won'),
    ('lost', 'Fell out'),
]
CODE = re.compile(r'^[A-Z]+')


def ist_day(dt):
    return (dt + IST).date() if dt else None


def kpis(since, until=None, user_ids=None):
    """({user_id: {metric: n, 'codes': {prefix: n}, 'first_reply_h': median hours}},
        {user_id: {ist date: {metric: n}}}) for activity between `since` and `until` (UTC)."""
    # a second of slack: the clock can read the same as a row written a moment ago
    until = until or datetime.utcnow() + timedelta(seconds=1)
    total = defaultdict(lambda: defaultdict(int))
    daily = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

    def add(uid, when, metric):
        if uid is None or (user_ids is not None and uid not in user_ids):
            return
        total[uid][metric] += 1
        daily[uid][ist_day(when)][metric] += 1

    rng = lambda col: (col >= since, col < until)        # noqa: E731
    for owner, created_by, created in (db.session.query(CrmLead.owner_id, CrmLead.created_by_id, CrmLead.created_at)
                                       .filter(*rng(CrmLead.created_at))):
        add(owner, created, 'leads')
        add(created_by, created, 'added')
    for owner, status, closed in (db.session.query(CrmLead.owner_id, CrmLead.status, CrmLead.closed_at)
                                  .filter(CrmLead.status.in_(('won', 'lost')), *rng(CrmLead.closed_at))):
        add(owner, closed, status)
    for agent, ch, direction, outcome, code, when, owner, tp_status in (
            db.session.query(CrmTouchpoint.agent_id, CrmTouchpoint.channel, CrmTouchpoint.direction,
                             CrmTouchpoint.outcome, CrmTouchpoint.code, CrmTouchpoint.created_at,
                             CrmLead.owner_id, CrmTouchpoint.status)
            .outerjoin(CrmLead, CrmLead.id == CrmTouchpoint.lead_id)
            .filter(*rng(CrmTouchpoint.created_at))):
        if tp_status == 'imported':
            continue                 # older messages brought onto the lead page are history, not work
        if direction == 'in':
            if ch != 'form':
                add(owner, when, 'replies')
        elif direction == 'out':
            if ch == 'call':
                add(agent, when, 'calls')
                if outcome == 'connected':
                    add(agent, when, 'talked')
            else:
                add(agent, when, 'messages')
            m = CODE.match(code or '')
            if m and agent is not None and (user_ids is None or agent in user_ids):
                codes = total[agent].setdefault('codes', defaultdict(int))
                codes[m.group(0)] += 1
    for by, when in (db.session.query(CrmTask.done_by_id, CrmTask.done_at)
                     .filter(CrmTask.status == 'done', *rng(CrmTask.done_at))):
        add(by, when, 'done')
    for by, when in (db.session.query(CrmStageChange.by_id, CrmStageChange.created_at)
                     .join(CrmStage, CrmStage.id == CrmStageChange.to_stage_id)
                     .filter(CrmStageChange.from_stage_id.isnot(None), CrmStage.kind == 'open',
                             *rng(CrmStageChange.created_at))):
        add(by, when, 'moved')

    # how long the first message took, for leads that came in during the period
    first_out = (db.session.query(CrmTouchpoint.lead_id, func.min(CrmTouchpoint.created_at).label('t'))
                 .filter(CrmTouchpoint.direction == 'out',
                         db.or_(CrmTouchpoint.status.is_(None), CrmTouchpoint.status != 'imported'))
                 .group_by(CrmTouchpoint.lead_id).subquery())
    waits = defaultdict(list)
    for owner, created, t in (db.session.query(CrmLead.owner_id, CrmLead.created_at, first_out.c.t)
                              .join(first_out, first_out.c.lead_id == CrmLead.id)
                              .filter(*rng(CrmLead.created_at))):
        if owner is not None and t and created and (user_ids is None or owner in user_ids):
            waits[owner].append(max((t - created).total_seconds() / 3600, 0))
    for uid, hours in waits.items():
        total[uid]['first_reply_h'] = round(median(hours), 1)
    return total, daily


def overdue_by_owner():
    return dict(db.session.query(CrmTask.owner_id, func.count(CrmTask.id))
                .filter(CrmTask.status == 'open', CrmTask.due_at < datetime.utcnow())
                .group_by(CrmTask.owner_id).all())


# ============================================================================================ checker

def ist_now():
    return datetime.utcnow() + IST


def slot_of(ist_dt):
    return ist_dt.hour * 2 + (1 if ist_dt.minute >= 30 else 0)


def slots():
    return list(range(CRM_CHECK_HOURS[0] * 2, CRM_CHECK_HOURS[1] * 2))


def slot_label(s):
    return '%02d:%02d' % (s // 2, 30 if s % 2 else 0)


def current():
    """(today in India, the half hour now -- None outside the checking hours)."""
    now = ist_now()
    s = slot_of(now)
    return now.date(), (s if s in slots() else None)


def grid(day):
    from app.services import crm
    # ticks made before an inbox was renamed still count under its new name
    return {(c.slot, crm.CHECK_RENAMED.get(c.channel, c.channel)): c
            for c in CrmChannelCheck.query.filter_by(day=day).all()}


def can_tick(day, slot):
    """The current half hour and the ones already gone today (a late tick is still a tick); never
    the future, and other days only by an admin through the history view."""
    today, now_slot = current()
    if day != today:
        return False
    last = now_slot if now_slot is not None else (max(slots()) if slot_of(ist_now()) > max(slots()) else -1)
    return slot in slots() and slot <= last


def toggle(day, slot, channel, user):
    hit = CrmChannelCheck.query.filter_by(day=day, slot=slot, channel=channel).first()
    if hit:
        db.session.delete(hit)
        db.session.commit()
        return False
    db.session.add(CrmChannelCheck(day=day, slot=slot, channel=channel, user_id=user.id))
    db.session.commit()
    return True


def tick_all(day, slot, user, channels):
    have = {c.channel for c in CrmChannelCheck.query.filter_by(day=day, slot=slot).all()}
    for ch in channels:
        if ch not in have:
            db.session.add(CrmChannelCheck(day=day, slot=slot, channel=ch, user_id=user.id))
    db.session.commit()


def coverage(day, channels):
    """How much of the day so far was covered: {'done', 'due', 'pct', 'missed': [slot labels]}."""
    today, now_slot = current()
    if day > today:
        upto = []
    elif day < today:
        upto = slots()
    else:
        upto = [s for s in slots() if now_slot is not None and s < now_slot] if now_slot is not None else \
            ([s for s in slots()] if slot_of(ist_now()) > max(slots()) else [])
    ticks = grid(day)
    full = [s for s in upto if all((s, ch) in ticks for ch in channels)]
    missed = [slot_label(s) for s in upto if s not in full]
    return {'done': len(full), 'due': len(upto), 'missed': missed,
            'pct': round(100 * len(full) / len(upto)) if upto else None}


def current_slot_done(channels):
    day, s = current()
    if s is None:
        return True
    ticks = grid(day)
    return all((s, ch) in ticks for ch in channels)


# ============================================================================================ the daily tracker

def day_bounds(day):
    start = datetime.combine(day, datetime.min.time()) - IST
    return start, start + timedelta(days=1)


def day_sheet(day, users):
    """What each person had to do on `day` (India time) and what they did -- the admin's daily
    tracker. {user id: {...}} with:
        checklist  follow-ups due that day (and earlier ones finished that day), by customer:
                   [{'lead', 'items': [{'task', 'state': done/late/missed/pending/moved, 'at'}]}]
        timeline   [(time, lead or None, icon, text)] oldest first
        counts     due, done, missed, pending, messages, calls, moves, added, checks
        first, last  their first and last action of the day
        log        what they entered in "Log today's work"
    """
    from app.models import CrmActivity, CrmChannelCheck, CrmLead, CrmStageChange
    start, end = day_bounds(day)
    now = datetime.utcnow()
    ids = [u.id for u in users]
    sheet = {u.id: {'user': u, 'checklist': defaultdict(list), 'timeline': [], 'first': None, 'last': None,
                    'counts': defaultdict(int), 'log': {}} for u in users}

    def touch(uid, when):
        s = sheet.get(uid)
        if s is None or when is None:
            return
        s['first'] = when if s['first'] is None or when < s['first'] else s['first']
        s['last'] = when if s['last'] is None or when > s['last'] else s['last']

    # the checklist: due that day, or finished that day though due before
    tasks = (CrmTask.query.filter(CrmTask.owner_id.in_(ids) | CrmTask.done_by_id.in_(ids))
             .filter(((CrmTask.due_at >= start) & (CrmTask.due_at < end)) |
                     ((CrmTask.done_at >= start) & (CrmTask.done_at < end))).all())
    for t in tasks:
        due_today = start <= t.due_at < end
        if t.status == 'done':
            # on time: due that day and done that day; otherwise done, but late
            state = 'done' if due_today and t.done_at and t.done_at < end else 'late'
            who = t.done_by_id or t.owner_id
        elif t.status == 'skipped':
            state, who = 'moved', t.owner_id
        else:
            state, who = ('pending' if t.due_at > now else 'missed'), t.owner_id
        s = sheet.get(who)
        if s is None:
            continue
        s['checklist'][t.lead].append({'task': t, 'state': state, 'at': t.done_at})
        if due_today:
            s['counts']['due'] += 1
        s['counts'][{'done': 'done', 'late': 'done', 'missed': 'missed', 'pending': 'pending',
                     'moved': 'moved'}[state]] += 1
        if t.done_at and start <= t.done_at < end and t.status == 'done':
            s['timeline'].append((t.done_at, t.lead, 'fa-check', 'Did %s · %s' % (t.code or '', t.title)))
            touch(who, t.done_at)

    # messages and calls they made
    for tp in (CrmTouchpoint.query.filter(CrmTouchpoint.agent_id.in_(ids), CrmTouchpoint.direction == 'out',
                                          CrmTouchpoint.created_at >= start, CrmTouchpoint.created_at < end)):
        s = sheet[tp.agent_id]
        if tp.channel == 'call':
            s['counts']['calls'] += 1
            s['timeline'].append((tp.created_at, tp.lead, 'fa-phone', 'Called — %s' % (tp.outcome or '').replace('_', ' ')))
        else:
            s['counts']['messages'] += 1
            s['timeline'].append((tp.created_at, tp.lead, 'fa-paper-plane',
                                  'Sent %s on %s' % (tp.code or 'a message', tp.channel)))
        touch(tp.agent_id, tp.created_at)
    # notes they wrote
    for tp in (CrmTouchpoint.query.filter(CrmTouchpoint.agent_id.in_(ids), CrmTouchpoint.direction == 'none',
                                          CrmTouchpoint.created_at >= start, CrmTouchpoint.created_at < end)):
        if tp.channel == 'system':
            sheet[tp.agent_id]['timeline'].append((tp.created_at, tp.lead, 'fa-flag', tp.body or 'Marked'))
        else:
            sheet[tp.agent_id]['timeline'].append((tp.created_at, tp.lead, 'fa-note-sticky', 'Wrote a note'))
        touch(tp.agent_id, tp.created_at)
    # leads they moved
    for ch in (CrmStageChange.query.filter(CrmStageChange.by_id.in_(ids), CrmStageChange.from_stage_id.isnot(None),
                                           CrmStageChange.created_at >= start, CrmStageChange.created_at < end)):
        s = sheet[ch.by_id]
        s['counts']['moves'] += 1
        s['timeline'].append((ch.created_at, ch.lead, 'fa-arrow-right-arrow-left',
                              'Moved %s → %s' % (ch.from_stage.name if ch.from_stage else '?',
                                                 ch.to_stage.name if ch.to_stage else '?')))
        touch(ch.by_id, ch.created_at)
    # leads they added
    for l in CrmLead.query.filter(CrmLead.created_by_id.in_(ids), CrmLead.created_at >= start, CrmLead.created_at < end):
        s = sheet[l.created_by_id]
        s['counts']['added'] += 1
        s['timeline'].append((l.created_at, l, 'fa-user-plus', 'Added this lead'))
        touch(l.created_by_id, l.created_at)
    # the inbox check
    for c in CrmChannelCheck.query.filter(CrmChannelCheck.day == day, CrmChannelCheck.user_id.in_(ids)):
        s = sheet[c.user_id]
        s['counts']['checks'] += 1
        s.setdefault('slots', set()).add(c.slot)
        touch(c.user_id, c.checked_at)
    for s in sheet.values():
        n = len(s.get('slots') or ())
        if n:
            s['timeline'].append((s['first'] or start, None, 'fa-clipboard-check',
                                  'Checked the inboxes in %d half hour%s' % (n, '' if n == 1 else 's')))
        s['counts']['slots'] = n
    # what they logged by hand
    for a in CrmActivity.query.filter(CrmActivity.day == day, CrmActivity.user_id.in_(ids),
                                      CrmActivity.source == 'manual'):
        sheet[a.user_id]['log'][a.metric] = a.count
    for s in sheet.values():
        s['timeline'].sort(key=lambda e: e[0])
        due = s['counts']['due']
        s['counts']['score'] = round(100 * min(s['counts']['done'], due) / due) if due else None
        s['checklist'] = sorted(s['checklist'].items(),
                                key=lambda kv: min(i['task'].due_at for i in kv[1]))
    return sheet


# ============================================================================================ team today

def visible_staff(user, staff):
    """Who of `staff` the person sees on Team today. Admins, and anybody who can open the workspace's
    people page, see everybody; a team lead sees their own workspace teams (and themselves)."""
    from app.services import access
    if user.is_admin or access.can(user, 'ws_members'):
        return list(staff)
    ws = access.current_workspace(user)
    member = next((m for m in access.memberships(user) if ws is not None and m.workspace_id == ws.id), None)
    ids = {user.id}
    if member is not None:
        ids |= {u.id for t in access.teams_of(member) for u in t.users}
    return [u for u in staff if u.id in ids]


def team_numbers(day, users, now=None):
    """{user id: {'open', 'late', 'waiting', 'replies', 'unanswered', 'first_reply'}} for Team today,
    from seven queries however many people there are. The first three are as things stand now; the
    rest are about `day` (India time). first_reply: median minutes for a person's first answer, or
    None."""
    from app.services import crm_metrics
    now = now or datetime.utcnow()
    ids = [u.id for u in users]
    out = {i: {'open': 0, 'late': 0, 'waiting': 0, 'replies': 0, 'unanswered': 0, 'first_reply': None}
           for i in ids}
    if not ids:
        return out
    start, end = day_bounds(day)
    for owner, n in (db.session.query(CrmLead.owner_id, func.count(CrmLead.id))
                     .filter(CrmLead.status == 'open', CrmLead.owner_id.in_(ids))
                     .group_by(CrmLead.owner_id)):
        out[owner]['open'] = n
    for owner, n in overdue_by_owner().items():
        if owner in out:
            out[owner]['late'] = n
    for owner, n in crm_metrics.waiting_by_owner(ids).items():
        out[owner]['waiting'] = n
    for owner, n in (db.session.query(CrmLead.owner_id, func.count(CrmTouchpoint.id))
                     .join(CrmLead, CrmLead.id == CrmTouchpoint.lead_id)
                     .filter(CrmTouchpoint.channel == 'whatsapp', CrmTouchpoint.direction == 'in',
                             func.coalesce(CrmTouchpoint.status, '') != 'imported',
                             CrmTouchpoint.created_at >= start, CrmTouchpoint.created_at < end,
                             CrmLead.owner_id.in_(ids))
                     .group_by(CrmLead.owner_id)):
        out[owner]['replies'] = n
    for owner, n in crm_metrics.unanswered_by_owner(start, min(end, now), ids).items():
        out[owner]['unanswered'] = n
    for agent, minutes in crm_metrics.first_reply_minutes(start, end, now).items():
        if agent in out:
            out[agent]['first_reply'] = minutes
    return out


def step_ticks(day, owner_ids=None):
    """How each WhatsApp follow-up step went out on `day`: [{'title', 'pipeline', 'sent', 'delivered',
    'read', 'failed', 'opened', 'total'}] in pipeline, stage and step order. Each message counts once,
    at its latest tick. `owner_ids`: only leads of those people. Two queries."""
    from app.models import CrmPipeline, CrmPlaybookStep
    from app.services.crm_timeline import TICKS
    start, end = day_bounds(day)
    steps = {}
    for code, title, pipe, ppos, spos in (db.session.query(CrmPlaybookStep.code, CrmPlaybookStep.title,
                                                          CrmPipeline.name, CrmStage.position, CrmPlaybookStep.position)
                                          .join(CrmStage, CrmStage.id == CrmPlaybookStep.stage_id)
                                          .join(CrmPipeline, CrmPipeline.id == CrmStage.pipeline_id)
                                          .filter(CrmPlaybookStep.channel == 'whatsapp')
                                          .order_by(CrmPipeline.id, CrmStage.position, CrmPlaybookStep.position)):
        steps.setdefault(code, (pipe, title, len(steps)))
    if not steps:
        return []
    q = (db.session.query(CrmTouchpoint.code, CrmTouchpoint.status, func.count(CrmTouchpoint.id))
         .filter(CrmTouchpoint.channel == 'whatsapp', CrmTouchpoint.direction == 'out',
                 CrmTouchpoint.created_at >= start, CrmTouchpoint.created_at < end,
                 CrmTouchpoint.code.in_(list(steps)),
                 CrmTouchpoint.status.in_([t for t in TICKS if t != 'sending']))
         .group_by(CrmTouchpoint.code, CrmTouchpoint.status))
    if owner_ids is not None:
        q = q.join(CrmLead, CrmLead.id == CrmTouchpoint.lead_id).filter(CrmLead.owner_id.in_(list(owner_ids)))
    rows = {}
    for code, status, n in q:
        r = rows.setdefault(code, {'sent': 0, 'delivered': 0, 'read': 0, 'failed': 0, 'opened': 0})
        r[status] = n
    out = []
    for code in sorted(rows, key=lambda c: steps[c][2]):
        pipe, title, _pos = steps[code]
        r = rows[code]
        out.append({'title': title, 'pipeline': pipe, **r, 'total': sum(r.values())})
    return out
