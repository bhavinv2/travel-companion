"""The report builder (Sales CRM 2.0, run 4b): choose what to count, how to measure it, how to group it, and look at
a bar chart, a table and an Excel download.

SAFETY. A report is a small dict of choices (`config`). Every choice is checked against a fixed list in this file
(SOURCES, MEASURES, GROUPS, DATE_FIELDS, status words) or turned into a number or a date; nothing a person types is
ever put into a query. The query columns are fixed per source; "group by" is not SQL at all -- rows come back as
plain column values and are grouped here, by the functions in DIMENSIONS (which also gives India-time months and
the reporting-currency sums). Saved reports keep the same cleaned dict.

VISIBILITY. Leads, people and activities are limited with crm_access.lead_filter / person_filter written out in
every query (so a saved report, a pinned one on Sales results, or a download shows each viewer only what that viewer
may see), and removed (recycle bin) leads never count.

MONEY. Values are in the reporting currency (crm_money.to_base); a currency with no rate counts as 0 and is named
in a note, as on Forecast.
"""
from collections import OrderedDict, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, or_, select

from app import db
from app.models import (CRM_CHANNEL_LABELS, CRM_FORECASTS, CRM_LIKELIHOOD, CrmLead, CrmPerson, CrmPipeline,
                        CrmSavedReport, CrmSource, CrmStage, CrmTask, CrmTouchpoint, User, WorkspaceTeam)
from app.services import crm_access, crm_money

IST = timedelta(hours=5, minutes=30)
ROW_LIMIT = 100000
MAX_PER_USER = 40
NAME_MAX = 80

SOURCES = OrderedDict([('leads', 'Leads'), ('people', 'People'), ('activities', 'Activities (messages, calls and tasks)')])
MEASURES = OrderedDict([('count', 'Number of'), ('value', 'Total value'), ('revenue', 'Total our revenue'),
                        ('average', 'Average value')])
MONEY_MEASURES = ('value', 'revenue', 'average')
GROUPS = {
    'leads': OrderedDict([
        ('owner', 'Who looks after it'), ('team', 'Team'), ('stage', 'Stage'), ('phase', 'Phase'),
        ('pipeline', 'Pipeline'), ('product', 'Product'), ('source', 'Where it came from'),
        ('forecast', 'Counts in the forecast as'), ('rating', 'How likely it is'), ('country', 'Country'),
        ('lost_reason', 'Why it was lost'), ('created_month', 'Month it came in'),
        ('closed_month', 'Month it was won or lost'), ('close_month', 'Month it should close'),
        ('campaign', 'Campaign')]),
    'people': OrderedDict([('country', 'Country'), ('created_month', 'Month they were added'),
                           ('permission', 'WhatsApp permission'), ('offers', 'OK to send offers')]),
    'activities': OrderedDict([('owner', 'Who did it'), ('team', 'Team'), ('channel', 'Channel'),
                               ('created_month', 'Month'), ('pipeline', 'Pipeline')]),
}
DATE_FIELDS = {
    'leads': OrderedDict([('created', 'Came in'), ('closed', 'Was won or lost'), ('close_date', 'Should close')]),
    'people': OrderedDict([('created', 'Was added')]),
    'activities': OrderedDict([('created', 'Happened')]),
}
STATUSES = OrderedDict([('open', 'Still open'), ('won', 'Won'), ('lost', 'Lost')])
PHASE_WORDS = {'cold': 'New', 'prospect': 'Talking', 'pipeline': 'Quoted', 'customer': 'Won', 'lost': 'Lost'}
DEFAULT = {'what': 'leads', 'measure': 'count', 'group': 'owner', 'group2': '', 'date': 'created', 'from': '', 'to': '',
           'pipeline': '', 'owner': '', 'status': '', 'source': '', 'offers': ''}
# "OK to send offers" (run 5b): a filter on leads (their person's) and on people
OFFERS = OrderedDict([('yes', 'OK to send offers'), ('no', 'Not OK to send offers')])


class ReportError(ValueError):
    """A choice the report builder does not offer, phrased for the person."""


# ================================================================================================ the choices

def _int(v):
    v = str(v or '').strip()
    return str(int(v)) if v.isdigit() and len(v) < 10 else ''


def _day(v, label):
    v = str(v or '').strip()
    if not v:
        return ''
    try:
        return datetime.strptime(v, '%Y-%m-%d').date().isoformat()
    except ValueError:
        raise ReportError('Use a real date for "%s".' % label) from None


def clean_config(raw):
    """The report's choices, each one checked against the lists above. Anything unknown is an error, never ignored
    into the query."""
    raw = raw or {}
    get = raw.get if hasattr(raw, 'get') else (lambda k, d=None: d)
    cfg = dict(DEFAULT)
    what = str(get('what') or DEFAULT['what'])
    if what not in SOURCES:
        raise ReportError('Choose what to count: leads, people or activities.')
    cfg['what'] = what
    measure = str(get('measure') or DEFAULT['measure'])
    if measure not in MEASURES:
        raise ReportError('Choose how to measure it.')
    if measure in MONEY_MEASURES and what != 'leads':
        raise ReportError('Only leads have a value. For %s, count how many.' % SOURCES[what].split(' (')[0].lower())
    cfg['measure'] = measure
    group = str(get('group') or '')
    if group not in GROUPS[what]:
        group = next(iter(GROUPS[what]))
    group2 = str(get('group2') or '')
    if group2 and (group2 not in GROUPS[what] or group2 == group):
        raise ReportError('Choose a different second grouping, or none.')
    cfg['group'], cfg['group2'] = group, group2
    date_field = str(get('date') or 'created')
    if date_field not in DATE_FIELDS[what]:
        date_field = 'created'
    cfg['date'] = date_field
    cfg['from'], cfg['to'] = _day(get('from'), 'from'), _day(get('to'), 'to')
    if cfg['from'] and cfg['to'] and cfg['from'] > cfg['to']:
        raise ReportError('The first date is after the last date.')
    cfg['pipeline'] = _int(get('pipeline'))
    cfg['source'] = _int(get('source'))
    owner = str(get('owner') or '').strip()
    cfg['owner'] = owner if owner in ('mine', 'none') else _int(owner)
    status = str(get('status') or '')
    if status and status not in STATUSES:
        raise ReportError('Choose open, won or lost.')
    cfg['status'] = status if what == 'leads' else ''
    offers = str(get('offers') or '')
    if offers and offers not in OFFERS:
        raise ReportError('Choose whether they are OK to receive offers, or anyone.')
    cfg['offers'] = offers if what in ('leads', 'people') else ''
    if what != 'leads':
        cfg['source'] = ''
    if what == 'people':
        cfg['pipeline'] = cfg['owner'] = ''
    return cfg


def describe(cfg):
    """The report in a sentence, for its title: "Number of leads by who looks after it and stage"."""
    noun = {'leads': 'leads', 'people': 'people', 'activities': 'activities'}[cfg['what']]
    head = {'count': 'Number of %s', 'value': 'Total value of %s', 'revenue': 'Our revenue on %s',
            'average': 'Average value of %s'}[cfg['measure']] % noun
    text = '%s by %s' % (head, GROUPS[cfg['what']][cfg['group']].lower())
    if cfg['group2']:
        text += ' and %s' % GROUPS[cfg['what']][cfg['group2']].lower()
    return text


# ================================================================================================ the rows

def _bounds(cfg):
    if not (cfg['from'] or cfg['to']):
        return None, None
    first = date.fromisoformat(cfg['from']) if cfg['from'] else date(2000, 1, 1)
    last = date.fromisoformat(cfg['to']) if cfg['to'] else date(2100, 1, 1)
    return first, last


def _owner_value(cfg, user):
    o = cfg['owner']
    if o == 'mine':
        return user.id
    if o == 'none':
        return 'none'
    return int(o) if o else None


def _lead_rows(cfg, user):
    L = CrmLead
    q = (db.session.query(L.id, L.owner_id, L.stage_id, L.pipeline_id, L.product, L.source_id, L.forecast, L.status,
                          L.likelihood, L.fallout_reason, L.created_at, L.closed_at, L.close_date, L.amount, L.currency,
                          L.revenue, CrmPerson.country, L.utm)
         .join(CrmPerson, CrmPerson.id == L.person_id).filter(L.deleted_at.is_(None)))
    if cfg.get('offers'):
        q = q.filter(CrmPerson.consent_marketing.is_(cfg['offers'] == 'yes'))
    crit = crm_access.lead_filter(user)
    if crit is not None:
        q = q.filter(crit)
    if cfg['pipeline']:
        q = q.filter(L.pipeline_id == int(cfg['pipeline']))
    if cfg['source']:
        q = q.filter(L.source_id == int(cfg['source']))
    if cfg['status']:
        q = q.filter(L.status == cfg['status'])
    own = _owner_value(cfg, user)
    if own == 'none':
        q = q.filter(L.owner_id.is_(None))
    elif own:
        q = q.filter(L.owner_id == own)
    first, last = _bounds(cfg)
    if first is not None:
        if cfg['date'] == 'close_date':
            q = q.filter(L.close_date >= first, L.close_date <= last)
        else:
            col = L.created_at if cfg['date'] == 'created' else L.closed_at
            start, end = crm_money.utc_bounds(first, last)
            q = q.filter(col >= start, col < end)
    return q.limit(ROW_LIMIT).all()


def _person_rows(cfg, user):
    P = CrmPerson
    q = db.session.query(P.id, P.country, P.created_at, P.consent_whatsapp, P.consent_marketing)
    if cfg.get('offers'):
        q = q.filter(P.consent_marketing.is_(cfg['offers'] == 'yes'))
    crit = crm_access.person_filter(user)
    if crit is not None:
        q = q.filter(crit)
    first, last = _bounds(cfg)
    if first is not None:
        start, end = crm_money.utc_bounds(first, last)
        q = q.filter(P.created_at >= start, P.created_at < end)
    return q.limit(ROW_LIMIT).all()


def _activity_rows(cfg, user):
    """(kind, owner id, channel, when, pipeline id) of messages/calls/notes and of tasks."""
    first, last = _bounds(cfg)
    bounds = crm_money.utc_bounds(first, last) if first is not None else None
    vis = crm_access.lead_filter(user)
    pvis = crm_access.person_filter(user)
    own = _owner_value(cfg, user)
    rows = []
    for model, owner_col, when_col, chan in ((CrmTouchpoint, CrmTouchpoint.agent_id, CrmTouchpoint.created_at, CrmTouchpoint.channel),
                                             (CrmTask, CrmTask.owner_id, CrmTask.created_at, CrmTask.kind)):
        q = (db.session.query(chan, owner_col, when_col, CrmLead.pipeline_id)
             .select_from(model).outerjoin(CrmLead, CrmLead.id == model.lead_id))
        if model is CrmTouchpoint:
            q = q.filter(CrmTouchpoint.channel.notin_(('system', 'form')),
                         db.func.coalesce(CrmTouchpoint.status, '') != 'imported')
            person_col = CrmTouchpoint.person_id
        else:
            person_col = CrmTask.person_id
        # an activity on a lead: the lead must be there (not in the bin) and visible; one on a person only: the person visible
        on_lead = and_(model.lead_id.isnot(None), CrmLead.id.isnot(None))
        if vis is not None:
            on_lead = and_(on_lead, vis)
        person_only = model.lead_id.is_(None)
        if pvis is not None:
            person_only = and_(person_only, person_col.in_(select(CrmPerson.id).where(pvis)))
        q = q.filter(or_(on_lead, person_only))
        if cfg['pipeline']:
            q = q.filter(CrmLead.pipeline_id == int(cfg['pipeline']))
        if own == 'none':
            q = q.filter(owner_col.is_(None))
        elif own:
            q = q.filter(owner_col == own)
        if bounds:
            q = q.filter(when_col >= bounds[0], when_col < bounds[1])
        for chan_v, owner_id, when, pipe in q.limit(ROW_LIMIT).all():
            label = CRM_CHANNEL_LABELS.get(chan_v, chan_v or 'Other') if model is CrmTouchpoint else 'Task'
            rows.append((model.__name__, owner_id, label, when, pipe))
    return rows


# ================================================================================================ the grouping

NOT_SET = ((10 ** 6, 0), 'Not set')


def _month_of(dt_or_date, shift=True):
    if dt_or_date is None:
        return NOT_SET
    d = (dt_or_date + IST).date() if (shift and isinstance(dt_or_date, datetime)) else dt_or_date
    return ((d.year, d.month), d.strftime('%b %Y'))


class _Context:
    def __init__(self):
        from app.services import crm_kpi, crm_products
        self.users = {u.id: (u.full_name or u.username or 'Someone') for u in User.query.all()}
        self.stages = {s.id: s.name for s in CrmStage.query.all()}
        self.stage_pos = {s.id: (s.pipeline_id, s.position) for s in CrmStage.query.all()}
        self.pipes = {p.id: p.name for p in CrmPipeline.query.all()}
        self.sources = {s.id: s.name for s in CrmSource.query.all()}
        self.products = crm_products.labels()
        self.roles = crm_kpi.stage_roles()
        self.smap = crm_money.stage_map()
        self.rates = crm_money.rates()
        self.teams = {}
        for t in WorkspaceTeam.query.order_by(WorkspaceTeam.name).all():
            for u in t.users:
                self.teams.setdefault(u.id, t.name)
        self.missing = set()
        self._campaigns = None

    def campaign_label(self, utm, source_id, created_at):
        """The campaign a lead belongs to (Lead sources > Marketing activities), in the list's order."""
        from app.services import crm_campaigns
        if self._campaigns is None:
            self._campaigns = [c for c in crm_campaigns.rows() if crm_campaigns.is_campaign(c)]
        for n, c in enumerate(self._campaigns):
            if crm_campaigns.owns(c, utm, source_id, created_at):
                return (n, crm_campaigns.label(c))
        return (10 ** 5, 'No campaign')

    def user_label(self, uid):
        return (0, self.users.get(uid, 'Someone who left')) if uid else (10 ** 5, 'Nobody yet')

    def team_label(self, uid):
        t = self.teams.get(uid) if uid else None
        return (0, t) if t else (10 ** 5, 'No team')


def _country(iso):
    """The country's name for the code kept on a person ("IN" -> "India"); never a code on screen."""
    from app.services import phone as phone_svc
    iso = (iso or '').strip().upper()
    if not iso:
        return 'Not known'
    return (phone_svc.BY_ISO.get(iso) or {}).get('name') or 'Not known'


def _forecast_of(r, ctx):
    if r.status == 'won':
        return 'won'
    if r.status == 'lost':
        return 'lost'
    if r.forecast in crm_money.OPEN_FORECASTS:
        return r.forecast
    cat = (ctx.smap.get(r.stage_id) or ('pipeline', 10))[0]
    return cat if cat in crm_money.OPEN_FORECASTS else 'pipeline'


# each: row -> (sort key, label). The row is a tuple of the query's columns; positions are named below.
_LEAD = {name: i for i, name in enumerate(('id', 'owner', 'stage', 'pipeline', 'product', 'source', 'forecast', 'status',
                                           'likelihood', 'lost', 'created', 'closed', 'close_date', 'amount',
                                           'currency', 'revenue', 'country', 'utm'))}


def _lead_dims(ctx):
    g = _LEAD

    def col(r, name):
        return r[g[name]]
    return {
        'owner': lambda r: ctx.user_label(col(r, 'owner')),
        'team': lambda r: ctx.team_label(col(r, 'owner')),
        'stage': lambda r: ((ctx.stage_pos.get(col(r, 'stage')) or (0, 10 ** 5)),
                            ctx.stages.get(col(r, 'stage'), 'No stage')),
        'phase': lambda r: (list(PHASE_WORDS).index(ctx.roles.get(col(r, 'stage'))) if ctx.roles.get(col(r, 'stage')) in PHASE_WORDS else 99,
                            PHASE_WORDS.get(ctx.roles.get(col(r, 'stage')), 'Not routed')),
        'pipeline': lambda r: ((0, ctx.pipes.get(col(r, 'pipeline'), 'Not routed yet'))),
        'product': lambda r: (0, ctx.products.get(col(r, 'product'), col(r, 'product') or 'Other')),
        'source': lambda r: (0, ctx.sources.get(col(r, 'source'), 'Not known')),
        'forecast': lambda r: (list(CRM_FORECASTS).index(_forecast_of(r, ctx)), CRM_FORECASTS[_forecast_of(r, ctx)]),
        'rating': lambda r: ((list(CRM_LIKELIHOOD).index(col(r, 'likelihood')), CRM_LIKELIHOOD[col(r, 'likelihood')])
                             if col(r, 'likelihood') in CRM_LIKELIHOOD else (99, 'Not rated')),
        'country': lambda r: (0, _country(col(r, 'country'))),
        'lost_reason': lambda r: (0, (col(r, 'lost') or 'No reason given') if col(r, 'status') == 'lost' else 'Not lost'),
        'created_month': lambda r: _month_of(col(r, 'created')),
        'closed_month': lambda r: _month_of(col(r, 'closed')),
        'close_month': lambda r: _month_of(col(r, 'close_date'), shift=False),
        'campaign': lambda r: ctx.campaign_label(col(r, 'utm'), col(r, 'source'), col(r, 'created')),
    }


def _person_dims(ctx):
    return {
        'country': lambda r: (0, _country(r[1])),
        'created_month': lambda r: _month_of(r[2]),
        'permission': lambda r: ((0, 'Agreed to WhatsApp messages') if r[3] else (1, 'No permission yet')),
        'offers': lambda r: ((0, 'OK to send offers') if r[4] else (1, 'Not OK to send offers')),
    }


def _activity_dims(ctx):
    return {
        'owner': lambda r: ctx.user_label(r[1]) if r[1] else (10 ** 5, 'Automatic or the system'),
        'team': lambda r: ctx.team_label(r[1]),
        'channel': lambda r: (0, r[2]),
        'created_month': lambda r: _month_of(r[3]),
        'pipeline': lambda r: (0, ctx.pipes.get(r[4], 'Not on a lead')),
    }


class _Agg:
    __slots__ = ('n', 'value', 'revenue', 'valued')

    def __init__(self):
        self.n, self.value, self.revenue, self.valued = 0, Decimal(0), Decimal(0), 0

    def add(self, other_value, other_revenue, has_value):
        self.n += 1
        if has_value:
            self.value += other_value
            self.revenue += other_revenue
            self.valued += 1

    def get(self, measure):
        if measure == 'count':
            return self.n
        if measure == 'value':
            return self.value
        if measure == 'revenue':
            return self.revenue
        return (self.value / self.valued) if self.valued else Decimal(0)


def run(cfg, user):
    """The report: {'cfg', 'title', 'unit', 'cols', 'rows': [{'label','cells','total'}], 'total', 'max', 'notes',
    'count'}. `cfg` must have been through clean_config."""
    ctx = _Context()
    what = cfg['what']
    if what == 'leads':
        rows, dims = _lead_rows(cfg, user), _lead_dims(ctx)
    elif what == 'people':
        rows, dims = _person_rows(cfg, user), _person_dims(ctx)
    else:
        rows, dims = _activity_rows(cfg, user), _activity_dims(ctx)
    d1 = dims[cfg['group']]
    d2 = dims[cfg['group2']] if cfg['group2'] else None
    grid = defaultdict(_Agg)                  # (row key, col key) -> Agg
    row_tot, col_tot, all_tot = defaultdict(_Agg), defaultdict(_Agg), _Agg()
    money = cfg['measure'] in MONEY_MEASURES
    for r in rows:
        has, val, rev = False, Decimal(0), Decimal(0)
        if money and r[_LEAD['amount']] is not None:
            cur = (r[_LEAD['currency']] or crm_money.reporting_currency()).upper()
            if cur not in ctx.rates:
                ctx.missing.add(cur)
            has = True
            val = crm_money.to_base(r[_LEAD['amount']], cur, ctx.rates)
            rev = crm_money.to_base(r[_LEAD['revenue']] if r[_LEAD['revenue']] is not None else r[_LEAD['amount']], cur,
                                    ctx.rates)
        k1 = d1(r)
        k2 = d2(r) if d2 else (0, '')
        for agg in (grid[(k1, k2)], row_tot[k1], col_tot[k2], all_tot):
            agg.add(val, rev, has)
    measure = cfg['measure']
    r_keys = sorted(row_tot, key=lambda k: k)
    if not _ordered(cfg['group']):
        r_keys = sorted(row_tot, key=lambda k: (-_sortval(row_tot[k], measure), k[1]))
    c_keys = sorted(col_tot, key=lambda k: k) if d2 else []
    if d2 and not _ordered(cfg['group2']):
        c_keys = sorted(col_tot, key=lambda k: (-_sortval(col_tot[k], measure), k[1]))
    out_rows = []
    for k in r_keys:
        cells = [(grid[(k, c)].get(measure) if (k, c) in grid else (0 if measure == 'count' else Decimal(0)))
                 for c in c_keys]
        out_rows.append({'label': k[1], 'cells': cells, 'total': row_tot[k].get(measure)})
    biggest = max([r['total'] for r in out_rows] or [0])
    notes = []
    if ctx.missing:
        notes.append('No exchange rate for %s, so those leads count as 0. Set the rate in Pipelines & products.'
                     % ', '.join(sorted(ctx.missing)))
    if len(rows) >= ROW_LIMIT:
        notes.append('Only the first %d records are included. Narrow the dates to see the rest.' % ROW_LIMIT)
    return {'cfg': cfg, 'title': describe(cfg), 'unit': 'money' if money else 'count',
            'cols': [c[1] for c in c_keys], 'rows': out_rows, 'total': all_tot.get(measure),
            'col_totals': [col_tot[c].get(measure) for c in c_keys], 'max': biggest, 'notes': notes,
            'count': all_tot.n, 'currency': crm_money.reporting_currency(), 'group_label': GROUPS[what][cfg['group']],
            'group2_label': GROUPS[what][cfg['group2']] if cfg['group2'] else ''}


ORDERED = ('created_month', 'closed_month', 'close_month', 'stage', 'phase', 'forecast', 'rating', 'permission', 'offers',
           'campaign')


def _ordered(group):
    """Months, stages and the like keep their natural order; the rest are listed biggest first."""
    return group in ORDERED


def _sortval(agg, measure):
    return agg.get(measure)


def pct(value, biggest):
    """A bar's width as a whole percent (never above 100)."""
    try:
        return max(0, min(100, int(round(float(value) * 100 / float(biggest))))) if biggest else 0
    except (TypeError, ValueError, ZeroDivisionError):
        return 0


# ================================================================================================ download

def csv_rows(result):
    """The table as rows of text for Excel: a header, a line per group, a total."""
    cur = result['currency']
    unit = ' (%s)' % cur if result['unit'] == 'money' else ''

    def num(v):
        return crm_money.plain_amount(v) if result['unit'] == 'money' else int(v)
    head = [result['group_label']] + list(result['cols']) + ([('Total' + unit)] if result['cols'] else [
        MEASURES[result['cfg']['measure']] + unit])
    out = [[result['title']], head]
    for r in result['rows']:
        out.append([r['label']] + [num(c) for c in r['cells']] + [num(r['total'])])
    if result['cols']:
        out.append(['Total'] + [num(c) for c in result['col_totals']] + [num(result['total'])])
    else:
        out.append(['Total', num(result['total'])])
    return out


# ================================================================================================ saved reports

class SavedError(ValueError):
    pass


def create(user, name, cfg, shared=False):
    name = ' '.join(str(name or '').split())[:NAME_MAX]
    if not name:
        raise SavedError('Give the report a name so you can find it again.')
    if CrmSavedReport.query.filter_by(owner_id=user.id).count() >= MAX_PER_USER:
        raise SavedError('You already have %d saved reports. Delete one to make room.' % MAX_PER_USER)
    if CrmSavedReport.query.filter_by(owner_id=user.id, name=name).first():
        raise SavedError('You already have a report called "%s".' % name)
    rep = CrmSavedReport(name=name, owner_id=user.id, shared=bool(shared), config=cfg, pinned=False, position=0,
                         created_at=datetime.utcnow())
    db.session.add(rep)
    db.session.commit()
    return rep


def listing(user):
    """{'mine': [...], 'shared': [...]}: reports the person made, and reports colleagues shared."""
    rows = (CrmSavedReport.query.filter(or_(CrmSavedReport.owner_id == user.id, CrmSavedReport.shared.is_(True)))
            .order_by(CrmSavedReport.name, CrmSavedReport.id).all())
    return {'mine': [r for r in rows if r.owner_id == user.id], 'shared': [r for r in rows if r.owner_id != user.id]}


def get_for(user, report_id):
    r = db.session.get(CrmSavedReport, report_id)
    if r is None or not (r.owner_id == user.id or r.shared):
        return None
    return r


def _mine(user, report_id):
    r = db.session.get(CrmSavedReport, report_id)
    if r is None or not (r.owner_id == user.id or user.is_admin):
        raise SavedError('That report is not yours to change.')
    return r


def set_pinned(user, report_id, pinned):
    r = _mine(user, report_id)
    r.pinned = bool(pinned)
    if r.pinned:
        top = db.session.query(db.func.max(CrmSavedReport.position)).scalar() or 0
        r.position = top + 1
    db.session.commit()
    return r


def move(user, report_id, direction):
    r = _mine(user, report_id)
    pinned = (CrmSavedReport.query.filter(CrmSavedReport.pinned.is_(True))
              .order_by(CrmSavedReport.position, CrmSavedReport.id).all())
    if r not in pinned:
        return r
    i = pinned.index(r)
    j = i - 1 if direction == 'up' else i + 1
    if 0 <= j < len(pinned):
        pinned[i], pinned[j] = pinned[j], pinned[i]
        for n, rep in enumerate(pinned, start=1):
            rep.position = n
        db.session.commit()
    return r


def delete(user, report_id):
    r = _mine(user, report_id)
    db.session.delete(r)
    db.session.commit()


def pinned_for(user):
    """[{'report', 'result'}] pinned reports this person may see, in their saved order, each run with THEIR
    visibility. A report that no longer runs is left out (a missing pipeline must not break Sales results)."""
    reps = (CrmSavedReport.query.filter(CrmSavedReport.pinned.is_(True))
            .filter(or_(CrmSavedReport.owner_id == user.id, CrmSavedReport.shared.is_(True)))
            .order_by(CrmSavedReport.position, CrmSavedReport.id).all())
    out = []
    for rep in reps:
        try:
            out.append({'report': rep, 'result': run(clean_config(rep.config), user)})
        except Exception:          # noqa: BLE001
            db.session.rollback()
    return out
