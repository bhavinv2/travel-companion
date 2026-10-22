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
                        CRM_CHANNEL_LABELS, CRM_CHECK_HOURS)
from app.services import crm_words

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
    ('lost', 'Lost'),
]
CODE = re.compile(r'^[A-Z]+')


def ist_day(dt):
    return (dt + IST).date() if dt else None


# the per-person download's columns, and the registry number each one is (services/crm_numbers.py)
KPI_NUMBER = {'leads': 'new_leads', 'added': 'leads_added', 'replies': 'replies_in', 'messages': 'messages_by_agent',
              'calls': 'calls', 'talked': 'calls_connected', 'done': 'followups_done', 'moved': 'moves',
              'won': 'won', 'lost': 'lost'}


def kpis(since, until=None, user_ids=None):
    """({user_id: {metric: n, 'codes': {prefix: n}, 'first_reply_h': median hours}},
        {user_id: {ist date: {metric: n}}}) for activity between `since` and `until` (UTC). The numbers are the
    registry's (crm_numbers), saved days where they are there."""
    from app.services import crm_numbers
    # a second of slack: the clock can read the same as a row written a moment ago
    until = until or datetime.utcnow() + timedelta(seconds=1)
    total = defaultdict(lambda: defaultdict(int))
    daily = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    by_key = {v: k for k, v in KPI_NUMBER.items()}
    for uid, days in crm_numbers.daily_by_owner(list(by_key), since, until, user_ids).items():
        for day, vals in days.items():
            for key, n in vals.items():
                total[uid][by_key[key]] += int(n)
                daily[uid][day][by_key[key]] += int(n)
    # which kind of message each person sent: the first letters of the step's code
    tp = CrmTouchpoint
    q = (db.session.query(tp.agent_id, tp.code, func.count(tp.id))
         .filter(tp.direction == 'out', tp.agent_id.isnot(None), tp.code.isnot(None),
                 func.coalesce(tp.status, '') != 'imported', tp.created_at >= since, tp.created_at < until))
    if user_ids is not None:
        q = q.filter(tp.agent_id.in_(list(user_ids)))
    for agent, code, n in q.group_by(tp.agent_id, tp.code).all():
        m = CODE.match(code or '')
        if m:
            codes = total[agent].setdefault('codes', defaultdict(int))
            codes[m.group(0)] += n
    # how long the first message took (people only), for leads that came in during the period
    scope = crm_numbers.scope(owner_ids=None if user_ids is None else list(user_ids))
    for uid, minutes in crm_numbers.by_owner('first_contact_minutes', since, until, scope).items():
        total[uid]['first_reply_h'] = round(minutes / 60, 1)
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


def slots_so_far(day):
    """The half hours of `day` that are over: all of a past day, none of a future one, today's up to now."""
    today, now_slot = current()
    if day > today:
        return []
    if day < today:
        return slots()
    if now_slot is not None:
        return [s for s in slots() if s < now_slot]
    return list(slots()) if slot_of(ist_now()) > max(slots()) else []


def coverage(day, channels):
    """How much of the day so far was covered: {'done', 'due', 'pct', 'missed': [slot labels]}."""
    upto = slots_so_far(day)
    ticks = grid(day)
    full = [s for s in upto if all((s, ch) in ticks for ch in channels)]
    missed = [slot_label(s) for s in upto if s not in full]
    return {'done': len(full), 'due': len(upto), 'missed': missed,
            'pct': round(100 * len(full) / len(upto)) if upto else None}


BULK_SECONDS = 5        # three or more inboxes ticked this close together by one person: one press of "Tick all"
# what a line of a person's day (day_sheet's timeline, by its icon) counts as, for "what they did that half hour":
# (one, several), in the order they are said
WORK_KINDS = {'fa-paper-plane': ('message', 'messages'), 'fa-phone': ('call', 'calls'),
              'fa-check': ('follow-up done', 'follow-ups done'),
              'fa-arrow-right-arrow-left': ('lead moved', 'leads moved'), 'fa-user-plus': ('lead added', 'leads added'),
              'fa-note-sticky': ('note', 'notes'), 'fa-flag': ('note', 'notes')}


def slot_end(day, s):
    """The moment half hour `s` of `day` (India time) is over, in UTC."""
    return datetime.combine(day, datetime.min.time()) + timedelta(minutes=30 * (s + 1)) - IST


def ist_hm(dt):
    return (dt + IST).strftime('%H:%M') if dt else ''


def _work_text(counts):
    """{'message': 3, 'call': 1} -> '3 messages · 1 call', in WORK_KINDS' order."""
    return ' · '.join('%d %s' % (counts[one], one if counts[one] == 1 else many)
                      for one, many in dict.fromkeys(WORK_KINDS.values()) if counts.get(one))


def checks_by_team(day, users, channels, teams, sheet=None):
    """Team today's "Half-hourly checks, team by team": each of `teams` (then everybody of `users` in none of
    them) with, for each member, how many inboxes they ticked in each half hour -- one inbox is ticked once
    per half hour, by whoever checks it -- and the team's coverage: the half hours so far in which every
    inbox was ticked by one of its members or by itself (a connected inbox). One query.
    `log`: what was checked, half hour by half hour, newest first -- for each inbox who ticked it and when (late:
    after that half hour was over; "Tick all": several inboxes in one press), and, from `sheet` (day_sheet), what
    the team's people did in that half hour. `inboxes`: each inbox's half hours checked by the team.
    [{'name', 'rows': [{'user', 'by_slot': {slot: n}, 'detail': {slot: text}, 'total'}], 'covered', 'due', 'pct',
      'missed', 'log': [{'slot', 'label', 'cells': [...], 'full', 'over', 'bulk', 'work'}], 'inboxes': [...]}]"""
    from app.services import crm
    upto = slots_so_far(day)
    over = set(upto)
    by_slot, mine, at = {}, {}, {}
    for c in CrmChannelCheck.query.filter_by(day=day).all():
        ch = crm.CHECK_RENAMED.get(c.channel, c.channel)
        if ch not in channels:
            continue
        by_slot.setdefault(c.slot, {})[ch] = c.user_id
        at[(c.slot, ch)] = c
        if c.user_id:
            mine.setdefault(c.user_id, {}).setdefault(c.slot, set()).add(ch)
    wanted = {u.id for u in users}
    names = {u.id: u.full_name for u in users}
    for c in at.values():
        if c.user_id and c.user_id not in names and c.user is not None:
            names[c.user_id] = c.user.full_name
    # "Tick all": one person's three or more ticks in a half hour, all within a few seconds
    bulk = set()
    for uid, slots_ in mine.items():
        for s, chs in slots_.items():
            times = sorted(at[(s, ch)].checked_at for ch in chs if at[(s, ch)].checked_at)
            if len(times) >= 3 and (times[-1] - times[0]).total_seconds() <= BULK_SECONDS:
                bulk.add((uid, s))
    # what each person did, half hour by half hour (their day's timeline, the checks themselves left out)
    work = {}
    for uid, s in (sheet or {}).items():
        for when, _lead, icon, _text in s['timeline']:
            kind = WORK_KINDS.get(icon)
            local = when + IST if when else None
            if kind and local is not None and local.date() == day:
                cnt = work.setdefault(uid, {}).setdefault(slot_of(local), {})
                cnt[kind[0]] = cnt.get(kind[0], 0) + 1

    def detail(uid, s):
        return ', '.join('%s %s' % (ch, ist_hm(at[(s, ch)].checked_at)) for ch in channels if ch in mine[uid][s])

    def group(name, members):
        ids = {u.id for u in members}
        covered = [s for s in upto if channels and all(
            ch in by_slot.get(s, {}) and (by_slot[s][ch] is None or by_slot[s][ch] in ids) for ch in channels)]
        rows = [{'user': u, 'by_slot': {s: len(chs) for s, chs in mine.get(u.id, {}).items()},
                 'detail': {s: detail(u.id, s) for s in mine.get(u.id, {})},
                 'total': sum(len(chs) for chs in mine.get(u.id, {}).values())} for u in members]
        shown = sorted({s for s in upto} | {s for s in by_slot if any(
            v is None or v in ids for v in by_slot[s].values())}, reverse=True)
        log = []
        for s in shown:
            cells = []
            for ch in channels:
                c = at.get((s, ch))
                if c is None:
                    cells.append({'channel': ch, 'state': 'miss' if s in over else 'open'})
                    continue
                late = c.checked_at is not None and c.checked_at > slot_end(day, s)
                cells.append({'channel': ch, 'state': 'late' if late else 'ok', 'at': ist_hm(c.checked_at),
                              'who': names.get(c.user_id, 'Someone') if c.user_id else 'Ticked itself',
                              'auto': c.user_id is None, 'other': c.user_id is not None and c.user_id not in ids,
                              'bulk': (c.user_id, s) in bulk})
            done = {}
            for uid in ids:
                for k, n in work.get(uid, {}).get(s, {}).items():
                    done[k] = done.get(k, 0) + n
            log.append({'slot': s, 'label': slot_label(s), 'until': slot_label(s + 1), 'cells': cells,
                        'full': s in covered, 'over': s in over,
                        'bulk': sorted({names.get(uid, '') for uid, bs in bulk if bs == s and uid in ids}),
                        'work': _work_text(done)})
        inboxes = [{'channel': ch, 'due': len(upto),
                    'done': sum(1 for s in upto if ch in by_slot.get(s, {})
                                and (by_slot[s][ch] is None or by_slot[s][ch] in ids))} for ch in channels]
        return {'name': name, 'rows': rows, 'covered': len(covered), 'covered_slots': set(covered), 'due': len(upto),
                'pct': round(100 * len(covered) / len(upto)) if upto else None,
                'missed': [slot_label(s) for s in upto if s not in covered], 'log': log, 'inboxes': inboxes}

    out, placed = [], set()
    for t in teams:
        members = [u for u in t.users if u.id in wanted]
        if members:
            out.append(group(t.name, members))
            placed |= {u.id for u in members}
    rest = [u for u in users if u.id not in placed]
    if rest:
        out.append(group('Not in a team' if out else 'Everybody', rest))
    return out


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
        if t.lead is not None:          # tasks with no lead are counted below, not listed under a lead
            s['checklist'][t.lead].append({'task': t, 'state': state, 'at': t.done_at})
        if due_today:
            s['counts']['due'] += 1
        s['counts'][{'done': 'done', 'late': 'done', 'missed': 'missed', 'pending': 'pending',
                     'moved': 'moved'}[state]] += 1
        if t.done_at and start <= t.done_at < end and t.status == 'done':
            if t.lead is not None:
                s['timeline'].append((t.done_at, t.lead, 'fa-check', 'Did: %s' % crm_words.message_name(t.code, t.title)))
            touch(who, t.done_at)

    # messages and calls they made
    titles = crm_words.step_titles()
    for tp in (CrmTouchpoint.query.filter(CrmTouchpoint.agent_id.in_(ids), CrmTouchpoint.direction == 'out',
                                          CrmTouchpoint.created_at >= start, CrmTouchpoint.created_at < end)):
        s = sheet[tp.agent_id]
        if tp.channel == 'call':
            s['counts']['calls'] += 1
            s['timeline'].append((tp.created_at, tp.lead, 'fa-phone', 'Called — %s' % (tp.outcome or '').replace('_', ' ')))
        else:
            s['counts']['messages'] += 1
            s['timeline'].append((tp.created_at, tp.lead, 'fa-paper-plane',
                                  'Sent %s on %s' % (crm_words.message_name(tp.code, titles.get(tp.code)).lower()
                                                     if tp.code else 'a message', CRM_CHANNEL_LABELS.get(tp.channel, tp.channel))))
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
    # the inbox check: a line per half hour they checked -- which inboxes, and whether it was late or "Tick all"
    from app.services import crm
    ticks = defaultdict(list)
    for c in CrmChannelCheck.query.filter(CrmChannelCheck.day == day, CrmChannelCheck.user_id.in_(ids)):
        s = sheet[c.user_id]
        s['counts']['checks'] += 1
        s.setdefault('slots', set()).add(c.slot)
        ticks[(c.user_id, c.slot)].append(c)
        touch(c.user_id, c.checked_at)
    for (uid, slot), cs in ticks.items():
        cs.sort(key=lambda c: c.checked_at or start)
        names = [crm.CHECK_RENAMED.get(c.channel, c.channel) for c in cs]
        when = cs[0].checked_at or start
        notes = []
        if any(c.checked_at and c.checked_at > slot_end(day, slot) for c in cs):
            notes.append('late, after %s' % slot_label(slot + 1))
        times = [c.checked_at for c in cs if c.checked_at]
        if len(times) >= 3 and (times[-1] - times[0]).total_seconds() <= BULK_SECONDS:
            notes.append('all with Tick all')
        sheet[uid]['timeline'].append((when, None, 'fa-clipboard-check', 'Checked %s for %s–%s%s' % (
            ', '.join(names), slot_label(slot), slot_label(slot + 1), (' (%s)' % '; '.join(notes)) if notes else '')))
    for s in sheet.values():
        s['counts']['slots'] = len(s.get('slots') or ())
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
    from app.services import access, crm_access
    if user.is_admin or access.can(user, 'ws_members'):
        return crm_access.limit_users(user, staff)          # a role that sees only its own leads sees only those people
    ws = access.current_workspace(user)
    member = next((m for m in access.memberships(user) if ws is not None and m.workspace_id == ws.id), None)
    ids = {user.id}
    if member is not None:
        ids |= {u.id for t in access.teams_of(member) for u in t.users}
    return crm_access.limit_users(user, [u for u in staff if u.id in ids])


def team_numbers(day, users, now=None):
    """{user id: {'open', 'late', 'waiting', 'replies', 'unanswered', 'first_reply'}} for Team today, from the
    registry (crm_numbers) in one grouped query per number however many people there are. The first three are as
    things stand now; the rest are about `day` (India time). first_reply: median minutes for a person's first
    answer, or None."""
    from app.services import crm_numbers
    now = now or datetime.utcnow()
    ids = [u.id for u in users]
    out = {i: {'open': 0, 'late': 0, 'waiting': 0, 'replies': 0, 'unanswered': 0, 'first_reply': None}
           for i in ids}
    if not ids:
        return out
    start, end = day_bounds(day)
    scope = crm_numbers.scope(owner_ids=ids, now=now)
    for field, key, span in (('open', 'open_leads', (start, end)), ('late', 'late_followups', (start, end)),
                             ('waiting', 'waiting_now', (start, end)), ('replies', 'whatsapp_replies', (start, end)),
                             ('unanswered', 'unanswered', (start, end)), ('first_reply', 'reply_minutes', (start, end))):
        for owner, n in crm_numbers.by_owner(key, span[0], span[1], scope).items():
            if owner in out:
                out[owner][field] = n
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
