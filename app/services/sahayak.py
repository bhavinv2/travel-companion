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

# Who can join as a Sahayak. Only registered nurses, and only these three routes into nursing:
# the page, the application form and the server all read this one list.
QUALIFICATIONS = ('B.Sc Nursing', 'GNM', 'ANM')

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


# What to say about each of Preventia's categories, keyed by their code.
#
# Their catalogue is authoritative for the names, the prices and the ids, and we take all three
# from it. It is not written for a public page, though: every category's `description` comes
# back as its own internal code ("Category code: SAHAYAK_WELLNESS"), and the API carries no icon
# or duration at all. Printing those would give a row of identical icons under nine lines of
# jargon. So the blurb, the icon and the duration are ours, matched to their code; anything they
# add that is not listed here still appears, just with a plain icon and their own description.
REMOTE_COPY = {
    'WELLNESS_SCREEN': (
        'A full home check: history, vitals, blood and urine samples, and an ECG — written up '
        'and shared with you.', 'fa-heart-pulse', '60–75 min'),
    'LAB_WORK': (
        'Samples collected at home and handed to the lab, with the submission time recorded.',
        'fa-vial', '20–30 min'),
    'VITALS': (
        'Blood pressure, pulse, SpO2, temperature, sugar, breathing rate, weight and BMI.',
        'fa-wave-square', '20–30 min'),
    'OUT_PATIENT_VISIT': (
        'Your parent is taken to the clinic, accompanied through the appointment, and brought '
        'home.', 'fa-user-doctor', '2–4 hours'),
    'IN_PATIENT_VISIT': (
        'Company and practical help through a hospital stay, procedure or follow-up.',
        'fa-hospital', '3–6 hours'),
    'PHARMACY_DELIVERY': (
        'Prescription medicines collected and delivered to your parents, with the doses '
        'explained.', 'fa-pills', '45–60 min'),
    'DEMO': (
        'A short introductory visit so your parents can meet a Sahayak before booking anything '
        'longer.', 'fa-handshake-angle', '30–45 min'),
    'VIRTUAL_CONSULT_SUPPORT': (
        'A Sahayak sits with your parents through an online consultation and handles the '
        'technology.', 'fa-video', '45–60 min'),
    'OTHER': (
        'Something not on this list — tell us what your parents need and we will arrange it.',
        'fa-notes-medical', 'Varies'),
}


# What to call each step of the visit, keyed by Preventia's gig type.
#
# The API decides WHICH steps a service has and whether each is required -- that is the part
# that must stay theirs, so a step they add or make optional shows up here without a deploy.
# What it is CALLED is ours: their names are operational ("Customer Digitization", "Verified
# Signature", "Wellness Questionary"), written for the person doing the work, and this list is
# read by a son in New Jersey deciding whether to book a visit for his mother.
#
# A code not listed keeps their name, so a new step appears rather than disappearing.
STEP_COPY = {
    'SAHAYAK_CHECKIN': ('Sahayak arrives', 'Time and place recorded when they get there.'),
    'SAHAYAK_WELLNESS_QUESTIONARY': ('Wellness questionnaire',
                                     'Health history, lifestyle, allergies and symptoms.'),
    'SAHAYAK_VITALS_CAPTURE': ('Vitals', 'BP, pulse, SpO2, temperature, sugar, weight and BMI.'),
    'SAHAYAK_BLOODWORK': ('Blood tests', 'Pre- or post-meal samples, as advised.'),
    'SAHAYAK_URINE': ('Urine test', 'Collected and labelled during the visit.'),
    'SAHAYAK_ECG': ('ECG', 'A reading taken at home on a portable device.'),
    'SAHAYAK_CLINICAL_HISTORY': ('Clinical history',
                                 'Complaints, past illness, surgery and family history.'),
    'MEDICINES': ('Medicines review', 'Names, doses and schedule written down.'),
    'SAHAYAK_HEALTH_RECORDS': ('Health records updated',
                               'Prescriptions, reports and visit notes saved for you.'),
    'SAHAYAK_CUSTOMER_DIGITIZATION': ('App set-up for your parents',
                                      'Help using the app for bookings, records and payments.'),
    'SAHAYAK_DROP_LOCATION': ('Taken to the appointment',
                              'Accompanied to the hospital, clinic or chosen place.'),
    'SAHAYAK_SAMPLE_SUBMISSION': ('Samples handed to the lab', 'With the time recorded.'),
    'SAHAYAK_CHECKOUT': ('Visit closed', 'Summary of the visit shared with you.'),
    'SAHAYAK_CUSTOMER_RATING': ('Your feedback', 'Rate the visit and tell us how it went.'),
    'DOCTOR_SIGNATURE': ('Doctor sign-off', 'A doctor verifies and signs the record.'),
}


def decorate_steps(steps):
    """Preventia's journey in words a family can read. None stays None: see journey()."""
    if steps is None:
        return None
    out = []
    for s in steps:
        row = dict(s)
        title, text = STEP_COPY.get(row.get('key') or '', (None, None))
        if title:
            row['title'] = title
            row['text'] = text
        out.append(row)
    return out


def decorate(rows):
    """Put our own words and icons on Preventia's catalogue, matched by their category code."""
    out = []
    for r in rows:
        row = dict(r)
        blurb, icon, duration = REMOTE_COPY.get((row.get('code') or '').upper(), (None,) * 3)
        if blurb:
            row['blurb'] = blurb
            row['icon'] = icon
            row['duration'] = duration
        elif (row.get('blurb') or '').startswith('Category code:'):
            # their placeholder, which is worse on the page than saying nothing
            row['blurb'] = ''
        out.append(row)
    return out


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
            return decorate(preventia.as_catalogue(remote))

    rows = _blob().get('services')
    if rows is None:
        return [dict(zip(FIELDS, row)) for row in DEFAULT_SERVICES]
    return [dict(r) for r in rows]


def specializations():
    """The specialisations a family may ask for when booking, from Preventia; [] when it cannot
    be asked (the page then simply does not offer the choice)."""
    from app.services import preventia
    return preventia.specializations() or []


def specialization(code):
    """The specialisation with this code, or None."""
    return next((s for s in specializations() if s['code'] == code), None)


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


# ---------------------------------------------------------------------------
# Did the copy reach Preventia?
# ---------------------------------------------------------------------------

def lead_state(booking_ids):
    """{booking_id: {'ok': bool, 'submission_id': str|None}} for the rows on one page.

    Read out of the activity log rather than a column on the booking: this is a record of an
    attempt, not a property of the request, and it would be a migration to store what one query
    already answers.

    There is no GET at their end to ask what became of a lead, so "ok" means only that they
    accepted it -- the queue says "sent", never "approved", because the second would be a claim
    we cannot check. Bookings with no event at all are absent from the result: they predate the
    integration, or it was switched off, and either way the honest display is nothing rather
    than a red mark against a booking nobody tried to copy.
    """
    from app.models import ActivityEvent

    ids = [i for i in (booking_ids or []) if i]
    if not ids:
        return {}
    rows = (ActivityEvent.query
            .filter(ActivityEvent.event.in_(('preventia_lead', 'preventia_lead_failed')))
            .filter(ActivityEvent.meta['booking_id'].as_integer().in_(ids))
            .order_by(ActivityEvent.created_at.asc(), ActivityEvent.id.asc())
            .all())
    out = {}
    for ev in rows:
        bid = (ev.meta or {}).get('booking_id')
        if bid in ids:
            # last attempt wins: a retry that succeeded should not read as a failure
            out[bid] = {'ok': ev.event == 'preventia_lead',
                        'submission_id': (ev.meta or {}).get('submission_id')}
    return out
