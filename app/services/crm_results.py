"""Results (E17): the Sales CRM's numbers for some days, one pipeline and one person.

Every definition is in `crm_metrics.DEFINITIONS` (the (i) on the page). There are two kinds of number:

  what happened during the days     New leads, Replied, Quoted, Customers won, the messages, the quotes and
                                    payment links, and why we lost leads
  what became of the leads that     From lead to customer, and Where customers come from
  came in during the days

A person here is whoever looks after the lead (CrmLead.owner_id). The number of queries is fixed, whatever
the period. `since` / `until` are UTC datetimes ([since, until)); `pipeline_id` and `owner_id` may be None.
"""
from sqlalchemy import func, select

from app import db
from app.models import CrmLead, CrmSource, CrmStage, CrmStageChange, CrmTouchpoint
from app.services import crm_kpi, crm_metrics

NO_REASON, NO_SOURCE = 'No reason given', 'No source'


def _scope(pipeline_id, owner_id):
    """Conditions on CrmLead for the chosen pipeline and person."""
    out = []
    if pipeline_id:
        out.append(CrmLead.pipeline_id == pipeline_id)
    if owner_id:
        out.append(CrmLead.owner_id == owner_id)
    return out


def _cohort(since, until, pipeline_id, owner_id):
    """Conditions for the leads that came in during the days (brought-in ones are not counted)."""
    return [CrmLead.created_at >= since, CrmLead.created_at < until, CrmLead.imported.is_(False),
            *_scope(pipeline_id, owner_id)]


def counts(since, until, pipeline_id=None, owner_id=None):
    """{'new_leads', 'replied', 'quoted', 'won'}: what happened during the days."""
    tp, sc = CrmTouchpoint, CrmStageChange
    scope = _scope(pipeline_id, owner_id)
    new_leads = db.session.query(func.count(CrmLead.id)).filter(*_cohort(since, until, pipeline_id, owner_id)).scalar()
    first_in = (select(tp.lead_id.label('lead_id'), func.min(tp.created_at).label('t'))
                .where(tp.direction == 'in', tp.channel != 'form', func.coalesce(tp.status, '') != 'imported',
                       tp.lead_id.isnot(None))
                .group_by(tp.lead_id).subquery())
    replied = (db.session.query(func.count(CrmLead.id)).join(first_in, first_in.c.lead_id == CrmLead.id)
               .filter(first_in.c.t >= since, first_in.c.t < until, *scope).scalar())
    quoted_stages = [sid for sid, role in crm_kpi.stage_roles().items() if role == 'pipeline']
    quoted = 0
    if quoted_stages:
        first_quote = (select(sc.lead_id.label('lead_id'), func.min(sc.created_at).label('t'))
                       .where(sc.to_stage_id.in_(quoted_stages),
                              ~func.coalesce(sc.reason, '').like('Sales sheet%'))
                       .group_by(sc.lead_id).subquery())
        quoted = (db.session.query(func.count(CrmLead.id)).join(first_quote, first_quote.c.lead_id == CrmLead.id)
                  .filter(first_quote.c.t >= since, first_quote.c.t < until, *scope,
                          CrmLead.imported.is_(False)).scalar())
    won = (db.session.query(func.count(CrmLead.id))
           .filter(CrmLead.status == 'won', CrmLead.closed_at >= since, CrmLead.closed_at < until, *scope).scalar())
    return {'new_leads': new_leads or 0, 'replied': replied or 0, 'quoted': quoted or 0, 'won': won or 0}


def cards(since, until, pipeline_id=None, owner_id=None, now=None):
    """The seven cards: counts() plus the two times (people only) and who is waiting now."""
    out = counts(since, until, pipeline_id, owner_id)
    scope = _scope(pipeline_id, owner_id)
    out['first_contact'] = crm_metrics.first_contact_minutes(
        select(CrmLead.id).where(*_cohort(since, until, pipeline_id, owner_id)))
    out['reply_time'] = crm_metrics.reply_minutes(
        since, until, select(CrmLead.person_id).where(*scope) if scope else None, now)
    out['waiting_now'] = crm_metrics.waiting_people(
        select(CrmLead.person_id).where(CrmLead.status == 'open', *scope))
    return out


def funnel(since, until, pipeline=None, owner_id=None):
    """From lead to customer, for the leads that came in during the days: {'rows': [{'label', 'n', 'pct',
    'won'}], 'lost', 'total'}. With a pipeline, its own stages (reached or later); without one, the five
    meanings."""
    cohort = _cohort(since, until, pipeline.id if pipeline else None, owner_id)
    leads = db.session.query(CrmLead.id, CrmLead.stage_id, CrmLead.status).filter(*cohort).all()
    visited = {lid: {sid} for lid, sid, _ in leads if sid}
    ids = select(CrmLead.id).where(*cohort)
    for lid, sid in db.session.query(CrmStageChange.lead_id, CrmStageChange.to_stage_id).filter(
            CrmStageChange.lead_id.in_(ids)).all():
        visited.setdefault(lid, set()).add(sid)
    lost = sum(1 for _, _, status in leads if status == 'lost')
    rows = []
    if pipeline is not None:
        pos = {s.id: s.position for s in pipeline.stages if s.kind != 'lost'}
        best = []
        for lid, _, _ in leads:
            reached = [pos[s] for s in visited.get(lid, ()) if s in pos]
            best.append(max(reached) if reached else None)
        for s in pipeline.stages:
            if s.kind == 'lost':
                continue
            rows.append({'label': s.name, 'n': sum(1 for b in best if b is not None and b >= s.position),
                         'won': s.kind == 'won'})
    else:
        rank = {'cold': 0, 'prospect': 1, 'pipeline': 2, 'customer': 3}
        roles = crm_kpi.stage_roles()
        best = [max([rank.get(roles.get(s), 0) for s in visited.get(lid, ())] or [0]) for lid, _, _ in leads]
        for label, need, won in (('New leads', 0, False), ('Talking', 1, False), ('Quoted', 2, False),
                                 ('Won (customer)', 3, True)):
            rows.append({'label': label, 'n': sum(1 for b in best if b >= need), 'won': won})
    prev = None
    for r in rows:
        r['pct'] = round(100 * r['n'] / prev) if prev else None
        prev = r['n']
    return {'rows': rows, 'lost': lost, 'total': len(leads)}


def sources(since, until, pipeline_id=None, owner_id=None):
    """Where customers come from, for the leads that came in during the days: {'rows', 'campaigns'}, each row
    {'name', 'leads', 'replied', 'won', 'pct'} (pct: won out of leads)."""
    cohort = _cohort(since, until, pipeline_id, owner_id)
    leads = db.session.query(CrmLead.id, CrmLead.person_id, CrmLead.source_id, CrmLead.status, CrmLead.utm).filter(*cohort).all()
    names = dict(db.session.query(CrmSource.id, CrmSource.name).all())
    tp = CrmTouchpoint
    ids = select(CrmLead.id).where(*cohort)
    replied = {r[0] for r in db.session.query(tp.lead_id).filter(
        tp.lead_id.in_(ids), tp.direction == 'in', tp.channel != 'form',
        func.coalesce(tp.status, '') != 'imported').distinct().all()}

    def table(key):
        acc = {}
        for lid, _pid, sid, status, utm in leads:
            name = key(sid, utm)
            if not name:
                continue
            row = acc.setdefault(name, {'name': name, 'leads': 0, 'replied': 0, 'won': 0})
            row['leads'] += 1
            row['replied'] += lid in replied
            row['won'] += status == 'won'
        rows = sorted(acc.values(), key=lambda r: (-r['leads'], r['name'].lower()))
        for r in rows:
            r['pct'] = round(100 * r['won'] / r['leads'])
        return rows
    return {'rows': table(lambda sid, utm: names.get(sid) or NO_SOURCE),
            'campaigns': table(lambda sid, utm: str((utm or {}).get('utm_campaign') or '').strip()[:80])}


def by_sender(since, until, pipeline_id=None, owner_id=None):
    """Messages, by who sent them: [('People', n), ('Automatic', n), ('Broadcast', n)]. Calls and brought-in
    messages are not counted."""
    tp = CrmTouchpoint
    via = crm_metrics.via_expr()
    q = db.session.query(via, func.count(tp.id)).filter(
        tp.direction == 'out', tp.channel.notin_(('call', 'system', 'note', 'form')),
        func.coalesce(tp.status, '') != 'imported', tp.created_at >= since, tp.created_at < until)
    scope = _scope(pipeline_id, owner_id)
    if scope:
        q = q.join(CrmLead, CrmLead.id == tp.lead_id).filter(*scope)
    got = {'People': 0, 'Automatic': 0, 'Broadcast': 0}
    for v, n in q.group_by(via).all():
        if v == 'person':
            got['People'] += n
        elif v == 'broadcast':
            got['Broadcast'] += n
        elif v != 'import':
            got['Automatic'] += n
    return list(got.items())


def milestones(since, until, pipeline_id=None, owner_id=None):
    """Quotes and payment links: [(label, n)], Q and PLS first, then any other stage button; a zero is kept."""
    from app.services import crm
    labels = {'Q': crm.LEGACY_MILESTONES['Q'], 'PLS': crm.LEGACY_MILESTONES['PLS']}
    for code, label in (db.session.query(CrmStage.button_code, CrmStage.button_label)
                        .filter(CrmStage.button_code.isnot(None), CrmStage.button_label.isnot(None))
                        .order_by(CrmStage.id).all()):
        labels.setdefault(code, label)
    tp = CrmTouchpoint
    q = db.session.query(tp.code, func.count(tp.id)).filter(
        tp.code.in_(list(labels)), tp.created_at >= since, tp.created_at < until,
        func.coalesce(tp.status, '') != 'imported')
    scope = _scope(pipeline_id, owner_id)
    if scope:
        q = q.join(CrmLead, CrmLead.id == tp.lead_id).filter(*scope)
    got = dict(q.group_by(tp.code).all())
    order = ['Q', 'PLS'] + sorted((c for c in labels if c not in ('Q', 'PLS')), key=lambda c: labels[c])
    return [(labels[c], got.get(c, 0)) for c in order]


def lost_reasons(since, until, pipeline_id=None, owner_id=None):
    """Why we lost leads: [(reason or 'No reason given', n)], most first."""
    rows = (db.session.query(CrmLead.fallout_reason, func.count(CrmLead.id))
            .filter(CrmLead.status == 'lost', CrmLead.closed_at >= since, CrmLead.closed_at < until,
                    *_scope(pipeline_id, owner_id))
            .group_by(CrmLead.fallout_reason).all())
    out = [((r or '').strip() or NO_REASON, n) for r, n in rows]
    merged = {}
    for r, n in out:
        merged[r] = merged.get(r, 0) + n
    return sorted(merged.items(), key=lambda x: (-x[1], x[0]))
