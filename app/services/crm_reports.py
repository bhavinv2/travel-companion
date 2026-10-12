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
    for agent, ch, direction, outcome, code, when, owner in (
            db.session.query(CrmTouchpoint.agent_id, CrmTouchpoint.channel, CrmTouchpoint.direction,
                             CrmTouchpoint.outcome, CrmTouchpoint.code, CrmTouchpoint.created_at,
                             CrmLead.owner_id)
            .outerjoin(CrmLead, CrmLead.id == CrmTouchpoint.lead_id)
            .filter(*rng(CrmTouchpoint.created_at))):
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
                 .filter(CrmTouchpoint.direction == 'out').group_by(CrmTouchpoint.lead_id).subquery())
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
    return {(c.slot, c.channel): c for c in CrmChannelCheck.query.filter_by(day=day).all()}


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
