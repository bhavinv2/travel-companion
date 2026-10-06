"""Detect, normalise and validate contact-point values."""
import re
from app.models import CONTACT_TYPES

_EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
_URL = re.compile(r'^(https?://)?([a-z0-9.-]+)(/.*)?$', re.I)


def detect_type(value):
    v = (value or '').strip()
    if not v:
        return 'other'
    if _EMAIL.match(v):
        return 'email'
    low = v.lower()
    if 'facebook.com' in low or 'fb.com' in low or low.startswith('fb:'):
        return 'facebook'
    if 'instagram.com' in low or low.startswith('@') or low.startswith('ig:'):
        return 'instagram'
    if 'wa.me' in low or 'whatsapp' in low:
        return 'whatsapp'
    digits = re.sub(r'[^\d]', '', v)
    if 7 <= len(digits) <= 15 and re.fullmatch(r'[\d\s().+-]+', v):
        return 'mobile'
    return 'other'


def normalize_value(ctype, value, iso=None):
    """The stored form of a contact value.

    `iso` is the country somebody CHOSE beside a phone number (the contact rows have a picker
    for it). With one, a phone is stored as E.164 like every other number on the site. Without
    one -- the importer and the scraper, which have nobody to ask -- a national number is still
    left as bare digits, because inventing a country would be worse than not knowing it.
    """
    v = (value or '').strip()
    if ctype == 'email':
        return v.lower()
    if ctype in ('mobile', 'whatsapp'):
        if iso:
            from app.services import phone as phone_svc
            e164, err = phone_svc.normalise(v, iso)
            if e164 and not err:
                return e164
        digits = re.sub(r'[^\d]', '', v)
        if v.startswith('+'):
            return '+' + digits
        if v.startswith('00'):
            return '+' + digits[2:]
        # No country chosen and none typed: leave the digits; we don't guess the country code.
        return digits or v
    if ctype in ('facebook', 'instagram'):
        if ctype == 'instagram' and v.startswith('@'):
            return 'https://instagram.com/' + v[1:]
        if v and not v.lower().startswith('http'):
            return 'https://' + v
        return v
    return v


def display(ctype, value):
    """A contact value as a person should read it.

    A phone is spaced so its country code is findable ("+46 764498115", not "+46764498115").
    Only one that carries its + is touched: a legacy row saved as bare national digits has no
    country in it, and prettifying "9175551234" would read its first two digits as India -- shown
    as stored, the not-knowing stays visible. An e-mail or a profile link is shown as stored.
    Links (tel:, wa.me, mailto:) must keep using the raw value.
    """
    v = (value or '').strip()
    if ctype in ('mobile', 'whatsapp') and v.startswith('+'):
        from app.services import phone as phone_svc
        return phone_svc.pretty(v, v)
    return v


def validate(ctype, value):
    """Return (ok, error_message)."""
    if ctype not in CONTACT_TYPES:
        return False, 'Unknown contact type.'
    v = (value or '').strip()
    if ctype == 'inapp_chat':
        return True, None
    if not v:
        return False, 'Contact value is required.'
    if ctype == 'email' and not _EMAIL.match(v):
        return False, 'That does not look like a valid e-mail address.'
    if ctype in ('mobile', 'whatsapp'):
        digits = re.sub(r'[^\d]', '', v)
        if not (7 <= len(digits) <= 15):
            return False, 'Phone numbers need 7-15 digits (include the country code, e.g. +1 ...).'
    if ctype in ('facebook', 'instagram') and not _URL.match(v) and not v.startswith('@'):
        return False, 'Enter the profile link (or @handle for Instagram).'
    return True, None


def parse_contact_rows(form_or_json):
    """Read repeatable contact rows and return (rows, errors).

    Accepts either a JSON list of dicts ({type, value, label, consent}) or a Flask form
    (MultiDict) with parallel fields contact_type[], contact_value[], contact_label[] and
    contact_consent[] whose checkbox values carry the row index.
    """
    rows, errors = [], []
    if isinstance(form_or_json, list):
        raw = form_or_json
    else:
        types = form_or_json.getlist('contact_type')
        values = form_or_json.getlist('contact_value')
        labels = form_or_json.getlist('contact_label')
        # the country picked beside each row's number; every row has one, used only by phones
        countries = form_or_json.getlist('contact_cc')
        consents = set(form_or_json.getlist('contact_consent'))
        raw = []
        for i, t in enumerate(types):
            raw.append({
                'type': t,
                'value': values[i] if i < len(values) else '',
                'label': labels[i] if i < len(labels) else '',
                'cc': countries[i] if i < len(countries) else '',
                'consent': str(i) in consents or 'all' in consents,
            })
    for r in raw:
        ctype = (r.get('type') or 'auto').strip()
        value = (r.get('value') or '').strip()
        if ctype == 'inapp_chat':
            rows.append({'type': ctype, 'value': 'inapp', 'label': (r.get('label') or '')[:100],
                         'consent': bool(r.get('consent'))})
            continue
        if not value:
            continue  # blank row
        if ctype == 'auto' or not ctype:
            ctype = detect_type(value)
        ok, err = validate(ctype, value)
        if not ok:
            errors.append(f"{value}: {err}")
            continue
        rows.append({
            'type': ctype,
            'value': normalize_value(ctype, value, (r.get('cc') or '').strip().upper() or None),
            'label': (r.get('label') or '').strip()[:100],
            'consent': bool(r.get('consent')),
        })
    return rows, errors
