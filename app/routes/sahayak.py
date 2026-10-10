"""Sahayak home healthcare: the public page and the booking requests it produces.

This phase is deliberately a request desk, not a dispatch system. Somebody asks for a visit, it
lands in the CS queue, an agent phones them and assigns a Sahayak by name. No worker app, no
automated matching, no card payment -- and nothing clinical is stored here yet, so a booking
holds only what is needed to turn up at the right door at the right time.
"""
import re
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, render_template, request
from flask_login import current_user

from app import db
from app.models import ActivityEvent, SahayakBooking, SAHAYAK_WHEN, SAHAYAK_WHEN_LABELS
from app.services import help_center, sahayak
from app.services.ratelimit import rate_limit

sahayak_bp = Blueprint('sahayak', __name__)

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
PHONE_RE = re.compile(r'[0-9]')
PIN_RE = re.compile(r'^[1-9][0-9]{5}$')       # an Indian PIN code
IST = timedelta(hours=5, minutes=30)


def _faqs():
    """Every question filed under Sahayak, from Admin -> Sahayak -> Help & FAQ.

    By site rather than by one category key: an admin who adds a second Sahayak category expects
    its questions on this page too, and filtering by a single key would quietly drop them.
    """
    return help_center.faqs('sahayak')


def _canonical():
    aliases = [a for a in (current_app.config.get('APP_ALIAS_PATHS') or []) if 'sahayak' in a]
    if not aliases:
        return request.url
    return request.host_url.rstrip('/') + '/' + aliases[0].strip('/')


PAGE_TITLE = ('Sahayak | A health professional with your parents, every step | '
              'NRI Parent Service')
PAGE_DESCRIPTION = ('A trained health professional takes each step with your parents in India '
                    '-- the health check, the lab work, the hospital appointment, the medicines '
                    '-- and every step is recorded for you to read. Or join the Sahayak network '
                    'as a health professional.')


@sahayak_bp.route('/sahayak')
def landing():
    """The public page. A React bundle (frontend/sahayak) over server-supplied content.

    Everything the business owns is handed to it here rather than baked into the build: the
    catalogue, the published helplines, the support address and the endpoints. services() is
    the one seam to repoint when the catalogue API arrives.
    """
    from app.services import offices, phone, urls

    phones = [{'label': p['label'], 'display': p['display'], 'digits': p['digits']}
              for p in offices.numbers('sahayak')]
    return render_template('sahayak/landing.html',
                           services=sahayak.services(),
                           faqs=_faqs(),
                           phones=phones,
                           support_email=offices.email('sahayak'),
                           whatsapp_digits=offices.whatsapp('sahayak'),
                           wa_link=offices.wa_link('sahayak'),
                           # the same dialling codes the rest of the site validates
                           # against, so the bundle's picker and services/phone cannot
                           # disagree -- as the insurance page already does
                           dial_codes=[{'name': n, 'iso': i, 'dial': d}
                                       for i, n, d in phone.COUNTRIES],
                           # the digit counts the server holds a number to, so the form can say
                           # "one digit short" before sending rather than after
                           phone_rules={d: list(r) for d, r in phone.NATIONAL_RANGE.items()},
                           specializations=[{k: s[k] for k in ('code', 'name', 'description')}
                                            for s in sahayak.specializations()],
                           qualifications=list(sahayak.QUALIFICATIONS),
                           contact_url=urls.public_url('main.contact_us'),
                           page_title=PAGE_TITLE, page_description=PAGE_DESCRIPTION,
                           canonical_url=_canonical())


@sahayak_bp.route('/api/sahayak-journey')
def journey():
    """What one service's visit covers, from Preventia.

    Asked for one service at a time, when a visitor opens it, rather than handed over with the
    page: the upstream call is slow and its response is large, and nine of them cold is eleven
    seconds of a landing page nobody is looking at yet.

    An empty list means "we could not tell you" -- the page keeps the steps it shipped with
    rather than claiming a visit covers nothing.
    """
    from app.services import preventia

    key = (request.args.get('service') or '').strip()
    svc = sahayak.by_key(key) if key else None
    if not svc or not svc.get('remote_id') or not preventia.enabled():
        return jsonify({'success': True, 'steps': []})
    steps = sahayak.decorate_steps(preventia.journey(svc['remote_id']))
    return jsonify({'success': True, 'steps': steps or []})


def _push_lead(submission_type, full_name, phone, email, details, **event):
    """Copy a request into Preventia's review queue. Returns their submissionId, or None.

    Always called after our own commit, never instead of it. The booking or application is
    already saved and the visitor is already owed an answer, so this is a copy: if it does not
    get across, a row is missing at their end and nothing is missing at ours.

    The outcome is written to the activity log either way. Without that, a lead that failed
    would exist only in a log file nobody reads, and the first anyone would know is a Preventia
    admin asking why their queue is empty.
    """
    from app.services import preventia

    if not preventia.enabled():
        return None
    try:
        submission_id = preventia.submit_lead(submission_type, full_name, phone,
                                              email=email, details=details)
        actor = current_user if current_user.is_authenticated else None
        ActivityEvent.log('preventia_lead' if submission_id else 'preventia_lead_failed',
                          actor=actor, kind=submission_type, submission_id=submission_id, **event)
        db.session.commit()
        return submission_id
    except Exception:
        # submit_lead already swallows every network and protocol failure, so reaching here
        # means something unforeseen -- writing the audit row, most likely. The booking is
        # committed and the visitor is owed an answer either way, so a bare except is the
        # honest shape: there is no failure in copying a request that justifies a 500 on a
        # form that worked.
        current_app.logger.exception('preventia lead %s could not be recorded', submission_type)
        db.session.rollback()
        return None


@sahayak_bp.route('/api/sahayak-booking', methods=['POST'])
@rate_limit(10, 3600)
def book():
    """Take a request for a visit.

    Signing in is not required: the person booking is often an NRI arranging care for a parent,
    and sometimes the parent themselves. Making them register first would lose the booking.

    Stored here first, then copied to Preventia as a lead -- in that order, so the request
    survives anything that happens to the copy. See _push_lead.
    """
    from app.services import phone as phone_svc

    data = request.get_json(silent=True) or request.form

    def get(key, limit=200):
        return (data.get(key) or '').strip()[:limit]

    service = sahayak.by_key(get('service', 40))
    patient_name = get('patient_name', 120)
    phone = get('phone', 30)
    email = get('email', 255).lower()
    address = get('address', 600)
    when_type = get('when_type', 12) or 'asap'
    scheduled_raw = get('scheduled_for', 32)

    errors = []
    if not service:
        errors.append('Choose which service you need.')
    if not patient_name:
        errors.append('Tell us who the visit is for.')
    if not phone or not PHONE_RE.search(phone):
        errors.append('A phone number is required — the team calls to confirm.')
    else:
        # Stored the way every other number on the site is stored. The form sends the
        # dialling code and the number separately joined by a space; without this the table
        # would hold "+46 764498115" while the contact table holds "+46764498115", and a
        # column of numbers in two shapes is a column nobody can scan.
        # the country picked beside the number (an ISO code). A bundle cached from before
        # sends "+91 ..." joined instead, which still works: a leading + wins.
        e164, bad_phone = phone_svc.normalise(
            phone, get('phone_cc', 4).upper() or phone_svc.DEFAULT_ISO)
        bad_phone = bad_phone or phone_svc.length_error(e164)
        if bad_phone:
            errors.append(bad_phone)
        else:
            phone = e164
    if email and not EMAIL_RE.match(email):
        errors.append('That e-mail address does not look right.')
    if not address:
        errors.append('We need the address to send somebody to.')
    pincode = get('pincode', 12)
    if pincode and not PIN_RE.match(pincode):
        errors.append('A PIN code is six digits and does not start with 0.')
    # Optional, and only ever one Preventia actually lists: asking for a specialisation nobody
    # offers would be a promise the team then has to break on the phone.
    spec_code = get('specialization', 60)
    spec = sahayak.specialization(spec_code) if spec_code else None
    if spec_code and not spec:
        errors.append('That specialisation is not one we can arrange -- choose another or leave it.')
    if when_type not in SAHAYAK_WHEN:
        when_type = 'asap'

    scheduled_for = None
    if when_type == 'scheduled':
        try:
            scheduled_for = datetime.strptime(scheduled_raw, '%Y-%m-%dT%H:%M')
        except ValueError:
            errors.append('Pick a date and time for the visit.')
        else:
            if scheduled_for < datetime.now():
                errors.append('That time has already passed.')
    else:
        # No time asked for: the booking forms no longer offer one, and the team rings to agree it.
        # Recorded as the moment it was asked, in India's time like the times people type, so the
        # copy Preventia receives still carries a date and a time.
        scheduled_for = (datetime.utcnow() + IST).replace(second=0, microsecond=0)

    if errors:
        return jsonify({'success': False, 'error': ' '.join(errors)}), 400

    age = get('patient_age', 3)
    booking = SahayakBooking(
        user_id=current_user.id if current_user.is_authenticated else None,
        service_key=service['key'], service_name=service['name'], quoted_price=service.get('price'),
        patient_name=patient_name,
        patient_age=int(age) if age.isdigit() and 0 < int(age) < 130 else None,
        contact_name=get('contact_name', 120) or None,
        phone=phone, email=email or None,
        address=address, landmark=get('landmark', 200) or None,
        pincode=pincode or None, access_notes=get('access_notes', 300) or None,
        when_type=when_type, scheduled_for=scheduled_for,
        notes='\n'.join(x for x in (spec and 'Preferred specialisation: %s' % spec['name'],
                                    get('notes', 2000)) if x) or None,
    )
    db.session.add(booking)
    db.session.commit()
    ActivityEvent.log('sahayak_booking', actor=current_user if current_user.is_authenticated else None,
                      booking_id=booking.id, service=service['key'], when=when_type)
    db.session.commit()

    from app.services import preventia
    _push_lead(preventia.BOOKING_REQUEST,
               # who to ring, which is not always who the visit is for
               booking.contact_name or booking.patient_name, booking.phone, booking.email,
               {'service': service['name'], 'serviceCategoryId': service.get('remote_id'),
                'patient': booking.patient_name, 'patientAge': booking.patient_age,
                'pincode': booking.pincode, 'address': booking.address,
                'landmark': booking.landmark, 'accessNotes': booking.access_notes,
                'when': SAHAYAK_WHEN_LABELS.get(when_type, when_type),
                'scheduledFor': scheduled_for.isoformat(' ') if scheduled_for else None,
                'specialization': spec['name'] if spec else None,
                'specializationCode': spec['code'] if spec else None,
                'specializationId': spec.get('id') if spec else None,
                'message': booking.notes,
                'ourReference': 'sahayak_bookings#%d' % booking.id},
               booking_id=booking.id)

    return jsonify({'success': True, 'booking_id': booking.id,
                    # read back spaced, the way the application reply and the console show it:
                    # "+46764498115" is the one shape nobody can check at a glance
                    'message': 'Request received. Our team will call %s to confirm.'
                               % phone_svc.pretty(phone, phone)}), 201


# The fields the "Join as a Sahayak" form collects, in the order a reader wants them. Kept as a
# list rather than columns of their own: this is an application to be read and phoned, not
# something anything queries or filters on, and a table nobody filters is a migration spent on
# nothing. One list, read twice -- it composes the message CS opens, and it fills the `details`
# of the lead Preventia's reviewer sees, so the two can never drift apart.
APPLY_FIELDS = [
    ('full_name', 'Name'), ('age', 'Age'), ('mobile', 'Mobile'), ('whatsapp', 'WhatsApp'),
    ('email', 'E-mail'), ('location', 'City / area / PIN'),
    ('qualification', 'Nursing qualification'), ('years', 'Years of experience'),
    ('registration_number', 'Nursing council registration no.'),
    ('nursing_council', 'State Nursing Council'), ('institution', 'Institution'),
    ('year', 'Year of completion'), ('certification', 'Other certification'),
    ('home', 'Worked in home healthcare'), ('elder', 'Assisted elderly patients'),
    ('hosp', 'Worked with hospitals or clinics'), ('experience', 'Experience'),
    ('services', 'Services they can provide'), ('work', 'Work type'),
    ('service_city', 'City they can serve'), ('service_pins', 'Areas / PINs'),
    ('availability', 'Availability'), ('languages', 'Languages'), ('transport', 'Transport'),
    ('documents_offered', 'Documents they have ready'),
]


@sahayak_bp.route('/api/sahayak-apply', methods=['POST'])
@rate_limit(6, 3600)
def apply():
    """Take an application from a healthcare professional who wants to join.

    It reaches CS as a contact message filed under Sahayak rather than a table of its own --
    see APPLY_FIELDS -- and a copy goes to Preventia as a SAHAYAK_SIGNUP lead for their own
    reviewer. Documents are not accepted here: an upload needs storage, a size limit and a
    scan, and the team asks for certificates on the confirming call anyway. The form says so
    rather than pretending to take them.
    """
    from app.routes.main import _save_contact
    from app.services import phone as phone_svc

    data = request.get_json(silent=True) or request.form

    def get(key, limit=300):
        return (data.get(key) or '').strip()[:limit]

    def shown(key):
        """A field as it should read in the message CS opens. The two phone fields are spaced
        the way the rest of the site spaces them, so whoever rings can see the country."""
        raw = get(key)
        if key in ('mobile', 'whatsapp') and raw:
            e164, bad = phone_svc.normalise(raw, country(key))
            return raw if bad else phone_svc.pretty(e164, raw)
        return raw

    def country(key):
        """The country picked beside `key` (mobile_cc / whatsapp_cc), as an ISO code."""
        return get(key + '_cc', 4).upper() or phone_svc.DEFAULT_ISO

    name = get('full_name', 120)
    phone = get('mobile', 30)
    email = get('email', 255).lower()
    # The nursing qualification. A bundle cached from before this asked "background" or
    # "healthcare qualification" instead, so those are read too -- and then held to the same list.
    qualification = next((q for q in sahayak.QUALIFICATIONS
                          if q.lower() == (get('qualification') or get('healthcare_qualification')
                                           or get('background')).lower()), None)

    errors = []
    if not name:
        errors.append('Please tell us your name.')
    if not qualification:
        errors.append('We are recruiting nurses with a B.Sc Nursing, GNM or ANM qualification only.')
    if not get('registration_number', 60):
        errors.append('Your State Nursing Council registration number is needed to verify you.')
    year = get('year', 4)
    if year and not (year.isdigit() and 1960 <= int(year) <= datetime.now().year):
        errors.append('The year of completion does not look right.')
    age = get('age', 3)
    if age and not (age.isdigit() and 18 <= int(age) <= 75):
        errors.append('Age should be between 18 and 75.')
    if not phone or not PHONE_RE.search(phone):
        errors.append('A phone number is required — the team calls to talk it through.')
    else:
        e164, bad_phone = phone_svc.normalise(phone, country('mobile'))
        bad_phone = bad_phone or phone_svc.length_error(e164)
        if bad_phone:
            errors.append(bad_phone)
        else:
            phone = e164
    if email and not EMAIL_RE.match(email):
        errors.append('That e-mail address does not look right.')
    if errors:
        return jsonify({'success': False, 'error': ' '.join(errors)}), 400

    lines = ['Sahayak application.', '']
    lines += ['%s: %s' % (label, qualification if key == 'qualification' else shown(key))
              for key, label in APPLY_FIELDS if key == 'qualification' or get(key)]
    msg = _save_contact({'name': name, 'email': email or 'no-email@nriparentservice.com',
                         'phone': phone, 'message': '\n'.join(lines)}, topic='sahayak')
    ActivityEvent.log('sahayak_application',
                      actor=current_user if current_user.is_authenticated else None,
                      contact_id=msg.id)
    db.session.commit()

    from app.services import preventia
    _push_lead(preventia.SAHAYAK_SIGNUP, name, phone, email,
               # the whole application: `details` is unstructured at their end and shown to the
               # reviewing admin as it arrives, so it carries the same fields CS reads
               dict([(key, shown(key)) for key, _ in APPLY_FIELDS if get(key)],
                    qualification=qualification, ourReference='contact_messages#%d' % msg.id),
               contact_id=msg.id)
    return jsonify({'success': True,
                    'message': 'Application received. Our team will call %s.'
                               % phone_svc.pretty(phone, phone)}), 201
