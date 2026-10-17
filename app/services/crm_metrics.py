"""The Sales CRM's numbers, each defined once (design principle 10: one meaning per number).

Every function reads in one query for all the people or leads it is given -- never one per lead
-- so a list of 200 leads costs the same as one. Pass a page of people at a time.

    last_touches()       per person: the newest WhatsApp message either way, the newest real
                         WhatsApp message from them, and the newest message either way on a
                         channel we answer from here (WhatsApp, Instagram, Facebook)
    waiting_on_us()      "Waiting on us": they wrote last and nobody has answered
    window_left_hours()  how long WhatsApp still allows free text after their last real message
    waiting_count()      how many customers on somebody's open leads are waiting on us
    waiting_by_owner()   the same for many owners at once
    unanswered_by_owner()  customers who wrote in a time span and had no answer when it ended
    first_reply_minutes()  per person, the median wait for a person's first answer
    reply_minutes() / first_contact_minutes() / waiting_people()  the same for Results: one median or count
    DEFINITIONS          the words behind each number's (i) on Results
    waiting_rows() / window_open_people()  the SQL forms of waiting_on_us / window_left_hours, for
                         filtering and counting in the database
    via_expr() / via_of()  who sent an outbound message, with the rule for rows from before `via`

Nothing here decides what may be sent: crm.whatsapp_window_open() does that, and it also asks
the WhatsApp CRM, which keeps Meta's clock.
"""
from datetime import datetime, timedelta
from statistics import median

from sqlalchemy import and_, case, func, or_, select

from app import db
from app.models import CrmLead, CrmPerson, CrmTouchpoint
from app.services.crm import WINDOW_HOURS

REPLY_CHANNELS = ('whatsapp', 'instagram', 'facebook')    # where they write and we answer from here


def _ranked(person_filter, until=None):
    """Every message either way on a reply channel, for the people `person_filter` picks, numbered
    newest first three ways (one subquery):
      wa_n     among their WhatsApp messages
      reply_n  among the ones that count for "who wrote last" (reply_ok): not a WhatsApp message
               from them at or before they opted out (STOP is not a question), and not one of ours
               that failed (an answer that never arrived is no answer)
      in_n     among their real WhatsApp messages (real_in): WhatsApp gave it an id (the webhook,
               the catch-up -- not one an agent typed in), after any opt-out
    `until`: only messages before that moment (how it stood then)."""
    tp, p = CrmTouchpoint, CrmPerson
    is_wa = tp.channel == 'whatsapp'
    before_out = and_(p.wa_opt_out_at.isnot(None), tp.created_at <= p.wa_opt_out_at)
    failed_out = and_(tp.direction == 'out', func.coalesce(tp.status, '') == 'failed')
    wa = case((is_wa, 1), else_=0)
    reply_ok = case((and_(~and_(is_wa, tp.direction == 'in', before_out), ~failed_out), 1), else_=0)
    real_in = case((and_(is_wa, tp.direction == 'in', func.coalesce(tp.external_id, '') != '', ~before_out), 1),
                   else_=0)
    newest = (tp.created_at.desc(), tp.id.desc())
    where = [person_filter, tp.channel.in_(REPLY_CHANNELS), tp.direction.in_(('in', 'out'))]
    if until is not None:
        where.append(tp.created_at < until)
    return (select(tp.person_id, tp.lead_id, tp.body, tp.channel, tp.direction, tp.status, tp.created_at,
                   wa.label('is_wa'), reply_ok.label('reply_ok'), real_in.label('real_in'),
                   func.row_number().over(partition_by=(tp.person_id, wa), order_by=newest).label('wa_n'),
                   func.row_number().over(partition_by=(tp.person_id, reply_ok), order_by=newest).label('reply_n'),
                   func.row_number().over(partition_by=(tp.person_id, real_in), order_by=newest).label('in_n'))
            .join(p, p.id == tp.person_id)
            .where(*where)
            .subquery())


def last_touches(person_ids):
    """{person_id: {'wa_last': (direction, at, status) | None,
                    'wa_last_in': at | None,
                    'reply_last': (channel, direction, at) | None}} for every id given:

      wa_last     their newest WhatsApp message either way ('in' / 'out'), with its tick status
      wa_last_in  when they last wrote on WhatsApp for real: WhatsApp gave the message an id, and
                  it came after any opt-out (what the 24 hours count from)
      reply_last  the newest message either way on WhatsApp, Instagram or Facebook that counts
                  for "who wrote last" (see _ranked)

    Notes, calls, forms and e-mails are not messages here. One query; none for no ids."""
    ids = sorted({int(i) for i in person_ids if i})
    out = {pid: {'wa_last': None, 'wa_last_in': None, 'reply_last': None} for pid in ids}
    if not ids:
        return out
    r = _ranked(CrmTouchpoint.person_id.in_(ids))
    rows = db.session.execute(select(r).where(or_(and_(r.c.is_wa == 1, r.c.wa_n == 1),
                                                  and_(r.c.reply_ok == 1, r.c.reply_n == 1),
                                                  and_(r.c.real_in == 1, r.c.in_n == 1)))).all()
    for row in rows:
        e = out[row.person_id]
        if row.is_wa == 1 and row.wa_n == 1:
            e['wa_last'] = (row.direction, row.created_at, row.status)
        if row.reply_ok == 1 and row.reply_n == 1:
            e['reply_last'] = (row.channel, row.direction, row.created_at)
        if row.real_in == 1 and row.in_n == 1:
            e['wa_last_in'] = row.created_at
    return out


def waiting_on_us(entry):
    """"Waiting on us": they wrote last on WhatsApp, Instagram or Facebook and nobody has answered
    since -- the newest message that counts (last_touches' reply_last) is theirs. `entry`: one
    value of last_touches()."""
    last = (entry or {}).get('reply_last')
    return bool(last) and last[1] == 'in'


def window_left_hours(wa_last_in, now=None):
    """Hours WhatsApp still allows free text after their last real message (WINDOW_HOURS after
    it): 3.5, say; 0.0 once it has closed; None when they have never written on WhatsApp. For
    showing only: crm.whatsapp_window_open() decides."""
    if wa_last_in is None:
        return None
    left = WINDOW_HOURS - ((now or datetime.utcnow()) - wa_last_in).total_seconds() / 3600
    return max(left, 0.0)


def waiting_count(owner_id):
    """How many customers on `owner_id`'s open leads are waiting on us (waiting_on_us): each person
    once, however many of their open leads are this owner's. None: the open leads nobody looks
    after. One query."""
    owner = CrmLead.owner_id.is_(None) if owner_id is None else CrmLead.owner_id == owner_id
    owned = select(CrmLead.person_id).where(CrmLead.status == 'open', owner)
    r = _ranked(CrmTouchpoint.person_id.in_(owned))
    return db.session.execute(select(func.count()).select_from(r)
                              .where(r.c.reply_ok == 1, r.c.reply_n == 1, r.c.direction == 'in')).scalar() or 0


VIA_PERSON = 'person'


def waiting_rows(person_filter, until=None):
    """The SQL form of waiting_on_us(): a select of (person_id, lead_id, channel, created_at, body), one
    row per person `person_filter` picks who is waiting on us, with the message they are waiting with
    -- their newest that counts (see _ranked). `until`: as it stood then. Run it, or use it inside a
    query of your own; one query either way."""
    r = _ranked(person_filter, until)
    return (select(r.c.person_id, r.c.lead_id, r.c.channel, r.c.created_at, r.c.body)
            .where(r.c.reply_ok == 1, r.c.reply_n == 1, r.c.direction == 'in'))


def window_open_people(person_filter, now=None):
    """The SQL form of "their chat is open": a select of person_id for the people `person_filter` picks
    who have a real WhatsApp message from them in the last 24 hours, after any opt-out. Display,
    filters and the sign-off list only; crm.whatsapp_window_open / the WhatsApp CRM decide a send."""
    r = _ranked(person_filter)
    since = (now or datetime.utcnow()) - timedelta(hours=WINDOW_HOURS)
    return select(r.c.person_id).where(r.c.real_in == 1, r.c.in_n == 1, r.c.created_at > since)


def waiting_by_owner(owner_ids):
    """{owner_id: n}: waiting_count() for many owners in one query. Snoozed leads still count: a
    snooze hides a row on My day, it does not change a number."""
    ids = sorted({int(i) for i in owner_ids if i})
    if not ids:
        return {}
    owned = select(CrmLead.person_id).where(CrmLead.status == 'open', CrmLead.owner_id.in_(ids))
    w = waiting_rows(CrmTouchpoint.person_id.in_(owned)).subquery()
    rows = (db.session.query(CrmLead.owner_id, func.count(func.distinct(CrmLead.person_id)))
            .join(w, w.c.person_id == CrmLead.person_id)
            .filter(CrmLead.status == 'open', CrmLead.owner_id.in_(ids))
            .group_by(CrmLead.owner_id).all())
    return {o: n for o, n in rows}


def _wrote_between(start, end):
    tp = CrmTouchpoint
    return select(tp.person_id).where(tp.direction == 'in', tp.channel.in_(REPLY_CHANNELS),
                                      tp.created_at >= start, tp.created_at < end)


def unanswered_by_owner(start, end, owner_ids):
    """{owner_id: n}: "left unanswered at day end" -- customers who wrote on a reply channel in
    [start, end) and whose newest counting message before `end` is theirs. Each is counted for the
    owner of the lead that message is on. One query."""
    ids = sorted({int(i) for i in owner_ids if i})
    if not ids:
        return {}
    w = waiting_rows(CrmTouchpoint.person_id.in_(_wrote_between(start, end)), until=end).subquery()
    rows = (db.session.query(CrmLead.owner_id, func.count(func.distinct(w.c.person_id)))
            .join(CrmLead, CrmLead.id == w.c.lead_id)
            .filter(w.c.created_at >= start, CrmLead.owner_id.in_(ids))
            .group_by(CrmLead.owner_id).all())
    return {o: n for o, n in rows}


def via_expr():
    """SQL: who sent an outbound touchpoint -- its via; on a row from before via existed, 'person'
    when it has an agent, else 'automation'."""
    tp = CrmTouchpoint
    return func.coalesce(tp.via, case((tp.agent_id.isnot(None), 'person'), else_='automation'))


def via_of(via, agent_id):
    """The same rule for one row already read."""
    return via or ('person' if agent_id else 'automation')


def _reply_samples(start, end, now=None, person_ids=None):
    """[(agent_id, minutes)]: one per customer wait that began in [start, end) and a PERSON answered first.
    `person_ids`: a select that limits it to those people. One query."""
    tp = CrmTouchpoint
    now = now or datetime.utcnow()
    stop = min(now, end + timedelta(hours=WINDOW_HOURS))
    where = [tp.person_id.in_(_wrote_between(start, end)), tp.channel.in_(REPLY_CHANNELS),
             tp.direction.in_(('in', 'out')), func.coalesce(tp.status, '') != 'failed',
             tp.created_at >= start - timedelta(hours=WINDOW_HOURS), tp.created_at < stop]
    if person_ids is not None:
        where.append(tp.person_id.in_(person_ids))
    rows = (db.session.query(tp.person_id, tp.direction, tp.created_at, tp.id, tp.agent_id, via_expr())
            .filter(*where).order_by(tp.person_id, tp.created_at, tp.id).all())
    samples = []
    person, wait = None, None
    for pid, direction, at, _id, agent, via in rows:
        if pid != person:
            person, wait = pid, None
        if direction == 'in':
            if wait is None:
                wait = at
        elif wait is not None:
            if start <= wait < end and via == VIA_PERSON and agent:
                samples.append((agent, (at - wait).total_seconds() / 60))
            wait = None
    return samples


def first_reply_minutes(start, end, now=None):
    """{agent_id: median minutes}: how long customers waited for a PERSON's first answer, for waits that
    began in [start, end). An answer from an automation, a flow or the AI is not counted; a wait
    answered first by one of those gives no sample. One query."""
    by_agent = {}
    for agent, minutes in _reply_samples(start, end, now):
        by_agent.setdefault(agent, []).append(minutes)
    return {a: round(median(v)) for a, v in by_agent.items()}


def reply_minutes(start, end, person_ids=None, now=None):
    """Median minutes customers waited for a PERSON's answer, for waits that began in [start, end), over
    everybody (or the people `person_ids` -- a select -- picks). None without samples."""
    got = [m for _, m in _reply_samples(start, end, now, person_ids)]
    return round(median(got)) if got else None


def first_contact_minutes(lead_ids):
    """Median minutes from a lead coming in to the first message or call a PERSON made on it, for the leads
    `lead_ids` (a select of CrmLead.id). Automatic messages are not counted; a lead nobody has contacted yet gives
    no sample. None without samples."""
    tp = CrmTouchpoint
    first = (select(tp.lead_id.label('lead_id'), func.min(tp.created_at).label('t'))
             .where(tp.lead_id.in_(lead_ids), tp.direction == 'out', tp.channel.notin_(('system', 'note', 'form')),
                    func.coalesce(tp.status, '') != 'imported', via_expr() == VIA_PERSON)
             .group_by(tp.lead_id).subquery())
    rows = (db.session.query(CrmLead.created_at, first.c.t)
            .join(first, first.c.lead_id == CrmLead.id).all())
    got = [max((t - created).total_seconds() / 60, 0) for created, t in rows if created and t]
    return round(median(got)) if got else None


def waiting_people(person_ids):
    """How many of the people `person_ids` (a select) are waiting on us now (waiting_rows)."""
    w = waiting_rows(CrmTouchpoint.person_id.in_(person_ids)).subquery()
    return db.session.execute(select(func.count()).select_from(w)).scalar() or 0


DEFINITIONS = {
    'new_leads': 'Leads that came in during these days. Leads brought in from a list or the sales sheet are not counted.',
    'replied': 'Leads whose customer wrote back for the first time during these days, on any channel. A form is not a reply.',
    'quoted': 'Leads that reached a stage meaning Quoted for the first time during these days.',
    'won': 'Leads marked won during these days.',
    'first_contact': ('How long new leads waited for the first message or call from a person; half waited less. '
                      'Automatic messages are not counted, nor leads nobody has contacted yet.'),
    'reply_time': ("How long customers waited for a person's answer after they wrote; half waited less. "
                   'Automatic replies are not counted.'),
    'waiting_now': 'Customers who wrote last on WhatsApp, Instagram or Facebook and have no answer yet. Right now.',
    'funnel': 'Of the leads that came in during these days: how many got this far.',
    'sources': ('Leads that came in during these days, by where they came from: how many replied and how many '
                'are customers now.'),
    'campaigns': "The same, by the campaign name in the ad's link.",
    'by_sender': ('Messages we sent during these days: by a person, by itself (follow-ups, reply rules, the chatbot, '
                  'AI replies) or in a broadcast. Calls are not messages.'),
    'milestones': 'How often somebody pressed I sent the quote or I sent the payment link on a lead.',
    'lost': 'Leads lost during these days, by the reason given.',
    'day_by_day': 'Every number of the sales sheet, day by day. It counts every pipeline.',
}
