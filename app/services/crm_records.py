"""Everything the site holds about a person, on one card (Sales CRM 2.0, run 4a): their trip posts, insurance
quote requests, Sahayak bookings, contact messages and site account -- found by the account they are linked
to (CrmPerson.user_id), by e-mail, by phone, and by the records their enquiries came from -- and the one
helper that says where each record can be opened (also used by the lead page's "Open the original").

Where a record has a screen of its own (a trip post) the link goes there; the others only have a list page,
which opens filtered to that record (`?id=`; the row also carries `#rec-<id>`).
"""
import re

from flask import url_for
from sqlalchemy import func, or_

from app import db
from app.models import (CompanionRequest, ContactMessage, CrmLead, InsuranceQuote, SahayakBooking, User)
from app.services import phone as phone_svc

LIMIT = 10
LABELS = {'trip': 'Trip post', 'insurance_quote': 'Insurance quote request', 'sahayak_booking': 'Sahayak booking',
          'contact_message': 'Contact message', 'user': 'Site account'}
# a lead's ref_type -> the kind above
KIND_OF_REF = {'companion_requests': 'trip', 'insurance_quotes': 'insurance_quote',
               'sahayak_bookings': 'sahayak_booking', 'contact_messages': 'contact_message', 'users': 'user'}


def record_url(kind, record_id, email=None, viewer=None):
    """Where this record opens, or None. Site accounts open for admins only (the Users list, searched)."""
    try:
        if kind == 'trip':
            return url_for('cs.post_detail', trip_id=record_id)
        if kind == 'insurance_quote':
            return url_for('cs.insurance_quotes', id=record_id) + '#rec-%d' % record_id
        if kind == 'sahayak_booking':
            return url_for('cs.sahayak_bookings', id=record_id) + '#rec-%d' % record_id
        if kind == 'contact_message':
            return url_for('cs.voices', tab='contact', id=record_id) + '#rec-%d' % record_id
        if kind == 'user':
            if viewer is not None and getattr(viewer, 'is_admin', False):
                return url_for('admin.users', q=email or str(record_id))
            return None
    except Exception:          # noqa: BLE001 -- a screen that is not there must not break the page
        return None
    return None


def url_for_ref(ref_type, ref_id, email=None, viewer=None):
    kind = KIND_OF_REF.get(ref_type)
    return record_url(kind, ref_id, email=email, viewer=viewer) if kind and ref_id else None


def _tail(phone):
    digits = re.sub(r'\D', '', phone or '')
    return digits[-10:] if len(digits) >= 7 else ''


def _phone_cond(column, phone):
    tail = _tail(phone)
    return phone_svc.search_condition(column, tail) if tail else None


def _site_user_ids(person):
    conds = []
    if person.user_id:
        conds.append(User.id == person.user_id)
    if person.email:
        conds.append(func.lower(User.email) == person.email.lower())
    c = _phone_cond(User.phone, person.phone)
    if c is not None:
        conds.append(c)
    if not conds:
        return []
    return [u.id for u in User.query.filter(or_(*conds)).order_by(User.id).limit(LIMIT)]


def _ref_ids(person_id, ref_type):
    return [r for (r,) in db.session.query(CrmLead.ref_id).filter(CrmLead.person_id == person_id,
                                                                   CrmLead.ref_type == ref_type,
                                                                   CrmLead.ref_id.isnot(None)).all()]


def _day(dt):
    return dt.strftime('%d %b %Y') if dt else ''


def records_for(person, viewer=None):
    """[{'kind', 'label', 'id', 'title', 'sub', 'when', 'url'}] newest first -- a fixed number of queries."""
    out = []
    uids = _site_user_ids(person)
    email = (person.email or '').lower()

    def match(model, user_col='user_id', ref_type=None, email_col=None, phone_col=None):
        conds = []
        if uids:
            conds.append(getattr(model, user_col).in_(uids))
        if email and email_col is not None:
            conds.append(func.lower(email_col) == email)
        if phone_col is not None:
            c = _phone_cond(phone_col, person.phone)
            if c is not None:
                conds.append(c)
        ids = _ref_ids(person.id, ref_type) if ref_type else []
        if ids:
            conds.append(model.id.in_(ids))
        if not conds:
            return []
        return model.query.filter(or_(*conds)).order_by(model.created_at.desc()).limit(LIMIT).all()

    for r in match(CompanionRequest, ref_type='companion_requests'):
        route = getattr(r, 'route_display', '') or ''
        out.append(('trip', r.id, 'Trip post #%d' % r.id, '%s %s' % (route, _day(r.from_date)), r.created_at))
    for r in match(InsuranceQuote, ref_type='insurance_quotes', email_col=InsuranceQuote.email,
                   phone_col=InsuranceQuote.phone):
        out.append(('insurance_quote', r.id, 'Insurance quote request',
                    '%s, travelling %s' % ((r.insurance_type or '').title(), _day(r.start_date)), r.created_at))
    for r in match(SahayakBooking, ref_type='sahayak_bookings', email_col=SahayakBooking.email,
                   phone_col=SahayakBooking.phone):
        out.append(('sahayak_booking', r.id, 'Sahayak booking: %s' % r.service_name,
                    'for %s' % r.patient_name, r.created_at))
    for r in match(ContactMessage, ref_type='contact_messages', email_col=ContactMessage.email,
                   phone_col=ContactMessage.phone):
        out.append(('contact_message', r.id, 'Contact message', (r.message or '')[:80], r.created_at))
    users = User.query.filter(User.id.in_(uids)).all() if uids else []
    for u in users:
        out.append(('user', u.id, 'Site account: %s' % (u.full_name or u.username), u.email or '',
                    getattr(u, 'created_at', None)))
    rows = []
    seen = set()
    for kind, rid, title, sub, when in out:
        if (kind, rid) in seen:
            continue
        seen.add((kind, rid))
        email_for = next((u.email for u in users if u.id == rid), None) if kind == 'user' else None
        rows.append({'kind': kind, 'label': LABELS[kind], 'id': rid, 'title': title, 'sub': sub, 'when': when,
                     'url': record_url(kind, rid, email=email_for, viewer=viewer)})
    from datetime import datetime
    rows.sort(key=lambda r: r['when'] or datetime.min, reverse=True)
    return rows
