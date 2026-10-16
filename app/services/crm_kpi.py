"""The KPI tabs of "Sales Process 1.5" (KPI, HB KPI, AP KPI, HK KPI), kept by the portal.

Same rows, same day columns. Every number comes from one of three places, added together:

  auto      counted from what the team does in the CRM and on the site: leads in, stage moves,
            messages by code, posts, blogs, how fast the first message went out
  manual    what the CRM cannot see (Google reviews, website work...), entered by the person who
            did it in "Log today's work" (CrmActivity, source 'manual')
  import    the days already in the workbook (CrmActivity, source 'import'), so the history goes on

Leads and moves brought in from the past (CrmLead.imported, "Sales sheet:" moves, touchpoints with
status 'imported') are left out of the auto counts: their days are in the imported numbers already.

A day is a day in India. A person's numbers are what they did: leads they added or own, moves they
made (or that happened to their leads by themselves), messages they sent, posts and blogs they wrote.
"""
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from statistics import median

from app import db
from app.models import (CrmActivity, CrmLead, CrmPipeline, CrmSource, CrmStage, CrmStageChange,
                        CrmTouchpoint)

IST = timedelta(hours=5, minutes=30)

# (group, [(key, label, how, question, unit)]) -- the rows of the KPI tab, in its order. how: auto / manual;
# question and unit: what My day asks for a hand-entered row ("How many posts ...?", "posts")
GROUPS = [
    ('Lead source points', [
        ('src_fb', 'Facebook groups', 'auto', None, None),
        ('src_wa', 'WhatsApp groups', 'auto', None, None),
        ('src_tg', 'Telegram groups', 'manual',
         'How many posts did you share in Telegram groups today?', 'posts'),
        ('src_web', 'Internet', 'auto', None, None),
    ]),
    ('Leads', [
        ('cold', 'Cold leads', 'auto', None, None),
        ('cold_web', 'Cold leads from the website', 'auto', None, None),
        ('cold_to_prospect', 'Cold lead → prospect', 'auto', None, None),
        ('prospects', 'Prospects', 'auto', None, None),
        ('prospect_fallout', 'Prospect fallout', 'auto', None, None),
        ('prospect_to_pipeline', 'Prospect → pipeline', 'auto', None, None),
        ('pipeline', 'Pipeline', 'auto', None, None),
        ('pipeline_fallout', 'Pipeline fallout', 'auto', None, None),
        ('customers', 'Pipeline → customer', 'auto', None, None),
        ('upsell', 'Customer upsell', 'auto', None, None),
        ('quotes_sent', 'Quotes sent', 'auto', None, None),
        ('payment_links_sent', 'Payment links sent', 'auto', None, None),
    ]),
    ('Messages sent', [
        ('msg_total', 'All messages', 'auto', None, None),
        ('msg_prospect', 'To cold leads and prospects', 'auto', None, None),
        ('msg_ce', 'Customer engagement', 'auto', None, None),
        ('msg_prospect_fallout', 'Prospect fallout', 'auto', None, None),
        ('msg_pi', 'Pipeline', 'auto', None, None),
        ('msg_pipeline_fallout', 'Pipeline fallout', 'auto', None, None),
        ('msg_bw', 'Birthday wishes', 'auto', None, None),
        ('msg_er', 'Expiration reminders', 'auto', None, None),
        ('msg_fm', 'Festival and occasion messages', 'auto', None, None),
        ('msg_mkt', 'WhatsApp marketing', 'auto', None, None),
    ]),
    ('Marketing', [
        ('blogs', 'Blogs published', 'auto', None, None),
        ('tc_posts', 'Travel companion leads', 'auto', None, None),
        ('ads_total', 'Total ads (trip posts)', 'auto', None, None),
        ('ads_users', 'Ads posted by users', 'auto', None, None),
        ('ads_self', 'Self ad posts (by the team)', 'auto', None, None),
        ('google_reviews', 'Google reviews', 'manual',
         'How many Google reviews did we get from your customers today?', 'reviews'),
        ('ti_site', 'Travel insurance site', 'manual',
         'How many updates did you make to the travel insurance site today?', 'updates'),
        ('response_time', 'Response time (hours to first message)', 'auto', None, None),
        ('wordpress', 'WordPress website', 'manual',
         'How many updates did you make to the WordPress website today?', 'updates'),
        ('nps', 'NRI Parent Service', 'manual',
         'How many posts did you make for NRI Parent Service today?', 'posts'),
        ('p360', 'P360', 'manual',
         'How many posts did you make for P360 today?', 'posts'),
    ]),
]
METRICS = {k: (label, how) for _, rows in GROUPS for k, label, how, _q, _u in rows}
QUESTIONS = {k: (q, u) for _, rows in GROUPS for k, _l, how, q, u in rows if how == 'manual'}
MANUAL = [k for k, (_, how) in METRICS.items() if how == 'manual']
AVERAGED = {'response_time'}             # a day's value is a median, the period's is their mean
WEBSITE_KINDS = ('form', 'popup', 'api')
CODE = re.compile(r'^[A-Z]+')


def ist_day(dt):
    return (dt + IST).date() if dt else None


def utc_bounds(first, last):
    """UTC datetimes covering India days first..last."""
    return datetime.combine(first, time(0)) - IST, datetime.combine(last + timedelta(days=1), time(0)) - IST


# ============================================================================================ stages

def stage_roles():
    """{stage id: cold / prospect / pipeline / customer / lost} for every pipeline: its first open
    stage is cold, the stage a reply moves to is prospect, open stages after it are pipeline."""
    out = {}
    for p in CrmPipeline.query.all():
        stages = sorted(p.stages, key=lambda s: s.position)
        opens = [s for s in stages if s.kind == 'open']
        reply = next((s for s in stages if s.on_reply), None)
        for s in stages:
            if s.kind == 'won':
                out[s.id] = 'customer'
            elif s.kind == 'lost':
                out[s.id] = 'lost'
            elif opens and s.id == opens[0].id:
                out[s.id] = 'cold'
            elif reply is not None and s.id == reply.id:
                out[s.id] = 'prospect'
            elif reply is not None and s.position < reply.position:
                out[s.id] = 'cold'
            else:
                out[s.id] = 'pipeline'
    return out


def _fallout_kind(stage_key, from_role):
    if from_role in ('cold', 'prospect') or 'prospect' in (stage_key or ''):
        return 'prospect'
    return 'pipeline'


# ============================================================================================ counting

def compute(first, last, user_id=None):
    """{metric: {day: value}} for India days first..last; one person's or (None) the team's."""
    since, until = utc_bounds(first, last)
    grid = defaultdict(lambda: defaultdict(float))
    roles = stage_roles()
    keys = {s.id: s.key for s in CrmStage.query.all()}

    def mine(*uids):
        return user_id is None or user_id in uids

    def add(metric, when, n=1):
        d = ist_day(when) if isinstance(when, datetime) else when
        if d and first <= d <= last:
            grid[metric][d] += n

    # ---- leads in
    rows = (db.session.query(CrmLead.id, CrmLead.created_at, CrmLead.created_by_id, CrmLead.owner_id,
                             CrmLead.product, CrmSource.kind)
            .outerjoin(CrmSource, CrmSource.id == CrmLead.source_id)
            .filter(CrmLead.created_at >= since, CrmLead.created_at < until, CrmLead.imported.is_(False)))
    for _, created, by, owner, product, kind in rows:
        if not mine(by or owner):
            continue
        add('cold', created)
        if kind in WEBSITE_KINDS:
            add('cold_web', created)
        if product == 'TC':
            add('tc_posts', created)

    # ---- stage moves
    won_before = defaultdict(list)       # person -> dates of earlier wins, for upsell
    for person_id, closed in (db.session.query(CrmLead.person_id, CrmLead.closed_at)
                              .filter(CrmLead.status == 'won', CrmLead.closed_at.isnot(None))):
        won_before[person_id].append(closed)
    q = (db.session.query(CrmStageChange.created_at, CrmStageChange.from_stage_id, CrmStageChange.to_stage_id,
                          CrmStageChange.by_id, CrmStageChange.reason, CrmLead.owner_id, CrmLead.imported,
                          CrmLead.person_id, CrmLead.id)
         .join(CrmLead, CrmLead.id == CrmStageChange.lead_id)
         .filter(CrmStageChange.created_at >= since, CrmStageChange.created_at < until,
                 CrmStageChange.from_stage_id.isnot(None)))
    for when, frm, to, by, reason, owner, imported, person_id, lead_id in q:
        if (reason or '').startswith('Sales sheet') or (imported and (reason or '').startswith('Came in')):
            continue
        if not mine(by or owner):
            continue
        fr, tr = roles.get(frm), roles.get(to)
        if tr == 'prospect':
            add('prospects', when)
            if fr == 'cold':
                add('cold_to_prospect', when)
        elif tr == 'pipeline' and fr != 'pipeline':
            add('pipeline', when)
            if fr == 'prospect':
                add('prospect_to_pipeline', when)
        elif tr == 'customer':
            add('customers', when)
            if any(c < when for c in won_before.get(person_id, [])):
                add('upsell', when)
        elif tr == 'lost':
            add('%s_fallout' % _fallout_kind(keys.get(to), fr), when)

    # ---- messages, by their code
    q = (db.session.query(CrmTouchpoint.created_at, CrmTouchpoint.code, CrmTouchpoint.agent_id,
                          CrmTouchpoint.channel, CrmLead.stage_id)
         .outerjoin(CrmLead, CrmLead.id == CrmTouchpoint.lead_id)
         .filter(CrmTouchpoint.direction == 'out', CrmTouchpoint.channel != 'call',
                 db.or_(CrmTouchpoint.status.is_(None), CrmTouchpoint.status != 'imported'),
                 CrmTouchpoint.created_at >= since, CrmTouchpoint.created_at < until))
    for when, code, agent, channel, stage_id in q:
        if not mine(agent) or code in ('Q', 'PLS'):
            continue                 # the lead page's milestone buttons have their own rows below
        add('msg_total', when)
        add(message_row(code, roles.get(stage_id), keys.get(stage_id)), when)

    # ---- the lead page's milestone buttons ("I sent the quote" / "I sent the payment link")
    for when, code, agent in (db.session.query(CrmTouchpoint.created_at, CrmTouchpoint.code, CrmTouchpoint.agent_id)
                              .filter(CrmTouchpoint.code.in_(('Q', 'PLS')),
                                      db.or_(CrmTouchpoint.status.is_(None), CrmTouchpoint.status != 'imported'),
                                      CrmTouchpoint.created_at >= since, CrmTouchpoint.created_at < until)):
        if mine(agent):
            add('quotes_sent' if code == 'Q' else 'payment_links_sent', when)

    # ---- trip posts and blogs
    from app.models import Blog, CompanionRequest
    for created, by, source in (db.session.query(CompanionRequest.created_at, CompanionRequest.created_by_id,
                                                  CompanionRequest.source)
                                .filter(CompanionRequest.created_at >= since, CompanionRequest.created_at < until)):
        if by is None:
            if user_id is None:
                add('ads_users', created)
                add('ads_total', created)
            continue
        if not mine(by):
            continue
        add('ads_self', created)
        add('ads_total', created)
        add({'facebook': 'src_fb', 'whatsapp': 'src_wa'}.get(source, 'src_web'), created)
    for published, author in (db.session.query(Blog.published_at, Blog.author_id)
                              .filter(Blog.is_published.is_(True), Blog.published_at >= since,
                                      Blog.published_at < until)):
        if mine(author):
            add('blogs', published)

    # ---- how fast the first message went out, per day the lead came in
    first_out = (db.session.query(CrmTouchpoint.lead_id, db.func.min(CrmTouchpoint.created_at).label('t'))
                 .filter(CrmTouchpoint.direction == 'out',
                         db.or_(CrmTouchpoint.status.is_(None), CrmTouchpoint.status != 'imported'))
                 .group_by(CrmTouchpoint.lead_id).subquery())
    waits = defaultdict(list)
    for created, owner, t in (db.session.query(CrmLead.created_at, CrmLead.owner_id, first_out.c.t)
                              .join(first_out, first_out.c.lead_id == CrmLead.id)
                              .filter(CrmLead.created_at >= since, CrmLead.created_at < until,
                                      CrmLead.imported.is_(False))):
        if mine(owner) and t and created:
            waits[ist_day(created)].append(max((t - created).total_seconds() / 3600, 0))
    for d, hours in waits.items():
        grid['response_time'][d] = round(median(hours), 1)

    # ---- entered by hand, and the workbook's own days
    q = CrmActivity.query.filter(CrmActivity.day >= first, CrmActivity.day <= last)
    if user_id is None:
        # the team: everybody's own entries, and the team KPI tab -- not the personal tabs again
        q = q.filter(db.or_(CrmActivity.source == 'manual', CrmActivity.user_id.is_(None)))
    else:
        q = q.filter(CrmActivity.user_id == user_id)
    for a in q:
        if a.metric in AVERAGED:
            grid[a.metric][a.day] = a.count if not grid[a.metric].get(a.day) else grid[a.metric][a.day]
        else:
            grid[a.metric][a.day] += a.count
    return grid


def message_row(code, role, stage_key):
    """Which "Messages sent" row a message counts on, from its code (or, without one, the stage)."""
    prefix = CODE.match(code or '')
    prefix = prefix.group(0) if prefix else ''
    fixed = {'TC': 'msg_prospect', 'TI': 'msg_prospect', 'CL': 'msg_prospect', 'GEN': 'msg_prospect',
             'PI': 'msg_pi', 'CE': 'msg_ce', 'SH': 'msg_ce', 'NR': 'msg_prospect',
             'BW': 'msg_bw', 'ER': 'msg_er', 'FM': 'msg_fm', 'OM': 'msg_fm', 'PM': 'msg_mkt'}
    if prefix in fixed:
        return fixed[prefix]
    if prefix == 'PF' or role == 'lost':
        return 'msg_%s_fallout' % _fallout_kind(stage_key, None if 'prospect' in (stage_key or '') else 'pipeline')
    return {'customer': 'msg_ce', 'pipeline': 'msg_pi'}.get(role, 'msg_prospect')


def table(first, last, user_id=None):
    """Rows ready to draw: [(group, [(key, label, how, [values by day], total)])], days oldest first."""
    grid = compute(first, last, user_id)
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    out = []
    for group, rows in GROUPS:
        lines = []
        for key, label, how, _q, _u in rows:
            vals = [grid[key].get(d) for d in days]
            nums = [v for v in vals if v]
            if key in AVERAGED:
                total = round(sum(nums) / len(nums), 1) if nums else None
            else:
                total = sum(nums)
            lines.append((key, label, how, vals, total))
        out.append((group, lines))
    return days, out


# ============================================================================================ entries

def question(key, day, today):
    """The question My day asks for a hand-entered row: as written for today, "... on 3 Oct?" for another day."""
    q = QUESTIONS[key][0]
    if day == today:
        return q
    return q.replace(' today?', ' on %d %s?' % (day.day, day.strftime('%b')))


def entries(day, user_id):
    return {a.metric: a.count for a in CrmActivity.query.filter_by(day=day, user_id=user_id, source='manual')}


def set_entry(day, user_id, metric, count):
    if metric not in METRICS:
        raise ValueError(metric)
    a = CrmActivity.query.filter_by(day=day, user_id=user_id, metric=metric, source='manual').first()
    if count in (None, 0):
        if a:
            db.session.delete(a)
    else:
        if a is None:
            a = CrmActivity(day=day, user_id=user_id, metric=metric, source='manual')
            db.session.add(a)
        a.count = float(count)
    db.session.commit()


# ============================================================================================ the workbook's KPI tabs

LABELS = {
    'fb (x)': 'src_fb', 'whatsapp (1)': 'src_wa', 'telegram (15)': 'src_tg', 'internet (4)': 'src_web',
    'cold leads': 'cold', 'cold leads website': 'cold_web', 'cold lead to prospects': 'cold_to_prospect',
    'prospects to pipeline': 'prospect_to_pipeline', 'pipeline to customers': 'customers',
    'customer upsell': 'upsell', 'communication messages sent': 'msg_total', 'customer engagement': 'msg_ce',
    'birthday wishes': 'msg_bw', 'exipration remainder': 'msg_er', 'expiration reminder': 'msg_er',
    'festival messages': 'msg_fm', 'whatsapp messages (mkt)': 'msg_mkt', 'blogs': 'blogs',
    'travel companion': 'tc_posts', 'total ads': 'ads_total', 'ads posted by users': 'ads_users',
    'self ad posts': 'ads_self', 'google reviews': 'google_reviews', 'trave insuranse site': 'ti_site',
    'travel insurance site': 'ti_site', 'response time': 'response_time', 'wordpress website': 'wordpress',
    'nri parent service': 'nps', 'p360': 'p360',
}
# the same words mean a funnel row before "Communication Messages sent" and a message row after it
TWICE = {'prospects': ('prospects', 'msg_prospect'), 'prospect fallout': ('prospect_fallout', 'msg_prospect_fallout'),
         'pipeline': ('pipeline', 'msg_pi'), 'pipeline fallout': ('pipeline_fallout', 'msg_pipeline_fallout')}


def read_kpi_rows(rows):
    """[(day, metric, count)] from one KPI tab given as row dicts ({column letter: text})."""
    from app.services.crm_import import excel_date
    dates, out, in_messages = {}, [], False
    for cells in rows:
        if not dates:
            if any((v or '').strip().lower() == 'totals' for v in cells.values()):
                dates = {c: excel_date(v) for c, v in cells.items() if excel_date(v)}
            continue
        label = re.sub(r'\s+', ' ', (cells.get('A') or '')).strip().lower()
        if label == 'communication messages sent':
            in_messages = True
        metric = LABELS.get(label) or (TWICE[label][1 if in_messages else 0] if label in TWICE else None)
        if not metric:
            continue
        for col, day in dates.items():
            try:
                n = float(cells.get(col) or 0)
            except ValueError:
                continue
            if n:
                out.append((day, metric, n))
    return out


def import_kpi(rows, user_id=None):
    """Replace the imported days of one tab (the team's, or one person's) with these."""
    CrmActivity.query.filter_by(user_id=user_id, source='import').delete(synchronize_session=False)
    for day, metric, n in rows:
        db.session.add(CrmActivity(day=day, user_id=user_id, metric=metric, count=n, source='import'))
    db.session.commit()
    return len(rows)
