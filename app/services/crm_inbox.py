"""Inbox › All conversations (Staff Console 2.0, 2026-10-26): everybody who wrote to us, on any channel, one row each.

WhatsApp, e-mail, Instagram, Facebook, the website's forms (contact us, insurance, Sahayak, trip posts, ad forms) and
its chat (tawk.to) all land on the lead's timeline as a message from them (CrmTouchpoint, direction 'in'), so this
is a list over those messages and stores nothing of its own. A row is a person: what was said last either way, the
lead it is about, who looks after it, and whether they are waiting on us (crm_metrics.waiting_on_us -- the one
meaning of that number). Opening a row goes where it is answered: their chat in WhatsApp chats when the last word
was on WhatsApp and the person may open it, else the lead page (its message box and timeline), else the contact.

What somebody sees is what they may see anywhere else: the listeners of crm_access (own / team / all), crm_scope
(the workspace) and crm_bin (removed leads) act on every read here as on every other page.

    filters(args)      the page's filters from the query string, made safe
    page(f, user, n)   the rows of one page, the total, and the count of each "whose" tab
"""
from sqlalchemy import case, exists, func, or_, select

from app import db
from app.models import CrmLead, CrmPerson, CrmTouchpoint
from app.services import crm_metrics

# the channels people write to us on, as the page groups them: (key, words, icon, touchpoint channels)
GROUPS = (('whatsapp', 'WhatsApp', 'fa-brands fa-whatsapp', ('whatsapp',)),
          ('email', 'E-mail', 'fa-solid fa-envelope', ('email',)),
          ('forms', 'Website forms', 'fa-solid fa-file-lines', ('form',)),
          ('chat', 'Website chat', 'fa-regular fa-comment-dots', ('chat',)),
          ('social', 'Instagram & Facebook', 'fa-brands fa-instagram', ('instagram', 'facebook')))
GROUP_BY_KEY = {g[0]: g for g in GROUPS}
CHANNELS = tuple(c for g in GROUPS for c in g[3])
CHANNEL_GROUP = {c: g for g in GROUPS for c in g[3]}
WHO = (('all', 'All'), ('mine', 'Mine'), ('none', 'Not given to anyone'), ('waiting', 'Waiting on us'))
PER_PAGE = 40
SNIPPET = 160

EMPTY = 'Nobody has written to us yet. Messages from WhatsApp, e-mail, the website and its chat show up here.'
NO_MATCH = 'Nothing here with these filters.'


def filters(args):
    who = args.get('who') if args.get('who') in dict(WHO) else 'all'
    ch = args.get('ch') if args.get('ch') in GROUP_BY_KEY else ''
    return {'who': who, 'ch': ch, 'q': ' '.join((args.get('q') or '').split())[:80]}


def _channels(f):
    return GROUP_BY_KEY[f['ch']][3] if f['ch'] else CHANNELS


def _people(f):
    """Per person who ever wrote on the chosen channels: their newest message from them, and the newest either way
    (a send that failed is no message). One grouped select."""
    tp = CrmTouchpoint
    said = or_(tp.direction == 'in', func.coalesce(tp.status, '') != 'failed')
    last_in = func.max(case((tp.direction == 'in', tp.created_at)))
    return (select(tp.person_id.label('pid'), last_in.label('last_in'), func.max(tp.created_at).label('last_at'))
            .where(tp.channel.in_(_channels(f)), tp.direction.in_(('in', 'out')), said)
            .group_by(tp.person_id)
            .having(last_in.isnot(None)))


def _query(f, user, who):
    """(pid, last_in, last_at) of the people a "whose" tab lists with the filters `f`."""
    from app.services import crm_people
    sub = _people(f).subquery()
    q = (db.session.query(sub.c.pid, sub.c.last_in, sub.c.last_at)
         .join(CrmPerson, CrmPerson.id == sub.c.pid))
    if f['q']:
        q = q.filter(crm_people.person_match(f['q']))
    L = CrmLead
    if who == 'mine':                    # anybody whose lead I look after
        q = q.filter(exists().where(L.person_id == sub.c.pid, L.owner_id == user.id))
    elif who == 'none':                  # an open lead nobody has taken yet
        q = q.filter(exists().where(L.person_id == sub.c.pid, L.status == 'open', L.owner_id.is_(None)))
    elif who == 'waiting':               # they wrote last and nobody answered (crm_metrics: the one meaning)
        w = crm_metrics.waiting_rows(CrmTouchpoint.person_id.in_(select(sub.c.pid))).subquery()
        q = q.filter(sub.c.pid.in_(select(w.c.person_id)))
    return q


def page(f, user, n=1):
    """{'rows', 'total', 'pages', 'page', 'counts': {who: n}} for the filters `f` (filters()). A row: {'person',
    'lead', 'channel', 'group', 'direction', 'body', 'at', 'agent', 'waiting', 'waiting_since'}."""
    counts = {key: _query(f, user, key).count() for key, _w in WHO}
    total = counts[f['who']]
    pages = max(1, -(-total // PER_PAGE))
    n = max(1, min(n or 1, pages))
    hits = _query(f, user, f['who']).subquery()
    ids = [pid for (pid,) in db.session.query(hits.c.pid).order_by(hits.c.last_at.desc(), hits.c.pid.desc())
           .offset((n - 1) * PER_PAGE).limit(PER_PAGE)]
    return {'rows': _rows(ids, f), 'total': total, 'pages': pages, 'page': n, 'counts': counts}


def _rows(ids, f):
    if not ids:
        return []
    from sqlalchemy.orm import joinedload, selectinload
    people = {p.id: p for p in CrmPerson.query.options(selectinload(CrmPerson.leads).joinedload(CrmLead.owner),
                                                       selectinload(CrmPerson.leads).joinedload(CrmLead.stage))
              .filter(CrmPerson.id.in_(ids))}
    tp = CrmTouchpoint
    said = or_(tp.direction == 'in', func.coalesce(tp.status, '') != 'failed')
    ranked = (select(tp.id, tp.person_id,
                     func.row_number().over(partition_by=tp.person_id,
                                            order_by=(tp.created_at.desc(), tp.id.desc())).label('n'))
              .where(tp.person_id.in_(ids), tp.channel.in_(_channels(f)), tp.direction.in_(('in', 'out')), said)
              .subquery())
    newest = {t.person_id: t for t in CrmTouchpoint.query.options(joinedload(CrmTouchpoint.agent))
              .filter(CrmTouchpoint.id.in_(select(ranked.c.id).where(ranked.c.n == 1)))}
    touches = crm_metrics.last_touches(ids)
    out = []
    for pid in ids:
        person, t = people.get(pid), newest.get(pid)
        if person is None or t is None:
            continue
        entry = touches.get(pid) or {}
        waiting = crm_metrics.waiting_on_us(entry)
        out.append({'person': person, 'lead': _lead_of(person, t), 'channel': t.channel,
                    # the number of our own it went through (Set-up › Channels); None = the WhatsApp CRM's
                    'line': t.line.label if t.line_id and t.line is not None else None,
                    'group': CHANNEL_GROUP.get(t.channel, GROUPS[0]), 'direction': t.direction,
                    'body': _snippet(t.body), 'at': t.created_at,
                    'agent': t.agent.full_name if t.direction == 'out' and t.agent is not None else None,
                    'waiting': waiting, 'waiting_since': entry['reply_last'][2] if waiting else None})
    return out


def _lead_of(person, touch):
    """The lead a row is about: the message's own, else the open lead WhatsApp messages go to, else their newest."""
    from app.services import crm
    leads = [l for l in person.leads if l.deleted_at is None]
    own = next((l for l in leads if l.id == touch.lead_id), None)
    return own or crm.wa_lead_for(person) or (leads[0] if leads else None)


def _snippet(body):
    text = ' '.join((body or '').split())
    return text if len(text) <= SNIPPET else text[:SNIPPET - 1].rstrip() + '…'
