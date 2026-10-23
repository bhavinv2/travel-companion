"""Team analysis (Overview › All reports › Team analysis): compare the sales people over any period, side by
side -- their half-hourly inbox checks, the hours they worked, their follow-ups, messages and calls, how fast
they answer, and what they won.

    PERIODS      the choices above the page: today, yesterday, the last 7 or 30 days, this month, custom dates
    period()     those choices as India days
    working()    {user id: {India day: (first, last)}}: each person's first and last action in the CRM that day
    checks()     the half-hourly check over the days: per person and day, per day for the team, per half hour of
                 the day (when it is missed), per inbox
    analysis()   everything the page shows, for the people it may show

The work and results come from crm_numbers -- one definition each, the same as Sales results and the Report
builder; the checks from CrmChannelCheck, the way the Half-hourly check and Team today count them.
"""
from collections import defaultdict
from datetime import datetime, timedelta

from app.models import CrmChannelCheck, CrmLead, CrmStageChange, CrmTask, CrmTouchpoint
from app.services import crm_numbers, crm_reports

IST = crm_reports.IST
PERIODS = (('today', 'Today'), ('yesterday', 'Yesterday'), ('7d', 'Last 7 days'), ('30d', 'Last 30 days'),
           ('month', 'This month'), ('custom', 'Custom'))
MAX_DAYS = 92                       # a custom period is cut to its last three months

# The scorecard, in the order it reads: (key, label, unit, better, where from). `better`: which way is good
# ('high' / 'low'), or None when neither is (follow-ups due, Tick all). `unit`: count, percent, minutes, money,
# time (a time of day), hours.
GROUPS = (
    ('Inbox checks', 'fa-clipboard-check', (
        ('chk_slots', 'Half hours checked', 'count', 'high'),
        ('chk_days', 'Days with checks', 'count', 'high'),
        ('chk_late', 'Half hours checked late', 'count', 'low'),
        ('chk_bulk', 'Tick all presses', 'count', None),
        ('chk_first', 'First check of the day', 'time', None),
    )),
    ('Time', 'fa-clock', (
        ('days_active', 'Days active', 'count', 'high'),
        ('start_avg', 'Starts, on average', 'time', None),
        ('end_avg', 'Ends, on average', 'time', None),
        ('hours_avg', 'Hours a day, on average', 'hours', 'high'),
    )),
    ('Follow-ups and messages', 'fa-list-check', (
        ('followups_due', 'Follow-ups due', 'count', None),
        ('followups_done', 'Follow-ups done', 'count', 'high'),
        ('done_rate', 'Done of due', 'percent', 'high'),
        ('messages_by_agent', 'Messages sent', 'count', 'high'),
        ('calls', 'Calls', 'count', 'high'),
        ('calls_connected', 'Calls answered', 'count', 'high'),
        ('moves', 'Leads moved on', 'count', 'high'),
        ('leads_added', 'Leads they added', 'count', 'high'),
    )),
    ('Speed', 'fa-stopwatch', (
        ('first_contact_minutes', 'First contact time', 'minutes', 'low'),
        ('reply_minutes', 'Reply time', 'minutes', 'low'),
        ('unanswered', 'Left unanswered at day end', 'count', 'low'),
    )),
    ('Results', 'fa-trophy', (
        ('new_leads', 'New leads given', 'count', None),
        ('quoted', 'Quotes sent', 'count', 'high'),
        ('won', 'Won', 'count', 'high'),
        ('won_value', 'Won value', 'money', 'high'),
        ('lost', 'Lost', 'count', None),
    )),
    ('Right now', 'fa-bolt', (
        ('open_leads', 'Open leads', 'count', None),
        ('late_followups', 'Late follow-ups', 'count', 'low'),
        ('waiting_now', 'Customers waiting now', 'count', 'low'),
    )),
)
ROWS = [r for _g, _i, rows in GROUPS for r in rows]
# what this page works out itself, said once (the rest read crm_numbers' definitions)
OWN_TIPS = {
    'chk_slots': 'Half hours they ticked at least one inbox on the half-hourly check.',
    'chk_days': 'Days they ticked the half-hourly check at least once.',
    'chk_late': 'Half hours they only started ticking after the half hour was over.',
    'chk_bulk': 'Times they ticked three or more inboxes in one press, within a few seconds ("Tick all").',
    'chk_first': 'Their first tick of the day, on average over the days they checked (India time).',
    'days_active': 'Days with any action of theirs in the Sales CRM: a message, call, note, move, follow-up or check.',
    'start_avg': 'Their first action of the day, on average over the days they were active (India time).',
    'end_avg': 'Their last action of the day, on average over the days they were active (India time).',
    'hours_avg': 'From their first to their last action of the day, on average over the days they were active.',
    'done_rate': 'Follow-ups done, of those due in these days.',
    'new_leads': 'Leads that came in during these days and are looked after by them.',
}
EVENT_KEYS = ['followups_due', 'followups_done', 'messages_by_agent', 'calls', 'calls_connected', 'moves',
              'leads_added', 'new_leads', 'quoted', 'won', 'won_value', 'lost']
STATE_KEYS = ['first_contact_minutes', 'reply_minutes', 'unanswered', 'open_leads', 'late_followups', 'waiting_now']
# what "Day by day" can show, one at a time: (key, label)
DAILY = (('chk_slots', 'Half hours checked'), ('hours', 'Hours worked'), ('followups_done', 'Follow-ups done'),
         ('messages_by_agent', 'Messages sent'), ('calls', 'Calls'), ('moves', 'Leads moved on'),
         ('leads_added', 'Leads they added'), ('won', 'Won'))


def tip(key):
    return OWN_TIPS.get(key) or crm_numbers.definition(key)


# ============================================================================================ the period

def period(key=None, start=None, end=None, today=None):
    """{'key', 'label', 'first', 'last', 'days', 'since', 'until'} -- India days `first`..`last` (never past today)
    and their UTC bounds [since, until)."""
    today = today or crm_reports.current()[0]
    one = timedelta(days=1)
    if key == 'yesterday':
        first = last = today - one
    elif key == '7d':
        first, last = today - 6 * one, today
    elif key == '30d':
        first, last = today - 29 * one, today
    elif key == 'month':
        first, last = today.replace(day=1), today
    elif key == 'custom' and start:
        first, last = start, min(end or start, today)
        if last < first:
            first, last = last, first
        first = max(first, last - (MAX_DAYS - 1) * one)
    else:
        key, first, last = 'today', today, today
    days = [first + i * one for i in range((last - first).days + 1)]
    names = dict(PERIODS)
    label = names[key] if key not in ('custom',) else (
        first.strftime('%d %b %Y') if first == last else '%s – %s' % (first.strftime('%d %b'), last.strftime('%d %b %Y')))
    return {'key': key, 'label': label, 'first': first, 'last': last, 'days': days,
            'since': crm_numbers.day_bounds(first)[0], 'until': crm_numbers.day_bounds(last)[1]}


def parse_day(text):
    try:
        return datetime.strptime(text or '', '%Y-%m-%d').date()
    except ValueError:
        return None


# ============================================================================================ when they worked

def working(since, until, ids):
    """{user id: {India day: [first, last]}} (UTC moments): their first and last action each day -- a message,
    call or note, a lead moved or added, a follow-up done, a tick of the check (as Team today counts them). A tick
    belongs to the day of its half hour, even when it came after midnight."""
    out = defaultdict(dict)
    ids = list(ids)
    if not ids:
        return out

    def add(uid, when, d=None):
        if uid is None or when is None:
            return
        d = d or (when + IST).date()
        cur = out[uid].get(d)
        out[uid][d] = [when, when] if cur is None else [min(cur[0], when), max(cur[1], when)]
    T, S, L, C, K = CrmTouchpoint, CrmStageChange, CrmLead, CrmChannelCheck, CrmTask
    for uid, when in T.query.with_entities(T.agent_id, T.created_at).filter(
            T.agent_id.in_(ids), T.direction.in_(('out', 'none')), T.created_at >= since, T.created_at < until):
        add(uid, when)
    for uid, when in S.query.with_entities(S.by_id, S.created_at).filter(
            S.by_id.in_(ids), S.from_stage_id.isnot(None), S.created_at >= since, S.created_at < until):
        add(uid, when)
    for uid, when in L.query.with_entities(L.created_by_id, L.created_at).filter(
            L.created_by_id.in_(ids), L.created_at >= since, L.created_at < until):
        add(uid, when)
    first, last = (since + IST).date(), (until - timedelta(seconds=1) + IST).date()
    for uid, when, d in C.query.with_entities(C.user_id, C.checked_at, C.day).filter(
            C.user_id.in_(ids), C.day >= first, C.day <= last):
        add(uid, when, d)
    for done_by, owner, when in K.query.with_entities(K.done_by_id, K.owner_id, K.done_at).filter(
            K.status == 'done', K.done_at >= since, K.done_at < until,
            K.done_by_id.in_(ids) | (K.done_by_id.is_(None) & K.owner_id.in_(ids))):
        add(done_by or owner, when)
    return out


def _clock(minutes):
    """Minutes after midnight (India) -> '09:05'."""
    if minutes is None:
        return None
    minutes = int(round(minutes)) % (24 * 60)
    return '%02d:%02d' % (minutes // 60, minutes % 60)


def _minute_of(when, day):
    """Minutes from the start of India day `day` to `when` -- past 1440 after midnight, so times average right."""
    return ((when + IST) - datetime.combine(day, datetime.min.time())).total_seconds() / 60


# ============================================================================================ the inbox check

def checks(days, ids, channels):
    """The half-hourly check over `days`:
        person  {user id: {day: {'slots', 'late', 'bulk', 'first'}}}  half hours they ticked, of those late
                (they only started after it was over), "Tick all" presses, their first tick (UTC)
        team    [{'day', 'due', 'full', 'pct'}]  each day's half hours over, and fully checked (every inbox, by
                anybody, or by itself)
        by_slot [{'slot', 'label', 'due', 'full', 'pct'}]  each half hour of the day: on how many of the days it
                was fully checked -- where the gaps fall
        inboxes [{'channel', 'due', 'done'}]"""
    from app.services import crm
    ids = set(ids)
    at = defaultdict(dict)                                       # (day, slot) -> {inbox: tick}
    mine = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))     # uid -> day -> slot -> [ticks]
    for c in CrmChannelCheck.query.filter(CrmChannelCheck.day >= days[0], CrmChannelCheck.day <= days[-1]).all():
        ch = crm.CHECK_RENAMED.get(c.channel, c.channel)
        if ch not in channels:
            continue
        at[(c.day, c.slot)][ch] = c
        if c.user_id in ids:
            mine[c.user_id][c.day][c.slot].append(c)
    person = {}
    for uid, by_day in mine.items():
        person[uid] = {}
        for d, by_slot in by_day.items():
            late = bulk = 0
            first = None
            for s, ticks in by_slot.items():
                times = sorted(t.checked_at for t in ticks if t.checked_at)
                if times and times[0] > crm_reports.slot_end(d, s):
                    late += 1
                if len(times) >= 3 and (times[-1] - times[0]).total_seconds() <= crm_reports.BULK_SECONDS:
                    bulk += 1
                if times and (first is None or times[0] < first):
                    first = times[0]
            person[uid][d] = {'slots': len(by_slot), 'late': late, 'bulk': bulk, 'first': first}
    every = crm_reports.slots()
    team, slot_due, slot_full, inbox_done, due_total = [], defaultdict(int), defaultdict(int), defaultdict(int), 0
    for d in days:
        over = crm_reports.slots_so_far(d)
        full = 0
        for s in over:
            ticked = at.get((d, s), {})
            slot_due[s] += 1
            if channels and all(ch in ticked for ch in channels):
                full += 1
                slot_full[s] += 1
            for ch in ticked:
                inbox_done[ch] += 1
        due_total += len(over)
        team.append({'day': d, 'due': len(over), 'full': full, 'pct': round(100 * full / len(over)) if over else None})
    by_slot = [{'slot': s, 'label': crm_reports.slot_label(s), 'until': crm_reports.slot_label(s + 1),
                'due': slot_due[s], 'full': slot_full[s],
                'pct': round(100 * slot_full[s] / slot_due[s]) if slot_due[s] else None} for s in every]
    return {'person': person, 'team': team, 'by_slot': by_slot,
            'inboxes': [{'channel': ch, 'due': due_total, 'done': inbox_done[ch]} for ch in channels]}


# ============================================================================================ the page

def analysis(per, users, channels, now=None):
    """Everything Team analysis shows for `per` (period()) and `users` (who the viewer may see):
        people   [{'user', 'values': {row key: value}, 'daily': {daily key: {day: n}}}]
        team     the same for all of them together (counts added up; times and medians left out)
        daily_json  the day-by-day numbers for the page's script (days as text)
        checks   checks(), for the inbox-check tab
        day      check_report() of the one day, when the period is one day (the half-hour strips)"""
    ids = [u.id for u in users]
    since, until, days = per['since'], per['until'], per['days']
    scope = crm_numbers.scope(owner_ids=ids)
    ev = {k: crm_numbers.by_owner(k, since, until, scope) for k in EVENT_KEYS} if ids else {}
    st = {k: crm_numbers.by_owner(k, since, until, scope) for k in STATE_KEYS} if ids else {}
    daily = crm_numbers.daily_by_owner([k for k, _ in DAILY if k in crm_numbers.METRICS], since, until,
                                       user_ids=ids, now=now) if ids else {}
    chk = checks(days, ids, channels)
    work = working(since, until, ids)
    people = []
    for u in users:
        v = {}
        mine = chk['person'].get(u.id, {})
        v['chk_slots'] = sum(x['slots'] for x in mine.values())
        v['chk_days'] = sum(1 for x in mine.values() if x['slots'])
        v['chk_late'] = sum(x['late'] for x in mine.values())
        v['chk_bulk'] = sum(x['bulk'] for x in mine.values())
        firsts = [_minute_of(x['first'], d) for d, x in mine.items() if x['first']]
        v['chk_first'] = _clock(sum(firsts) / len(firsts)) if firsts else None
        spans = work.get(u.id, {})
        v['days_active'] = len(spans)
        if spans:
            v['start_avg'] = _clock(sum(_minute_of(a, d) for d, (a, _b) in spans.items()) / len(spans))
            v['end_avg'] = _clock(sum(_minute_of(b, d) for d, (_a, b) in spans.items()) / len(spans))
            v['hours_avg'] = round(sum((b - a).total_seconds() for a, b in spans.values()) / 3600 / len(spans), 1)
        else:
            v['start_avg'] = v['end_avg'] = v['hours_avg'] = None
        for k in EVENT_KEYS:
            v[k] = ev[k].get(u.id, 0) or 0
        for k in STATE_KEYS:
            v[k] = st[k].get(u.id)
        due, done = v['followups_due'], v['followups_done']
        v['done_rate'] = round(100 * min(done, due) / due) if due else None
        by_day = {}
        for k, _label in DAILY:
            if k == 'chk_slots':
                by_day[k] = {d: x['slots'] for d, x in mine.items() if x['slots']}
            elif k == 'hours':
                by_day[k] = {d: round((b - a).total_seconds() / 3600, 1) for d, (a, b) in spans.items()}
            else:
                by_day[k] = {d: n.get(k) for d, n in daily.get(u.id, {}).items() if n.get(k)}
        people.append({'user': u, 'values': v, 'daily': by_day})
    team = {}
    for key, _label, unit, _better in ROWS:
        if unit in ('count', 'money'):
            team[key] = sum((p['values'][key] or 0) for p in people)
    due = team.get('followups_due') or 0
    team['done_rate'] = round(100 * min(team.get('followups_done', 0), due) / due) if due else None
    daily_json = {'days': [d.isoformat() for d in days],
                  'people': [{'id': p['user'].id, 'name': p['user'].full_name,
                              'daily': {k: {d.isoformat(): float(n) for d, n in by.items()} for k, by in p['daily'].items()}}
                             for p in people]}
    return {'people': people, 'team': team, 'checks': chk, 'daily_json': daily_json,
            'day': crm_reports.check_report(days[0], users, channels, sheet=crm_reports.day_sheet(days[0], users))
            if len(days) == 1 else None}


def csv_rows(result):
    """The scorecard as rows for a download: a header, then one row per person."""
    head = ['Person'] + [label for _k, label, _u, _b in ROWS]
    rows = [head]
    for p in result['people']:
        rows.append([p['user'].full_name] + ['' if p['values'].get(k) is None else str(p['values'][k])
                                             for k, _l, _u, _b in ROWS])
    return rows
