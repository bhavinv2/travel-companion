"""The lead page's timeline: one stream of their messages and this lead's events, oldest first, from
portal data in a fixed number of queries, whatever its length.

What goes in:
  messages   WhatsApp, Instagram and Messenger of the person, across all their leads (one chat
             is one person's), plus anything they wrote us elsewhere (the other WhatsApp number,
             Telegram, SMS, e-mail, a phone call) as a bubble with its channel named
  events     only this lead's: stage moves, calls, notes, who looks after it, follow-ups done or
             not needed, "I sent the quote", the opt-out -- as slim lines

number_thread() is one chat beside WhatsApp chats: only their WhatsApp messages with one number of ours;
channel_thread() is one chat of another channel the portal answers in (the website's live chat).

Nothing here calls the WhatsApp CRM.
"""
from datetime import datetime, timedelta

from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload

from app.models import (CRM_CALL_OUTCOMES, CRM_CHANNEL_LABELS, CrmStageChange, CrmTask, CrmTouchpoint, User)
from app.services import crm

TIMELINE_LIMIT = 300
PERSON_CHANNELS = ('whatsapp', 'instagram', 'facebook', 'webchat')     # every one of their leads' messages
BUBBLE_CHANNELS = ('whatsapp', 'instagram', 'facebook', 'wa_other', 'sms', 'telegram', 'email', 'chat', 'call',
                   'webchat')
ICONS = {'webchat': 'fa-regular fa-comment-dots', 'whatsapp': 'fa-brands fa-whatsapp', 'wa_other': 'fa-brands fa-whatsapp',
         'instagram': 'fa-brands fa-instagram', 'facebook': 'fa-brands fa-facebook-messenger',
         'telegram': 'fa-brands fa-telegram', 'sms': 'fa-solid fa-comment-sms', 'email': 'fa-solid fa-envelope',
         'call': 'fa-solid fa-phone', 'chat': 'fa-regular fa-comment'}
TICKS = ('sent', 'delivered', 'read', 'failed', 'opened', 'sending')
MORE_TEXT = 'Older messages are in Open full chat.'
THREAD_LIMIT = 200
THREAD_MORE = 'Older messages are on the lead page.'


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


def _touch(tp, lead, person, crm_via=None):
    """One touchpoint as a timeline item, or None when it is not for this page."""
    here = tp.lead_id == lead.id
    ch, body, who = tp.channel, tp.body or '', _agent(tp)
    # 1. the milestone buttons ("I sent the quote"): this lead's, old ones logged as WhatsApp too
    if not tp.external_id and ((ch == 'system' and tp.code) or (ch == 'whatsapp' and tp.code in crm.LEGACY_MILESTONES)):
        if not here:
            return None
        text = tp.body if ch == 'system' and tp.body else crm.LEGACY_MILESTONES.get(tp.code, tp.code)
        return _event(tp.created_at, 'fa-solid fa-flag', text + (' (%s)' % who if who else ''))
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
    if ch == 'whatsapp':
        # a number of our own (Set-up › Channels) is named; so is the WhatsApp CRM's once it is not the only one
        via_label = ('WhatsApp · %s' % tp.line.label) if tp.line_id and tp.line is not None else crm_via
    else:
        via_label = 'Phone call' if ch == 'call' else CRM_CHANNEL_LABELS.get(ch, ch)
    return {'kind': 'msg', 'side': tp.direction, 'channel': ch, 'via_label': via_label,
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
    # the WhatsApp CRM's number is named only once there is another (channels.several): asked once, not per message
    crm_via = None
    if any(tp.channel == 'whatsapp' and not tp.line_id for tp in rows[:limit]):
        from app.services import channels
        if channels.several():
            crm_via = 'WhatsApp · %s' % channels.badge(None)['name']
    items = []
    for tp in reversed(rows[:limit]):
        it = _touch(tp, lead, p, crm_via)
        if it is not None and tp.created_at is not None:
            items.append(it)
    for ch in (CrmStageChange.query.options(joinedload(CrmStageChange.from_stage), joinedload(CrmStageChange.to_stage),
                                            joinedload(CrmStageChange.by))
               .filter_by(lead_id=lead.id).all()):
        to = ch.to_stage.name if ch.to_stage else '?'
        text = 'Stage: %s → %s' % (ch.from_stage.name, to) if ch.from_stage else 'Stage: %s' % to
        text += ' (%s)' % ch.by.full_name if ch.by else ' (automatic)'
        detail = (ch.reason or '').replace(' (automatic)', '').strip()
        if detail in crm.LEGACY_MILESTONES.values() or (ch.to_stage is not None and ch.to_stage.button_label
                                                        and detail == ch.to_stage.button_label):
            detail = ''
        items.append(_event(ch.created_at, 'fa-solid fa-arrow-right-arrow-left', text, detail, order=1))
    tasks = (CrmTask.query.filter(CrmTask.lead_id == lead.id, CrmTask.status != 'open', CrmTask.done_at.isnot(None))
             .all())
    ids = {t.done_by_id for t in tasks if t.done_by_id}
    names = {u.id: u.full_name for u in User.query.filter(User.id.in_(ids))} if ids else {}
    for t in tasks:
        if t.note in ('Stage changed', 'Pipeline changed', crm.WAIT_NOTE):
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
    return _days(items, now, MORE_TEXT if more else None)


def number_thread(lead, line, now=None, limit=THREAD_LIMIT):
    """One chat as WhatsApp chats shows it for a number answered in the portal: the person's WhatsApp messages with
    one number of ours (`line`; None = the WhatsApp CRM's), oldest first, with the days between. The bubbles do not
    name the number: the whole thread is on it."""
    on = CrmTouchpoint.line_id.is_(None) if line is None else CrmTouchpoint.line_id == line.id
    return _thread(lead, [CrmTouchpoint.channel == 'whatsapp', on], now, limit)


def channel_thread(lead, channel, now=None, limit=THREAD_LIMIT):
    """One chat of one channel, all of it the person's (the website's live chat: 'webchat'), as number_thread draws a
    number's."""
    return _thread(lead, [CrmTouchpoint.channel == channel], now, limit)


def _thread(lead, where, now, limit):
    p = lead.person
    rows = (CrmTouchpoint.query.options(joinedload(CrmTouchpoint.agent))
            .filter(CrmTouchpoint.person_id == p.id, *where)
            .order_by(CrmTouchpoint.created_at.desc(), CrmTouchpoint.id.desc()).limit(limit + 1).all())
    items = []
    for tp in reversed(rows[:limit]):
        it = _touch(tp, lead, p)
        if it is not None and it['kind'] == 'msg' and tp.created_at is not None:      # the lead's events: its page
            it['via_label'] = None
            items.append(it)
    return _days(items, now or datetime.utcnow(), THREAD_MORE if len(rows) > limit else None)


def _days(items, now, more):
    """The items with a day line before each new day and their times filled in; `more` first when older ones were
    left out."""
    from app.services import clock
    today = clock.local(now).date()
    out, last_day = [], None
    if more:
        out.append({'kind': 'more', 'text': more})
    for it in items:
        day = clock.local(it['at']).date()
        if day != last_day:
            out.append({'kind': 'day', 'label': day_label(day, today)})
            last_day = day
        it['time'] = clock.fmt(it['at'], '%H:%M')
        out.append(it)
    return out
