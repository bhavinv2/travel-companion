"""The two sheets of "Sales Process 1.5" that are about the team rather than the customers.

KPI (HB KPI, AP KPI, HK KPI): per person, per day -- leads they were given or added, replies,
messages and calls, follow-ups done, stage moves, won and lost, how fast the first message went out.
Counted from what the CRM already records, so nobody fills a sheet in.

Checker: every half hour, day and night (07:00 to midnight before CRM_CHECK_ALL_DAY_FROM; India time) somebody
confirms each inbox was looked at -- Tawk, Messenger, Instagram, comments, both WhatsApp numbers, e-mail, calls, Telegram,
the website. One click ticks them all for the current half hour.
"""
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median

from sqlalchemy import func

from app import db
from app.models import (CrmChannelCheck, CrmLead, CrmStage, CrmStageChange, CrmTask, CrmTouchpoint,
                        CRM_CHANNEL_LABELS, CRM_CHECK_ALL_DAY_FROM, CRM_CHECK_HOURS)
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


def hours(day=None):
    """The checking hours (India time) of `day`, default today: round the clock from CRM_CHECK_ALL_DAY_FROM, 07:00 to
    midnight before -- an old day is judged by the hours it was checked to."""
    day = day or ist_now().date()
    return (0, 24) if day >= CRM_CHECK_ALL_DAY_FROM else CRM_CHECK_HOURS


def slots(day=None):
    """The half hours of `day` (default today) that are checked."""
    a, b = hours(day)
    return list(range(a * 2, b * 2))


def slot_label(s):
    return '%02d:%02d' % (s // 2, 30 if s % 2 else 0)


def current():
    """(today in India, the half hour now -- None outside the checking hours)."""
    now = ist_now()
    s = slot_of(now)
    return now.date(), (s if s in slots(now.date()) else None)


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
    every = slots(day)
    last = now_slot if now_slot is not None else (max(every) if slot_of(ist_now()) > max(every) else -1)
    return slot in every and slot <= last


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
    every = slots(day)
    if day < today:
        return every
    if now_slot is not None:
        return [s for s in every if s < now_slot]
    return every if slot_of(ist_now()) > max(every) else []


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
    """'14:05': a tick's or an action's time as shown (the header's clock; India unless another zone is picked)."""
    from app.services import clock
    return clock.fmt(dt, '%H:%M')


def _work_text(counts):
    """{'message': 3, 'call': 1} -> '3 messages · 1 call', in WORK_KINDS' order."""
    return ' · '.join('%d %s' % (counts[one], one if counts[one] == 1 else many)
                      for one, many in dict.fromkeys(WORK_KINDS.values()) if counts.get(one))


def check_report(day, users, channels, sheet=None, names=None):
    """One day of the half-hourly check in plain words -- what Team analysis (crm_team) shows when its period is
    one day. A half hour is fully checked when every inbox of `channels` was ticked -- by anybody, or by itself
    (a connected inbox). For each of `users`:
    the hours they worked (their first to last action, from `sheet`, day_sheet's), the half hours they
    ticked, how many of those were late (their first tick in it came after it was over -- one tick late
    of several on time is shown, not counted) or one press of "Tick all",
    the half hours nobody fully checked while they were working, and a strip of their day; then the half
    hours not fully checked, with who was working then, and each inbox's half hours. A tick by somebody not
    in `users` says "someone in another team" -- `names` ({user id: name}) may name them.
    {'due', 'full', 'pct', 'gap_count', 'late', 'checking', 'people': [...], 'gaps': [...], 'inboxes': [...]}"""
    from app.services import crm
    every = slots(day)
    upto = slots_so_far(day)
    over = set(upto)
    at = {}                                                   # (slot, inbox) -> its tick
    for c in CrmChannelCheck.query.filter_by(day=day).all():
        ch = crm.CHECK_RENAMED.get(c.channel, c.channel)
        if ch in channels:
            at[(c.slot, ch)] = c
    full = {s for s in every if channels and all((s, ch) in at for ch in channels)}
    seen = {u.id: u.full_name for u in users}
    seen.update(names or {})

    def late(c, s):
        return c.checked_at is not None and c.checked_at > slot_end(day, s)

    def who(c):
        return 'ticked itself' if c.user_id is None else seen.get(c.user_id, 'someone in another team')

    def window(uid):
        s = (sheet or {}).get(uid)
        if not s or not s.get('first'):
            return set()
        first, last = s['first'] + IST, s['last'] + IST
        a = slot_of(first) if first.date() == day else every[0]
        b = slot_of(last) if last.date() == day else every[-1]     # a late tick for 23:30 lands after midnight
        return {x for x in every if a <= x <= b}

    did = {}                                                  # what each person did, half hour by half hour
    for uid, s in (sheet or {}).items():
        for when, _lead, icon, _text in s['timeline']:
            kind = WORK_KINDS.get(icon)
            local = when + IST if when else None
            if kind and local is not None and local.date() == day:
                cnt = did.setdefault(uid, {}).setdefault(slot_of(local), {})
                cnt[kind[0]] = cnt.get(kind[0], 0) + 1

    people, windows = [], {}
    for u in users:
        mine = {}
        for (s, ch), c in at.items():
            if c.user_id == u.id:
                mine.setdefault(s, []).append((ch, c))
        work = windows[u.id] = window(u.id)
        strip_, rows = [], []
        for s in every:
            got = sorted(mine.get(s, []), key=lambda t: channels.index(t[0]))
            when = '%s–%s' % (slot_label(s), slot_label(s + 1))
            if got:
                was_late = all(late(c, s) for _, c in got)       # they only started after it was over
                state = 'late' if was_late else ('all' if len(got) == len(channels) else 'some')
                times = sorted(c.checked_at for _, c in got if c.checked_at)
                bulk = len(times) >= 3 and (times[-1] - times[0]).total_seconds() <= BULK_SECONDS
                said = '%s: ticked %s' % (when, ', '.join('%s %s' % (ch, ist_hm(c.checked_at)) for ch, c in got))
                rows.append({'slot': s, 'when': when, 'state': state, 'bulk': bulk,
                             'ticks': [{'channel': ch, 'at': ist_hm(c.checked_at), 'late': late(c, s)} for ch, c in got],
                             'others': [ch for ch in channels if (s, ch) not in at],
                             'did': _work_text(did.get(u.id, {}).get(s, {}))})
            elif s not in over:
                state, said = 'open', '%s: not over yet' % when
            elif s not in work:
                state, said = 'off', '%s: not working then' % when
            elif s in full:
                state = 'covered'
                said = '%s: others checked every inbox' % when
            else:
                state = 'gap'
                missing = [ch for ch in channels if (s, ch) not in at]
                said = '%s: working, but %s not checked by anybody' % (when, ', '.join(missing))
                rows.append({'slot': s, 'when': when, 'state': 'gap', 'bulk': False, 'ticks': [], 'others': missing,
                             'did': _work_text(did.get(u.id, {}).get(s, {}))})
            strip_.append({'slot': s, 'state': state, 'title': said, 'hour': s % 2 == 0})
        checked = sorted(mine)
        n_late = sum(1 for r in rows if r['state'] == 'late')
        n_bulk = sum(1 for r in rows if r['bulk'])
        missed = sum(1 for r in rows if r['state'] == 'gap')
        working_due = [s for s in upto if s in work]
        if not checked:
            status = ('none', 'No checks') if working_due else ('off', 'Nothing due yet' if work else 'No activity')
        elif n_late * 4 >= len(checked) and n_late:
            status = ('late', 'Often late')
        elif missed:
            status = ('gaps', 'Some missed')
        else:
            status = ('good', 'Checking well')
        s = (sheet or {}).get(u.id) or {}
        people.append({'user': u, 'status': status[0], 'label': status[1], 'strip': strip_,
                       'rows': sorted(rows, key=lambda r: r['slot'], reverse=True),
                       'checked': len(checked), 'ticks': sum(len(v) for v in mine.values()), 'late': n_late,
                       'bulk': n_bulk, 'missed': missed, 'working_due': len(working_due),
                       'start': ist_hm(s.get('first')), 'end': ist_hm(s.get('last'))})
    order = {'none': 0, 'gaps': 1, 'late': 2, 'good': 3, 'off': 4}
    people.sort(key=lambda p: (order[p['status']], p['user'].full_name.lower()))

    gaps = []
    for s in sorted(upto, reverse=True):
        if s in full:
            continue
        missing = [ch for ch in channels if (s, ch) not in at]
        gaps.append({'slot': s, 'when': '%s–%s' % (slot_label(s), slot_label(s + 1)), 'missing': missing,
                     'none': len(missing) == len(channels),
                     'ticked': [{'channel': ch, 'who': who(at[(s, ch)]), 'at': ist_hm(at[(s, ch)].checked_at)}
                                for ch in channels if (s, ch) in at],
                     'working': [u.full_name for u in users if s in windows[u.id]]})
    done = [s for s in upto if s in full]
    return {'due': len(upto), 'full': len(done), 'pct': round(100 * len(done) / len(upto)) if upto else None,
            'gap_count': len(gaps), 'late': sum(p['late'] for p in people),
            'checking': sum(1 for p in people if p['checked']), 'people': people, 'gaps': gaps,
            'hours': [slot_label(s)[:2] for s in every if s % 2 == 0],
            'inboxes': [{'channel': ch, 'due': len(upto), 'done': sum(1 for s in upto if (s, ch) in at)}
                        for ch in channels]}


def leads_by_inbox(day, rows):
    """{inbox name: leads that came in on `day` (India) from the lead source the inbox watches} -- two inboxes on
    one source (Messenger and Instagram on Meta) both say that source's number."""
    from app.models import CrmSource
    from app.services import crm_sources
    keys = {r['name']: crm_sources.canonical(r['source_key']) for r in rows if r.get('source_key')}
    if not keys:
        return {}
    ids = {s.key: s.id for s in CrmSource.query.filter(CrmSource.key.in_(set(keys.values()))).all()}
    start, end = day_bounds(day)
    counts = dict(db.session.query(CrmLead.source_id, func.count(CrmLead.id))
                  .filter(CrmLead.created_at >= start, CrmLead.created_at < end,
                          CrmLead.source_id.in_(list(ids.values()) or [0]))
                  .group_by(CrmLead.source_id).all())
    return {name: counts.get(ids.get(key), 0) for name, key in keys.items()}


def last_ticks(ticks, channels):
    """{inbox: its latest tick of the day} from grid(day)."""
    out = {}
    for (s, ch), c in ticks.items():
        if ch in channels and (ch not in out or (c.checked_at or datetime.min) > (out[ch].checked_at or datetime.min)):
            out[ch] = c
    return out


def longest_gap(day, channels, ticks=None):
    """The longest run of half hours over on `day` that were not fully checked: (first label, last label, how many)
    or None."""
    ticks = grid(day) if ticks is None else ticks
    best, run = None, []
    for s in slots_so_far(day) + [None]:
        if s is not None and not all((s, ch) in ticks for ch in channels):
            run.append(s)
            continue
        if run and (best is None or len(run) > best[2]):
            best = (slot_label(run[0]), slot_label(run[-1] + 1), len(run))
        run = []
    return best


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
