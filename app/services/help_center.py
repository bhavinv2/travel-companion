"""Help centre: admin-managed categories and FAQs, rendered live on /help.

Stored as one JSON blob in app_settings (key 'help_center'), the same way options.py and
messages.py keep admin-editable content — so an edit shows up on the public page within the
settings cache window, with no migration and no deploy.

Shape:
    {'categories': [{'key', 'title', 'icon', 'blurb'}],
     'faqs':       [{'id', 'category', 'question', 'answer'}]}

The built-in defaults below are the eight questions that used to be hard-coded in
templates/pages/help.html; nothing is lost if an admin never touches the screen.
"""
import re
import uuid

SETTING_KEY = 'help_center'
KEY_RE = re.compile(r'^[a-z0-9_]{1,40}$')

# Icons an admin can choose from. A free-text Font Awesome class was too easy to get
# wrong (and browsers happily autofilled nonsense into it), so the admin screen offers
# this list and anything outside it falls back to the question mark.
ICON_CHOICES = [
    ('fa-circle-question', 'Question mark'), ('fa-rocket', 'Rocket / getting started'),
    ('fa-shield-halved', 'Shield / privacy'), ('fa-lock', 'Lock / security'),
    ('fa-handshake', 'Handshake / matches'), ('fa-user-group', 'People'),
    ('fa-user-gear', 'Account settings'), ('fa-id-card', 'Profile / identity'),
    ('fa-plane-departure', 'Departure'), ('fa-plane-arrival', 'Arrival'),
    ('fa-suitcase-rolling', 'Baggage'), ('fa-passport', 'Passport / documents'),
    ('fa-ticket', 'Tickets'), ('fa-calendar-days', 'Dates'),
    ('fa-location-dot', 'Places'), ('fa-route', 'Routes'),
    ('fa-comments', 'Chat / messages'), ('fa-envelope', 'E-mail'),
    ('fa-bell', 'Notifications'), ('fa-headset', 'Support'),
    ('fa-credit-card', 'Payments'), ('fa-receipt', 'Billing'),
    ('fa-wheelchair', 'Accessibility'), ('fa-hand-holding-heart', 'Help / care'),
    ('fa-language', 'Languages'), ('fa-globe', 'International'),
    ('fa-triangle-exclamation', 'Warnings'), ('fa-circle-info', 'Information'),
    ('fa-clock', 'Timing'), ('fa-star', 'Reviews'),
    ('fa-gavel', 'Terms / legal'), ('fa-trash', 'Deleting things'),
]
ICON_KEYS = {k for k, _ in ICON_CHOICES}

DEFAULT_CATEGORIES = [
    {'key': 'getting_started', 'icon': 'fa-rocket', 'title': 'Getting started',
     'blurb': 'Posting a trip and finding your first companion.'},
    {'key': 'privacy', 'icon': 'fa-shield-halved', 'title': 'Privacy & contact details',
     'blurb': 'Who can see what, and when.'},
    {'key': 'matches', 'icon': 'fa-handshake', 'title': 'Matches & connections',
     'blurb': 'How we pair travellers and introduce you.'},
    {'key': 'account', 'icon': 'fa-user-gear', 'title': 'Account & listings',
     'blurb': 'Editing, closing and deleting things.'},
]

DEFAULT_FAQS = [
    {'id': 'faq_start_post', 'category': 'getting_started',
     'question': 'How do I post a trip?',
     'answer': 'Sign up or log in, then use the form on the home page. Say whether you need a companion or can '
               'help someone, fill in your route and dates, choose how a matched companion may reach you, and '
               'click "Connect Desis".'},
    {'id': 'faq_start_free', 'category': 'getting_started',
     'question': 'Is Connecting Desis free?',
     'answer': 'Yes, the core features are completely free. We may introduce premium features in the future.'},
    {'id': 'faq_privacy_contacts', 'category': 'privacy',
     'question': 'Who can see my contact details?',
     'answer': 'Only a travel companion we match you with — and only if you ticked the consent box for that trip. '
               'Everyone else sees just the type of contact you offer (for example an e-mail icon), never the '
               'value. You can skip contact details entirely and use in-app chat instead.'},
    {'id': 'faq_privacy_link', 'category': 'privacy',
     'question': 'I got a message from your team with a link. What is it?',
     'answer': 'If you asked for a travel companion on Facebook or another website, our team may offer to list '
               'your request here. The link lets you confirm the request and add the contact details you want to '
               'share. Nothing is published until you confirm.'},
    {'id': 'faq_match_connect', 'category': 'matches',
     'question': 'How do I connect with another traveller?',
     'answer': 'Browse the listings and click "Connect" on any listing. The other person can accept or decline; '
               'once accepted you can chat in-app.'},
    {'id': 'faq_account_modify', 'category': 'account',
     'question': 'Can I modify my trip after posting?',
     'answer': 'In-place editing is coming soon. For now, close the trip from "My Trips" and post an updated one, '
               'or contact us and we will update it for you.'},
    {'id': 'faq_account_expiry', 'category': 'account',
     'question': 'What happens to my listing after my travel date?',
     'answer': 'Listings are automatically removed from search results after the departure date has passed.'},
    {'id': 'faq_account_delete', 'category': 'account',
     'question': 'How do I delete my account or a request?',
     'answer': 'Contact us and we will delete your account, your requests and all associated data within 48 hours.'},
]


def _stored():
    try:
        from app.services import settings
        return settings.get_setting(SETTING_KEY, {}) or {}
    except Exception:           # pragma: no cover - table not created yet
        return {}


def categories():
    stored = _stored().get('categories')
    return [dict(c) for c in (stored if stored is not None else DEFAULT_CATEGORIES)]


def faqs():
    stored = _stored().get('faqs')
    return [dict(f) for f in (stored if stored is not None else DEFAULT_FAQS)]


def is_customised():
    s = _stored()
    return bool(s.get('categories') is not None or s.get('faqs') is not None)


def grouped():
    """[(category, [faq, ...])] in admin order. FAQs whose category was deleted are
    collected under a synthetic 'Other' group so an edit can never hide content."""
    cats = categories()
    by_key = {c['key']: [] for c in cats}
    orphans = []
    for f in faqs():
        (by_key[f['category']] if f.get('category') in by_key else orphans).append(f)
    out = [(c, by_key[c['key']]) for c in cats]
    if orphans:
        out.append(({'key': 'other', 'icon': 'fa-circle-question', 'title': 'Other',
                     'blurb': 'Questions not filed under a category yet.'}, orphans))
    return out


def _slug(text, fallback='category'):
    s = re.sub(r'[^a-z0-9]+', '_', str(text or '').lower()).strip('_')[:40]
    return s or fallback


def clean_categories(rows):
    """Validate admin input. Returns (categories, errors)."""
    out, errors, seen = [], [], set()
    for row in rows or []:
        title = str(row.get('title') or '').strip()
        if not title:
            continue                                    # blank row = deleted
        key = str(row.get('key') or '').strip() or _slug(title)
        if not KEY_RE.match(key):
            key = _slug(title)
        base, n = key, 2
        while key in seen:
            key, n = f'{base}_{n}', n + 1
        seen.add(key)
        # only known icons are stored; anything else (a typo, a browser autofill) would
        # render as a blank box on the public page, so fall back to the question mark
        icon = str(row.get('icon') or '').strip()[:40]
        if icon not in ICON_KEYS:
            icon = 'fa-circle-question'
        out.append({'key': key, 'title': title[:80], 'icon': icon,
                    'blurb': str(row.get('blurb') or '').strip()[:200]})
    if not out:
        errors.append('Keep at least one category — the help page groups every question under one.')
    return out, errors


def clean_faqs(rows, valid_keys):
    """Validate admin input. Returns (faqs, errors)."""
    out, errors, seen = [], [], set()
    for row in rows or []:
        q = str(row.get('question') or '').strip()
        a = str(row.get('answer') or '').strip()
        if not q and not a:
            continue                                    # blank row = deleted
        if not q or not a:
            errors.append(f'"{(q or a)[:48]}" needs both a question and an answer.')
            continue
        fid = str(row.get('id') or '').strip() or 'faq_' + uuid.uuid4().hex[:10]
        while fid in seen:
            fid = 'faq_' + uuid.uuid4().hex[:10]
        seen.add(fid)
        cat = str(row.get('category') or '').strip()
        if cat not in valid_keys:
            cat = valid_keys[0] if valid_keys else 'other'
        out.append({'id': fid, 'category': cat, 'question': q[:300], 'answer': a[:4000]})
    return out, errors


def save(cat_rows, faq_rows, actor=None):
    """Persist both lists together. Returns (ok, errors)."""
    from app.services import settings
    cats, errors = clean_categories(cat_rows)
    if errors:
        return False, errors
    fqs, ferrors = clean_faqs(faq_rows, [c['key'] for c in cats])
    if ferrors:
        return False, ferrors
    settings.set_setting(SETTING_KEY, {'categories': cats, 'faqs': fqs}, actor)
    settings.clear_cache()
    return True, []


def reset(actor=None):
    """Drop the admin's version and go back to the shipped defaults."""
    from app.services import settings
    settings.set_setting(SETTING_KEY, {}, actor)
    settings.clear_cache()
