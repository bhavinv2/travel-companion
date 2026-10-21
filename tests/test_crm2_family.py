"""Sales CRM 2.0, run 4a -- families (4.1) and everything about a person on one page (4.2).

    migration  u5crm021 up, down, up on SQLite
    family     the first link makes the family ("<surname> family"), roles, remove, an empty family is deleted,
               one person cannot be in two families, the lead page line, History in words, Find matches the name
    erase      Erase this person leaves the family and deletes an empty one
    records    the contact page lists their trip posts, quote requests, bookings, messages and account, each
               linked to THAT record; the list pages open filtered to it; the lead's "Open the original" too
    visibility the family card and the lead line never show a person the viewer may not see
"""
import os
import re
from datetime import date, timedelta

import pytest

from conftest import login, make_user
from app import db as _db
from app.models import (CompanionRequest, ContactMessage, CrmAudit, CrmHousehold, CrmLead, CrmPerson,
                        InsuranceQuote, SahayakBooking)
from app.services import access, crm, crm_audit, crm_household, crm_people

from test_crm_wa_sync_engine import ti_lead
from test_crm2_visibility import lead_for, staff, words


def person(name, phone, **kw):
    p = CrmPerson(name=name, phone=phone, **kw)
    _db.session.add(p)
    _db.session.commit()
    return p


# ====================================================================================== the migration

def test_migration_u5crm021_goes_up_down_up_on_sqlite(tmp_path):
    import importlib.util
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations', 'versions',
                        'u5crm021_households_files.py')
    spec = importlib.util.spec_from_file_location('u5crm021', path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    assert mig.revision == 'u5crm021' and mig.down_revision == 'u4crm020'
    engine = sa.create_engine('sqlite:///%s' % (tmp_path / 'm.db'))
    meta = sa.MetaData()
    sa.Table('users', meta, sa.Column('id', sa.Integer, primary_key=True))
    sa.Table('crm_leads', meta, sa.Column('id', sa.Integer, primary_key=True))
    sa.Table('crm_people', meta, sa.Column('id', sa.Integer, primary_key=True), sa.Column('name', sa.String(20)))
    meta.create_all(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO crm_people (id, name) VALUES (1, 'Old Person')"))
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mig.upgrade()
        insp = sa.inspect(conn)
        assert {'crm_households', 'crm_files'} <= set(insp.get_table_names())
        assert {c['name'] for c in insp.get_columns('crm_people')} >= {'household_id', 'household_role'}
        assert {c['name'] for c in insp.get_columns('crm_files')} >= {
            'person_id', 'lead_id', 'filename', 'stored_name', 'size', 'content_type', 'uploaded_by_id', 'uploaded_at'}
        assert conn.execute(sa.text('SELECT household_id FROM crm_people WHERE id = 1')).scalar() is None
        with Operations.context(ctx):
            mig.downgrade()
        insp = sa.inspect(conn)
        assert not {'crm_households', 'crm_files'} & set(insp.get_table_names())
        assert 'household_id' not in {c['name'] for c in insp.get_columns('crm_people')}
        with Operations.context(ctx):
            mig.upgrade()
        assert 'crm_households' in sa.inspect(conn).get_table_names()


# ====================================================================================== the family

@pytest.fixture
def agent(app):
    return staff('agent@test.com', 'agent')


def test_the_first_link_makes_the_family_and_names_it(app):
    ravi = person('Ravi Rao', '+14085550100', country='US')
    lata = person('Lata Rao', '+919876500100', country='IN')
    assert crm_household.link(ravi, lata, 'parent') is None
    _db.session.commit()
    assert ravi.household_id == lata.household_id is not None
    assert ravi.household.name == 'Rao family'
    assert (ravi.household_role, lata.household_role) == ('other', 'parent')
    crm_household.set_role(ravi, 'payer')
    _db.session.commit()
    assert ravi.household_role == 'payer'


def test_a_person_cannot_be_in_two_families(app):
    a, b, c, d = (person('A One', '+919876500101'), person('B Two', '+919876500102'),
                  person('C Three', '+919876500103'), person('D Four', '+919876500104'))
    crm_household.link(a, b)
    crm_household.link(c, d)
    _db.session.commit()
    assert 'already in the' in crm_household.link(a, c)
    assert crm_household.link(a, a) == crm_household.SAME


def test_remove_deletes_an_empty_family(app):
    a, b = person('Anil Rao', '+919876500111'), person('Bina Rao', '+919876500112')
    crm_household.link(a, b)
    _db.session.commit()
    hid = a.household_id
    crm_household.leave(a)
    _db.session.commit()
    assert a.household_id is None and a.household_role is None
    assert _db.session.get(CrmHousehold, hid) is not None          # Bina is still in it
    crm_household.leave(b)
    _db.session.commit()
    assert _db.session.get(CrmHousehold, hid) is None


def test_the_routes_add_change_and_remove(app, client, agent):
    ravi = person('Ravi Rao', '+14085550100', country='US')
    login(client, agent.email)
    base = '/cs/crm/contact/%d' % ravi.id
    # a new person straight into the family
    r = client.post(base + '/family/add', data={'name': 'Lata Rao', 'phone': '+91 98765 00200', 'role': 'parent'})
    assert r.status_code == 302
    lata = CrmPerson.query.filter_by(phone='+919876500200').one()
    assert lata.household_id == ravi.household_id and lata.household_role == 'parent'
    assert ravi.household.name == 'Rao family'
    # an existing person
    sita = person('Sita Devi', '+919876500201')
    client.post(base + '/family/add', data={'other_id': sita.id, 'role': 'carer'})
    _db.session.expire_all()
    assert _db.session.get(CrmPerson, sita.id).household_role == 'carer'
    # change a role
    client.post(base + '/family/role', data={'member_id': ravi.id, 'role': 'payer'})
    _db.session.expire_all()
    assert _db.session.get(CrmPerson, ravi.id).household_role == 'payer'
    # rename
    client.post(base + '/family/rename', data={'name': 'The Raos'})
    _db.session.expire_all()
    assert _db.session.get(CrmPerson, ravi.id).household.name == 'The Raos'
    # the card
    t = words(client.get(base).get_data(as_text=True))
    assert 'Lata Rao' in t and 'Sita Devi' in t and 'Remove from family' in t and 'Add a family member' in t
    # remove with the in-page confirm form
    client.post(base + '/family/remove', data={'member_id': sita.id})
    _db.session.expire_all()
    assert _db.session.get(CrmPerson, sita.id).household_id is None
    # a number we already have is refused, with the name
    r = client.post(base + '/family/add', data={'name': 'Again', 'phone': '+14085550100', 'role': 'other'},
                    follow_redirects=True)
    assert 'already a contact' in words(r.get_data(as_text=True))


def test_the_family_card_lists_open_enquiries_and_the_search_finds_people(app, client, agent):
    ravi = person('Ravi Rao', '+14085550100', country='US')
    l = ti_lead(phone='+919876500300', name='Lata Rao')
    crm_household.link(ravi, l.person, 'parent')
    _db.session.commit()
    login(client, agent.email)
    t = words(client.get('/cs/crm/contact/%d' % ravi.id).get_data(as_text=True))
    assert 'Lata Rao' in t and 'Travel Insurance' in t or 'TI' in t
    t = words(client.get('/cs/crm/contact/%d?fq=Lata' % ravi.id).get_data(as_text=True))
    assert 'Add' in t
    t = words(client.get('/cs/crm/contact/%d?fq=zzzzzz' % ravi.id).get_data(as_text=True))
    assert 'No one found' in t


def test_the_lead_page_names_the_family_with_links(app, client, agent):
    l = ti_lead(phone='+919876500301', name='Lata Rao')
    ravi = person('Ravi Rao', '+14085550101', country='US')
    crm_household.link(l.person, ravi, 'payer')
    _db.session.commit()
    login(client, agent.email)
    html = client.get('/cs/crm/lead/%d' % l.id).get_data(as_text=True)
    t = words(html)
    assert 'Family: Ravi (pays, in United States)' in t
    assert '/contact/%d' % ravi.id in html


def test_find_a_person_also_matches_the_family_name(app, client, agent):
    ravi = person('Ravi Kumar', '+14085550102')
    lata = person('Lata Devi', '+919876500302')
    crm_household.link(ravi, lata)
    ravi.household.name = 'Zephyr family'
    _db.session.commit()
    login(client, agent.email)
    names = {i['name'] for i in client.get('/cs/crm/find?q=Zephyr').get_json()['items']}
    assert {'Ravi Kumar', 'Lata Devi'} <= names
    t = words(client.get('/cs/crm/contacts?q=Zephyr').get_data(as_text=True))
    assert 'Ravi Kumar' in t and 'Lata Devi' in t


def test_family_changes_read_in_words_in_the_history(app, client, agent):
    ravi = person('Ravi Rao', '+14085550103')
    lata = person('Lata Rao', '+919876500303')
    login(client, agent.email)
    client.post('/cs/crm/contact/%d/family/add' % ravi.id, data={'other_id': lata.id, 'role': 'parent'})
    t = words(client.get('/cs/crm/contact/%d' % lata.id).get_data(as_text=True))
    assert 'put them in the Rao family' in t
    assert 'set their part in the family to parent' in t
    client.post('/cs/crm/contact/%d/family/remove' % ravi.id, data={'member_id': lata.id})
    t = words(client.get('/cs/crm/contact/%d' % lata.id).get_data(as_text=True))
    assert 'took them out of the' in t


def test_erasing_a_person_leaves_the_family_and_an_empty_family_goes(app, admin_user):
    a, b = person('Anil Rao', '+919876500311'), person('Bina Rao', '+919876500312')
    crm_household.link(a, b)
    _db.session.commit()
    hid = a.household_id
    crm_people.erase(a, admin_user)
    assert _db.session.get(CrmHousehold, hid) is not None and _db.session.get(CrmPerson, b.id).household_id == hid
    assert CrmAudit.query.filter_by(record_type='person', record_id=a.id).count() == 0
    crm_people.erase(_db.session.get(CrmPerson, b.id), admin_user)
    assert _db.session.get(CrmHousehold, hid) is None


# ====================================================================================== visibility

def test_the_family_never_shows_a_person_the_viewer_may_not_see(app, client):
    asha = staff('asha@test.com', 'asha', scope='own')
    bela = staff('bela@test.com', 'bela')
    mine = lead_for('Ownerone Mine', '+919876500401', asha)
    hidden = lead_for('Otherwoman Hidden', '+919876500402', bela)
    free = person('Nolead Person', '+919876500403')
    crm_household.link(mine.person, hidden.person, 'parent')
    crm_household.link(mine.person, free, 'carer')
    _db.session.commit()
    login(client, asha.email)
    for url in ('/cs/crm/contact/%d' % mine.person_id, '/cs/crm/lead/%d' % mine.id,
                '/cs/crm/lead/%d/live' % mine.id):
        t = words(client.get(url).get_data(as_text=True))
        assert 'Otherwoman' not in t and 'Hidden' not in t.replace('hidden', ''), url
    t = words(client.get('/cs/crm/lead/%d' % mine.id).get_data(as_text=True))
    assert 'Nolead' in t                                           # a person with no enquiry is seen by everyone
    # a POST naming a person the role may not see is a 404, and nothing is linked
    r = client.post('/cs/crm/contact/%d/family/add' % mine.person_id, data={'other_id': hidden.person_id})
    assert r.status_code == 404
    assert client.get('/cs/crm/contact/%d' % hidden.person_id).status_code == 404
    assert client.post('/cs/crm/contact/%d/family/add' % hidden.person_id,
                       data={'name': 'X Y', 'phone': '+919876500499'}).status_code == 404
    assert client.post('/cs/crm/contact/%d/family/remove' % mine.person_id,
                       data={'member_id': hidden.person_id}).status_code == 404
    # the family search box never offers a hidden person
    t = words(client.get('/cs/crm/contact/%d?fq=Otherwoman' % mine.person_id).get_data(as_text=True))
    assert 'Otherwoman' not in t


# ====================================================================================== records on the site

def _site(user=None):
    today = date.today()
    q = InsuranceQuote(email='ravi@example.com', phone='+919000000555', insurance_type='visitors', citizenship='IND',
                       start_date=today + timedelta(days=9), end_date=today + timedelta(days=40), status='quoted',
                       travellers=[{'age': '62'}])
    other_q = InsuranceQuote(email='someone@else.com', phone='+919000000777', insurance_type='health',
                             citizenship='IND', start_date=today, end_date=today + timedelta(days=3),
                             travellers=[])
    b = SahayakBooking(service_key='lab_work', service_name='Lab Work', patient_name='Lakshmi',
                       phone='+91 90000 00555', address='12 Green Park', when_type='asap')
    m = ContactMessage(name='Ravi', email='RAVI@example.com', message='please call me back', topic='general')
    _db.session.add_all([q, other_q, b, m])
    trip = None
    if user is not None:
        trip = CompanionRequest(user_id=user.id, travel_type='air', trip_type='one_way', source='organic',
                                flying_from='Hyderabad (HYD)', destination='Dallas (DFW)',
                                from_date=today + timedelta(days=30))
        trip.set_status('open')
        _db.session.add(trip)
    _db.session.commit()
    return q, other_q, b, m, trip


def test_the_contact_page_lists_every_record_and_links_to_that_record(app, client, agent, admin_user):
    site_user = make_user('ravi@example.com', 'ravi')
    p = person('Ravi Rao', '+919000000555', email='ravi@example.com', user_id=site_user.id)
    q, other_q, b, m, trip = _site(site_user)
    login(client, agent.email)
    html = client.get('/cs/crm/contact/%d' % p.id).get_data(as_text=True)
    t = words(html)
    assert 'Records on the site' in t
    for label in ('Insurance quote request', 'Sahayak booking', 'Contact message', 'Trip post', 'Site account'):
        assert label in t, label
    assert '/insurance-quotes?id=%d' % q.id in html and '/sahayak?id=%d' % b.id in html
    assert '/voices?tab=contact&amp;id=%d' % m.id in html
    assert '/posts/%d' % trip.id in html
    assert 'id=%d' % other_q.id not in html                       # somebody else's request is not theirs


def test_the_list_pages_open_filtered_to_one_record(app, client, agent, admin_user):
    q, other_q, b, m, _ = _site()
    login(client, agent.email)
    html = client.get('/cs/insurance-quotes?id=%d' % q.id).get_data(as_text=True)
    assert 'ravi@example.com' in html and 'someone@else.com' not in html and 'Showing one record' in html
    assert 'id="rec-%d"' % q.id in html
    html = client.get('/cs/sahayak?id=%d' % b.id).get_data(as_text=True)
    assert 'Lakshmi' in html and 'Showing one record' in html
    html = client.get('/cs/voices?tab=contact&id=%d' % m.id).get_data(as_text=True)
    assert 'please call me back' in html and 'Showing one record' in html
    # the admin copies take the same filter
    c = app.test_client()
    login(c, admin_user.email)
    html = c.get('/admin/insurance-quotes?id=%d' % q.id).get_data(as_text=True)
    assert 'ravi@example.com' in html and 'someone@else.com' not in html
    html = c.get('/admin/sahayak?id=%d' % b.id).get_data(as_text=True)
    assert 'Lakshmi' in html
    html = c.get('/admin/voices?tab=contact&id=%d' % m.id).get_data(as_text=True)
    assert 'please call me back' in html


def test_the_lead_pages_source_link_uses_the_same_helper(app, client, agent):
    q, *_ = _site()
    l = crm.capture('ti-quote', name='Ravi Rao', phone='+919000000555', email='ravi@example.com', utm={},
                    ref=('insurance_quotes', q.id))
    _db.session.commit()
    login(client, agent.email)
    html = client.get('/cs/crm/lead/%d' % l.id).get_data(as_text=True)
    assert '/insurance-quotes?id=%d' % q.id in html


def test_the_records_card_skips_records_that_only_a_hidden_enquiry_points_to(app, client):
    asha = staff('asha2@test.com', 'asha2', scope='own')
    bela = staff('bela2@test.com', 'bela2')
    mine = lead_for('Mixed Records', '+919000000888', asha)
    q_hidden = InsuranceQuote(email='nobody@elsewhere.com', phone='+919111111111', insurance_type='health',
                              citizenship='IND', start_date=date.today(), end_date=date.today() + timedelta(days=3),
                              travellers=[])
    _db.session.add(q_hidden)
    _db.session.commit()
    second = crm.capture('sh-booking', name='Mixed Records', phone='+919000000888', product='SH', utm={},
                         ref=('insurance_quotes', q_hidden.id))
    assert second.person_id == mine.person_id and second.id != mine.id
    second.owner_id = bela.id
    _db.session.commit()
    login(client, asha.email)
    html = client.get('/cs/crm/contact/%d' % mine.person_id).get_data(as_text=True)
    assert 'insurance-quotes?id=%d' % q_hidden.id not in html      # found only through the enquiry she cannot see
    assert 'Records on the site' in html
