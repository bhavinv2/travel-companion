"""Money in the Sales CRM (Phase 1): deal values, what we earn, forecast categories, exchange rates, targets.

A lead carries an `amount` in its own `currency`; reports add amounts up in the reporting currency (app
setting `crm.currency`, INR unless changed) through the rates in `crm_currency_rates`. A currency with no
rate counts as 0 and is listed as a warning (`missing_rates`), never guessed.

Forecast categories (CRM_FORECASTS): pipeline (talking, early), best_case (quote sent), commit (payment link
sent / promised), won (paid), lost. A stage gives its leads a category and a chance to win; both are
automatic unless set on the stage; a lead may override the category while it is open.
"""
import calendar
import re
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import and_, false, func, or_

from app import db
from app.models import (CRM_FORECASTS, CrmCurrencyRate, CrmLead, CrmProduct, CrmStage, CrmTarget, User,
                        WorkspaceTeam)
from app.services import crm_products

SETTING_CURRENCY = 'crm.currency'
DEFAULT_CURRENCY = 'INR'
DEFAULT_CLOSE_DAYS = 14
DEPARTURE_LEAD_DAYS = 3
OPEN_FORECASTS = ('pipeline', 'best_case', 'commit')
CENT = Decimal('0.01')
ZERO = Decimal('0')
SYMBOLS = {'INR': '₹', 'USD': '$', 'EUR': '€', 'GBP': '£', 'AED': 'AED ', 'CAD': 'C$', 'AUD': 'A$', 'SGD': 'S$'}
AUTO_LABELS = {'pipeline': 'Pipeline', 'best_case': 'Best case', 'commit': 'Committed', 'won': 'Closed won',
               'lost': 'Lost'}
PERIOD_RE = re.compile(r'^(\d{4})-(0[1-9]|1[0-2])$')
CURRENCY_RE = re.compile(r'^[A-Z]{3}$')


# ------------------------------------------------------------------------------------------ numbers

def dec(value):
    """A Decimal from a number or text ("1,20,000" works); None for nothing or rubbish."""
    if value is None or value == '':
        return None
    if isinstance(value, Decimal):
        return value
    try:
        text = str(value).replace(',', '').replace('₹', '').strip()
        return Decimal(text) if text else None
    except Exception:
        return None


def money_amount(value):
    """A Decimal for Numeric(12,2), or None. Negative and too-large amounts are refused (ValueError)."""
    d = dec(value)
    if d is None:
        if value is None or str(value).strip() == '':
            return None
        raise ValueError('amount')              # something was typed, and it is not a number
    if not d.is_finite() or d < 0 or d >= Decimal('10000000000'):
        raise ValueError('amount')
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def reporting_currency():
    from app.services import settings
    code = str(settings.get_setting(SETTING_CURRENCY, DEFAULT_CURRENCY) or DEFAULT_CURRENCY).strip().upper()
    return code if CURRENCY_RE.match(code) else DEFAULT_CURRENCY


def clean_currency(value, fallback=None):
    code = (value or '').strip().upper()
    return code if CURRENCY_RE.match(code) else (fallback or reporting_currency())


def rates():
    """{code: Decimal rate} for every currency with a rate, and the reporting currency at 1."""
    out = {r.code: Decimal(r.rate) for r in CrmCurrencyRate.query.all() if r.rate and r.rate > 0}
    out[reporting_currency()] = Decimal('1')
    return out


def to_base(amount, currency=None, rate_map=None):
    """`amount` in `currency` as reporting-currency money; 0 for a currency with no rate (see missing_rates)."""
    d = dec(amount)
    if not d:
        return ZERO
    rate_map = rate_map if rate_map is not None else rates()
    code = (currency or reporting_currency()).upper()
    rate = rate_map.get(code)
    return (d * rate) if rate else ZERO


def convert(amount, from_currency, to_currency, rate_map=None):
    """Money from one currency into another through the reporting currency; None when a rate is missing."""
    d = dec(amount)
    if d is None:
        return None
    a = (from_currency or reporting_currency()).upper()
    b = (to_currency or reporting_currency()).upper()
    if a == b:
        return d
    rate_map = rate_map if rate_map is not None else rates()
    if not rate_map.get(a) or not rate_map.get(b):
        return None
    return d * rate_map[a] / rate_map[b]


# ----------------------------------------------------------------------------------------- show money

def _indian(n):
    s = str(int(n))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ','.join(parts + [tail])


def _western(n):
    return '{:,}'.format(int(n))


def money(amount, currency=None, compact=False):
    """₹1,20,000 (Indian grouping for rupees); compact: ₹1.2 L / ₹1.5 Cr for big rupee amounts. '' for nothing."""
    d = dec(amount)
    if d is None:
        return ''
    code = (currency or DEFAULT_CURRENCY).upper()
    sym = SYMBOLS.get(code, code + ' ')
    neg = '-' if d < 0 else ''
    d = abs(d)
    if code == 'INR' and compact and d >= 100000:
        if d >= 10000000:
            v, unit = d / Decimal(10000000), ' Cr'
        else:
            v, unit = d / Decimal(100000), ' L'
        text = ('%.1f' % v).rstrip('0').rstrip('.')
        return '%s%s%s%s' % (neg, sym, text, unit)
    whole = d.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    group = _indian if code == 'INR' else _western
    text = group(int(d)) if not compact else group(whole)
    frac = d - int(d)
    if not compact and frac:
        text += '.%02d' % int((frac * 100).to_integral_value(rounding=ROUND_HALF_UP))
    return '%s%s%s' % (neg, sym, text)


def plain_amount(amount):
    """12000 / 12000.50 for an input box; '' for nothing."""
    d = dec(amount)
    if d is None:
        return ''
    return str(int(d)) if d == int(d) else format(d.quantize(CENT), 'f')


def plain_rate(rate):
    """83.5 for an input box (up to six decimals, no trailing zeros)."""
    d = dec(rate)
    if d is None:
        return ''
    text = format(d.quantize(Decimal('0.000001')), 'f').rstrip('0').rstrip('.')
    return text or '0'


def money_c(amount, currency=None):
    return money(amount, currency, compact=True)


# ------------------------------------------------------------------------------------------ products

def product_row(code):
    return crm_products.by_code(code)


def revenue_for(amount, currency, product, rate_map=None):
    """What we earn on `amount` (in `currency`) for this product (a Product / CrmProduct, or None).
    No rule: the whole amount; fixed: the fixed amount in the lead's currency; percent: amount x value / 100.
    None when there is no amount, or a fixed amount cannot be converted for want of a rate."""
    amount = dec(amount)
    if amount is None:
        return None
    kind = getattr(product, 'revenue_kind', None)
    value = dec(getattr(product, 'revenue_value', None))
    if kind == 'percent' and value is not None:
        return (amount * value / 100).quantize(CENT, rounding=ROUND_HALF_UP)
    if kind == 'fixed' and value is not None:
        cur = (currency or getattr(product, 'currency', None) or reporting_currency()).upper()
        pcur = (getattr(product, 'currency', None) or DEFAULT_CURRENCY).upper()
        got = convert(value, pcur, cur, rate_map)
        return got.quantize(CENT, rounding=ROUND_HALF_UP) if got is not None else None
    return amount


def recalc_revenue(lead):
    """Set lead.revenue from its amount, currency and product."""
    lead.revenue = revenue_for(lead.amount, lead.currency, product_row(lead.product))
    return lead.revenue


def set_amount(lead, amount, currency=None):
    """Change a lead's deal value (and what we earn on it). `amount` None clears it."""
    lead.amount = money_amount(amount)
    if lead.amount is None:
        lead.revenue = None
        return
    prod = product_row(lead.product)
    lead.currency = clean_currency(currency, lead.currency or getattr(prod, 'currency', None))
    recalc_revenue(lead)


def apply_new_lead_defaults(lead, today=None):
    """A lead just made by capture / Add a lead: the product's usual price, and a close date. Leads brought in
    by an importer get nothing. A price already on the lead is kept."""
    if lead.imported:
        return
    today = today or date.today()
    prod = product_row(lead.product)
    if lead.amount is None and prod is not None and dec(prod.price):
        lead.amount = money_amount(prod.price)
        lead.currency = (prod.currency or DEFAULT_CURRENCY).upper()
        recalc_revenue(lead)
    if lead.close_date is None:
        lead.close_date = default_close_date(lead, prod, today)


def default_close_date(lead, prod=None, today=None):
    today = today or date.today()
    if lead.departure_date:
        return max(today, lead.departure_date - timedelta(days=DEPARTURE_LEAD_DAYS))
    days = getattr(prod, 'close_days', None) if prod is not None else None
    base = (lead.created_at.date() if lead.created_at else today)
    return base + timedelta(days=days if days else DEFAULT_CLOSE_DAYS)


def lead_won(lead, today=None):
    """A lead was just marked won: with no close date it counts in the day it was won."""
    if lead.close_date is None:
        lead.close_date = today or (lead.closed_at.date() if lead.closed_at else date.today())


# ------------------------------------------------------------------------------- forecast categories

def auto_forecast(stage):
    """(category, chance %) a stage gives by itself."""
    if stage is None:
        return 'pipeline', 10
    means = stage.means or stage.stage_means
    if stage.kind == 'won' or means == 'won':
        return 'won', 100
    if stage.kind == 'lost' or means == 'lost':
        return 'lost', 0
    label = (stage.button_label or '').lower()
    if (stage.button_code or '').strip().upper() == 'PLS' or 'payment' in label:
        return 'commit', 80
    if means == 'quoted':
        return 'best_case', 50
    if means == 'talking':
        return 'pipeline', 25
    return 'pipeline', 10


def stage_forecast(stage):
    if stage is not None and stage.forecast in CRM_FORECASTS:
        return stage.forecast
    return auto_forecast(stage)[0]


def stage_probability(stage):
    if stage is not None and stage.probability is not None and 0 <= stage.probability <= 100:
        return int(stage.probability)
    return auto_forecast(stage)[1]


def stage_map():
    """{stage id: (category, chance)} for every stage, one query."""
    return {s.id: (stage_forecast(s), stage_probability(s)) for s in CrmStage.query.all()}


def lead_forecast(lead, smap=None):
    if lead.status == 'won':
        return 'won'
    if lead.status == 'lost':
        return 'lost'
    if lead.forecast in OPEN_FORECASTS:
        return lead.forecast
    if smap is not None:
        cat = (smap.get(lead.stage_id) or ('pipeline', 10))[0]
    else:
        cat = stage_forecast(lead.stage)
    return cat if cat in OPEN_FORECASTS else 'pipeline'


def lead_chance(lead, smap=None):
    if lead.status == 'won':
        return 100
    if lead.status == 'lost':
        return 0
    if smap is not None:
        return (smap.get(lead.stage_id) or ('pipeline', 10))[1]
    return stage_probability(lead.stage)


def lead_expected(lead):
    amount = dec(lead.amount)
    if not amount:
        return ZERO
    return (amount * lead_chance(lead) / 100).quantize(CENT, rounding=ROUND_HALF_UP)


def forecast_label(category):
    return AUTO_LABELS.get(category, '')


# ----------------------------------------------------------------------------------------- periods

def parse_period(text, today=None):
    """'YYYY-MM' as given, else this month."""
    today = today or date.today()
    m = PERIOD_RE.match((text or '').strip())
    return '%s-%s' % (m.group(1), m.group(2)) if m else '%04d-%02d' % (today.year, today.month)


def period_start(period):
    y, m = PERIOD_RE.match(period).groups()
    return date(int(y), int(m), 1)


def shift_period(period, months):
    d = period_start(period)
    n = d.year * 12 + d.month - 1 + months
    return '%04d-%02d' % (n // 12, n % 12 + 1)


def month_range(period):
    first = period_start(period)
    return first, date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])


def quarter_months(period):
    """The three months of the calendar quarter holding `period`."""
    first = period_start(period)
    q0 = (first.month - 1) // 3 * 3 + 1
    return ['%04d-%02d' % (first.year, q0 + i) for i in range(3)]


def span_months(period, quarter=False):
    return quarter_months(period) if quarter else [period]


def span_dates(months):
    return month_range(months[0])[0], month_range(months[-1])[1]


def utc_bounds(first, last):
    """[start, end) in UTC for the India-time days first..last."""
    from app.services.crm_reports import IST
    start = datetime.combine(first, datetime.min.time()) - IST
    return start, datetime.combine(last + timedelta(days=1), datetime.min.time()) - IST


def month_label(period):
    return period_start(period).strftime('%B %Y')


def closes_bounds(text):
    """('YYYY-MM' | 'YYYY-Qn') as (first day, last day), or None."""
    t = (text or '').strip().upper()
    m = re.match(r'^(\d{4})-Q([1-4])$', t)
    if m:
        y, q = int(m.group(1)), int(m.group(2))
        first = date(y, (q - 1) * 3 + 1, 1)
        last = month_range('%04d-%02d' % (y, q * 3))[1]
        return first, last
    if PERIOD_RE.match(t):
        return month_range(t)
    return None


# ------------------------------------------------------------------------------------ list filters

def stage_ids_for(category):
    return [sid for sid, (cat, _p) in stage_map().items() if cat == category]


def apply_filters(query, closes=None, forecast=None, no_value=False, no_close=False):
    """Narrow a CrmLead query: closes ('YYYY-MM' / 'YYYY-Qn': the close date is in it; with forecast=won, the
    lead was won in it), forecast (a category), no_value (no amount), no_close (open with no close date)."""
    bounds = closes_bounds(closes)
    won_in = forecast == 'won' and bounds is not None
    if won_in:
        start, end = utc_bounds(*bounds)
        query = query.filter(CrmLead.status == 'won', CrmLead.closed_at >= start, CrmLead.closed_at < end)
    elif bounds is not None:
        query = query.filter(CrmLead.close_date >= bounds[0], CrmLead.close_date <= bounds[1])
    if forecast == 'won' and not won_in:
        query = query.filter(CrmLead.status == 'won')
    elif forecast == 'lost':
        query = query.filter(CrmLead.status == 'lost')
    elif forecast in OPEN_FORECASTS:
        ids = stage_ids_for(forecast)
        query = query.filter(CrmLead.status == 'open', or_(
            CrmLead.forecast == forecast,
            and_(or_(CrmLead.forecast.is_(None), CrmLead.forecast.notin_(OPEN_FORECASTS)),
                 CrmLead.stage_id.in_(ids) if ids else false())))
        if forecast == 'pipeline':
            # a lead with no stage counts as pipeline
            query = query.filter(or_(CrmLead.forecast == 'pipeline', CrmLead.forecast.is_(None),
                                     CrmLead.forecast.notin_(OPEN_FORECASTS)))
    if no_value:
        query = query.filter(CrmLead.amount.is_(None))
    if no_close:
        query = query.filter(CrmLead.status == 'open', CrmLead.close_date.is_(None))
    return query


def column_total(leads, rate_map=None):
    """Sum of the leads' amounts in the reporting currency."""
    rate_map = rate_map if rate_map is not None else rates()
    return sum((to_base(l.amount, l.currency, rate_map) for l in leads if l.amount is not None), ZERO)


def totals_by_stage(query, rate_map=None):
    """{stage id: reporting-currency total of amounts} for a CrmLead query (grouped by stage and currency).
    One query when nobody has a value yet; the rates are only read when there is something to add up."""
    rows = (query.with_entities(CrmLead.stage_id, CrmLead.currency, func.sum(CrmLead.amount))
            .filter(CrmLead.amount.isnot(None)).group_by(CrmLead.stage_id, CrmLead.currency).all())
    if not rows:
        return {}
    rate_map = rate_map if rate_map is not None else rates()
    out = {}
    for sid, cur, total in rows:
        out[sid] = out.get(sid, ZERO) + to_base(total, cur, rate_map)
    return out


# --------------------------------------------------------------------------------------------- rates

def currencies_in_use():
    """Currencies of products and leads, other than the reporting one, sorted."""
    codes = {c for (c,) in db.session.query(CrmProduct.currency).distinct() if c}
    codes |= {c for (c,) in db.session.query(CrmLead.currency).filter(CrmLead.currency.isnot(None)).distinct()}
    codes |= {r.code for r in CrmCurrencyRate.query.all()}
    codes.discard(reporting_currency())
    return sorted(c.upper() for c in codes)


def missing_rates(extra=()):
    """Currencies in use that have no rate yet."""
    have = rates()
    return [c for c in currencies_in_use() if c not in have] + [c for c in extra if c not in have]


def set_rate(code, rate, actor=None):
    code = clean_currency(code, None)
    if code == reporting_currency():
        raise ValueError('reporting')
    value = dec(rate)
    if value is None or value <= 0 or value >= Decimal('100000000'):
        raise ValueError('rate')
    row = db.session.get(CrmCurrencyRate, code)
    if row is None:
        row = CrmCurrencyRate(code=code)
        db.session.add(row)
    row.rate = value.quantize(Decimal('0.000001'))
    row.updated_at = datetime.utcnow()
    row.updated_by_id = getattr(actor, 'id', None)
    return row


def currency_choices(lead=None):
    """For the deal value form: the reporting currency, those with a rate, and the product's / lead's."""
    out = [reporting_currency()]
    for c in sorted(rates()):
        if c not in out:
            out.append(c)
    prod = product_row(lead.product) if lead is not None else None
    more = [getattr(prod, 'currency', None), getattr(lead, 'currency', None)]
    if lead is None:
        more += [p.currency for p in crm_products.all()]       # Add a lead: any product may be chosen
    for c in more:
        if c and c.upper() not in out:
            out.append(c.upper())
    return out


# ------------------------------------------------------------------------------------------ targets

def target_key(user_id=None, team_id=None):
    return ('t', team_id) if team_id else (('u', user_id) if user_id else ('c', None))


def targets_for(period, pipeline_id=None):
    """{('u', user id) | ('t', team id) | ('c', None): CrmTarget} for one month and one pipeline (None: all)."""
    q = CrmTarget.query.filter(CrmTarget.period == period)
    q = q.filter(CrmTarget.pipeline_id == pipeline_id) if pipeline_id else q.filter(CrmTarget.pipeline_id.is_(None))
    return {target_key(t.user_id, t.team_id): t for t in q.order_by(CrmTarget.id)}


def save_target(period, *, user_id=None, team_id=None, pipeline_id=None, amount=None, deals=None, leads=None,
                actor=None):
    """Upsert one target row; with nothing to aim for the row is removed. Returns the row or None."""
    if not PERIOD_RE.match(period or ''):
        raise ValueError('period')
    if user_id and team_id:
        raise ValueError('who')
    amount = money_amount(amount)
    deals = _count(deals)
    leads = _count(leads)
    q = CrmTarget.query.filter(CrmTarget.period == period, CrmTarget.user_id == user_id,
                               CrmTarget.team_id == team_id, CrmTarget.pipeline_id == pipeline_id) \
        if (user_id and team_id is None and pipeline_id) else None
    row = _find(period, user_id, team_id, pipeline_id)
    if amount is None and deals is None and leads is None:
        if row is not None:
            db.session.delete(row)
        return None
    if row is None:
        row = CrmTarget(period=period, user_id=user_id or None, team_id=team_id or None,
                        pipeline_id=pipeline_id or None)
        db.session.add(row)
    row.amount, row.deals, row.leads = amount, deals, leads
    row.updated_at = datetime.utcnow()
    row.updated_by_id = getattr(actor, 'id', None)
    return row


def _find(period, user_id, team_id, pipeline_id):
    q = CrmTarget.query.filter(CrmTarget.period == period)
    for col, val in ((CrmTarget.user_id, user_id), (CrmTarget.team_id, team_id), (CrmTarget.pipeline_id, pipeline_id)):
        q = q.filter(col == val) if val else q.filter(col.is_(None))
    return q.first()


def _count(value):
    if value is None or str(value).strip() == '':
        return None
    try:
        n = int(Decimal(str(value).replace(',', '').strip()))
    except Exception:
        raise ValueError('count')
    if n < 0 or n > 10000000:
        raise ValueError('count')
    return n


def copy_targets(from_period, to_period, pipeline_id=None, user_ids=None, team_ids=None, company=False, actor=None):
    """Copy last month's targets into a month, only where that month has none yet. Returns how many rows."""
    done = 0
    mine = targets_for(to_period, pipeline_id)
    for key, t in targets_for(from_period, pipeline_id).items():
        kind, ident = key
        if kind == 'u' and user_ids is not None and ident not in user_ids:
            continue
        if kind == 't' and team_ids is not None and ident not in team_ids:
            continue
        if kind == 'c' and not company:
            continue
        if key in mine:
            continue
        save_target(to_period, user_id=ident if kind == 'u' else None, team_id=ident if kind == 't' else None,
                    pipeline_id=pipeline_id, amount=t.amount, deals=t.deals, leads=t.leads, actor=actor)
        done += 1
    return done


def target_sums(months, pipeline_id=None):
    """{key: {'amount', 'deals', 'leads'}} summed over the months (None where nobody set one)."""
    out = {}
    for period in months:
        for key, t in targets_for(period, pipeline_id).items():
            cell = out.setdefault(key, {'amount': None, 'deals': None, 'leads': None})
            for f in ('amount', 'deals', 'leads'):
                v = getattr(t, f)
                if v is not None:
                    cell[f] = (cell[f] or 0) + v
    return out


# ---------------------------------------------------------------------------------------- the forecast

def _blank_row():
    return {'target': None, 'deals_target': None, 'leads_target': None, 'won': ZERO, 'won_n': 0,
            'revenue': ZERO, 'commit': ZERO, 'best_case': ZERO, 'pipeline': ZERO, 'commit_n': 0,
            'best_case_n': 0, 'pipeline_n': 0, 'new_leads': 0, 'gap': ZERO, 'pct': None, 'expected': ZERO}


def _finish(row):
    target = row['target']
    row['gap'] = max(ZERO, Decimal(target) - row['won']) if target is not None else ZERO
    row['pct'] = int(row['won'] * 100 / Decimal(target)) if target else None
    return row


def forecast(first, last, users, pipeline_id=None, months=None, rate_map=None):
    """Numbers per person for the days first..last (India time), all in the reporting currency.

    users: the people to show (leads are those they look after). Returns {'rows': {user id: row}, 'fix':
    {...}, 'missing_rates': [codes]}. Row: target, deals_target, leads_target (None: not set), won / won_n
    (won in the days), commit / best_case / pipeline (+ _n: open leads whose close date is in the days),
    new_leads, gap, pct, expected."""
    rate_map = rate_map if rate_map is not None else rates()
    ids = [u.id for u in users]
    rows = {i: _blank_row() for i in ids}
    fix = {'no_close': 0, 'no_value': 0, 'won_no_value': 0, 'no_rate': 0}
    out = {'rows': rows, 'fix': fix, 'missing_rates': [], 'first': first, 'last': last}
    if not ids:
        return out
    months = months or sorted({'%04d-%02d' % (d.year, d.month) for d in
                               (first + timedelta(days=i) for i in range((last - first).days + 1))})
    sums = target_sums(months, pipeline_id)
    for i in ids:
        t = sums.get(('u', i))
        if t:
            rows[i]['target'], rows[i]['deals_target'], rows[i]['leads_target'] = t['amount'], t['deals'], t['leads']
    start, end = utc_bounds(first, last)
    smap = stage_map()
    lead_q = CrmLead.query.filter(CrmLead.owner_id.in_(ids))
    if pipeline_id:
        lead_q = lead_q.filter(CrmLead.pipeline_id == pipeline_id)
    missing = {}

    def count_rate(lead):
        cur = (lead.currency or reporting_currency()).upper()
        if lead.amount is not None and cur not in rate_map:
            missing[cur] = missing.get(cur, 0) + 1
            fix['no_rate'] += 1

    for l in lead_q.filter(CrmLead.status == 'won', CrmLead.closed_at >= start, CrmLead.closed_at < end):
        r = rows[l.owner_id]
        r['won_n'] += 1
        if l.amount is None:
            fix['won_no_value'] += 1
            continue
        count_rate(l)
        r['won'] += to_base(l.amount, l.currency, rate_map)
        r['revenue'] += to_base(l.revenue if l.revenue is not None else l.amount, l.currency, rate_map)
    for l in lead_q.filter(CrmLead.status == 'open'):
        if l.amount is None:
            fix['no_value'] += 1               # every open lead without a value, whenever it closes
        if l.close_date is None:
            fix['no_close'] += 1
            continue
        if not (first <= l.close_date <= last):
            continue
        cat = lead_forecast(l, smap)
        r = rows[l.owner_id]
        r[cat + '_n'] += 1
        if l.amount is not None:
            count_rate(l)
            v = to_base(l.amount, l.currency, rate_map)
            r[cat] += v
            r['expected'] += v * lead_chance(l, smap) / 100
    for owner, n in (db.session.query(CrmLead.owner_id, func.count(CrmLead.id))
                     .filter(CrmLead.owner_id.in_(ids), CrmLead.created_at >= start, CrmLead.created_at < end,
                             CrmLead.imported.is_(False),
                             *([CrmLead.pipeline_id == pipeline_id] if pipeline_id else []))
                     .group_by(CrmLead.owner_id)):
        rows[owner]['new_leads'] = n
    for r in rows.values():
        _finish(r)
    out['missing_rates'] = sorted(missing)
    out['missing_counts'] = missing
    return out


def team_row(members_rows, own_target=None):
    """A team's row: members' numbers added up; the team's own target (a CrmTarget-like dict) when set.
    'members_target' is what the members' targets add up to."""
    row = _blank_row()
    for r in members_rows:
        for k in ('won', 'revenue', 'commit', 'best_case', 'pipeline', 'expected'):
            row[k] += r[k]
        for k in ('won_n', 'commit_n', 'best_case_n', 'pipeline_n', 'new_leads'):
            row[k] += r[k]
        for k, src in (('target', 'target'), ('deals_target', 'deals_target'), ('leads_target', 'leads_target')):
            if r[src] is not None:
                row[k] = (row[k] or 0) + r[src]
    row['members_target'] = row['target']
    if own_target:
        for k in ('target', 'deals_target', 'leads_target'):
            if own_target.get(k) is not None:
                row[k] = own_target[k]
    return _finish(row)


def won_value(since, until, pipeline_id=None, owner_id=None, rate_map=None):
    """(deals, amount, revenue) won in [since, until) UTC, in the reporting currency; imported ones included."""
    rate_map = rate_map if rate_map is not None else rates()
    q = CrmLead.query.filter(CrmLead.status == 'won', CrmLead.closed_at >= since, CrmLead.closed_at < until)
    if pipeline_id:
        q = q.filter(CrmLead.pipeline_id == pipeline_id)
    if owner_id:
        q = q.filter(CrmLead.owner_id == owner_id)
    amount = revenue = ZERO
    n = 0
    missing = {}
    for cur, total, rev, cnt in (q.with_entities(CrmLead.currency, func.sum(CrmLead.amount),
                                                 func.sum(CrmLead.revenue), func.count(CrmLead.id))
                                 .group_by(CrmLead.currency)):
        n += cnt
        c = (cur or reporting_currency()).upper()
        if total is not None and c not in rate_map:
            missing[c] = missing.get(c, 0) + cnt
        amount += to_base(total, c, rate_map)
        revenue += to_base(rev if rev is not None else total, c, rate_map)
    return {'deals': n, 'amount': amount, 'revenue': revenue, 'missing_rates': sorted(missing),
            'missing_counts': missing}


def rate_warning(counts):
    """"3 leads in USD, 1 in GBP have no exchange rate - set it under Pipelines & products." or ''."""
    if not counts:
        return ''
    parts = ['%d lead%s in %s' % (n, '' if n == 1 else 's', c) if i == 0 else '%d in %s' % (n, c)
             for i, (c, n) in enumerate(sorted(counts.items()))]
    verb = 'have' if len(counts) > 1 or sum(counts.values()) != 1 else 'has'
    return '%s %s no exchange rate (counted as 0). Set %s under Pipelines & products.' % (
        ', '.join(parts), verb, 'the rate' if len(counts) == 1 else 'the rates')


def top_sellers(since, until, users, pipeline_id=None, rate_map=None):
    """Zoho's "prolific reps": [{'user', 'deals', 'amount', 'target', 'pct'}] by amount won, then deals.
    target: their month target(s) for the months the days touch, taken in proportion to the days covered."""
    rate_map = rate_map if rate_map is not None else rates()
    ids = [u.id for u in users]
    if not ids:
        return []
    q = (CrmLead.query.filter(CrmLead.status == 'won', CrmLead.closed_at >= since, CrmLead.closed_at < until,
                              CrmLead.owner_id.in_(ids)))
    if pipeline_id:
        q = q.filter(CrmLead.pipeline_id == pipeline_id)
    got = {i: {'deals': 0, 'amount': ZERO} for i in ids}
    for owner, cur, total, cnt in (q.with_entities(CrmLead.owner_id, CrmLead.currency, func.sum(CrmLead.amount),
                                                   func.count(CrmLead.id)).group_by(CrmLead.owner_id, CrmLead.currency)):
        got[owner]['deals'] += cnt
        got[owner]['amount'] += to_base(total, cur, rate_map)
    # target for the days: each month's target times the share of that month the days cover
    from app.services.crm_reports import IST
    d0 = (since + IST).date()
    d1 = (until + IST).date() - timedelta(days=1)
    share = {}
    d = d0
    while d <= d1:
        p = '%04d-%02d' % (d.year, d.month)
        share[p] = share.get(p, 0) + 1
        d += timedelta(days=1)
    targets = {}
    for p, covered in share.items():
        days_in = month_range(p)[1].day
        for key, t in targets_for(p, pipeline_id).items():
            if key[0] == 'u' and t.amount is not None:
                targets[key[1]] = targets.get(key[1], ZERO) + Decimal(t.amount) * covered / days_in
    out = []
    for u in users:
        g = got[u.id]
        tgt = targets.get(u.id)
        out.append({'user': u, 'deals': g['deals'], 'amount': g['amount'], 'target': tgt,
                    'pct': int(g['amount'] * 100 / tgt) if tgt else None})
    out.sort(key=lambda r: (-r['amount'], -r['deals'], r['user'].full_name or ''))
    return [r for r in out if r['deals']]


def my_target_line(user, today=None):
    """For My day: this month's target for `user`, or None when they have none.
    {'period', 'label', 'target', 'won', 'commit', 'pct'}."""
    today = today or date.today()
    period = '%04d-%02d' % (today.year, today.month)
    t = targets_for(period).get(('u', user.id))
    if t is None or t.amount is None:
        return None
    first, last = month_range(period)
    res = forecast(first, last, [user], months=[period])
    r = res['rows'][user.id]
    return {'period': period, 'label': period_start(period).strftime('%B'), 'target': Decimal(t.amount),
            'won': r['won'], 'commit': r['commit'], 'pct': r['pct'] or 0}


# ------------------------------------------------------------------------------- changing a lead's money

KEEP = object()


def _value_text(amount, currency):
    return money(amount, currency) if amount is not None else 'no value'


def _day_text(d):
    return ('%d %s' % (d.day, d.strftime('%b'))) if d else 'no date'


def change_value(lead, amount=KEEP, currency=KEEP, close_date=KEEP, forecast=KEEP, user=None):
    """Change a lead's value, close date and/or forecast category by hand. A line for each change goes on its
    history ("Value ₹12,000 → ₹18,500"); nothing is sent to the customer and nothing goes to WhatsApp.
    Raises ValueError for rubbish. Returns the lines written. No commit."""
    from app.services import crm
    lines = []
    if amount is not KEEP or currency is not KEEP:
        before = (lead.amount, lead.currency)
        new_amount = money_amount(amount) if amount is not KEEP else lead.amount
        if new_amount is None:
            lead.amount, lead.revenue = None, None
        else:
            set_amount(lead, new_amount, None if currency is KEEP else currency)
        if (before[0] != lead.amount) or (lead.amount is not None and before[1] != lead.currency):
            lines.append('Value %s → %s' % (_value_text(*before), _value_text(lead.amount, lead.currency)))
    if close_date is not KEEP:
        if close_date is not None and not isinstance(close_date, date):
            raise ValueError('date')
        if close_date != lead.close_date:
            lines.append('Closes %s → %s' % (_day_text(lead.close_date), _day_text(close_date)))
            lead.close_date = close_date
    if forecast is not KEEP:
        forecast = forecast or None
        if forecast is not None and forecast not in OPEN_FORECASTS:
            raise ValueError('forecast')
        if forecast != lead.forecast:
            lines.append('Counts in the forecast as: %s → %s' % (
                CRM_FORECASTS.get(lead.forecast, 'Automatic'), CRM_FORECASTS.get(forecast, 'Automatic')))
            lead.forecast = forecast
    for text in lines:
        crm.log_touch(lead, 'system', 'none', body=text, user=user, activity=False)
    return lines


def save_rates(form, actor=None):
    """The Exchange rates form: the reporting currency and a rate per other currency. Returns (saved, errors).
    A blank rate is left as it is; a bad one is reported and nothing is saved."""
    from app.services import settings
    errors, todo = {}, {}
    base = (form.get('reporting_currency') or reporting_currency()).strip().upper()
    if not CURRENCY_RE.match(base):
        errors['reporting_currency'] = 'Choose a currency.'
    for key in form:
        if not key.startswith('rate_'):
            continue
        code, raw = key[5:].upper(), (form.get(key) or '').strip()
        if not raw or code == base:
            continue
        try:
            value = dec(raw)
            if value is None or value <= 0 or value >= Decimal('100000000'):
                raise ValueError
            todo[code] = value
        except ValueError:
            errors[key] = 'Type the rate as a number, like 83.5.'
    if errors:
        return 0, errors
    if base != reporting_currency():
        settings.set_setting(SETTING_CURRENCY, base, actor=actor)
    n = 0
    for code, value in todo.items():
        row = db.session.get(CrmCurrencyRate, code)
        if row is None or Decimal(row.rate) != value:
            set_rate(code, value, actor)
            n += 1
    return n, {}
