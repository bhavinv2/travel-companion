"""One set of numbers (Sales CRM 2.0, phase 2): every number the Sales CRM shows is defined once, here.

    METRICS            ordered {key: Metric(key, label, definition, unit, kind, compute)}
    compute()          one number for some days and a scope
    bundle()           several at once (one query for all the saved ones)
    by_owner()         the same, per person, with GROUP BY in SQL
    daily_by_owner()   per person and India day (the per-person download)
    definition(key)    the one plain sentence behind a number's (i); `metric_tip('won')` in templates

A metric is one of two kinds:

  event   something that happened between two moments (leads that came in, messages sent, deals won). It can be
          added up day by day, so each India day is saved once in `crm_daily_stats` (snapshot_day) and a period that
          ends before today is the sum of its saved days. Today is always counted live, and so is any period whose
          days are not all saved yet. Both ways give the same answer (tests/test_crm2_numbers.py).
  state   how things stand now, or a cohort (open leads, customers waiting, a median time). Always live.

Scope: dict(pipeline_id=None, owner_ids=None, team_id=None, now=None). "Owner" is whoever looks after the lead
(CrmLead.owner_id), except for what a person does themselves -- calls, follow-ups done, moves, leads added,
messages typed -- which belong to that person. Days are India days; `since` / `until` are UTC ([since, until)).

Days before today are saved at night and kept as they were: later changes to old leads do not rewrite them
(`recalculate()` rebuilds the last days on request).
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median
from typing import Callable, Optional

from sqlalchemy import func, select

from app import db
from app.models import (CrmDailyStat, CrmLead, CrmStage, CrmStageChange, CrmTask, CrmTouchpoint,
                        WorkspaceTeam)
from app.services import crm_metrics, crm_money, crm_scope

IST = timedelta(hours=5, minutes=30)
KEEP_DAYS = 180                  # how far back the night job fills in
CENT = Decimal('0.01')
NO_REASON = 'No reason given'


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    definition: str                         # ONE plain sentence: the (i) wherever the number appears
    unit: str                               # count / money / minutes / percent
    kind: str                               # event / state
    compute: Optional[Callable] = None      # event: (since, until, pipeline_id, owners) -> [(user, pipeline, value)]
    #                                         state: (since, until, pipeline_id, owners, now) -> number
    per_owner: Optional[Callable] = None    # state: (since, until, pipeline_id, owners, now) -> {user_id: value}
    snapshot: bool = True                   # event only: saved in crm_daily_stats
    breakdown: bool = False                 # compute returns a list of (name, n) instead of grouped rows


# ============================================================================================ helpers

def day_bounds(day):
    """UTC [start, end) of an India day."""
    start = datetime.combine(day, datetime.min.time()) - IST
    return start, start + timedelta(days=1)


def ist_day(dt):
    return (dt + IST).date() if dt else None


def today_ist(now=None):
    return ((now or datetime.utcnow()) + IST).date()


def _lead_conds(pid, owners):
    out = []
    if pid:
        out.append(CrmLead.pipeline_id == pid)
    if owners is not None:
        out.append(CrmLead.owner_id.in_(list(owners)))
    return out


def _rows(query):
    return [(u, p, v) for u, p, v in query.all()]


def resolve_scope(scope=None):
    """(pipeline_id, owner ids or None, now, live) from a scope dict; a team becomes its members."""
    scope = scope or {}
    pid = scope.get('pipeline_id') or None
    owners = scope.get('owner_ids')
    owners = None if owners is None else sorted({int(i) for i in owners if i})
    team_id = scope.get('team_id')
    if team_id:
        team = db.session.get(WorkspaceTeam, int(team_id))
        members = {u.id for u in team.users} if team is not None else set()
        owners = sorted(members if owners is None else members & set(owners))
    return pid, owners, scope.get('now') or datetime.utcnow(), bool(scope.get('live'))


def scope(pipeline_id=None, owner_ids=None, team_id=None, **extra):
    return dict(pipeline_id=pipeline_id, owner_ids=owner_ids, team_id=team_id, **extra)


def _money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


# ============================================================================================ event metrics

def _new_leads(since, until, pid, owners):
    return _rows(db.session.query(CrmLead.owner_id, CrmLead.pipeline_id, func.count(CrmLead.id))
                 .filter(CrmLead.created_at >= since, CrmLead.created_at < until, CrmLead.imported.is_(False),
                         *_lead_conds(pid, owners))
                 .group_by(CrmLead.owner_id, CrmLead.pipeline_id))


def reply_conds():
    """What counts as a reply from them: a message in (not the form they sent), not one brought in from before.
    The one definition: the "Replied" number and lead scoring's "they replied" both use it."""
    tp = CrmTouchpoint
    return (tp.direction == 'in', tp.channel != 'form', func.coalesce(tp.status, '') != 'imported')


def _replied(since, until, pid, owners):
    tp = CrmTouchpoint
    first_in = (select(tp.lead_id.label('lead_id'), func.min(tp.created_at).label('t'))
                .where(*reply_conds(), tp.lead_id.isnot(None))
                .group_by(tp.lead_id).subquery())
    return _rows(db.session.query(CrmLead.owner_id, CrmLead.pipeline_id, func.count(CrmLead.id))
                 .join(first_in, first_in.c.lead_id == CrmLead.id)
                 .filter(first_in.c.t >= since, first_in.c.t < until, *_lead_conds(pid, owners))
                 .group_by(CrmLead.owner_id, CrmLead.pipeline_id))


def _quoted_leads(since, until, pid, owners):
    from app.services import crm_kpi
    sc = CrmStageChange
    stages = [sid for sid, role in crm_kpi.stage_roles().items() if role == 'pipeline']
    if not stages:
        return []
    first_quote = (select(sc.lead_id.label('lead_id'), func.min(sc.created_at).label('t'))
                   .where(sc.to_stage_id.in_(stages), ~func.coalesce(sc.reason, '').like('Sales sheet%'))
                   .group_by(sc.lead_id).subquery())
    return _rows(db.session.query(CrmLead.owner_id, CrmLead.pipeline_id, func.count(CrmLead.id))
                 .join(first_quote, first_quote.c.lead_id == CrmLead.id)
                 .filter(first_quote.c.t >= since, first_quote.c.t < until, CrmLead.imported.is_(False),
                         *_lead_conds(pid, owners))
                 .group_by(CrmLead.owner_id, CrmLead.pipeline_id))


def _marked(code):
    """Times somebody marked a step (Q = quote, PLS = payment link) as sent on a lead. THE MILESTONE LINE WINS: the
    "Quote sent" / "Payment link sent" lines are counted, and a quote or payment row (Phase 4b) counts by itself
    only when it logged no such line (its pipeline has no such button) -- so a row and its line are one."""
    def fn(since, until, pid, owners):
        from app.models import CrmPayment, CrmQuote
        tp = CrmTouchpoint
        got = defaultdict(int)
        for owner, pipe, n in _rows(
                db.session.query(CrmLead.owner_id, CrmLead.pipeline_id, func.count(tp.id))
                .select_from(tp).outerjoin(CrmLead, CrmLead.id == tp.lead_id)
                .filter(*mark_conds(code), tp.created_at >= since, tp.created_at < until,
                        *_lead_conds(pid, owners))
                .group_by(CrmLead.owner_id, CrmLead.pipeline_id)):
            got[(owner, pipe)] += n
        if code == 'Q':
            when, row, mark = CrmQuote.sent_at, CrmQuote, CrmQuote.sent_touch_id
        else:
            when, row, mark = CrmPayment.created_at, CrmPayment, CrmPayment.link_touch_id
        for owner, pipe, n in _rows(
                db.session.query(CrmLead.owner_id, CrmLead.pipeline_id, func.count(row.id))
                .select_from(row).join(CrmLead, CrmLead.id == row.lead_id)
                .filter(when >= since, when < until, mark.is_(None), *_lead_conds(pid, owners))
                .group_by(CrmLead.owner_id, CrmLead.pipeline_id)):
            got[(owner, pipe)] += n
        return [(o, p, n) for (o, p), n in got.items()]
    return fn


def mark_conds(code):
    """A "Quote sent" (Q) / "Payment link sent" (PLS) line: the milestone touches the numbers count (see _marked)."""
    tp = CrmTouchpoint
    return (tp.code == code, func.coalesce(tp.status, '') != 'imported')


# ---------------------------------------------------------------------------- the same signals, per lead
# Lead scoring (services/crm_scoring) asks "has this lead had X?" with the registry's own definitions, so a lead
# scores "quote sent" exactly when the Quotes sent number counts it.

def leads_replied(lead_ids):
    """The ids among `lead_ids` with a reply from them (reply_conds)."""
    ids = [i for i in lead_ids if i]
    if not ids:
        return set()
    tp = CrmTouchpoint
    return {r[0] for r in db.session.query(tp.lead_id).filter(tp.lead_id.in_(ids), *reply_conds()).distinct()}


def last_replies(lead_ids):
    """{lead id: when they last replied} (reply_conds)."""
    ids = [i for i in lead_ids if i]
    if not ids:
        return {}
    tp = CrmTouchpoint
    return dict(db.session.query(tp.lead_id, func.max(tp.created_at)).filter(tp.lead_id.in_(ids), *reply_conds())
                .group_by(tp.lead_id).all())


def leads_marked(code, lead_ids):
    """The ids among `lead_ids` with a quote (Q) / payment link (PLS) sent: its milestone line, or -- in a pipeline
    with no such button -- the quote / payment row itself, exactly as _marked counts them."""
    from app.models import CrmPayment, CrmQuote
    ids = [i for i in lead_ids if i]
    if not ids:
        return set()
    tp = CrmTouchpoint
    got = {r[0] for r in db.session.query(tp.lead_id).filter(tp.lead_id.in_(ids), *mark_conds(code)).distinct()}
    if code == 'Q':
        rows = db.session.query(CrmQuote.lead_id).filter(CrmQuote.lead_id.in_(ids), CrmQuote.sent_at.isnot(None),
                                                         CrmQuote.sent_touch_id.is_(None))
    else:
        rows = db.session.query(CrmPayment.lead_id).filter(CrmPayment.lead_id.in_(ids),
                                                           CrmPayment.link_touch_id.is_(None))
    return got | {r[0] for r in rows.distinct()}


def _closed(status):
    def fn(since, until, pid, owners):
        return _rows(db.session.query(CrmLead.owner_id, CrmLead.pipeline_id, func.count(CrmLead.id))
                     .filter(CrmLead.status == status, CrmLead.closed_at >= since, CrmLead.closed_at < until,
                             *_lead_conds(pid, owners))
                     .group_by(CrmLead.owner_id, CrmLead.pipeline_id))
    return fn


def _won_money(which):
    """Money on the leads won, in the reporting currency (`which`: 'amount' or 'revenue')."""
    def fn(since, until, pid, owners):
        rate_map = crm_money.rates()
        acc = defaultdict(lambda: crm_money.ZERO)
        q = (db.session.query(CrmLead.owner_id, CrmLead.pipeline_id, CrmLead.currency,
                              func.sum(CrmLead.amount), func.sum(CrmLead.revenue))
             .filter(CrmLead.status == 'won', CrmLead.closed_at >= since, CrmLead.closed_at < until,
                     *_lead_conds(pid, owners))
             .group_by(CrmLead.owner_id, CrmLead.pipeline_id, CrmLead.currency))
        for owner, pipe, cur, total, rev in q:
            c = (cur or crm_money.reporting_currency()).upper()
            got = total if which == 'amount' else (rev if rev is not None else total)
            acc[(owner, pipe)] += crm_money.to_base(got, c, rate_map)
        return [(o, p, _money(v)) for (o, p), v in acc.items()]
    return fn


def _lost_by_reason(since, until, pid, owners):
    rows = (db.session.query(CrmLead.fallout_reason, func.count(CrmLead.id))
            .filter(CrmLead.status == 'lost', CrmLead.closed_at >= since, CrmLead.closed_at < until,
                    *_lead_conds(pid, owners))
            .group_by(CrmLead.fallout_reason).all())
    merged = {}
    for reason, n in rows:
        name = (reason or '').strip() or NO_REASON
        merged[name] = merged.get(name, 0) + n
    return sorted(merged.items(), key=lambda x: (-x[1], x[0]))


def _messages(kind):
    """Messages we sent (not calls, notes or forms; not brought-in history), by who sent them."""
    def fn(since, until, pid, owners):
        tp = CrmTouchpoint
        via = crm_metrics.via_expr()
        who = {'people': via == crm_metrics.VIA_PERSON, 'broadcast': via == 'broadcast',
               'auto': ~via.in_((crm_metrics.VIA_PERSON, 'broadcast', 'import'))}[kind]
        return _rows(db.session.query(CrmLead.owner_id, CrmLead.pipeline_id, func.count(tp.id))
                     .select_from(tp).outerjoin(CrmLead, CrmLead.id == tp.lead_id)
                     .filter(tp.direction == 'out', tp.channel.notin_(('call', 'system', 'note', 'form')),
                             func.coalesce(tp.status, '') != 'imported', tp.created_at >= since,
                             tp.created_at < until, who, *_lead_conds(pid, owners))
                     .group_by(CrmLead.owner_id, CrmLead.pipeline_id))
    return fn


def _customer_messages(whatsapp_only):
    """Messages customers sent on leads (a form is not a message; brought-in history is not counted)."""
    def fn(since, until, pid, owners):
        tp = CrmTouchpoint
        cond = [tp.channel == 'whatsapp'] if whatsapp_only else [tp.channel != 'form']
        return _rows(db.session.query(CrmLead.owner_id, CrmLead.pipeline_id, func.count(tp.id))
                     .select_from(tp).outerjoin(CrmLead, CrmLead.id == tp.lead_id)
                     .filter(tp.direction == 'in', func.coalesce(tp.status, '') != 'imported',
                             tp.created_at >= since, tp.created_at < until, *cond, *_lead_conds(pid, owners))
                     .group_by(CrmLead.owner_id, CrmLead.pipeline_id))
    return fn


def _by_agent(kind):
    """What a person did themselves: calls made, calls answered, messages typed."""
    def fn(since, until, pid, owners):
        tp = CrmTouchpoint
        if kind == 'messages':
            what = [tp.channel != 'call']
        else:
            what = [tp.channel == 'call'] + ([tp.outcome == 'connected'] if kind == 'connected' else [])
        conds = [tp.direction == 'out', func.coalesce(tp.status, '') != 'imported', tp.created_at >= since,
                 tp.created_at < until, *what]
        if owners is not None:
            conds.append(tp.agent_id.in_(list(owners)))
        if pid:
            conds.append(CrmLead.pipeline_id == pid)
        return _rows(db.session.query(tp.agent_id, CrmLead.pipeline_id, func.count(tp.id))
                     .select_from(tp).outerjoin(CrmLead, CrmLead.id == tp.lead_id)
                     .filter(*conds).group_by(tp.agent_id, CrmLead.pipeline_id))
    return fn


def _followups_done(since, until, pid, owners):
    conds = [CrmTask.status == 'done', CrmTask.done_at >= since, CrmTask.done_at < until]
    if owners is not None:
        conds.append(CrmTask.done_by_id.in_(list(owners)))
    if pid:
        conds.append(CrmLead.pipeline_id == pid)
    return _rows(db.session.query(CrmTask.done_by_id, CrmLead.pipeline_id, func.count(CrmTask.id))
                 .select_from(CrmTask).outerjoin(CrmLead, CrmLead.id == CrmTask.lead_id)
                 .filter(*conds).group_by(CrmTask.done_by_id, CrmLead.pipeline_id))


def _followups_due(since, until, pid, owners):
    conds = [CrmTask.due_at >= since, CrmTask.due_at < until]
    if owners is not None:
        conds.append(CrmTask.owner_id.in_(list(owners)))
    if pid:
        conds.append(CrmLead.pipeline_id == pid)
    return _rows(db.session.query(CrmTask.owner_id, CrmLead.pipeline_id, func.count(CrmTask.id))
                 .select_from(CrmTask).outerjoin(CrmLead, CrmLead.id == CrmTask.lead_id)
                 .filter(*conds).group_by(CrmTask.owner_id, CrmLead.pipeline_id))


def _moves(since, until, pid, owners):
    conds = [CrmStageChange.from_stage_id.isnot(None), CrmStage.kind == 'open',
             CrmStageChange.created_at >= since, CrmStageChange.created_at < until]
    if owners is not None:
        conds.append(CrmStageChange.by_id.in_(list(owners)))
    if pid:
        conds.append(CrmLead.pipeline_id == pid)
    return _rows(db.session.query(CrmStageChange.by_id, CrmLead.pipeline_id, func.count(CrmStageChange.id))
                 .select_from(CrmStageChange).join(CrmStage, CrmStage.id == CrmStageChange.to_stage_id)
                 .outerjoin(CrmLead, CrmLead.id == CrmStageChange.lead_id)
                 .filter(*conds).group_by(CrmStageChange.by_id, CrmLead.pipeline_id))


def _leads_added(since, until, pid, owners):
    conds = [CrmLead.created_at >= since, CrmLead.created_at < until, CrmLead.imported.is_(False)]
    if owners is not None:
        conds.append(CrmLead.created_by_id.in_(list(owners)))
    if pid:
        conds.append(CrmLead.pipeline_id == pid)
    return _rows(db.session.query(CrmLead.created_by_id, CrmLead.pipeline_id, func.count(CrmLead.id))
                 .filter(*conds).group_by(CrmLead.created_by_id, CrmLead.pipeline_id))


# ============================================================================================ state metrics

def _open_leads(since, until, pid, owners, now):
    return db.session.query(func.count(CrmLead.id)).filter(
        CrmLead.status == 'open', *_lead_conds(pid, owners)).scalar() or 0


def _open_leads_by(since, until, pid, owners, now):
    return dict(db.session.query(CrmLead.owner_id, func.count(CrmLead.id))
                .filter(CrmLead.status == 'open', CrmLead.owner_id.isnot(None), *_lead_conds(pid, owners))
                .group_by(CrmLead.owner_id).all())


def _late_conds(pid, owners, now):
    conds = [CrmTask.status == 'open', CrmTask.due_at < now]
    if owners is not None:
        conds.append(CrmTask.owner_id.in_(list(owners)))
    if pid:
        conds.append(CrmLead.pipeline_id == pid)
    return conds


def _late(since, until, pid, owners, now):
    q = db.session.query(func.count(CrmTask.id))
    if pid:
        q = q.select_from(CrmTask).join(CrmLead, CrmLead.id == CrmTask.lead_id)
    return q.filter(*_late_conds(pid, owners, now)).scalar() or 0


def _late_by(since, until, pid, owners, now):
    q = db.session.query(CrmTask.owner_id, func.count(CrmTask.id)).select_from(CrmTask)
    if pid:
        q = q.join(CrmLead, CrmLead.id == CrmTask.lead_id)
    return dict(q.filter(*_late_conds(pid, owners, now), CrmTask.owner_id.isnot(None))
                .group_by(CrmTask.owner_id).all())


def _waiting(since, until, pid, owners, now):
    return crm_metrics.waiting_people(
        select(CrmLead.person_id).where(CrmLead.status == 'open', *_lead_conds(pid, owners)))


def _owner_ids_with_open_leads(pid, owners):
    if owners is not None:
        return list(owners)
    return [r[0] for r in db.session.query(CrmLead.owner_id).filter(
        CrmLead.status == 'open', CrmLead.owner_id.isnot(None), *_lead_conds(pid, None)).distinct().all()]


def _waiting_by(since, until, pid, owners, now):
    return crm_metrics.waiting_by_owner(_owner_ids_with_open_leads(pid, owners), pid)


def _cohort(since, until, pid, owners):
    return [CrmLead.created_at >= since, CrmLead.created_at < until, CrmLead.imported.is_(False),
            *_lead_conds(pid, owners)]


def _first_contact(since, until, pid, owners, now):
    return crm_metrics.first_contact_minutes(select(CrmLead.id).where(*_cohort(since, until, pid, owners)))


def _first_contact_by(since, until, pid, owners, now):
    by = defaultdict(list)
    for owner, m in crm_metrics.first_contact_samples(select(CrmLead.id).where(*_cohort(since, until, pid, owners))):
        if owner is not None:
            by[owner].append(m)
    return {o: round(median(v)) for o, v in by.items()}


def _reply(since, until, pid, owners, now):
    scope_ = _lead_conds(pid, owners)
    return crm_metrics.reply_minutes(since, until, select(CrmLead.person_id).where(*scope_) if scope_ else None, now)


def _reply_by(since, until, pid, owners, now):
    """Per person who answered: the median wait for the first answer a person gave."""
    people = select(CrmLead.person_id).where(*_lead_conds(pid, None)) if pid else None
    by = defaultdict(list)
    for agent, minutes in crm_metrics._reply_samples(since, until, now, people):
        if owners is None or agent in owners:
            by[agent].append(minutes)
    return {a: round(median(v)) for a, v in by.items()}


def _unanswered_by(since, until, pid, owners, now):
    ids = list(owners) if owners is not None else [
        r[0] for r in db.session.query(CrmLead.owner_id).filter(CrmLead.owner_id.isnot(None)).distinct().all()]
    return crm_metrics.unanswered_by_owner(since, min(until, now), ids)


def _sum_of(by_fn):
    def fn(since, until, pid, owners, now):
        return sum(by_fn(since, until, pid, owners, now).values())
    return fn


# ============================================================================================ the registry

def _m(key, label, definition, unit, kind, compute=None, **kw):
    return Metric(key, label, definition, unit, kind, compute, **kw)


_LIST = [
    # ---- what happened (event) -------------------------------------------------------------------------
    _m('new_leads', 'New leads',
       'Leads that came in during these days. Leads brought in from a list or the sales sheet are not counted.',
       'count', 'event', _new_leads),
    _m('replied', 'Replied',
       'Leads whose customer wrote back for the first time during these days, on any channel. A form is not a reply.',
       'count', 'event', _replied),
    _m('quoted_leads', 'Quoted',
       'Leads that reached a stage meaning Quoted for the first time during these days.',
       'count', 'event', _quoted_leads),
    _m('quoted', 'Quote sent',
       'How often somebody marked a quote as sent on a lead during these days (the "I sent the quote" button, or a quote marked as sent).', 'count', 'event', _marked('Q')),
    _m('payment_links', 'Payment link sent',
       'How often somebody marked a payment link as sent on a lead during these days (the "I sent the payment link" button, or a payment link added).',
       'count', 'event', _marked('PLS')),
    _m('won', 'Won',
       'Leads marked Won between these dates, whenever they came in.', 'count', 'event', _closed('won')),
    _m('won_value', 'Won value',
       'The money on the leads won in these days, added up in the reporting currency.',
       'money', 'event', _won_money('amount')),
    _m('revenue', 'Our revenue',
       'What we earn on the leads won in these days: the whole amount, a fixed amount or a percentage, as set for '
       'each product.', 'money', 'event', _won_money('revenue')),
    _m('lost', 'Lost', 'Leads marked Lost between these dates, whenever they came in.',
       'count', 'event', _closed('lost')),
    _m('lost_by_reason', 'Why we lost leads', 'Leads lost during these days, by the reason given.',
       'count', 'event', _lost_by_reason, snapshot=False, breakdown=True),
    _m('messages_people', 'Messages from people',
       'Messages a person sent on a lead during these days. Calls are not messages.',
       'count', 'event', _messages('people')),
    _m('messages_auto', 'Automatic messages',
       'Messages sent by themselves during these days: follow-ups, reply rules, the chatbot and AI replies.',
       'count', 'event', _messages('auto')),
    _m('messages_broadcast', 'Broadcast messages', 'Messages that went out in a broadcast during these days.',
       'count', 'event', _messages('broadcast')),
    _m('replies_in', 'Messages from customers',
       'Messages customers sent on a lead during these days, on any channel. A form is not a message.',
       'count', 'event', _customer_messages(False)),
    _m('whatsapp_replies', 'WhatsApp replies received',
       'WhatsApp messages customers sent on their leads that day.', 'count', 'event', _customer_messages(True)),
    _m('calls', 'Calls', 'Calls they logged in these days.', 'count', 'event', _by_agent('calls')),
    _m('calls_connected', 'Calls answered', 'Calls they logged in these days where the customer picked up.',
       'count', 'event', _by_agent('connected')),
    _m('messages_by_agent', 'Messages sent', 'Messages they typed or sent themselves in these days. Calls are not messages.',
       'count', 'event', _by_agent('messages')),
    _m('followups_due', 'Follow-ups due', 'Follow-ups that were due in these days, done or not.',
       'count', 'event', _followups_due),
    _m('followups_done', 'Follow-ups done', 'Follow-ups that they finished in these days, on time or late.',
       'count', 'event', _followups_done),
    _m('moves', 'Leads moved on', 'Times they moved a lead to a later open step in these days.',
       'count', 'event', _moves),
    _m('leads_added', 'Leads they added', 'Leads they added themselves in these days; brought-in leads are not counted.',
       'count', 'event', _leads_added),
    # ---- how things stand (state) ----------------------------------------------------------------------
    _m('first_contact_minutes', 'First contact time',
       'How long new leads waited for the first message or call from a person; half waited less. '
       'Automatic messages are not counted, nor leads nobody has contacted yet.',
       'minutes', 'state', _first_contact, per_owner=_first_contact_by),
    _m('reply_minutes', 'Reply time',
       "How long customers waited for a person's answer after they wrote; half waited less. "
       'Automatic replies are not counted.',
       'minutes', 'state', _reply, per_owner=_reply_by),
    _m('waiting_now', 'Customers waiting now',
       'Customers who wrote last on WhatsApp, Instagram or Facebook and have no answer yet. Right now.',
       'count', 'state', _waiting, per_owner=_waiting_by),
    _m('open_leads', 'Open leads', 'Leads they look after that are not won or lost yet. Right now.',
       'count', 'state', _open_leads, per_owner=_open_leads_by),
    _m('late_followups', 'Late follow-ups', 'Their follow-ups past due and not done yet. Right now.',
       'count', 'state', _late, per_owner=_late_by),
    _m('unanswered', 'Left unanswered at day end',
       'Customers who wrote that day and had no answer when it ended (today: so far).',
       'count', 'state', _sum_of(_unanswered_by), per_owner=_unanswered_by),
    # ---- numbers other screens work out, defined here so their (i) reads from one place ------------------
    _m('followups_done_of_due', 'Follow-ups done (of due)',
       'Follow-ups due that day that they did, of all that were due.', 'count', 'event'),
    _m('checks', 'Checks', 'Half hours they ticked on the half-hourly check that day.', 'count', 'event'),
    _m('last_active', 'Last active', 'Their last action in the Sales CRM that day (India time).', 'count', 'event'),
    _m('forecast_target', 'Target', 'The money a person or team aims to win in the month, set under Targets.',
       'money', 'state'),
    _m('forecast_won', 'Closed won', 'Money already won: leads marked Won in these days, added up in the reporting currency.',
       'money', 'state'),
    _m('forecast_commit', 'Committed',
       'Money on open leads closing in these days whose payment link was sent or who promised to pay.',
       'money', 'state'),
    _m('forecast_best_case', 'Best case', 'Money on open leads closing in these days whose quote is out.',
       'money', 'state'),
    _m('forecast_pipeline', 'Pipeline', 'Money on open leads closing in these days that are still talking or early.',
       'money', 'state'),
    _m('forecast_gap', 'Gap to target', 'The target minus the money already won; what is still to win.',
       'money', 'state'),
    _m('target_progress', 'Progress to target', 'The money won so far this month as a share of the target.',
       'percent', 'state'),
]
METRICS = {m.key: m for m in _LIST}
SNAP_KEYS = [m.key for m in _LIST if m.kind == 'event' and m.compute is not None and m.snapshot]

# the cards of Results use these metrics
CARD_METRIC = {'new_leads': 'new_leads', 'replied': 'replied', 'quoted': 'quoted_leads', 'won': 'won',
               'first_contact': 'first_contact_minutes', 'reply_time': 'reply_minutes', 'waiting_now': 'waiting_now'}


def definition(key):
    """The one sentence behind a number's (i)."""
    m = METRICS.get(key)
    return m.definition if m else ''


def card_definition(card):
    """The same for a card of Results ('quoted' there is the metric quoted_leads)."""
    return definition(CARD_METRIC.get(card, card))


def _number(m, value):
    """A count as an int, money as Decimal, a time as it is."""
    if value is None:
        return None
    if m.unit == 'money':
        return Decimal(value)
    if m.unit == 'count':
        return int(value)
    return value


# ============================================================================================ saved days

def _present_days(days):
    """{day: True} for the India days (a list) whose numbers are all saved: a company row for every saved metric."""
    if not days:
        return set()
    rows = (db.session.query(CrmDailyStat.day, func.count(func.distinct(CrmDailyStat.metric)))
            .filter(CrmDailyStat.day >= min(days), CrmDailyStat.day <= max(days),
                    CrmDailyStat.user_id.is_(None), CrmDailyStat.pipeline_id.is_(None),
                    CrmDailyStat.metric.in_(SNAP_KEYS))
            .group_by(CrmDailyStat.day).all())
    return {d for d, n in rows if n >= len(SNAP_KEYS)}


def _saved(keys, first, last, pid, owners, per_user):
    """Add up the saved days first..last (inclusive). per_user False: {key: total}; True: {key: {user: total}}."""
    q = db.session.query(CrmDailyStat.metric, CrmDailyStat.user_id, func.sum(CrmDailyStat.value)).filter(
        CrmDailyStat.day >= first, CrmDailyStat.day <= last, CrmDailyStat.metric.in_(list(keys)),
        CrmDailyStat.pipeline_id == pid if pid else CrmDailyStat.pipeline_id.is_(None))
    if owners is not None:
        q = q.filter(CrmDailyStat.user_id.in_(list(owners)))
    elif per_user:
        q = q.filter(CrmDailyStat.user_id.isnot(None))
    else:
        q = q.filter(CrmDailyStat.user_id.is_(None))
    q = q.group_by(CrmDailyStat.metric, CrmDailyStat.user_id)
    out = {}
    for metric, uid, total in q.all():
        if per_user:
            out.setdefault(metric, {})[uid] = Decimal(total)
        else:
            out[metric] = out.get(metric, Decimal(0)) + Decimal(total)
    return out


def _split(since, until, now=None):
    """The part of [since, until) made of whole India days before today (first day, last day, their UTC
    bounds), or None; everything else is counted live."""
    today = today_ist(now)
    end = min(until, day_bounds(today)[0])
    first = ist_day(since)
    if day_bounds(first)[0] < since:
        first += timedelta(days=1)
    stop = ist_day(end)                      # the day `end` falls in: not a whole day before it
    if first >= stop:
        return None
    return first, stop - timedelta(days=1), day_bounds(first)[0], day_bounds(stop)[0]


def _live_rows(m, since, until, pid, owners):
    return m.compute(since, until, pid, owners)


def _live_total(m, since, until, pid, owners):
    return sum((Decimal(v) if m.unit == 'money' else v for _, _, v in _live_rows(m, since, until, pid, owners)),
               Decimal(0) if m.unit == 'money' else 0)


def _live_by_user(m, since, until, pid, owners):
    out = defaultdict(lambda: Decimal(0) if m.unit == 'money' else 0)
    for u, _, v in _live_rows(m, since, until, pid, owners):
        if u is not None:
            out[u] += v
    return dict(out)


# ============================================================================================ asking

def _event_values(keys, since, until, pid, owners, now, live, per_user):
    """{key: total} (or {key: {user: value}} when per_user) for the event metrics `keys`: saved days where they are
    all there, live for the rest."""
    keys = list(keys)
    plan = None if live else _split(since, until, now)
    if plan is not None:
        first, last, a, b = plan
        days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
        if len(_present_days(days)) != len(days):
            plan = None
    out = {}
    saved = {}
    if plan is not None:
        snap_keys = [k for k in keys if k in SNAP_KEYS]
        saved = _saved(snap_keys, first, last, pid, owners, per_user) if snap_keys else {}
    for k in keys:
        m = METRICS[k]
        pieces = []
        if plan is not None and k in SNAP_KEYS:
            pieces.append(saved.get(k, {} if per_user else Decimal(0)))
            ranges = [(since, a), (b, until)]
        else:
            ranges = [(since, until)]
        total = {} if per_user else (Decimal(0) if m.unit == 'money' else 0)
        for lo, hi in ranges:
            if lo >= hi:
                continue
            if per_user:
                for u, v in _live_by_user(m, lo, hi, pid, owners).items():
                    total[u] = total.get(u, 0) + v
            else:
                total = total + _live_total(m, lo, hi, pid, owners)
        for piece in pieces:
            if per_user:
                for u, v in piece.items():
                    total[u] = total.get(u, 0) + v
            else:
                total = total + piece
        out[k] = ({u: _number(m, v) for u, v in total.items()} if per_user else _number(m, total))
    return out


def bundle(keys, since, until, scope=None):
    """{key: value} for several metrics of one scope. The saved ones come from one query."""
    pid, owners, now, live = resolve_scope(scope)
    keys = list(keys)
    if owners is not None and not owners:
        return {k: (None if METRICS[k].unit == 'minutes' else (Decimal(0) if METRICS[k].unit == 'money' else 0))
                for k in keys}
    events = [k for k in keys if METRICS[k].kind == 'event' and METRICS[k].compute is not None
              and not METRICS[k].breakdown]
    out = _event_values(events, since, until, pid, owners, now, live, False) if events else {}
    for k in keys:
        if k in out:
            continue
        m = METRICS[k]
        if m.compute is None:
            out[k] = None
        elif m.breakdown:
            out[k] = m.compute(since, until, pid, owners)
        else:
            out[k] = m.compute(since, until, pid, owners, now)
    return out


def compute(key, since, until, scope=None):
    """One number for [since, until) UTC and a scope (see the top of this file)."""
    return bundle([key], since, until, scope)[key]


def by_owner(key, since, until, scope=None):
    """{user_id: value}: the number for each person (GROUP BY in SQL)."""
    pid, owners, now, live = resolve_scope(scope)
    m = METRICS[key]
    if owners is not None and not owners:
        return {}
    if m.kind == 'event':
        return _event_values([key], since, until, pid, owners, now, live, True)[key]
    if m.per_owner is None:
        return {}
    return m.per_owner(since, until, pid, owners, now)


def days_between(since, until):
    first, last = ist_day(since), ist_day(until - timedelta(seconds=1))
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def daily_by_owner(keys, since, until, user_ids=None, now=None, live=False):
    """{user_id: {india day: {key: value}}} for event metrics, only non-zero values. A whole past day comes from
    the saved numbers when they are there, else it is counted live."""
    keys = [k for k in keys if METRICS[k].kind == 'event']
    owners = None if user_ids is None else sorted({int(i) for i in user_ids})
    out = defaultdict(lambda: defaultdict(dict))
    if owners is not None and not owners:
        return out
    days = days_between(since, until)
    today = today_ist(now)
    whole = [d for d in days if day_bounds(d)[0] >= since and day_bounds(d)[1] <= until and d < today]
    have = set() if live else _present_days(whole)
    if have:
        q = db.session.query(CrmDailyStat.day, CrmDailyStat.metric, CrmDailyStat.user_id, CrmDailyStat.value).filter(
            CrmDailyStat.day.in_(sorted(have)), CrmDailyStat.metric.in_(keys),
            CrmDailyStat.pipeline_id.is_(None), CrmDailyStat.user_id.isnot(None))
        if owners is not None:
            q = q.filter(CrmDailyStat.user_id.in_(owners))
        for d, metric, uid, v in q.all():
            if v:
                out[uid][d][metric] = _number(METRICS[metric], v)
    for d in days:
        if d in have:
            continue
        a, b = max(since, day_bounds(d)[0]), min(until, day_bounds(d)[1])
        if a >= b:
            continue
        for k in keys:
            for uid, v in _live_by_user(METRICS[k], a, b, None, owners).items():
                if v:
                    out[uid][d][k] = _number(METRICS[k], v)
    return out


def daily_totals(keys, since, until, pid=None, owners=None, now=None, live=False):
    """{key: {india day: value}} for event metrics, a day with nothing left out (the sales sheet's rows). A whole
    past day comes from the saved numbers when they are there, else it is counted live."""
    keys = [k for k in keys if METRICS[k].kind == 'event' and METRICS[k].compute is not None]
    owners = None if owners is None else sorted({int(i) for i in owners})
    out = {k: {} for k in keys}
    if owners is not None and not owners:
        return out
    days = days_between(since, until)
    whole = [d for d in days if day_bounds(d)[0] >= since and day_bounds(d)[1] <= until and d < today_ist(now)]
    have = set() if live else _present_days(whole)
    if have:
        q = db.session.query(CrmDailyStat.day, CrmDailyStat.metric, func.sum(CrmDailyStat.value)).filter(
            CrmDailyStat.day.in_(sorted(have)), CrmDailyStat.metric.in_(keys),
            CrmDailyStat.pipeline_id == pid if pid else CrmDailyStat.pipeline_id.is_(None))
        q = q.filter(CrmDailyStat.user_id.in_(owners)) if owners is not None else q.filter(CrmDailyStat.user_id.is_(None))
        for d, metric, v in q.group_by(CrmDailyStat.day, CrmDailyStat.metric).all():
            if v:
                out[metric][d] = _number(METRICS[metric], v)
    for d in days:
        if d in have:
            continue
        a, b = max(since, day_bounds(d)[0]), min(until, day_bounds(d)[1])
        if a >= b:
            continue
        for k in keys:
            v = _live_total(METRICS[k], a, b, pid, owners)
            if v:
                out[k][d] = _number(METRICS[k], v)
    return out


# ============================================================================================ snapshots

def snapshot_day(day, keys=None):
    """Save every event metric for one India day (replaces what was saved for it): per person and pipeline, per
    person, per pipeline, and the company -- a company row for every metric, even a zero, marks the day as done."""
    start, end = day_bounds(day)
    now = datetime.utcnow()
    for k in (keys or SNAP_KEYS):
        m = METRICS[k]
        agg = defaultdict(lambda: Decimal(0))
        agg[(None, None)] = Decimal(0)
        for u, p, v in m.compute(start, end, None, None):
            for target in {(u, p), (u, None), (None, p), (None, None)}:
                agg[target] += Decimal(v)
        CrmDailyStat.query.filter_by(day=day, metric=k).filter(crm_scope.here(CrmDailyStat)) \
            .delete(synchronize_session=False)
        for (u, p), v in agg.items():
            if v or (u is None and p is None):
                db.session.add(CrmDailyStat(day=day, metric=k, user_id=u, pipeline_id=p, value=_money(v),
                                            computed_at=now))
    db.session.commit()


def snapshot_missing_days(limit_days=5, today=None, back=KEEP_DAYS):
    """The night job: save yesterday and earlier days that are not saved yet (newest first, back to `back` days ago),
    at most `limit_days` days per run. Running it again does nothing more."""
    today = today or today_ist()
    days = [today - timedelta(days=n) for n in range(1, back + 1)]
    have = _present_days(days)
    done = 0
    for d in days:
        if d in have:
            continue
        if done >= limit_days:
            break
        snapshot_day(d)
        done += 1
    return {'crm_snapshot_days': done}


def snapshot_range(days=KEEP_DAYS, today=None):
    """Save every day of the last `days` days at once (the `flask crm-snapshot` command)."""
    today = today or today_ist()
    n = 0
    for back in range(1, days + 1):
        snapshot_day(today - timedelta(days=back))
        n += 1
    return n


def recalculate(days=90, now_days=10, today=None):
    """Forget what was saved for the last `days` days and save the newest `now_days` of them again at once; the
    night job fills in the rest. Until a day is saved again it is counted live, so no number is ever missing."""
    today = today or today_ist()
    first = today - timedelta(days=days)
    CrmDailyStat.query.filter(CrmDailyStat.day >= first, CrmDailyStat.day < today, crm_scope.here(CrmDailyStat)) \
        .delete(synchronize_session=False)
    db.session.commit()
    for back in range(1, min(now_days, days) + 1):
        snapshot_day(today - timedelta(days=back))
    return {'forgotten': days, 'rebuilt_now': min(now_days, days), 'left_for_tonight': max(days - now_days, 0)}
