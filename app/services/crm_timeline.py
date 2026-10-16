"""The lead page's timeline: one stream of their messages and this lead's events, oldest first, from
portal data in a fixed number of queries, whatever its length.

What goes in:
  messages   WhatsApp, Instagram and Messenger of the person, across all their leads (one chat
             is one person's), plus anything they wrote us elsewhere (the other WhatsApp number,
             Telegram, SMS, e-mail, a phone call) as a bubble with its channel named
  events     only this lead's: stage moves, calls, notes, who looks after it, follow-ups done or
             not needed, "I sent the quote", the opt-out -- as slim lines

Nothing here calls the WhatsApp CRM.
"""
from datetime import datetime, timedelta

from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload

from app.models import (CRM_CALL_OUTCOMES, CRM_CHANNEL_LABELS, CrmStageChange, CrmTask, CrmTouchpoint, User)
from app.services import crm

TIMELINE_LIMIT = 300
PERSON_CHANNELS = ('whatsapp', 'instagram', 'facebook')     # every one of their leads' messages
BUBBLE_CHANNELS = ('whatsapp', 'instagram', 'facebook', 'wa_other', 'sms', 'telegram', 'email', 'chat', 'call')
ICONS = {'whatsapp': 'fa-brands fa-whatsapp', 'wa_other': 'fa-brands fa-whatsapp',
         'instagram': 'fa-brands fa-instagram', 'facebook': 'fa-brands fa-facebook-messenger',
         'telegram': 'fa-brands fa-telegram', 'sms': 'fa-solid fa-comment-sms', 'email': 'fa-solid fa-envelope',
         'call': 'fa-solid fa-phone', 'chat': 'fa-regular fa-comment'}
TICKS = ('sent', 'delivered', 'read', 'failed', 'opened', 'sending')
MORE_TEXT = 'Older messages are in Open full chat.'


def day_label(d, today):
    """'Today', 'Yesterday' or 'Mon 12 Oct' (with the year when it is not this year's)."""
    if d == today:
        return 'Today'
    if d == today - timedelta(days=1):
        return 'Yesterday'
    text = '%s %d %s' % (d.strftime('%a'), d.day, d.strftime('%b'))
    return text if d.year == today.year else '%s %d' % (text, d.year)


def _agent(tp):
    return tp.agent.full_name if tp.agent is not None else None


def _event(at, icon, text, detail=None, order=0):
    return {'kind': 'event', 'icon': icon, 'text': text, 'detail': detail or None, 'at': at, 'order': order}


def _touch(tp, lead, person):
    """One touchpoint as a timeline item, or None when it is not for this page."""
    here = tp.lead_id == lead.id
    ch, body, who = tp.channel, tp.body or '', _agent(tp)
    # 1. the milestone buttons ("I sent the quote"): this lead's, old ones logged as WhatsApp too
    if ch in ('whatsapp', 'system') and tp.code in crm.MILESTONES and not tp.external_id:
        if not here:
            return None
        return _event(tp.created_at, 'fa-solid fa-flag', crm.EVENTS[tp.code][0] + (' (%s)' % who if who else ''))
    # 2. rows from the sales sheet's import
    if tp.status == 'imported' and not tp.external_id:
        return _event(tp.created_at, 'fa-solid fa-file-import', body) if here else None
    if not here and ch not in PERSON_CHANNELS:
        return None
    if ch == 'system':
        return _event(tp.created_at, 'fa-solid fa-user-tag', body)
    if ch == 'note':
        return _event(tp.created_at, 'fa-regular fa-note-sticky', 'Note by %s: %s' % (who, body) if who else body)
    if ch == 'form':
        return _event(tp.created_at, 'fa-solid fa-file-lines', 'They filled in a form', ' '.join(body.split())[:300])
    if ch == 'call' and tp.direction == 'out':
        text = 'Call: %s' % CRM_CALL_OUTCOMES.get(tp.outcome, 'made')
        return _event(tp.created_at, 'fa-solid fa-phone', text + (' (%s)' % who if who else ''), body)
    if ch not in BUBBLE_CHANNELS or tp.direction not in ('in', 'out'):
        return _event(tp.created_at, ICONS.get(ch, 'fa-regular fa-comment'), body or CRM_CHANNEL_LABELS.get(ch, ch)) \
            if here else None
    # 7. a bubble
    kind, label, rest = crm.wa_media(body)
    media, text, full_chat = None, body, False
    if kind == 'media':
        media = label + (': ' + rest if label == 'Document' and rest else '')
        text, full_chat = ('' if label == 'Document' else rest), True
    elif kind == 'button':
        text, full_chat = rest, True
    elif kind == 'template':
        media, text = label, ''
    out = tp.direction == 'out'
    sender = None
    if out:
        sender = who or ('Sent in WhatsApp' if tp.status == 'imported' else 'Automatic')
    tick = tp.status if (ch == 'whatsapp' and out and tp.status in TICKS) else None
    fail = None
    if tick == 'failed':
        fail = tp.fail_reason or crm.wa_failure_text(None, None, person)
    elif ch == 'email' and out and tp.status == 'failed':
        tick, fail = 'failed', 'The e-mail did not go.'
    return {'kind': 'msg', 'side': tp.direction, 'channel': ch,
            'via_label': None if ch == 'whatsapp' else ('Phone call' if ch == 'call' else CRM_CHANNEL_LABELS.get(ch, ch)),
            'icon': ICONS.get(ch, 'fa-regular fa-comment'), 'who': sender, 'media': media, 'text': text,
            'tick': tick, 'fail': fail, 'full_chat': full_chat, 'at': tp.created_at, 'order': 0}


def build(lead, now=None, limit=TIMELINE_LIMIT):
    """The stream, oldest first: day separators, message bubbles and event lines. Four queries at
    most (touches, stage moves, finished follow-ups, the people who finished them)."""
    now = now or datetime.utcnow()
    p = lead.person
    rows = (CrmTouchpoint.query.options(joinedload(CrmTouchpoint.agent))
            .filter(or_(and_(CrmTouchpoint.person_id == p.id, CrmTouchpoint.channel.in_(PERSON_CHANNELS)),
                        CrmTouchpoint.lead_id == lead.id))
            .order_by(CrmTouchpoint.created_at.desc(), CrmTouchpoint.id.desc()).limit(limit + 1).all())
    more = len(rows) > limit
    items = []
    for tp in reversed(rows[:limit]):
        it = _touch(tp, lead, p)
        if it is not None and tp.created_at is not None:
            items.append(it)
    for ch in (CrmStageChange.query.options(joinedload(CrmStageChange.from_stage), joinedload(CrmStageChange.to_stage),
                                            joinedload(CrmStageChange.by))
               .filter_by(lead_id=lead.id).all()):
        to = ch.to_stage.name if ch.to_stage else '?'
        text = 'Stage: %s → %s' % (ch.from_stage.name, to) if ch.from_stage else 'Stage: %s' % to
        text += ' (%s)' % ch.by.full_name if ch.by else ' (automatic)'
        detail = (ch.reason or '').replace(' (automatic)', '').strip()
        if detail in [v[0] for v in crm.EVENTS.values()]:
            detail = ''
        items.append(_event(ch.created_at, 'fa-solid fa-arrow-right-arrow-left', text, detail, order=1))
    tasks = (CrmTask.query.filter(CrmTask.lead_id == lead.id, CrmTask.status != 'open', CrmTask.done_at.isnot(None))
             .all())
    ids = {t.done_by_id for t in tasks if t.done_by_id}
    names = {u.id: u.full_name for u in User.query.filter(User.id.in_(ids))} if ids else {}
    for t in tasks:
        if t.note in ('Stage changed', 'Pipeline changed'):
            continue
        by = names.get(t.done_by_id)
        if t.status == 'done':
            text, icon = 'Follow-up done: %s' % t.title + (' (%s)' % by if by else ''), 'fa-solid fa-check'
        elif t.status == 'skipped':
            text, icon = 'Follow-up not needed: %s' % t.title, 'fa-solid fa-forward'
        else:
            text, icon = 'Follow-up being sent: %s' % t.title, 'fa-solid fa-paper-plane'
        items.append(_event(t.done_at, icon, text, None if t.note in CRM_CALL_OUTCOMES else t.note, order=2))
    if p.wa_opt_out_at is not None:
        items.append(_event(p.wa_opt_out_at, 'fa-solid fa-ban', 'Opted out of WhatsApp'))
    items.sort(key=lambda i: (i['at'], i['order']))
    today = (now + crm.IST).date()
    out, last_day = [], None
    if more:
        out.append({'kind': 'more', 'text': MORE_TEXT})
    for it in items:
        day = (it['at'] + crm.IST).date()
        if day != last_day:
            out.append({'kind': 'day', 'label': day_label(day, today)})
            last_day = day
        it['time'] = (it['at'] + crm.IST).strftime('%H:%M')
        out.append(it)
    return out
