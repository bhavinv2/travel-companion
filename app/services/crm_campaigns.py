"""Marketing activities and campaigns (Sales CRM 2.0, run 5b): Lead sources > Marketing activities -- one home.

Each row is a way we find people (platform, activity, who, where it stands; shown on How we sell) and, when it is a
campaign we pay for, the campaign key its links carry (utm_campaign), the lead source it feeds, its dates and its
cost. Sales results' "Campaigns" table counts each campaign's leads, customers won, won value, cost, cost per lead,
cost per customer and return (won value / cost), in the reporting currency (crm_money).

Why a table (crm_campaigns) and not the 'crm' setting any more: a cost is money (Numeric(12,2) and a currency, never
text in a JSON list), each workspace has its own campaigns (settings are global), and the report builder groups
leads by campaign. The migration copied the saved list into the first workspace.

Which leads are a campaign's: a lead whose utm_campaign is the campaign's key (any case); when the campaign names a
lead source as well, only that source's leads; with a source and no key, every lead of that source. Only leads that
came in between its first and last day (when given). Removed leads never count; each viewer sees only the leads their
role lets them see (crm_access).
"""
from collections import OrderedDict
from datetime import date, datetime, timedelta
from decimal import Decimal

from app import db
from app.models import CrmCampaign, CrmLead, CrmSource

IST = timedelta(hours=5, minutes=30)
MAX_ROWS = 80
COLS = ('platform', 'activity', 'who', 'status', 'utm', 'source', 'starts', 'ends', 'cost', 'currency')


class Default:
    """A starting row (crm_defaults.CHANNELS) shown until the first save -- never written by reading."""
    def __init__(self, n, platform, name, who, status):
        self.id, self.position = None, n
        self.platform, self.name, self.who, self.status = platform, name, who, status
        self.utm_campaign = self.source_id = self.starts_on = self.ends_on = self.cost = None
        self.currency = None


def rows():
    """The current workspace's activities, in order; the starting list while it has none."""
    got = CrmCampaign.query.order_by(CrmCampaign.position, CrmCampaign.id).all()
    if got:
        return got
    from app.services import crm_defaults
    return [Default(n, *c) for n, c in enumerate(crm_defaults.CHANNELS)]


def channels():
    """[[platform, activity, who, status]] for How we sell."""
    return [[r.platform or '', r.name or '', r.who or '', r.status or ''] for r in rows()]


def _day(text, label):
    text = (text or '').strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, '%Y-%m-%d').date()
    except ValueError:
        raise ValueError('%s: pick a date.' % label)


def parse(form):
    """(rows [dict], errors [text]) from the editor's aligned lists. A row needs a platform or an activity."""
    from app.services import crm_money
    cols = {k: form.getlist(k) for k in ('act_id',) + COLS}
    n = max(len(v) for v in cols.values()) if cols else 0
    sources = {str(s.id) for s in CrmSource.query.all()}
    out, errors = [], []
    for i in range(n):
        cell = lambda k: ((cols[k][i] if i < len(cols[k]) else '') or '').strip()       # noqa: E731
        r = {'id': int(cell('act_id')) if cell('act_id').isdigit() else None,
             'platform': cell('platform')[:200], 'name': cell('activity')[:200], 'who': cell('who')[:200],
             'status': cell('status')[:200], 'utm_campaign': cell('utm')[:120] or None}
        if not (r['platform'] or r['name']):
            if any(cell(k) for k in ('utm', 'source', 'starts', 'ends', 'cost')):
                errors.append('Row %d: give it a platform or an activity.' % (i + 1))
            continue
        label = r['name'] or r['platform']
        src = cell('source')
        if src and src not in sources:
            errors.append('%s: choose a lead source from the list.' % label)
            continue
        r['source_id'] = int(src) if src else None
        try:
            r['starts_on'], r['ends_on'] = _day(cell('starts'), label), _day(cell('ends'), label)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if r['starts_on'] and r['ends_on'] and r['ends_on'] < r['starts_on']:
            errors.append('%s: the last day is before the first day.' % label)
            continue
        try:
            r['cost'] = crm_money.money_amount(cell('cost'))
        except ValueError:
            errors.append('%s: type the cost as a number, like 25000.' % label)
            continue
        r['currency'] = crm_money.clean_currency(cell('currency')) if r['cost'] is not None else None
        out.append(r)
    return out[:MAX_ROWS], errors


def save(parsed):
    """Write the rows (the list on screen is the whole list): changed rows keep their id, new ones are added, rows
    no longer on screen are deleted. No commit. How many rows there are now."""
    have = {c.id: c for c in CrmCampaign.query.all()}
    keep = set()
    now = datetime.utcnow()
    for n, r in enumerate(parsed):
        row = have.get(r['id']) if r['id'] else None
        if row is None:
            row = CrmCampaign(created_at=now)
            db.session.add(row)
        for k in ('platform', 'name', 'who', 'status', 'utm_campaign', 'source_id', 'starts_on', 'ends_on', 'cost',
                  'currency'):
            setattr(row, k, r[k] if k == 'cost' else (r[k] or None))
        row.position = n
        row.updated_at = now
        if row.id:
            keep.add(row.id)
    for cid, row in have.items():
        if cid not in keep:
            db.session.delete(row)
    db.session.flush()
    return len(parsed)


def save_lines(text):
    """The old "Platform | Activity | Who | Where it stands" text box (How we sell's form): every line a row."""
    have = CrmCampaign.query.all()
    for row in have:
        db.session.delete(row)
    n = 0
    now = datetime.utcnow()
    for line in (text or '').splitlines():
        parts = [x.strip()[:200] for x in line.split('|')]
        if parts and parts[0]:
            p = (parts + ['', '', '', ''])[:4]
            db.session.add(CrmCampaign(platform=p[0] or None, name=p[1] or None, who=p[2] or None,
                                       status=p[3] or None, position=n, created_at=now, updated_at=now))
            n += 1
            if n >= MAX_ROWS:
                break
    db.session.flush()
    return n


# ============================================================================================ which leads

def is_campaign(c):
    return bool(getattr(c, 'utm_campaign', None) or getattr(c, 'source_id', None))


def _ist_day(dt):
    return (dt + IST).date() if dt else None


def owns(c, utm, source_id, created_at):
    """Is a lead (its utm dict, source id and when it came in) one of campaign `c`'s?"""
    if not is_campaign(c):
        return False
    key = (c.utm_campaign or '').strip().lower()
    if key:
        got = str((utm or {}).get('utm_campaign') or '').strip().lower() if isinstance(utm, dict) else ''
        if got != key:
            return False
    if c.source_id and source_id != c.source_id:
        return False
    day = _ist_day(created_at)
    if c.starts_on and (day is None or day < c.starts_on):
        return False
    if c.ends_on and (day is None or day > c.ends_on):
        return False
    return True


def campaign_of(campaigns, utm, source_id, created_at):
    """The first campaign (in the list's order) a lead belongs to, or None (the report builder's grouping)."""
    return next((c for c in campaigns if owns(c, utm, source_id, created_at)), None)


def label(c):
    return ' · '.join(x for x in (c.name, c.platform) if x) or (c.utm_campaign or 'A campaign')


# ============================================================================================ the Results table

def _ratio(a, b):
    return (a / b) if b else None


def results(user, first=None, last=None):
    """Sales results' Campaigns table: [{'campaign', 'name', 'leads', 'won', 'won_value', 'cost', 'per_lead',
    'per_customer', 'ret'}] for the campaigns that ran between `first` and `last` (India days; each campaign is
    counted over its own dates), and the notes (a currency with no rate). Visibility, workspace and bin hold."""
    from app.services import crm_access, crm_money
    camps = [c for c in CrmCampaign.query.order_by(CrmCampaign.position, CrmCampaign.id).all()
             if is_campaign(c) or c.cost is not None]
    if first is not None:
        camps = [c for c in camps if not (c.ends_on and c.ends_on < first) and not (last and c.starts_on and c.starts_on > last)]
    if not camps:
        return {'rows': [], 'notes': [], 'currency': crm_money.reporting_currency()}
    starts = [c.starts_on for c in camps if is_campaign(c)]
    q = (db.session.query(CrmLead.id, CrmLead.utm, CrmLead.source_id, CrmLead.created_at, CrmLead.status,
                          CrmLead.amount, CrmLead.currency)
         .filter(CrmLead.deleted_at.is_(None), CrmLead.imported.is_(False)))
    if starts and all(starts):
        q = q.filter(CrmLead.created_at >= datetime.combine(min(starts), datetime.min.time()) - IST)
    crit = crm_access.lead_filter(user)
    if crit is not None:
        q = q.filter(crit)
    src_ids = [c.source_id for c in camps if c.source_id]
    from sqlalchemy import or_
    q = q.filter(or_(CrmLead.utm.isnot(None), CrmLead.source_id.in_(src_ids or [0])))
    leads = q.all()
    rates = crm_money.rates()
    missing = set()
    out = []
    for c in camps:
        n = won = 0
        won_value = Decimal(0)
        for lid, utm, sid, created, status, amount, cur in leads:
            if not owns(c, utm, sid, created):
                continue
            n += 1
            if status == 'won':
                won += 1
                if amount is not None:
                    code = (cur or crm_money.reporting_currency()).upper()
                    if code not in rates:
                        missing.add(code)
                    won_value += crm_money.to_base(amount, code, rates)
        cost = None
        if c.cost is not None:
            code = (c.currency or crm_money.reporting_currency()).upper()
            if code not in rates:
                missing.add(code)
            cost = crm_money.to_base(c.cost, code, rates)
        out.append({'campaign': c, 'name': label(c), 'leads': n, 'won': won, 'won_value': won_value, 'cost': cost,
                    'per_lead': _ratio(cost, n) if cost else None, 'per_customer': _ratio(cost, won) if cost else None,
                    'ret': _ratio(won_value, cost) if cost else None, 'counted': is_campaign(c)})
    notes = []
    if missing:
        notes.append('No exchange rate for %s, so that money counts as 0. Set the rate in Pipelines & products.'
                     % ', '.join(sorted(missing)))
    return {'rows': out, 'notes': notes, 'currency': crm_money.reporting_currency()}


def ret_text(ret):
    """'3.2×' for a return; '—' when there is no cost."""
    if ret is None:
        return '—'
    from decimal import ROUND_HALF_UP
    text = format(Decimal(str(ret)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), 'f')
    return '%s×' % (text.rstrip('0').rstrip('.') if '.' in text else text)
