"""Where this business actually is, and how to reach it.

Real addresses and phone numbers that have to ring. They are configuration rather than
template text for the same reason the Organization schema is: the moment the same address is
typed into a second page, the two start to disagree, and the one somebody corrects is never the
one a visitor is reading. The structured data reads the head office from here too, so the
address a search engine is told is the address on the page.

Any of them can be changed with an environment variable, and an office with no street line is
left out entirely rather than rendered as a heading with nothing under it.
"""
import os


def _env(name, default=''):
    return (os.environ.get(name, default) or '').strip()


# The artwork each office is shown with, by key: a photograph of the place and a round flag.
# It lives beside the addresses rather than in the template because adding an office should be
# one edit, not two in two files -- and because an office with no photograph of its own has to
# fall back to something, which is a decision about the office, not about the markup.
#
# Files are in static/img/contact/ as WebP. '' means "there is no picture of this one": the page
# draws the generic skyline instead, and the emoji flag in place of the round one.
ARTWORK = {
    'hq':        {'photo': 'landmark-usa',              'flag': 'flag-usa'},
    'telangana': {'photo': 'landmark-india-telangana',  'flag': 'flag-india'},
    'andhra':    {'photo': 'landmark-india-andhra',     'flag': 'flag-india'},
    'australia': {'photo': 'landmark-australia',        'flag': 'flag-australia'},
    'uk':        {'photo': '',                          'flag': ''},
}
FALLBACK_PHOTO = 'landmarks-silhouette'

# Round flag artwork we have, by ISO. Short on purpose: a country without one falls back to the
# emoji flag, so publishing a number for anywhere in the world needs no new file.
FLAGS = {'IN': 'flag-india', 'US': 'flag-usa', 'CA': 'flag-canada', 'AU': 'flag-australia'}


# key, the heading, and the lines as they should be printed. The first is the head office.
def all_offices():
    rows = [
        {'key': 'hq', 'label': 'Head Quarters', 'country': 'USA', 'cc': 'US',
         'street': _env('ORG_STREET', '2512 Carpenter Rd'),
         'lines': [_env('ORG_CITY', 'Ann Arbor'),
                   '%s %s' % (_env('ORG_REGION', 'Michigan'), _env('ORG_POSTCODE', '48108')),
                   'USA']},
        {'key': 'telangana', 'label': 'India – Telangana', 'country': 'India', 'cc': 'IN',
         'street': _env('OFFICE_TG_STREET', '#202, 1st Floor, Kala Mansion, SD Road'),
         'lines': ['Secunderabad, Hyderabad', 'Telangana 500003', 'India']},
        {'key': 'andhra', 'label': 'India – Andhra Pradesh', 'country': 'India', 'cc': 'IN',
         'street': _env('OFFICE_AP_STREET', 'H.I.G 131, H.B Colony, Bhavanipuram'),
         'lines': ['Vijayawada', 'Andhra Pradesh 520012', 'India']},
        {'key': 'australia', 'label': 'Australia', 'country': 'Australia', 'cc': 'AU',
         'street': _env('OFFICE_AU_STREET', '24 Spriggs Drive'),
         'lines': ['Croydon, Victoria 3136', 'Australia']},
        {'key': 'uk', 'label': 'United Kingdom', 'country': 'United Kingdom', 'cc': 'GB',
         'street': _env('OFFICE_UK_STREET', '1 Welford Mews'),
         'lines': ['London SE6 2FB', 'United Kingdom']},
    ]
    for o in rows:
        art = ARTWORK.get(o['key'], {})
        o['photo'] = art.get('photo') or FALLBACK_PHOTO
        o['flag'] = art.get('flag') or ''
    # a heading with no address under it is worse than one fewer card
    return [o for o in rows if o['street']]


def countries():
    """The distinct countries the offices are in -- what "four countries, one team" counts.

    Derived rather than written down: an office removed by clearing its street should take the
    heading's number with it, not leave the page claiming a country it no longer has.
    """
    seen = []
    for o in all_offices():
        if o['country'] not in seen:
            seen.append(o['country'])
    return seen


def headquarters():
    rows = all_offices()
    return rows[0] if rows else None


# Where a number can be shown. A number with no sites ticked is published everywhere, which is
# what somebody adding their first one almost always means.
SITES = [('companion', 'Travel Companion'), ('insurance', 'Travel Insurance'),
         ('sahayak', 'Sahayak'), ('contact', 'Contact page')]
SITE_KEYS = [k for k, _ in SITES]

# What ships before anybody opens the admin screen. Two slots used to be all there was, and
# adding a third country meant editing the code -- which is the reason this is a list.
DEFAULT_NUMBERS = [
    {'label': 'India', 'iso': 'IN', 'number': '+91 80191 11360', 'whatsapp': True, 'sites': []},
    {'label': 'USA', 'iso': 'US', 'number': '+1 917 900 5094', 'whatsapp': False, 'sites': []},
    {'label': 'Canada', 'iso': 'CA', 'number': '+1 (647) 770-2288', 'whatsapp': False,
     'sites': []},
]


def _clean_row(row):
    """One stored row, normalised. Returns None when there is no usable number in it."""
    from app.services import phone as phone_svc

    iso = (row.get('iso') or phone_svc.DEFAULT_ISO).strip().upper()
    if iso not in phone_svc.BY_ISO:
        iso = phone_svc.DEFAULT_ISO
    raw = (row.get('number') or '').strip()
    e164, error = phone_svc.normalise(raw, iso)
    if not e164 or error:
        return None                      # never publish a line that cannot be rung
    sites = [s for s in (row.get('sites') or []) if s in SITE_KEYS]
    return {
        'label': (row.get('label') or phone_svc.BY_ISO[iso]['name']).strip()[:40],
        'iso': iso,
        'number': raw,
        # derived, not as typed: two people entering the same shape of number differently is
        # what made "+1 (647) 770-2288" and "+1 917 900 5094" sit under each other on the
        # contact page looking like one of them was wrong
        'display': phone_svc.pretty(e164, raw),
        'e164': e164,
        'digits': e164.lstrip('+'),
        'whatsapp': bool(row.get('whatsapp')),
        'sites': sites,
        # '' where we have no round flag for the country; the page draws the emoji instead
        'flag': FLAGS.get(iso, ''),
    }


def _stored():
    """The admin's list, or the shipped one. Rows saved under the old two-field shape are read
    through the same path, so nothing has to be migrated before the screen is opened."""
    from app.services import settings
    ls = settings.landing_settings()
    rows = ls.get('contact_numbers')
    if rows is None:
        legacy = [{'label': 'India', 'iso': 'IN', 'number': ls.get('whatsapp_in') or '',
                   'whatsapp': True, 'sites': []},
                  {'label': 'USA', 'iso': 'US', 'number': ls.get('whatsapp_us') or '',
                   'whatsapp': False, 'sites': []}]
        rows = [r for r in legacy if r['number'].strip()] or DEFAULT_NUMBERS
    out = [_clean_row(r) for r in rows]
    return [r for r in out if r]


# The pages whose own site key is not simply their blueprint's product.
_SITE_BY_ENDPOINT = {'main.contact_us': 'contact'}


def current_site():
    """Which page's list this request should show, so a number aimed at one product is not
    offered on another.

    The shared chooser is rendered once per page by the footer, which has no idea which product
    it is sitting under; without this it asked for every number there is, and ticking a site on
    the admin screen changed nothing outside the handful of places that passed one explicitly.
    None outside a request -- there is no page to be on.
    """
    from flask import has_request_context, request
    if not has_request_context():
        return None
    named = _SITE_BY_ENDPOINT.get(request.endpoint or '')
    if named:
        return named
    from app.services import products
    key = products.current_key()
    return key if key in SITE_KEYS else None


def numbers(site=None):
    """Every published number, or the ones a given page should show.

    A row with no sites ticked belongs everywhere: that is what somebody adding their first
    number means, and it keeps a new number visible rather than silently nowhere.
    """
    rows = _stored()
    if not site:
        return rows
    return [r for r in rows if not r['sites'] or site in r['sites']]


def primary(site=None):
    """The one number to print where there is room for one. {} when none is published.

    The country in phone.DEFAULT_ISO, because that is where most of the people reading this are
    -- the parents are in India, the person ringing about them usually is not. Falls back to the
    first published line, so an install that does not publish a US number still gets a button.
    One definition for "our main number", shared with what the forms open on.
    """
    from app.services import phone as phone_svc
    rows = numbers(site)
    for r in rows:
        if r['iso'] == phone_svc.DEFAULT_ISO:
            return r
    return rows[0] if rows else {}


def save_numbers(rows, actor=None):
    """Replace the list. Rows without a usable number are dropped on save."""
    from app.services import settings
    cleaned = [r for r in (_clean_row(x) for x in rows) if r]
    stored = [{'label': r['label'], 'iso': r['iso'], 'number': r['number'],
               'whatsapp': r['whatsapp'], 'sites': r['sites']} for r in cleaned]
    cur = settings.landing_settings()
    cur['contact_numbers'] = stored
    settings.set_setting(settings.LANDING_KEY, cur, actor)
    settings.clear_cache()
    return cleaned


def helplines(site=None):
    """The numbers printed on a page, each with the country it is answered in.

    display is what a reader sees; digits is what tel: and wa.me want. An unset number is not
    published -- the rule everywhere else on this site is never to print a line nobody answers.
    """
    return numbers(site)


def whatsapp(site=None):
    """Digits for the WhatsApp buttons: the row marked for WhatsApp, else the first one."""
    rows = numbers(site)
    for r in rows:
        if r['whatsapp']:
            return r['digits']
    return rows[0]['digits'] if rows else ''


DEFAULT_EMAILS = [
    {'label': 'General', 'address': 'info@nriparentservice.com', 'sites': []},
]

_EMAIL_RE = __import__('re').compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _clean_email(row):
    """One stored address, or None. An address that is not one is dropped rather than printed:
    a mailto: that bounces is worse than no link."""
    address = (row.get('address') or '').strip().lower()[:255]
    if not address or not _EMAIL_RE.match(address):
        return None
    sites = [x for x in (row.get('sites') or []) if x in SITE_KEYS]
    return {'label': (row.get('label') or 'Support').strip()[:40],
            'address': address, 'sites': sites}


def emails(site=None):
    """Published support addresses, or the ones a given page should show.

    Same rule as the numbers: no sites ticked means everywhere, which is what somebody adding
    their first address means.
    """
    from app.services import settings
    rows = settings.landing_settings().get('contact_emails')
    if rows is None:
        # whatever the single configured address was, so an install that never opens the screen
        # keeps the address it already had
        rows = [{'label': 'General', 'address': _env('ORG_EMAIL', 'info@nriparentservice.com'),
                 'sites': []}] or DEFAULT_EMAILS
    out = [r for r in (_clean_email(x) for x in rows) if r]
    if not site:
        return out
    return [r for r in out if not r['sites'] or site in r['sites']]


def save_emails(rows, actor=None):
    """Replace the list. Anything that is not an address is dropped on save."""
    from app.services import settings
    cleaned = [r for r in (_clean_email(x) for x in rows) if r]
    cur = settings.landing_settings()
    cur['contact_emails'] = cleaned
    settings.set_setting(settings.LANDING_KEY, cur, actor)
    settings.clear_cache()
    return cleaned


def email(site=None):
    """The one address to print where there is room for one. '' when none is published."""
    rows = emails(site)
    return rows[0]['address'] if rows else ''


# What is already in the box when WhatsApp opens. Somebody who taps a button and lands on an
# empty chat usually types nothing: the first line is the hardest one. It also tells whoever
# answers which page the message came from, which no amount of "Hi" does.
GREETINGS = {
    None: 'Hi NRI Parent Service, I would like to know more about your services.',
    'companion': 'Hi NRI Parent Service, I would like to ask about finding a travel companion.',
    'insurance': 'Hi NRI Parent Service, I would like to ask about travel insurance.',
    'sahayak': 'Hi NRI Parent Service, I would like to ask about a Sahayak home visit.',
    'contact': 'Hi NRI Parent Service, I would like to speak to someone about your services.',
}


def greeting(site=None):
    """The message a WhatsApp button opens with. An admin can override the lot with one line."""
    custom = _env('WHATSAPP_GREETING')
    if custom:
        return custom
    return GREETINGS.get(site) or GREETINGS[None]


def wa_link(site=None, text=None):
    """A wa.me address for `site`, with the opener already in it. '' when nothing is published."""
    from urllib.parse import quote
    digits = whatsapp(site)
    if not digits:
        return ''
    return 'https://wa.me/%s?text=%s' % (digits, quote(text or greeting(site), safe=''))
