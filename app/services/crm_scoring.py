"""Lead scoring (Sales CRM 2.0, run 5b): Set-up > Pipelines & products > Scoring.

Each workspace has its scoring lines (crm_score_rules): a SIGNAL and the points it is worth -- "They replied +20",
"Trip within 14 days +20", "No reply for 7 days -20". A lead's score is the sum of the lines it meets (0 to 100), and
its rating ("Ready to buy?") follows the score: hot at HOT or more, warm at WARM or more, else cold -- unless a person
picked the rating (CrmLead.likelihood_manual): then the score never changes it.

OFF until an admin presses "Turn scoring on" (setting `crm.scoring`, kept per workspace inside the one setting).
While off nothing is scored and no rating changes. A starter set of lines is written the first time the tab is
opened, so there is something to switch on.

The signals "replied", "quote sent" and "payment link sent" are the numbers registry's own (crm_numbers.leads_replied /
leads_marked): a lead scores "quote sent" exactly when Quotes sent counts it.

When: after a save that touched the lead (a message, a stage move, a changed value or detail, a new lead -- noted in
the save, worked out after the commit by crm_rules._after_commit), and nightly for every open lead (the jobs runner),
because "trip within N days" and "no reply for N days" change with the calendar.
"""
from collections import OrderedDict
from datetime import datetime, timedelta

from app import db
from app.models import CRM_LIKELIHOOD, CrmLead, CrmScoreRule

IST = timedelta(hours=5, minutes=30)
SETTING = 'crm.scoring'
DUE = 'crm_score_due'
HOT, WARM = 60, 30
BATCH = 500
NIGHT_LIMIT = 5000

SIGNALS = OrderedDict([
    ('replied', 'They replied'),
    ('quote_sent', 'A quote was sent'),
    ('payment_link_sent', 'A payment link was sent'),
    ('trip_within_days', 'The trip is within some days'),
    ('no_reply_days', 'No reply from them for some days'),
    ('has_value', 'It has a value'),
    ('source_is', 'It came from a lead source'),
    ('field_is', 'A detail is'),
])
DAY_SIGNALS = ('trip_within_days', 'no_reply_days')
FIELD_CHOICES = OrderedDict([('product', 'Product'), ('country', 'Country')])
STARTER = (
    ('They replied', 20, 'replied', None),
    ('A quote was sent', 25, 'quote_sent', None),
    ('A payment link was sent', 30, 'payment_link_sent', None),
    ('The trip is within 14 days', 20, 'trip_within_days', {'days': 14}),
    ('It has a value', 10, 'has_value', None),
    ('No reply for 7 days', -20, 'no_reply_days', {'days': 7}),
)
# the fields a save changes that move a score (the history listener tells us; a changed rating does not)
WATCHED = ('amount', 'details', 'departure_date', 'product', 'pipeline_id', 'stage_id', 'status')


# ============================================================================================ the switch

def _key(wid=None):
    from app.services import crm_scope
    wid = wid if wid is not None else crm_scope.stamp_id()
    return str(wid) if wid is not None else 'default'


def _all():
    from app.services import settings
    v = settings.get_setting(SETTING) or {}
    return v if isinstance(v, dict) else {}


def state(wid=None):
    """{'on', 'hot', 'warm', 'seeded', 'day'} for a workspace (the current one by default)."""
    from app.services import crm_scope
    raw = _all().get('workspaces') or {}
    got = raw.get(_key(wid))
    if got is None and crm_scope.is_default(wid if wid is not None else crm_scope.stamp_id()):
        got = raw.get('default')
    got = dict(got or {})
    return {'on': bool(got.get('on')), 'hot': int(got.get('hot') or HOT), 'warm': int(got.get('warm') or WARM),
            'seeded': bool(got.get('seeded')), 'day': got.get('day')}


def save_state(wid=None, actor=None, **changes):
    from app.services import settings
    whole = dict(_all())
    ws = dict(whole.get('workspaces') or {})
    cur = dict(ws.get(_key(wid)) or {})
    cur.update(changes)
    ws[_key(wid)] = cur
    whole['workspaces'] = ws
    settings.set_setting(SETTING, whole, actor)           # commits


def is_on(wid=None):
    return state(wid)['on']


def thresholds(hot, warm):
    """(hot, warm) from the form, or ValueError with the words."""
    try:
        hot, warm = int(str(hot).strip()), int(str(warm).strip())
    except (TypeError, ValueError):
        raise ValueError('Type the scores as whole numbers.')
    if not 0 < warm < hot <= 100:
        raise ValueError('“Thinking about it” must start below “Ready to buy”, and both between 1 and 100.')
    return hot, warm


# ============================================================================================ the lines

def lines(active_only=False):
    q = CrmScoreRule.query
    if active_only:
        q = q.filter(CrmScoreRule.active.is_(True))
    return q.order_by(CrmScoreRule.position, CrmScoreRule.id).all()


def ensure_starter(wid=None):
    """The first time: the starter lines for this workspace (scoring stays off). True when it wrote them."""
    if state(wid)['seeded']:
        return False
    if not CrmScoreRule.query.first():
        for n, (name, points, signal, args) in enumerate(STARTER):
            db.session.add(CrmScoreRule(name=name, points=points, signal=signal, args=args, active=True, position=n,
                                        created_at=datetime.utcnow()))
        db.session.flush()
    save_state(wid, seeded=True)                          # commits the lines too
    return True


def clean_line(form):
    """(dict, error) for one line from the Scoring tab's form."""
    from app.models import CrmSource
    name = ' '.join(str(form.get('name') or '').split())[:120]
    signal = str(form.get('signal') or '')
    if signal not in SIGNALS:
        return None, 'Choose what the line looks for.'
    try:
        points = int(str(form.get('points') or '').strip())
    except ValueError:
        return None, 'Type the points as a whole number, like 20 or -10.'
    if not -100 <= points <= 100 or points == 0:
        return None, 'Points go from -100 to 100 (not 0).'
    args = None
    if signal in DAY_SIGNALS:
        try:
            days = int(str(form.get('days') or '').strip())
        except ValueError:
            days = 0
        if not 1 <= days <= 365:
            return None, 'Say how many days (1 to 365).'
        args = {'days': days}
    elif signal == 'source_is':
        sid = str(form.get('source_id') or '')
        if not sid.isdigit() or CrmSource.query.filter_by(id=int(sid)).first() is None:
            return None, 'Choose a lead source.'
        args = {'source_id': int(sid)}
    elif signal == 'field_is':
        field = str(form.get('field') or '')
        value = ' '.join(str(form.get('value') or '').split())[:80]
        if field not in FIELD_CHOICES and not (field.startswith('details.') and len(field) > 8):
            return None, 'Choose which detail.'
        if not value:
            return None, 'Type what the detail should be.'
        args = {'field': field, 'value': value}
    if not name:
        name = SIGNALS[signal]
    return {'name': name, 'points': points, 'signal': signal, 'args': args,
            'active': str(form.get('active') or '') in ('1', 'on', 'true')}, None


def describe_line(line):
    a = line.args or {}
    if line.signal == 'trip_within_days':
        return 'The trip is within %s days' % a.get('days')
    if line.signal == 'no_reply_days':
        return 'No reply from them for %s days' % a.get('days')
    if line.signal == 'source_is':
        from app.models import CrmSource
        s = db.session.get(CrmSource, int(a.get('source_id') or 0))
        return 'It came from “%s”' % (s.name if s else 'a removed source')
    if line.signal == 'field_is':
        return '%s is “%s”' % (FIELD_CHOICES.get(a.get('field')) or str(a.get('field') or '')[8:].replace('_', ' ')
                               .capitalize(), a.get('value'))
    return SIGNALS.get(line.signal, line.signal)


# ============================================================================================ the score

def _field(lead, field):
    if field == 'product':
        return lead.product
    if field == 'country':
        return lead.person.country if lead.person is not None else None
    if field.startswith('details.'):
        return (lead.details or {}).get(field[8:])
    return None


def compute(leads, rules=None, now=None):
    """{lead id: (score 0-100, [(words, points)])} for `leads`, with the lines `rules` (the current workspace's
    switched-on lines by default). A fixed number of queries for the lot."""
    from app.services import crm_numbers
    now = now or datetime.utcnow()
    today = (now + IST).date()
    rules = rules if rules is not None else lines(active_only=True)
    leads = [l for l in leads if l is not None and l.id is not None]
    if not leads:
        return {}
    ids = [l.id for l in leads]
    need = {r.signal for r in rules}
    replied = crm_numbers.leads_replied(ids) if 'replied' in need else set()
    last = crm_numbers.last_replies(ids) if 'no_reply_days' in need else {}
    quoted = crm_numbers.leads_marked('Q', ids) if 'quote_sent' in need else set()
    linked = crm_numbers.leads_marked('PLS', ids) if 'payment_link_sent' in need else set()
    out = {}
    for lead in leads:
        parts = []
        for r in rules:
            a = r.args or {}
            hit, words = False, r.name
            if r.signal == 'replied':
                hit = lead.id in replied
            elif r.signal == 'quote_sent':
                hit = lead.id in quoted
            elif r.signal == 'payment_link_sent':
                hit = lead.id in linked
            elif r.signal == 'trip_within_days':
                if lead.departure_date is not None:
                    d = (lead.departure_date - today).days
                    hit = 0 <= d <= int(a.get('days') or 0)
                    words = 'trip in %d day%s' % (d, '' if d == 1 else 's') if d else 'trip today'
            elif r.signal == 'no_reply_days':
                days = int(a.get('days') or 0)
                since = now - timedelta(days=days)
                seen = last.get(lead.id)
                hit = bool(lead.created_at and lead.created_at <= since and (seen is None or seen <= since))
            elif r.signal == 'has_value':
                hit = lead.amount is not None and lead.amount > 0
            elif r.signal == 'source_is':
                hit = lead.source_id is not None and lead.source_id == a.get('source_id')
            elif r.signal == 'field_is':
                have = _field(lead, str(a.get('field') or ''))
                hit = have is not None and str(have).strip().lower() == str(a.get('value') or '').strip().lower()
            if hit:
                parts.append((words, int(r.points or 0)))
        score = max(0, min(100, sum(p for _, p in parts)))
        out[lead.id] = (score, parts)
    return out


def rating_for(score, hot=HOT, warm=WARM):
    return 'hot' if score >= hot else 'warm' if score >= warm else 'cold'


def apply(lead, score, st):
    """Store the score; the rating follows it unless a person picked it. Returns True when something changed."""
    changed = lead.score != score
    lead.score = score
    if lead.status == 'open' and not lead.likelihood_manual:
        want = rating_for(score, st['hot'], st['warm'])
        if lead.likelihood != want:
            lead.likelihood = want
            changed = True
    return changed


def breakdown(lead):
    """For the lead page: (score, 'They replied +20 · trip in 9 days +20 ...') with the lines as they are now, or
    None while scoring is off."""
    if not is_on():
        return None
    got = compute([lead]).get(lead.id)
    if got is None:
        return None
    score, parts = got
    text = ' · '.join('%s %s%d' % (w, '+' if p > 0 else '−', abs(p)) for w, p in parts)
    return {'score': score, 'parts': parts, 'text': text}


def recalc(leads, now=None, wid=None):
    """Score these leads (of ONE workspace, the current one) and let their rating follow. No commit. How many
    changed."""
    st = state(wid)
    if not st['on']:
        return 0
    rules = lines(active_only=True)
    got = compute(leads, rules, now)
    n = 0
    for lead in leads:
        if lead.id in got and apply(lead, got[lead.id][0], st):
            n += 1
    return n


def recalc_all(now=None, limit=NIGHT_LIMIT):
    """Every open lead of the current workspace, in batches (Turn scoring on, the nightly run). Commits."""
    if not is_on():
        return 0
    n, last_id = 0, 0
    done = 0
    while done < limit:
        batch = (CrmLead.query.filter(CrmLead.status == 'open', CrmLead.id > last_id)
                 .order_by(CrmLead.id).limit(BATCH).all())
        if not batch:
            break
        n += recalc(batch, now)
        last_id = batch[-1].id
        done += len(batch)
        db.session.commit()
    return n


def nightly(now=None):
    """The jobs runner, per workspace: once a day (India), every open lead again -- the days move."""
    if not is_on():
        return {}
    now = now or datetime.utcnow()
    today = (now + IST).date().isoformat()
    if state()['day'] == today:
        return {}
    n = recalc_all(now)
    save_state(day=today)
    return {'crm_scores_changed': n}


# ============================================================================================ after a save

def touched(lead):
    """Inside a save: this lead's score may change (worked out after the commit). No query."""
    if lead is None or getattr(lead, 'id', None) is None:
        return
    from sqlalchemy.orm import object_session
    sess = object_session(lead) or db.session()
    sess.info.setdefault(DUE, set()).add(lead.id)


def field_changes(sess, rows):
    """From the history listener: leads whose watched fields changed in this flush."""
    ids = {r['record_id'] for r in rows if r.get('record_type') == 'lead' and r.get('field') in WATCHED}
    if ids:
        sess.info.setdefault(DUE, set()).update(ids)


def recalc_due(ids):
    """After the commit (crm_rules._after_commit, in a session of its own): score the leads a save touched, per
    workspace, where scoring is on. Commits when a score or a rating changed."""
    from app.services import crm_scope
    if not _all().get('workspaces'):
        return 0                                          # nobody ever opened scoring: nothing can be on
    leads = (CrmLead.query.execution_options(all_workspaces=True)
             .filter(CrmLead.id.in_(sorted(ids)), CrmLead.status == 'open').all())
    groups = {}
    for lead in leads:
        groups.setdefault(crm_scope.of(lead), []).append(lead)
    n = 0
    for wid, group in groups.items():
        with crm_scope.use(wid if crm_scope.several() else None):
            if not is_on(wid):
                continue
            n += recalc(group, wid=wid)
    if n:
        db.session.commit()
    return n


def rating_label(lead):
    return CRM_LIKELIHOOD.get(lead.likelihood, '')
