"""Editable message templates: the copy CS agents paste into DMs + transactional e-mails.

Defaults live in code and in app/templates/email/*.txt. Admin edits are stored in the
app_settings key 'message_templates' ({'overrides': {key: {subject, body}}, 'custom': [...]})
and win over the defaults immediately - no deploy. Bodies/subjects are Jinja strings.
Managed at /admin/messages.
"""
import io
import os
import re

from flask import current_app

SETTING_KEY = 'message_templates'

TEMPLATES = {
    'cs_claim_dm': {
        'kind': 'cs_copy', 'title': 'Claim-link DM',
        'help': 'The message a CS agent copies into a DM together with the claim link (post page, "Copy DM text").',
        'vars': ['greeting', 'name', 'route', 'url'],
        'body': ("{{ greeting }} this is the Connecting Desis team. We help Desi travellers find companions on the "
                 "same route. We'd like to help with your {{ route }} trip. Please add your preferred contact details "
                 "here so we can introduce you to matching travellers: {{ url }}\n\n"
                 "We only share your details with a matched companion, and only with your consent."),
    },
    'email_verify': {
        'kind': 'email', 'title': 'Verify e-mail',
        'help': 'Sent right after registration with the confirmation link.',
        'subject': 'Welcome to Connecting Desis — please confirm your e-mail',
        'template': 'email/verify_email.txt', 'vars': ['user', 'link', 'site_url', 'support_email'],
    },
    'email_password_reset': {
        'kind': 'email', 'title': 'Password reset',
        'help': 'Sent from the "Forgot password?" flow with the reset link.',
        'subject': '[Connecting Desis] Reset your password',
        'template': 'email/password_reset.txt', 'vars': ['user', 'link', 'site_url', 'support_email'],
    },
    'email_match_found': {
        'kind': 'email', 'title': 'Match introduction',
        'help': 'Sent when CS notifies one side of a match (contact page link included).',
        'subject': '[Connecting Desis] Possible travel companion for your {{ trip.route_display }} trip',
        'template': 'email/match_found.txt', 'vars': ['trip', 'other', 'match', 'link', 'site_url', 'support_email'],
    },
    'email_new_match_alert': {
        'kind': 'email', 'title': 'New match alert',
        'help': 'The throttled "a new possible companion posted" alert.',
        'subject': '[Connecting Desis] New possible companion for your {{ trip.route_display }} trip',
        'template': 'email/new_match_alert.txt', 'vars': ['trip', 'other', 'best', 'count', 'site_url', 'support_email'],
    },
}


def _stored():
    from app.services import settings
    return settings.get_setting(SETTING_KEY, {}) or {}


def overrides():
    return _stored().get('overrides', {}) or {}


def custom_snippets():
    return list(_stored().get('custom', []) or [])


def default_body(key):
    spec = TEMPLATES[key]
    if 'body' in spec:
        return spec['body']
    path = os.path.join(current_app.root_path, 'templates', spec['template'])
    return io.open(path, encoding='utf-8').read()


def effective(key):
    """Subject/body actually in use for a registered template (+ whether it was edited)."""
    spec = TEMPLATES[key]
    o = overrides().get(key, {})
    return {'subject': o.get('subject') or spec.get('subject', ''),
            'body': o.get('body') or default_body(key),
            'edited': bool(o.get('subject') or o.get('body'))}


def render_string(text, **ctx):
    return current_app.jinja_env.from_string(text or '').render(**ctx)


def render_body(key, **ctx):
    return render_string(effective(key)['body'], **ctx)


def render_subject(key, **ctx):
    return render_string(effective(key)['subject'], **ctx)


def send_email(key, recipients, category, **ctx):
    """Render + send a registered e-mail template through the normal mailer gate."""
    from app.services import mailer
    return mailer.send(render_subject(key, **ctx), recipients, render_body(key, **ctx), category=category)


def save_override(key, subject, body, actor=None):
    """Store an admin edit; values equal to the default (or empty) clear the override."""
    from app.services import settings
    spec = TEMPLATES[key]
    entry = {}
    subject = (subject or '').strip()
    if subject and subject != spec.get('subject', ''):
        entry['subject'] = subject[:300]
    body = (body or '')
    if body.strip() and body.strip() != default_body(key).strip():
        entry['body'] = body[:8000]
    data = dict(_stored())
    ovr = dict(data.get('overrides', {}) or {})
    if entry:
        ovr[key] = entry
    else:
        ovr.pop(key, None)
    data['overrides'] = ovr
    settings.set_setting(SETTING_KEY, data, actor)
    return effective(key)


def set_custom(items, actor=None):
    """Replace the custom CS snippet list (full CRUD from the admin screen)."""
    from app.services import settings
    clean, seen = [], set()
    for row in items or []:
        title = str((row or {}).get('title') or '').strip()
        body = str((row or {}).get('body') or '').strip()
        if not title and not body:
            continue
        if not title or not body:
            raise ValueError('Each snippet needs both a title and a body')
        key = str((row or {}).get('key') or '').strip() or re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')[:40] or 'snippet'
        base, i = key, 2
        while key in seen:
            key, i = f'{base}_{i}', i + 1
        seen.add(key)
        clean.append({'key': key, 'title': title[:80], 'body': body[:4000]})
    data = dict(_stored())
    data['custom'] = clean
    settings.set_setting(SETTING_KEY, data, actor)
    return clean


def trip_ctx(trip, url=None):
    name = (getattr(trip, 'poster_name', '') or '').split(' ')[0]
    return {
        'trip': trip, 'name': name, 'greeting': f'Hi {name},' if name else 'Hi,',
        'route': trip.route_display if current_app.config.get('CLAIM_SHOW_ROUTE') else 'upcoming',
        'url': url or '',
        'site_url': current_app.config.get('SITE_URL', ''),
        'support_email': current_app.config.get('SUPPORT_EMAIL', ''),
    }


def snippets_for(trip, url=None):
    """Custom CS snippets rendered for one post (shown with Copy buttons on the post page)."""
    ctx = trip_ctx(trip, url)
    out = []
    for row in custom_snippets():
        try:
            text = render_string(row['body'], **ctx)
        except Exception:
            text = row['body']
        out.append({'key': row['key'], 'title': row['title'], 'text': text})
    return out


def sample_ctx():
    """Dummy data for the admin preview."""
    class _O:
        def __init__(self, **kw):
            self.__dict__.update(kw)
    trip = _O(route_display='Hyderabad (HYD) → Dallas (DFW)', poster_name='Priya Patel', display_name='Priya',
              from_date='2026-09-20', airline='Qatar Airways', flight_number='QR573')
    other = _O(route_display='Hyderabad (HYD) → Dallas (DFW)', poster_name='Ravi K', display_name='Ravi',
               from_date='2026-09-20', airline='Qatar Airways', flight_number='QR573')
    match = _O(score=95, criteria=[{'ok': True, 'label': 'Route', 'detail': 'HYD → DFW'},
                                  {'ok': True, 'label': 'Dates', 'detail': 'same day'}])
    return dict(trip=trip, other=other, match=match, best=match, count=2,
                user=_O(first_name='Priya', username='priya'),
                link='https://connectingdesis.com/claim/EXAMPLE',
                url='https://connectingdesis.com/claim/EXAMPLE',
                name='Priya', greeting='Hi Priya,', route=trip.route_display,
                site_url=current_app.config.get('SITE_URL', ''),
                support_email=current_app.config.get('SUPPORT_EMAIL', ''))
