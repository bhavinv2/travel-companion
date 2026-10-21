"""AI help on the lead page (Sales CRM 2.0, run 5b): "Summarise" writes a 3-5 line summary of the lead and a
suggested next message, which only fills the message box -- the agent reads it, edits it and presses Send.

OFF unless BOTH the setting `crm.ai` is on (Set-up > Automation > Overview, "AI on the lead page") and the server has
ANTHROPIC_API_KEY. What is sent to Anthropic: the product, the stage, the trip date and the text of the lead's recent
messages and notes -- with phone numbers and e-mail addresses taken out first (scrub). Nothing is sent anywhere else
and nothing is sent to the customer.

The answer is kept on the lead (CrmLead.ai_cache) until a newer message or note arrives. Any failure says
UNAVAILABLE. The one call out is call_claude() (tests replace it: no network in a test).
"""
import json
import logging
import os
import re
from datetime import datetime, timedelta

from app import db
from app.models import CrmTouchpoint

log = logging.getLogger(__name__)

SETTING = 'crm.ai'
ENV_KEY = 'ANTHROPIC_API_KEY'
API_URL = 'https://api.anthropic.com/v1/messages'
API_VERSION = '2023-06-01'
MODEL = 'claude-sonnet-5-5'
MAX_TOKENS = 2000
TIMEOUT = 20
TOUCHES = 30                     # the newest messages and notes that are read
BODY_MAX = 700                   # characters of one message
TEXT_MAX = 9000                  # characters of everything sent
UNAVAILABLE = 'AI is not available right now'
NOTE = ("When on, the text of a lead's recent messages and notes is sent to Anthropic to write the summary. "
        "No phone numbers or e-mail addresses are sent.")
IST = timedelta(hours=5, minutes=30)

EMAIL_RE = re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+')
# a run of 7+ digits, allowing the spaces, dots, dashes and brackets people write numbers with, with or without +
PHONE_RE = re.compile(r'(?<![\w])\+?\d(?:[\s().\-]{0,3}\d){6,}')

SYSTEM = ('You help a sales agent at NRI Parent Service (travel insurance, travel companions and home care for the '
          'parents of Indians living abroad). You read one customer enquiry and answer ONLY with JSON: '
          '{"summary": ["3 to 5 short lines"], "next_message": "a short, friendly WhatsApp message the agent could send '
          'next"}. Plain words, no bullet characters, no placeholders such as [name], no prices or promises that are '
          'not in the messages. The message must not ask for card or bank details.')


class AIError(RuntimeError):
    pass


# ============================================================================================ the switch

def switched_on():
    from app.services import settings
    v = settings.get_setting(SETTING) or {}
    return bool(v.get('on')) if isinstance(v, dict) else False


def has_key():
    return bool((os.environ.get(ENV_KEY) or '').strip())


def enabled():
    return switched_on() and has_key()


def switch(on, actor=None):
    from app.services import settings
    settings.set_setting(SETTING, {'on': bool(on)}, actor)        # commits


# ============================================================================================ what is sent

def scrub(text, extra=()):
    """The text with e-mail addresses and phone numbers taken out (and any of `extra`, the person's own)."""
    out = str(text or '')
    for v in extra:
        if v:
            out = out.replace(v, ' ')
    out = EMAIL_RE.sub('[e-mail]', out)
    return PHONE_RE.sub('[phone]', out)


def _who(tp):
    if tp.direction == 'in':
        return 'Customer'
    if tp.channel == 'note' or tp.direction == 'none':
        return 'Note'
    return 'Us'


def material(lead):
    """What is sent: a few facts about the enquiry and its recent messages and notes, oldest first, scrubbed."""
    from app.services import crm_products
    person = lead.person
    extra = []
    if person is not None:
        extra = [person.phone, person.email, (person.phone or '').lstrip('+')]
    tps = (CrmTouchpoint.query.filter(CrmTouchpoint.lead_id == lead.id, CrmTouchpoint.channel != 'system',
                                      CrmTouchpoint.body.isnot(None))
           .order_by(CrmTouchpoint.created_at.desc(), CrmTouchpoint.id.desc()).limit(TOUCHES).all())
    lines = ['Product: %s' % crm_products.labels().get(lead.product, lead.product),
             'Stage: %s' % (lead.stage.name if lead.stage else 'not routed yet'),
             'Status: %s' % lead.status]
    if lead.departure_date:
        lines.append('Travel date: %s' % lead.departure_date.strftime('%d %b %Y'))      # words: not read as a number
    lines.append('Messages and notes, oldest first:')
    for tp in reversed(tps):
        body = ' '.join(str(tp.body or '').split())[:BODY_MAX]
        if not body:
            continue
        when = (tp.created_at + IST).strftime('%d %b') if tp.created_at else ''
        lines.append('[%s] %s (%s): %s' % (when, _who(tp), tp.channel, body))
    text = '\n'.join(lines)
    return scrub(text, extra)[-TEXT_MAX:]


def newest_touch_id(lead):
    return db.session.query(db.func.max(CrmTouchpoint.id)).filter(CrmTouchpoint.lead_id == lead.id).scalar() or 0


# ============================================================================================ the call

def call_claude(system, text):
    """POST the Messages API (no SDK: requests is already a dependency). The answer's text, or AIError."""
    import requests
    key = (os.environ.get(ENV_KEY) or '').strip()
    if not key:
        raise AIError('no key')
    resp = requests.post(API_URL, timeout=TIMEOUT,
                         headers={'x-api-key': key, 'anthropic-version': API_VERSION,
                                  'content-type': 'application/json'},
                         json={'model': MODEL, 'max_tokens': MAX_TOKENS, 'system': system,
                               'output_config': {'effort': 'low'},
                               'messages': [{'role': 'user', 'content': text}]})
    if resp.status_code != 200:
        raise AIError('status %s' % resp.status_code)
    data = resp.json()
    if data.get('stop_reason') == 'refusal':
        raise AIError('refused')
    out = ''.join(b.get('text') or '' for b in data.get('content') or [] if b.get('type') == 'text').strip()
    if not out:
        raise AIError('empty')
    return out


def parse(text):
    """{'summary': [lines], 'next': text} from the model's JSON (or its plain text when it is not JSON)."""
    raw = str(text or '').strip()
    got = None
    a, b = raw.find('{'), raw.rfind('}')
    if a >= 0 and b > a:
        try:
            got = json.loads(raw[a:b + 1])
        except ValueError:
            got = None
    if isinstance(got, dict):
        summary = got.get('summary')
        if isinstance(summary, str):
            summary = [s for s in summary.splitlines()]
        summary = [' '.join(str(s).split()).lstrip('-• ').strip() for s in (summary or [])]
        nxt = ' '.join(str(got.get('next_message') or '').split())
    else:
        summary = [' '.join(s.split()).lstrip('-• ') for s in raw.splitlines()]
        nxt = ''
    summary = [s[:300] for s in summary if s][:5]
    if not summary:
        raise AIError('no summary')
    return {'summary': summary, 'next': nxt[:1500]}


def summarise(lead, fresh=False):
    """{'summary', 'next', 'cached'} for the lead page; AIError with nothing changed when it is off or fails. Kept on
    the lead until a newer message or note (the caller commits)."""
    if not enabled():
        raise AIError('off')
    newest = newest_touch_id(lead)
    cache = lead.ai_cache if isinstance(lead.ai_cache, dict) else None
    if cache and not fresh and cache.get('touch_id') == newest and cache.get('summary'):
        return {'summary': cache['summary'], 'next': cache.get('next') or '', 'cached': True}
    try:
        got = parse(call_claude(SYSTEM, material(lead)))
    except AIError:
        raise
    except Exception as exc:      # noqa: BLE001 -- the network, a timeout, a bad answer: all "not available"
        log.warning('AI summary failed for lead %s: %s', lead.id, exc.__class__.__name__)
        raise AIError('failed') from None
    lead.ai_cache = {'touch_id': newest, 'summary': got['summary'], 'next': got['next'],
                     'at': datetime.utcnow().isoformat(timespec='seconds')}
    return {'summary': got['summary'], 'next': got['next'], 'cached': False}
