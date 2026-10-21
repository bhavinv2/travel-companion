"""Families (Sales CRM 2.0, run 4a): the child abroad who pays, the parents, the carer.

A household is made with the first link ("Add a family member" on a contact page) and deleted when its
last member leaves. People point at it with CrmPerson.household_id and say their part in
household_role. Every screen that lists family members shows only the people the viewer may see
(crm_access.person_filter), and the open enquiries come from the normal lead query, so a lead the viewer
may not see is not listed either.
"""
from sqlalchemy import select

from app import db
from app.models import CrmHousehold, CrmPerson, HOUSEHOLD_ROLES
from app.services import crm, crm_access
from app.services import phone as phone_svc

ROLES = dict(HOUSEHOLD_ROLES)
SHORT = {'payer': 'pays', 'parent': 'parent', 'carer': 'carer', 'other': 'family'}

NO_NAME = 'Give a name and a phone number for the new person.'
BAD_PHONE = 'That phone number does not look right.'
ALREADY_HERE = '%s is already a contact. Search for them and add them from the list instead.'
OTHER_FAMILY = '%s is already in the %s. Take them out of it first.'
SAME = 'That is the same person.'


def default_name(person):
    words = (person.name or '').split()
    return ('%s family' % words[-1]) if words else 'Family'


def role_of(person):
    return person.household_role if person.household_role in ROLES else 'other'


def _country(person):
    iso = (person.country or '').upper()
    if not iso or iso == 'IN':
        return ''
    c = phone_svc.BY_ISO.get(iso)
    return c['name'] if c else ''


def members(person, viewer):
    """The people in this person's family that `viewer` may see, the person first, then by id."""
    if person.household_id is None:
        return []
    q = CrmPerson.query.filter(CrmPerson.household_id == person.household_id)
    seen = crm_access.person_filter(viewer)
    if seen is not None:
        q = q.filter(seen)
    rows = q.order_by(CrmPerson.id).all()
    rows.sort(key=lambda p: p.id != person.id)
    return rows


def card(person, viewer):
    """What the Family card shows: {'household', 'members': [{'person', 'role', 'label', 'me', 'leads'}]} or None."""
    if person.household is None:
        return None
    from app.models import CrmLead
    people = members(person, viewer)
    ids = [p.id for p in people] or [0]
    open_leads = {}
    for l in (CrmLead.query.filter(CrmLead.person_id.in_(ids), CrmLead.status == 'open')
              .order_by(CrmLead.created_at.desc()).all()):
        open_leads.setdefault(l.person_id, []).append(l)
    return {'household': person.household,
            'members': [{'person': p, 'role': role_of(p), 'label': ROLES[role_of(p)], 'me': p.id == person.id,
                         'leads': open_leads.get(p.id, [])} for p in people]}


def line(person, viewer):
    """The other family members for the lead page's 'Family: Ravi (pays, in USA) · Lata (parent)' line."""
    out = []
    for p in members(person, viewer):
        if p.id == person.id:
            continue
        bits = [SHORT[role_of(p)]]
        where = _country(p)
        if where:
            bits.append('in ' + where)
        out.append({'person': p, 'text': '%s (%s)' % (p.display_name.split()[0] if p.display_name else '?',
                                                        ', '.join(bits))})
    return out


def _check_role(role):
    return role if role in ROLES else 'other'


def link(person, other, role='other', actor=None):
    """Put `other` in `person`'s family (making the family if neither has one). Returns an error text or None."""
    if other.id == person.id:
        return SAME
    mine, theirs = person.household, other.household
    if mine is not None and theirs is not None and mine.id != theirs.id:
        return OTHER_FAMILY % (other.display_name, theirs.name)
    house = mine or theirs
    if house is None:
        house = CrmHousehold(name=default_name(person), created_by_id=getattr(actor, 'id', None))
        db.session.add(house)
        db.session.flush()
    for p in (person, other):
        if p.household_id != house.id:
            p.household = house
    if person.household_role is None:
        person.household_role = 'other'
    other.household_role = _check_role(role)
    db.session.flush()
    return None


def create_member(person, name, phone, role, actor=None, cc=None):
    """A new person (name + phone) straight into the family. Returns (new person, None) or (None, error)."""
    name = ' '.join((name or '').split())[:120]
    raw = (phone or '').strip()
    if not name or not raw:
        return None, NO_NAME
    e164 = crm.normalise_phone(raw, cc or None)
    if not e164:
        return None, BAD_PHONE
    existing = CrmPerson.query.filter_by(phone=e164).first()
    if existing is not None:
        return None, ALREADY_HERE % existing.display_name
    new = CrmPerson(name=name, phone=e164, country=(phone_svc.iso_for(e164) or '')[:2] or None)
    db.session.add(new)
    db.session.flush()
    err = link(person, new, role, actor)
    if err:
        return None, err
    return new, None


def set_role(person, role):
    person.household_role = _check_role(role)


def drop_if_empty(household_id):
    """Delete the family when nobody is left in it."""
    if household_id is None:
        return False
    left = db.session.execute(select(CrmPerson.id).where(CrmPerson.household_id == household_id).limit(1)).first()
    if left is None:
        h = db.session.get(CrmHousehold, household_id)
        if h is not None:
            db.session.delete(h)
            return True
    return False


def leave(person):
    """Take them out of their family; the family goes when it is empty."""
    hid = person.household_id
    if hid is None:
        return False
    person.household_id = None
    person.household_role = None
    db.session.flush()
    drop_if_empty(hid)
    return True


def rename(household, name):
    name = ' '.join((name or '').split())[:120]
    if name:
        household.name = name
    return bool(name)


def match_condition(q):
    """SQL condition on CrmPerson: they are in a family whose name has `q` in it (for Find a person)."""
    q = ' '.join((q or '').split())[:80]
    if not q:
        return None
    return CrmPerson.household_id.in_(select(CrmHousehold.id).where(CrmHousehold.name.ilike('%%%s%%' % q)))
