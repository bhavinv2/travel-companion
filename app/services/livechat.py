"""Live chat (2026-10-30): the portal's own chat bubble on our websites, answered in the portal -- in place of
tawk.to's bubble, whose inbox no other system can answer from (so it could only be framed, and it is not).

The visitor's side (routes/livechat.py, public): the bubble (static/js/live-chat.js, served at /live-chat.js) asks for
a name, an e-mail or phone number and the first message, and starts a chat: a lead under the source "Website live
chat" (crm.capture), the first message on its timeline. Their browser keeps the chat's secret (`token`) and asks for
news every few seconds; what they write after that is a reply on the lead (crm.record_reply).

Our side: Live chat in the rail beside WhatsApp chats, and Inbox › Live chat -- the chats (crm_inbox, channel
'webchat'), and one chat with the lead page's own message box ("Send on: Live chat", reply()). A visitor sees only
their own chat's messages (live_chat_id) and, of us, a first name -- whatever e-mail they type.

    config() / save_config()  the switch, the words and the colour of the bubble (Set-up › Integrations › Live chat)
    start()                   a new chat from the bubble
    said() / news()           what the visitor writes / what they get when they ask for news
    reply()                   one of us answers (the box's "Live chat")
    online()                  who of us is here to answer: staff with the page, seen in the portal lately
    chat_of() / chats_of()    a person's newest chat (where a reply goes) / for many people at once
    thread()                  one person's live chat messages, as the middle of the Live chat screen shows them
"""
import re
import secrets
import time
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app import db
from app.models import CrmLiveChat, CrmTouchpoint
from app.services import settings

CHANNEL = 'webchat'
SOURCE_KEY = 'live-chat'
SETTING = 'livechat'
BODY_MAX = 2000
NAME_MAX = 80
HERE_FOR = timedelta(seconds=75)          # their browser asks every 3-30 seconds: quiet longer, they left the page
TYPING_FOR = timedelta(seconds=7)
ONLINE_FOR = timedelta(minutes=10)        # a staff member seen in the portal this lately can answer
SEEN_EVERY = timedelta(seconds=20)        # seen_at is written at most this often
NEWS_MAX = 100
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

# what a visitor may pick before they write: the product the lead is about (crm_products codes; '' = general)
TOPICS = (('TC', 'A travel companion'), ('TI', 'Travel insurance'), ('SH', 'Care at home (Sahayak)'),
          ('', 'Something else'))
DEFAULTS = {'on': True,
            'title': 'NRI Parent Service',
            'greeting': 'Hi there! Ask us anything about care, travel or insurance for your parents.',
            'away': "We are away just now. Leave a message and we will reply by e-mail or WhatsApp.",
            'color': '#0F1F3D'}
COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


class ChatError(ValueError):
    """Something the visitor (or the agent) can put right, in words they can act on."""


# ------------------------------------------------------------------------------------------------ the settings

def config():
    """{'on', 'title', 'greeting', 'away', 'color'}: what an admin saved over the defaults."""
    v = settings.get_setting(SETTING) or {}
    out = dict(DEFAULTS)
    if isinstance(v, dict):
        out.update({k: v[k] for k in DEFAULTS if k in v and v[k] not in (None, '')})
        out['on'] = bool(v.get('on', True))
    if not COLOR_RE.match(out['color']):
        out['color'] = DEFAULTS['color']
    return out


def enabled():
    return config()['on']


def bubble_on():
    """enabled() for the public pages' templates: a page never fails over the bubble (an error page while the
    database is away, say)."""
    try:
        return enabled()
    except Exception:          # noqa: BLE001 -- no bubble rather than no page
        db.session.rollback()
        return False


def dark_enough(color):
    """White words on `color` read well (contrast 4.5:1 or more)."""
    if not COLOR_RE.match(color or ''):
        return False
    def lin(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return 1.05 / (0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b) + 0.05) >= 4.5


def save_config(form, actor):
    """Keep what the Settings tab sent. Returns False when the colour was too light to keep (the default is kept
    instead). Commits."""
    def words(key, n):
        return ' '.join(str(form.get(key) or '').split())[:n] or DEFAULTS[key]
    color = (form.get('color') or '').strip()
    ok = dark_enough(color)
    settings.set_setting(SETTING, {'on': form.get('on') in ('1', 'on', 'true', True),
                                   'title': words('title', 60), 'greeting': words('greeting', 240),
                                   'away': words('away', 240), 'color': color if ok else DEFAULTS['color']}, actor)
    return ok


# ------------------------------------------------------------------------------------------------ who answers

_online = {'at': 0.0, 'names': []}
ONLINE_EVERY = 20                         # seconds: every visitor's browser asks, the answer is shared this long


def online(now=None):
    """First names of the staff who may answer live chats (the page `web_chat`) and were in the portal in the last
    ONLINE_FOR, at most three; [] when nobody is. Worked out at most every ONLINE_EVERY seconds; `now` works it out
    afresh (Live chat's own page: whoever has it open is here)."""
    if time.monotonic() - _online['at'] < ONLINE_EVERY and now is None:
        return _online['names']
    from app.models import User, UserSession
    from app.services import access
    since = (now or datetime.utcnow()) - ONLINE_FOR
    ids = [uid for (uid,) in db.session.query(UserSession.user_id).distinct()
           .filter(UserSession.ended_at.is_(None), UserSession.last_seen_at >= since)]
    names = []
    for u in User.query.filter(User.id.in_(ids)).order_by(User.first_name) if ids else []:
        try:
            ok = access.is_staff(u) and access.can(u, 'web_chat')
        except Exception:          # noqa: BLE001 -- a role nobody can read: not somebody to promise
            ok = False
        if ok:
            names.append((u.first_name or u.username or 'Team').split(' ')[0][:20])
    _online.update(at=time.monotonic(), names=names[:3])
    return _online['names']


# ------------------------------------------------------------------------------------------------ the visitor

def _clean_page(url):
    url = str(url or '').strip().split('#', 1)[0][:500]
    return url if url.startswith(('https://', 'http://')) else None


def _site(url):
    m = re.match(r'^https?://([^/:?#]+)', url or '')
    return m.group(1).lower()[:120] if m else None


def start(name, contact, message, topic='', page_url=None, page_title=None):
    """A new chat from the bubble: the lead (new, or the person's open one) with their first message on it. Returns
    the CrmLiveChat; raises ChatError with what to put right. Commits."""
    from app.services import crm
    name = ' '.join(str(name or '').split())[:NAME_MAX]
    contact = str(contact or '').strip()[:120]
    message = str(message or '').strip()[:BODY_MAX]
    if not name:
        raise ChatError('Please tell us your name.')
    phone = email = None
    if '@' in contact:
        if not EMAIL_RE.match(contact):
            raise ChatError('That e-mail address does not look right.')
        email = contact.lower()
    elif contact:
        phone = crm.normalise_phone(re.sub(r'[\s().\-]', '', contact))
        if not phone:
            raise ChatError('That number does not look right. Start it with + and the country code.')
    else:
        raise ChatError('Please give an e-mail or a WhatsApp number, so we can answer if you leave.')
    if not message:
        raise ChatError('Write your question first.')
    topic = topic if topic in {k for k, _w in TOPICS} else ''
    page_url = _clean_page(page_url)
    chat = CrmLiveChat(token=secrets.token_urlsafe(32), site=_site(page_url), page_url=page_url,
                       page_title=' '.join(str(page_title or '').split())[:200] or None,
                       started_at=datetime.utcnow(), seen_at=datetime.utcnow())
    db.session.add(chat)
    db.session.flush()
    ext = 'livechat:%d:start' % chat.id
    lead = crm.capture_safely(SOURCE_KEY, name=name, phone=phone, email=email, product=topic or None,
                              message=message, channel=CHANNEL, external_id=ext)
    if lead is None:
        db.session.rollback()
        raise ChatError('Sorry, the chat could not start. Please try again in a moment.')
    tp = CrmTouchpoint.query.filter_by(external_id=ext).first()
    chat = db.session.get(CrmLiveChat, chat.id)
    if chat is None:               # the capture's own commit kept it; a rollback inside it did not
        raise ChatError('Sorry, the chat could not start. Please try again in a moment.')
    chat.person_id, chat.lead_id = lead.person_id, lead.id
    if tp is not None:
        tp.live_chat_id = chat.id
    db.session.commit()
    return chat


def by_token(token):
    token = str(token or '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{30,64}', token):
        return None
    return CrmLiveChat.query.filter_by(token=token).execution_options(include_hidden=True).first()


def _lead(chat):
    from app.services import crm
    lead = chat.lead
    if lead is None or lead.deleted_at is not None:
        lead = crm.wa_lead_for(chat.person) if chat.person is not None else None
    return lead


def said(chat, text):
    """The visitor wrote in their chat: a reply on the lead. Returns the touchpoint. Commits."""
    from app.services import crm
    text = str(text or '').strip()[:BODY_MAX]
    if not text:
        raise ChatError('Write something first.')
    lead = _lead(chat)
    if lead is None:
        raise ChatError('This chat has ended. Start a new one.')
    crm.record_reply(lead, text, channel=CHANNEL)
    tp = (CrmTouchpoint.query.filter_by(lead_id=lead.id, channel=CHANNEL, direction='in')
          .order_by(CrmTouchpoint.id.desc()).first())
    tp.live_chat_id = chat.id
    now = datetime.utcnow()
    chat.seen_at, chat.closed_at = now, None
    db.session.commit()
    return tp


def end(chat):
    chat.closed_at = datetime.utcnow()
    db.session.commit()


def _first(user):
    return ((user.first_name or user.username or 'Team').split(' ')[0])[:20] if user is not None else 'Team'


def news(chat, after=0, reading=False, now=None):
    """What the visitor's browser gets when it asks: this chat's messages after id `after` (theirs and ours, ours
    with a first name only), whether one of us is typing, and who is here to answer. `reading`: the chat is open on
    their screen, so what came is read. Writes when they were here at most every SEEN_EVERY."""
    now = now or datetime.utcnow()
    rows = (CrmTouchpoint.query.options(joinedload(CrmTouchpoint.agent)).execution_options(include_hidden=True)
            .filter(CrmTouchpoint.live_chat_id == chat.id, CrmTouchpoint.id > int(after or 0),
                    CrmTouchpoint.direction.in_(('in', 'out')))
            .order_by(CrmTouchpoint.id).limit(NEWS_MAX).all())
    msgs = [{'id': t.id, 'me': t.direction == 'in', 'text': t.body or '',
             'at': t.created_at.isoformat() + 'Z' if t.created_at else None,
             'who': None if t.direction == 'in' else _first(t.agent)} for t in rows]
    dirty = False
    if chat.seen_at is None or now - chat.seen_at > SEEN_EVERY:
        chat.seen_at, dirty = now, True
    newest_ours = max((m['id'] for m in msgs if not m['me']), default=0)
    if reading and newest_ours > (chat.read_upto or 0):
        chat.read_upto, dirty = newest_ours, True
    if dirty:
        db.session.commit()
    typing = bool(chat.agent_typing_at and now - chat.agent_typing_at < TYPING_FOR)
    here_now = list(online())
    # whoever answers this chat, or is typing in it, is here -- whatever the shared list said a moment ago
    ours = (CrmTouchpoint.query.with_entities(func.max(CrmTouchpoint.created_at)).execution_options(include_hidden=True)
            .filter(CrmTouchpoint.live_chat_id == chat.id, CrmTouchpoint.direction == 'out').scalar())
    if chat.agent is not None and (typing or (ours and now - ours < ONLINE_FOR)):
        name = _first(chat.agent)
        here_now = [name] + [n for n in here_now if n != name]
    return {'messages': msgs, 'typing': _first(chat.agent) if typing else None, 'online': here_now[:3],
            'closed': chat.closed_at is not None}


# ------------------------------------------------------------------------------------------------ our side

def chat_of(person):
    """The person's newest live chat (where a reply goes), or None."""
    if person is None:
        return None
    return (CrmLiveChat.query.filter_by(person_id=person.id)
            .order_by(CrmLiveChat.started_at.desc(), CrmLiveChat.id.desc()).first())


def chats_of(person_ids):
    """{person_id: their newest CrmLiveChat} in one query."""
    ids = sorted({int(i) for i in person_ids if i})
    if not ids:
        return {}
    newest = (db.session.query(CrmLiveChat.person_id, func.max(CrmLiveChat.id).label('id'))
              .filter(CrmLiveChat.person_id.in_(ids)).group_by(CrmLiveChat.person_id).subquery())
    return {c.person_id: c for c in CrmLiveChat.query.join(newest, newest.c.id == CrmLiveChat.id)}


def here(chat, now=None):
    """Is the visitor still on the page (their browser asked lately)?"""
    return bool(chat is not None and chat.closed_at is None and chat.seen_at is not None
                and (now or datetime.utcnow()) - chat.seen_at < HERE_FOR)


def reply(lead, text, user):
    """One of us answers in the person's live chat. Raises ChatError when they have none. Commits."""
    from app.services import crm
    chat = chat_of(lead.person)
    if chat is None:
        raise ChatError('They have no live chat with us. Answer on WhatsApp or by e-mail.')
    text = str(text or '').strip()[:BODY_MAX]
    if not text:
        raise ChatError('Write the message first.')
    tp = crm.log_touch(lead, CHANNEL, 'out', body=text, user=user, status='sent')
    tp.live_chat_id = chat.id
    chat.agent_id, chat.agent_typing_at = user.id, None
    db.session.commit()
    return {'mode': 'sent', 'here': here(chat)}


def typing(person, user):
    """One of us is typing in the person's chat: the visitor sees "… is typing" for a few seconds."""
    chat = chat_of(person)
    if chat is None:
        return False
    chat.agent_typing_at, chat.agent_id = datetime.utcnow(), user.id
    db.session.commit()
    return True


def thread(lead, now=None, limit=200):
    """One person's live chat messages, oldest first, with the days between (crm_timeline's bubbles)."""
    from app.services import crm_timeline
    return crm_timeline.channel_thread(lead, CHANNEL, now=now, limit=limit)


def status_line(chat, now=None):
    """'On the site now · Travel insurance' / 'Left 5 min ago' / 'Ended the chat', for the screens."""
    from app.services import clock
    if chat is None:
        return None
    now = now or datetime.utcnow()
    page = chat.page_title or chat.site
    if here(chat, now):
        return 'On the site now' + (' · %s' % page if page else '')
    if chat.closed_at is not None:
        return 'Ended the chat'
    if chat.seen_at is None:
        return 'Left the site'
    mins = int((now - chat.seen_at).total_seconds() // 60)
    if mins < 60:
        return 'Left %d min ago' % max(mins, 1)
    return 'Left %s' % clock.fmt(chat.seen_at, '%d %b, %H:%M')
