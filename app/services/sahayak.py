"""Sahayak home-healthcare: the service catalogue and the rules around a booking request.

Scope of this phase: people ask for a visit here, and staff assign somebody by hand in the CS
console. There is no Sahayak-facing app, no automated dispatch and no payment collection -- a
booking is a request with a quoted price, and the money is taken the way it is taken today.

The catalogue lives in app_settings, the same way options.py, help_center.py and
insurance_page.py keep admin-editable content: prices change, and changing one should not need a
deploy. The twelve defaults below are the categories in the Sahayak business guide (Sept 2026);
the moment an admin saves the screen, that saved list is what the site uses.
"""
import uuid

from app.services import settings

SETTING_KEY = 'sahayak_catalogue'

# The FAQ category the public page reads, managed on the ordinary Admin -> Help & FAQ screen.
FAQ_CATEGORY = 'sahayak'

FIELDS = ('key', 'name', 'blurb', 'price', 'duration', 'icon')
LIMITS = {'key': 40, 'name': 80, 'blurb': 240, 'price': 12, 'duration': 40, 'icon': 40}

# name, blurb, price (rupees, ex GST), duration, Font Awesome icon
DEFAULT_SERVICES = [
    ('health_checkup', 'Health checkup',
     'Blood pressure, temperature, pulse, SpO2, weight and respiratory rate, recorded and shared.',
     '299', '15–20 min', 'fa-heart-pulse'),
    ('phlebotomy', 'Blood draw (phlebotomy)',
     'Sample collected at home and handed to the lab. Lab charges are separate.',
     '149', '10–15 min', 'fa-vial'),
    ('vaccination', 'Vaccination',
     'Screening, the dose itself, five minutes of observation and a certificate. Vaccine cost extra.',
     '199', '20–25 min', 'fa-syringe'),
    ('wound_care', 'Wound care and dressing',
     'Inspection, cleaning, dressing and aftercare instructions. Supplies included.',
     '249', '15–20 min', 'fa-bandage'),
    ('catheter_care', 'Catheter care',
     'Site check, bag replacement and tubing inspection, using sterile technique.',
     '199', '10–15 min', 'fa-droplet'),
    ('iv_setup', 'IV fluid setup',
     'Line insertion and flow rate set to the prescription, with monitoring visits as ordered.',
     '349', '15–20 min', 'fa-hospital-user'),
    ('insulin', 'Insulin administration',
     'Glucose check, injection with site rotation, and a note on timing and diet.',
     '149', '10–15 min', 'fa-notes-medical'),
    ('ecg', 'ECG at home',
     'A 12-lead recording on a portable device, sent to a doctor for reading.',
     '399', '10 min', 'fa-wave-square'),
    ('oxygen', 'Oxygen therapy setup',
     'Cylinder or concentrator set up, flow rate set, and the family shown what to do.',
     '249', '20–25 min', 'fa-lungs'),
    ('post_op', 'Post-operative care',
     'Surgical site check, dressing, infection screening and recovery guidance.',
     '299', '15–20 min', 'fa-user-nurse'),
    ('medication', 'Medication support',
     'Pill organiser set up, doses explained, and a chart left in the house.',
     '99', '10–15 min', 'fa-pills'),
    ('education', 'Health education',
     'Condition-specific coaching on diet, exercise and daily routine, with the family included.',
     '199', '20–30 min', 'fa-chalkboard-user'),
]


def _blob():
    try:
        return settings.get_setting(SETTING_KEY, {}) or {}
    except Exception:            # pragma: no cover - table not created yet
        return {}


def services():
    """The catalogue, in priority order: Preventia, then the admin screen, then the defaults.

    Preventia360 owns the real catalogue and its pricing (services/preventia). It comes first
    because a price edited there and not here is the kind of disagreement nobody notices until
    a customer is quoted the wrong number -- and because it is the one list their own apps
    render, so ours matching it is the point.

    Anything an admin has saved here wins over the shipped defaults but not over Preventia; the
    screen is the way to run without the API, not a way to override it. All three return the
    same shape, so nothing downstream knows or cares which one answered.
    """
    from app.services import preventia

    if preventia.enabled():
        remote = preventia.service_categories()
        # None is "we could not ask" and falls through to the local list; [] is an answer, and
        # publishing nothing is a thing a catalogue is allowed to say.
        if remote is not None:
            return preventia.as_catalogue(remote)

    rows = _blob().get('services')
    if rows is None:
        return [dict(zip(FIELDS, row)) for row in DEFAULT_SERVICES]
    return [dict(r) for r in rows]


def by_key(key):
    for s in services():
        if s['key'] == key:
            return s
    return None


def keys():
    return [s['key'] for s in services()]


def is_customised():
    return _blob().get('services') is not None


def clean_rows(rows):
    """Trim, cap and drop the empty ones. A service needs a name and a key to be orderable."""
    out, seen = [], set()
    for row in rows:
        clean = {f: (row.get(f) or '').strip()[:LIMITS[f]] for f in FIELDS}
        if not clean['name']:
            continue
        key = clean['key'] or uuid.uuid4().hex[:10]
        key = ''.join(ch if ch.isalnum() or ch == '_' else '_' for ch in key.lower())[:40]
        while key in seen:                       # two rows must never share a key
            key = (key + '_2')[:40]
        seen.add(key)
        clean['key'] = key
        out.append(clean)
    return out


def save(rows, actor=None):
    blob = _blob()
    blob['services'] = clean_rows(rows)
    settings.set_setting(SETTING_KEY, blob, actor)
    settings.clear_cache()
    return blob['services']
