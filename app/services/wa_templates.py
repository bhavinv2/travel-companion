"""WhatsApp templates for the Sales CRM's messages.

WhatsApp lets a business write first, or write after 24 hours of silence, only with a template
Meta has approved. Most follow-ups (TI #2 on day 3, the festival greeting, the policy-ending
reminder) are exactly that, so each WhatsApp step and each ready message gets a template made
from its own wording:

    "Hi {name}, {agent} here from NRI Parent Service ... {insurance_link}"
 -> "Hi {{1}}, {{2}} here from NRI Parent Service ... https://nriparentservice.com/travel-insurance"

Only what differs per person becomes a numbered blank ({name}, {agent}, {product}, {departure},
{days}, {ends}); links and the helpline numbers are written in, because a template with fewer
blanks is approved faster and a link Meta has reviewed is one it will not query.

The same function turns a step into its template and, when sending, a lead into the values for
the blanks -- so what is submitted to Meta and what is sent with it cannot drift apart.
"""
import csv
import io
import logging
import re
import threading
import time
from contextlib import contextmanager

from app import db

log = logging.getLogger(__name__)

# per-person tokens -> template blanks; everything else is written into the template text
VARIABLE_TOKENS = ('name', 'agent', 'product', 'departure', 'days', 'ends')
SAMPLES = {'name': 'Priya', 'agent': 'Harsha', 'product': 'travel insurance', 'departure': '12 Nov',
           'days': '10', 'ends': '20 Dec'}
LANGUAGE = 'en'
TOKEN = re.compile(r'\{([a-z_]+)\}')
NAME_OK = re.compile(r'^[a-z0-9_]{1,512}$')


def _static_values():
    """The written-in values: the public links and the helplines, as the site publishes them."""
    from flask import current_app
    from app.services import offices, urls
    site = (current_app.config.get('SITE_URL') or '').rstrip('/')
    out = {'helplines': ', '.join('%s (%s)' % (n['display'], n['label']) for n in offices.numbers()[:3])
           or 'our helpline'}
    for var, endpoint in (('insurance_link', 'insurance.landing'), ('companion_link', 'main.all_trips'),
                          ('sahayak_link', 'sahayak.landing'), ('site_link', 'main.index')):
        try:
            out[var] = urls.site_link(endpoint)
        except Exception:      # noqa: BLE001 -- outside a request
            out[var] = site
    return out


def parts(body, static=None):
    """(template body, the tokens behind {{1}}, {{2}} ... in order) for a message text."""
    static = static if static is not None else _static_values()
    tokens = []

    def sub(m):
        t = m.group(1)
        if t in VARIABLE_TOKENS:
            if t not in tokens:
                tokens.append(t)
            return '{{%d}}' % (tokens.index(t) + 1)
        return str(static.get(t, m.group(0)))
    return TOKEN.sub(sub, body or ''), tokens


def params(body, values):
    """The values for a template's blanks, in its order, for one lead (values: crm.fill_values)."""
    _, tokens = parts(body, static={})
    return [str(values.get(t) or '').strip() or SAMPLES.get(t, '') for t in tokens]


def slug_name(code):
    """'TI #2' -> 'nri_ti_2'; Meta wants lowercase letters, digits and underscores."""
    s = re.sub(r'[^a-z0-9]+', '_', (code or '').lower()).strip('_')
    return ('nri_' + s)[:512] if s else ''


def problems(name, body, tokens):
    """What Meta would refuse, in words somebody can act on."""
    out = []
    if not NAME_OK.match(name or ''):
        out.append('The name may use only lowercase letters, digits and _.')
    if len(body) > 1024:
        out.append('Too long for a template (%d characters, at most 1024).' % len(body))
    stripped = body.strip()
    if stripped.startswith('{{') or stripped.endswith('}}'):
        out.append('A template cannot start or end with a blank ({{n}}).')
    if re.search(r'\}\}\s*\{\{', body):
        out.append('Two blanks next to each other need words between them.')
    if not stripped:
        out.append('There is no text.')
    return out


def _category(step=None, answer=None):
    """Sales follow-ups and greetings are MARKETING; reminders about something they already have
    (the policy ending, the trip coming up) are UTILITY. Meta has the last word either way."""
    if step is not None and step.stage is not None and step.stage.kind == 'won':
        return 'UTILITY'
    text = ((step.title if step else answer.title) or '').lower()
    if any(w in text for w in ('ends', 'ending', 'expir', 'renew', 'payment link', 'policy')):
        return 'UTILITY'
    return 'MARKETING'


def candidates():
    """Every message that needs a template: WhatsApp steps and ready messages (the ones with a
    code). [{name, code, title, category, language, body, tokens, samples, problems, step, answer}]"""
    from app.models import CrmAnswer, CrmPlaybookStep
    static = _static_values()
    rows = []
    steps = (CrmPlaybookStep.query.filter(CrmPlaybookStep.channel == 'whatsapp', CrmPlaybookStep.body.isnot(None))
             .order_by(CrmPlaybookStep.stage_id, CrmPlaybookStep.position).all())
    for s in steps:
        body, tokens = parts(s.body, static)
        rows.append({'kind': 'step', 'step': s, 'answer': None, 'code': s.code, 'title': s.title,
                     'pipeline': s.stage.pipeline.name if s.stage and s.stage.pipeline else '',
                     'product': s.stage.pipeline.product if s.stage and s.stage.pipeline else '',
                     'category': _category(step=s), 'body': body, 'tokens': tokens, 'source': s.body})
    for a in CrmAnswer.query.filter(CrmAnswer.code.isnot(None)).order_by(CrmAnswer.code).all():
        body, tokens = parts(a.body, static)
        rows.append({'kind': 'ready', 'step': None, 'answer': a, 'code': a.code, 'title': a.title,
                     'pipeline': 'Ready message', 'product': a.product,
                     'category': _category(answer=a), 'body': body, 'tokens': tokens, 'source': a.body})
    # One template per distinct text. A code used in two pipelines with different words gets the
    # product added, so neither overwrites the other; the same words used twice are one template
    # serving both (Meta would refuse a second with the same name anyway).
    out, by_name = [], {}
    for r in rows:
        name = r['step'].wa_template if r['step'] is not None and r['step'].wa_template else slug_name(r['code'])
        if name in by_name and by_name[name]['body'] != r['body']:
            name = '%s_%s' % (name, (r['product'] or 'x').lower())
        used = '%s: %s' % (r['pipeline'], r['title'])
        if name in by_name:
            first = by_name[name]
            first['used_for'].append(used)
            if r['step'] is not None:
                first['steps'].append(r['step'])
            continue
        r['name'] = name
        r['language'] = LANGUAGE
        r['samples'] = [SAMPLES.get(t, 'example') for t in r['tokens']]
        r['problems'] = problems(name, r['body'], r['tokens'])
        r['used_for'] = [used]
        r['steps'] = [r['step']] if r['step'] is not None else []
        by_name[name] = r
        out.append(r)
    return out


# ------------------------------------------------------------------- what WhatsApp has

_cache = {'at': 0.0, 'rows': None, 'info': None, 'error': None}
CACHE_SECONDS = 60
_local = threading.local()


@contextmanager
def cache_only():
    """Inside: statuses() answers from what it last heard (maybe nothing) and never asks the
    WhatsApp CRM -- for drawing a page without a network call."""
    before = getattr(_local, 'cache_only', False)
    _local.cache_only = True
    try:
        yield
    finally:
        _local.cache_only = before


def statuses(force=False):
    """{template name: status} from the WhatsApp CRM (APPROVED, PENDING, DRAFT, REJECTED...).
    Asked at most once a minute; {} when it cannot be reached (and error() says why)."""
    from app.services import wacrm_team
    if getattr(_local, 'cache_only', False):
        return _cache['rows'] or {}
    now = time.monotonic()
    if not force and _cache['rows'] is not None and now - _cache['at'] < CACHE_SECONDS:
        return _cache['rows']
    rows, info, error = {}, {}, None
    if wacrm_team.enabled():
        try:
            for t in wacrm_team.templates(status='ALL'):
                if (t.get('language') or LANGUAGE).split('_')[0] == LANGUAGE or t.get('name') not in rows:
                    rows[t.get('name')] = (t.get('status') or '').upper()
                    v = t.get('variables')
                    info[t.get('name')] = {
                        'status': (t.get('status') or '').upper(),
                        'category': (t.get('category') or '').strip().upper() or None,
                        'body': t.get('body') or '', 'language': t.get('language') or None,
                        'variables': v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None}
        except wacrm_team.TeamError as exc:
            error = str(exc)
    else:
        error = 'The WhatsApp CRM is not connected.'
    _cache.update(at=now, rows=rows, info=info, error=error)
    return rows


def template_info(name):
    """What the WhatsApp CRM says about one template -- {status, category ('MARKETING', 'UTILITY'...),
    variables (how many blanks it has)} -- from the same once-a-minute list as statuses(); {} when
    it is not known."""
    statuses()
    return dict((_cache.get('info') or {}).get(name) or {})


def heard():
    """Whether the WhatsApp CRM's template list has been heard at all yet."""
    return _cache['rows'] is not None


def approved_templates():
    """[{name, language, category, body, variables}] for the APPROVED templates, by name."""
    statuses()
    info = _cache.get('info') or {}
    return [{'name': n, 'language': i.get('language'), 'category': i.get('category'), 'body': i.get('body') or '',
             'variables': i.get('variables')}
            for n, i in sorted(info.items()) if i.get('status') == 'APPROVED' and n]


def template_text(name, params):
    """An approved template's words with {{1}}, {{2}} ... filled in; '' when its body is not known."""
    body = (template_info(name) or {}).get('body') or ''
    return re.sub(r'\{\{(\d+)\}\}', lambda m: str(params[int(m.group(1)) - 1])
                  if 0 < int(m.group(1)) <= len(params) else m.group(0), body)


def known_fills(values):
    """{template name: {'fill': [...], 'title'}} for templates the portal made from its own words:
    WhatsApp follow-ups (step.wa_template or slug_name(code)) and ready messages with a code
    (slug_name(code)); fill = params(body, values). Two queries."""
    from app.models import CrmAnswer, CrmPlaybookStep
    out = {}
    for s in CrmPlaybookStep.query.filter(CrmPlaybookStep.channel == 'whatsapp',
                                           CrmPlaybookStep.body.isnot(None)).all():
        name = s.wa_template or slug_name(s.code)
        if name and name not in out:
            out[name] = {'fill': params(s.body, values), 'title': s.title}
    for a in CrmAnswer.query.filter(CrmAnswer.code.isnot(None)).all():
        name = slug_name(a.code)
        if name and name not in out:
            out[name] = {'fill': params(a.body, values), 'title': a.title}
    return out


def blanks(body):
    """How many blanks ({{1}}, {{2}} ...) a step's words make: one per person token, counted once."""
    return len(parts(body or '', static={})[1])


def error():
    return _cache['error']


def approved(name):
    return bool(name) and statuses().get(name) == 'APPROVED'


def forget():
    _cache.update(at=0.0, rows=None, info=None, error=None)


# ------------------------------------------------------------------- putting them in

def push_drafts(rows=None):
    """Every candidate the WhatsApp CRM does not have yet goes in as a DRAFT (nothing is sent to
    Meta: a person reviews and submits each one on WhatsApp -> Templates), and each step is
    linked to its template so one-click and automatic sends use it once it is approved.
    Returns {created, skipped: [{name, reason}]}."""
    from app.services import wacrm_team
    rows = rows if rows is not None else candidates()
    items = [{'name': r['name'], 'category': r['category'], 'language': r['language'], 'body': r['body'],
              'sample_values': r['samples']} for r in rows if not r['problems']]
    skipped = [{'name': r['name'], 'reason': '; '.join(r['problems'])} for r in rows if r['problems']]
    result = wacrm_team.push_template_drafts(items) if items else {'created': 0, 'skipped': []}
    for r in rows:
        for step in r['steps']:
            if not step.wa_template and not r['problems']:
                step.wa_template = r['name']
    db.session.commit()
    forget()
    return {'created': result.get('created', 0), 'skipped': skipped + list(result.get('skipped') or [])}


def csv_text(rows=None):
    """The list as a spreadsheet: for review, or for submitting somewhere else."""
    rows = rows if rows is not None else candidates()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['Template name', 'Category', 'Language', 'Body', 'Sample values (in order)', 'Used for',
                'Code', 'Problems'])
    for r in rows:
        w.writerow([r['name'], r['category'], r['language'], r['body'], ' | '.join(r['samples']),
                    ' / '.join(r['used_for']), r['code'], '; '.join(r['problems'])])
    return out.getvalue()


# ------------------------------------------------------------------- ready answers -> quick replies

QUICK_TOKENS = {'name': '{{contact.first_name}}', 'agent': '{{agent.first_name}}'}


def quick_reply_text(body, static=None):
    """A ready answer in the WhatsApp CRM's quick-reply language: their first name and the
    agent's are filled in when it is picked in the inbox; links and helplines are written in.
    A lead-only value ({departure}, {days} ...) has no equivalent there and becomes "..."."""
    static = static if static is not None else _static_values()

    def sub(m):
        t = m.group(1)
        if t in QUICK_TOKENS:
            return QUICK_TOKENS[t]
        if t in static:
            return str(static[t])
        return '...'
    return TOKEN.sub(sub, body or '')


QUICK_KEY = 'crm_wa_quick'     # its own settings row, never "crm": a stale copy written back there could undo the switch
QUICK_TITLES_MAX = 500
QUICK_CONFLICT = '%d not copied: a WhatsApp button reply has the same title (%s). Rename one of them.'


def _quick_items():
    """Every quick reply as the WhatsApp CRM's quick replies take them. Built inside a request, so the links are the site's."""
    from app.models import CrmAnswer
    static = _static_values()
    return [{'title': ('%s · %s' % (a.code, a.title) if a.code else a.title).strip()[:120],
             'text': quick_reply_text(a.body, static)} for a in CrmAnswer.query.order_by(CrmAnswer.title).all()]


def quick_state():
    """What the portal last put in the WhatsApp CRM's quick replies: {titles, conflicts, due, error, at}.
    Read past the settings cache: both workers and a background thread write it."""
    from app.models import AppSetting
    row = db.session.get(AppSetting, QUICK_KEY, populate_existing=True)
    v = row.value if row is not None and isinstance(row.value, dict) else {}
    return {'titles': [t for t in v.get('titles') or [] if isinstance(t, str) and t.strip()],
            'conflicts': [t for t in v.get('conflicts') or [] if isinstance(t, str)],
            'due': bool(v.get('due')), 'error': v.get('error'), 'at': v.get('at')}


def _save_quick_state(state):
    from app.services import settings
    settings.set_setting(QUICK_KEY, state)        # commits


def conflict_words(titles):
    shown = ', '.join(titles[:5]) + (', …' if len(titles) > 5 else '')
    return QUICK_CONFLICT % (len(titles), shown)


def push_quick_replies(items=None):
    """Every quick reply into the WhatsApp CRM's quick replies, matched by title. The ones this portal
    put there before and no longer has (renamed or removed here) go out with remove_titles, so nothing
    the portal made stays there, locked, for good (contract 21). {created, updated, removed, conflicts}.
    Raises wacrm_team.TeamError, leaving the change marked for the jobs runner; the caller checks
    crm.wa_writes_on()."""
    from datetime import datetime
    from app.services import wacrm_team
    items = _quick_items() if items is None else items
    state = quick_state()
    have = {i['title'].strip().lower() for i in items}
    remove = [t for t in state['titles'] if t.strip().lower() not in have]
    try:
        out = (wacrm_team.push_quick_replies(items, remove_titles=remove) if (items or remove)
               else {'created': 0, 'updated': 0, 'removed': 0, 'conflicts': []})
    except wacrm_team.TeamError as exc:
        if exc.status == 404:                    # a WhatsApp CRM without it: nothing to copy to, nothing waits
            _save_quick_state(dict(state, due=False, error=None))
        else:
            _save_quick_state(dict(state, due=True, error=str(exc)[:250]))
        raise
    titles, seen = [], set()
    for i in items:
        k = i['title'].strip().lower()
        if k not in seen:
            seen.add(k)
            titles.append(i['title'].strip())
    _save_quick_state({'titles': titles[:QUICK_TITLES_MAX], 'conflicts': out['conflicts'], 'due': False, 'error': None,
                       'at': datetime.utcnow().isoformat(timespec='seconds')})
    return out


def quick_replies_changed():
    """A quick reply was saved or removed here, so WhatsApp's quick replies follow straight away in a
    background thread (WA_SYNC_INLINE, in tests: here and now). Marked first, so the jobs runner tries
    again if that fails. Nothing while the portal may not write to WhatsApp, as for contacts."""
    from flask import current_app
    from app.services import crm, wacrm_team
    if not (crm.wa_writes_on() and wacrm_team.enabled()):
        return
    items = _quick_items()                       # here, in the request: the links are the site's
    _save_quick_state(dict(quick_state(), due=True))
    app = current_app._get_current_object()
    if app.config.get('WA_SYNC_INLINE'):
        _push_isolated(app, items)
        return
    try:
        threading.Thread(target=_push_isolated, args=(app, items), daemon=True, name='wacrm-quick').start()
    except Exception:      # noqa: BLE001 -- marked: the jobs runner copies them
        log.warning('Quick replies not copied after a save; the jobs runner copies them', exc_info=True)


def _push_isolated(app, items):
    from app.services import wacrm
    with app.app_context():                     # its own session: the save is already committed
        try:
            with wacrm.short_timeouts():
                push_quick_replies(items)
        except Exception:      # noqa: BLE001 -- still marked; the jobs runner tries again
            db.session.rollback()
            log.warning('Quick replies not copied to WhatsApp after a save', exc_info=True)
        finally:
            db.session.remove()


def run_quick_replies():
    """For the jobs runner: quick replies a save could not copy to WhatsApp, tried again while the
    portal may write to WhatsApp. Only inside a request (POST /internal/jobs/run): from the command line
    the links would come out as the bare site, so it waits for the next posted run.
    {'crm_wa_quick': 'copied' | 'failed'}, or {} when nothing waits."""
    from flask import has_request_context
    from app.services import crm, wacrm, wacrm_team
    if not (has_request_context() and crm.wa_writes_on() and wacrm_team.enabled()) or not quick_state()['due']:
        return {}
    try:
        with wacrm.short_timeouts():
            push_quick_replies()
    except wacrm_team.TeamError:
        return {'crm_wa_quick': 'failed'}
    return {'crm_wa_quick': 'copied'}
