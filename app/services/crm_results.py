"""Results (E17): the Sales CRM's numbers for some days, one pipeline and one person.

Every number's definition is in `crm_numbers.METRICS` and the tables' in `crm_metrics.DEFINITIONS` (the (i) on the page). There are two kinds of number:

  what happened during the days     New leads, Replied, Quoted, Won in these days, the messages, the quotes and
                                    payment links, and why we lost leads
  what became of the leads that     From lead to customer, and Where customers come from
  came in during the days

A person here is whoever looks after the lead (CrmLead.owner_id). The number of queries is fixed, whatever
the period. `since` / `until` are UTC datetimes ([since, until)); `pipeline_id` and `owner_id` may be None.
"""
from sqlalchemy import func, select

from app import db
from app.models import CrmLead, CrmSource, CrmStage, CrmStageChange, CrmTouchpoint
from app.services import crm_kpi, crm_metrics, crm_numbers, crm_words

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


def _scope_dict(pipeline_id, owner_id, now=None):
    return crm_numbers.scope(pipeline_id, [owner_id] if owner_id else None, now=now)


def counts(since, until, pipeline_id=None, owner_id=None):
    """{'new_leads', 'replied', 'quoted', 'won'}: what happened during the days (crm_numbers.METRICS)."""
    got = crm_numbers.bundle(['new_leads', 'replied', 'quoted_leads', 'won'], since, until,
                             _scope_dict(pipeline_id, owner_id))
    return {'new_leads': got['new_leads'], 'replied': got['replied'], 'quoted': got['quoted_leads'],
            'won': got['won']}


def cards(since, until, pipeline_id=None, owner_id=None, now=None):
    """The seven cards: counts() plus the two times (people only) and who is waiting now."""
    out = counts(since, until, pipeline_id, owner_id)
    got = crm_numbers.bundle(['first_contact_minutes', 'reply_minutes', 'waiting_now'], since, until,
                             _scope_dict(pipeline_id, owner_id, now))
    out['first_contact'] = got['first_contact_minutes']
    out['reply_time'] = got['reply_minutes']
    out['waiting_now'] = got['waiting_now']
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
                                 ('Won so far', 3, True)):
            rows.append({'label': label, 'n': sum(1 for b in best if b >= need), 'won': won})
    prev = None
    for r in rows:
        r['tip'] = crm_metrics.DEFINITIONS['won_so_far'] if r['won'] else None
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
    got = crm_numbers.bundle(['messages_people', 'messages_auto', 'messages_broadcast'], since, until,
                             _scope_dict(pipeline_id, owner_id))
    return [('People', got['messages_people']), ('Automatic', got['messages_auto']),
            ('Broadcast', got['messages_broadcast'])]


def milestones(since, until, pipeline_id=None, owner_id=None):
    """Quotes and payment links: [(label, n)], Q and PLS first, then any other stage button; a zero is kept."""
    labels = dict(crm_words.MILESTONE_WORDS)
    for code, label in (db.session.query(CrmStage.button_code, CrmStage.button_label)
                        .filter(CrmStage.button_code.isnot(None), CrmStage.button_label.isnot(None))
                        .order_by(CrmStage.id).all()):
        labels.setdefault(code, label)
    got = {}
    others = [c for c in labels if c not in ('Q', 'PLS')]
    if others:
        tp = CrmTouchpoint
        q = db.session.query(tp.code, func.count(tp.id)).filter(
            tp.code.in_(others), tp.created_at >= since, tp.created_at < until,
            func.coalesce(tp.status, '') != 'imported')
        scope = _scope(pipeline_id, owner_id)
        if scope:
            q = q.join(CrmLead, CrmLead.id == tp.lead_id).filter(*scope)
        got = dict(q.group_by(tp.code).all())
    two = crm_numbers.bundle(['quoted', 'payment_links'], since, until, _scope_dict(pipeline_id, owner_id))
    got['Q'], got['PLS'] = two['quoted'], two['payment_links']
    order = ['Q', 'PLS'] + sorted(others, key=lambda c: labels[c])
    return [(labels[c], got.get(c, 0)) for c in order]


def lost_reasons(since, until, pipeline_id=None, owner_id=None):
    """Why we lost leads: [(reason or 'No reason given', n)], most first."""
    return crm_numbers.compute('lost_by_reason', since, until, _scope_dict(pipeline_id, owner_id))
