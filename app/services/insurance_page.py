"""Admin-managed content for the travel-insurance landing page.

Stored as one JSON blob in app_settings, the same way options.py, messages.py and
help_center.py keep admin-editable content -- an edit shows on the public page within the
settings cache window, with no migration and no deploy.

Shape:
    {'reviews':    [{'id', 'quote', 'name', 'place', 'cc', 'tag', 'photo'}],
     'price_from': 'from $1.20 a day ...',
     'assurances': ['Policy documents by e-mail in minutes', ...]}

`price_from` and `assurances` start EMPTY and their sections simply do not render until somebody
fills them in. Both are claims about what the business actually offers -- a made-up price or an
invented refund window on an insurance page is worse than no line at all.

The defaults below are the three sample testimonials the ported page shipped with, which it
labelled "replace with verified testimonials". They are here so the section is never empty
before anyone visits the admin screen, and the moment a real one is saved they are gone.
"""
import uuid

from app.services import settings

SETTING_KEY = 'insurance_page'

# The FAQ category whose questions the page's accordion and its JSON-LD both read. Editing them
# is the existing Admin -> Help & FAQ screen; nothing insurance-specific to learn.
FAQ_CATEGORY = 'travel_insurance'

DEFAULT_REVIEWS = [
    {'id': 'sample-1', 'tag': 'Parents visiting children',
     'quote': 'The quote took a few minutes and the plan terms were easy to follow.',
     'name': 'S. Krishnan', 'place': 'Canada', 'cc': 'CA', 'photo': ''},
    {'id': 'sample-2', 'tag': 'Family trip',
     'quote': 'Having one number to call while abroad made the whole trip calmer.',
     'name': 'R. Fernandes', 'place': 'United Kingdom', 'cc': 'GB', 'photo': ''},
    {'id': 'sample-3', 'tag': 'Business travel',
     'quote': 'I uploaded my documents from my phone and could track every step.',
     'name': 'A. Menon', 'place': 'Singapore', 'cc': 'SG', 'photo': ''},
]

FIELDS = ('quote', 'name', 'place', 'cc', 'tag', 'photo')
LIMITS = {'quote': 400, 'name': 80, 'place': 80, 'cc': 3, 'tag': 60, 'photo': 300}

# Short reassurance lines shown beside the quote button ("free look period", "no medical exam").
# Suggestions for the admin screen only -- nothing here is published until it is saved, because
# only the business knows which of them are true of its plans.
ASSURANCE_SUGGESTIONS = [
    'Policy documents by e-mail within minutes',
    'Free look period — cancel within 10 days',
    'No medical exam for most plans',
    'Buy online, no paperwork',
    'Claims guidance in your time zone',
]
MAX_ASSURANCES = 4


def _blob():
    return settings.get_setting(SETTING_KEY, {}) or {}


def reviews():
    """Testimonials for the page, falling back to the samples until an admin saves real ones."""
    rows = _blob().get('reviews')
    if rows is None:
        return [dict(r) for r in DEFAULT_REVIEWS]
    return [dict(r) for r in rows]


def price_from():
    """The "from ..." line under the hero CTA. Empty until an admin sets a real number."""
    return (_blob().get('price_from') or '').strip()


def assurances():
    """Short reassurance lines shown with the quote CTA. Empty by default, by design."""
    return [a for a in (_blob().get('assurances') or []) if a]


def save_page(price_from_text, assurance_rows, actor=None):
    blob = _blob()
    blob['price_from'] = (price_from_text or '').strip()[:120]
    blob['assurances'] = [(a or '').strip()[:60] for a in assurance_rows if (a or '').strip()][:MAX_ASSURANCES]
    settings.set_setting(SETTING_KEY, blob, actor)
    settings.clear_cache()
    return blob


def is_using_samples():
    """True while nobody has saved a testimonial -- the page says so, so samples never pass
    themselves off as real customers."""
    return _blob().get('reviews') is None


def clean_rows(rows):
    """Normalise submitted rows: trim, cap lengths, drop the empty ones, keep stable ids."""
    out = []
    for row in rows:
        clean = {f: (row.get(f) or '').strip()[:LIMITS[f]] for f in FIELDS}
        if not clean['quote'] or not clean['name']:
            continue                       # a testimonial is a quote and who said it
        clean['cc'] = clean['cc'].upper()
        clean['id'] = (row.get('id') or '').strip()[:40] or uuid.uuid4().hex[:12]
        out.append(clean)
    return out


def save_reviews(rows, actor=None):
    blob = _blob()
    blob['reviews'] = clean_rows(rows)
    settings.set_setting(SETTING_KEY, blob, actor)
    settings.clear_cache()
    return blob['reviews']
