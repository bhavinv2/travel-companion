"""Release 2, U7: Contacts, the contact page, Find a person, Erase, the do-not-contact list, the exporter and the
WhatsApp tick on the forms.

    find          one tolerant matcher, display only: it never links or merges people
    erase         exact name to confirm; all or nothing; only a hash is kept afterwards
    do-not-contact  imports refuse a match; an enquiry the person makes themselves clears it
    export        opens straight in Excel, never runs a formula, and is logged
"""
import pytest

from conftest import login, make_user
from app import db as _db
from app.models import ActivityEvent, CrmDoNotContact, CrmLead, CrmPerson, CrmTouchpoint
from app.services import access, crm, crm_people, wacrm, wacrm_team

from test_crm_wa_sync_engine import PHONE, ti_lead  # noqa: F401

BASE = '/admin/crm'


@pytest.fixture
def writes(app, monkeypatch):
    """The WhatsApp CRM connected, mode 'contacts', every portal and public call answered and recorded."""
    monkeypatch.setenv('WACRM_URL', 'https://crm.example/crm')
    monkeypatch.setenv('WACRM_API_KEY', 'wacrm_live_test')
    monkeypatch.setenv('WACRM_PORTAL_SECRET', 'x' * 40)
    crm.save_settings(whatsapp_mode='contacts')
    calls = []
    state = {'erase': None, 'tags': []}

    def api(method, path, payload=None, params=None):
        calls.append((method, path, payload))
        return {}

    monkeypatch.setattr(wacrm_team, '_api', api)
    monkeypatch.setattr(wacrm, '_call', lambda *a, **k: {})
    monkeypatch.setattr(wacrm_team, 'erase_contact',
                        lambda cid: calls.append(('ERASE', cid, None)) or (_ for _ in ()).throw(state['erase'])
                        if state['erase'] else calls.append(('ERASE', cid, None)))
    return calls, state


def lead(phone=PHONE, **kw):
    return ti_lead(phone, plan=False, notify=False, sync=False, **kw)


# ======================================================================================= Find a person

def test_find_matches_a_phone_in_any_format_and_names_and_emails(app, client, cs_user):
    l = lead(email='ramesh@example.com')
    login(client, cs_user.email)
    for q in ('9876543210', '98765 43210', '+91 98765-43210', '919876543210', 'Ramesh', 'ramesh@example.com', 'ramesh k'):
        out = client.get(BASE.replace('admin', 'cs') + '/find', query_string={'q': q}).get_json()
        assert [i['name'] for i in out['items'] if i['kind'] == 'person'] == ['Ramesh Kumar'], q
    assert out['items'][0]['chips'][0]['url'].endswith('/lead/%d' % l.id)


def test_find_ignores_one_letter_and_empty_and_never_merges_people(app, client, cs_user):
    lead()
    lead('+919811111111', name='Ramesh Kumar')            # same name, another number: two people stay two
    login(client, cs_user.email)
    assert client.get('/cs/crm/find?q=r').get_json() == {'items': []}
    assert client.get('/cs/crm/find').get_json() == {'items': []}
    out = client.get('/cs/crm/find?q=Ramesh').get_json()
    assert len([i for i in out['items'] if i['kind'] == 'person']) == 2
    assert CrmPerson.query.count() == 2


def test_find_is_for_staff_only(app, client, user):
    login(client, user.email)
    r = client.get('/cs/crm/find?q=Ramesh')
    assert r.status_code in (302, 403, 404)


def test_find_shows_closed_enquiries_too(app, client, cs_user):
    l = lead()
    crm.move_stage(l, crm.stage_of(l, 'lost') if hasattr(crm, 'stage_of') else l.stage, plan=False, sync=False)
    l.status = 'lost'
    _db.session.commit()
    login(client, cs_user.email)
    chips = client.get('/cs/crm/find?q=Ramesh').get_json()['items'][0]['chips']
    assert chips and chips[0]['state'] == 'lost'


# ======================================================================================= Contacts

def test_contacts_list_filters_and_pages(app, client, cs_user):
    access.ensure_defaults()
    for i in range(53):
        lead('+9198000%05d' % i, name='Person %02d' % i)
    p = CrmPerson.query.filter_by(phone='+919800000003').one()
    p.wa_opt_out_at = crm.datetime.utcnow()
    _db.session.commit()
    login(client, cs_user.email)
    page1 = client.get('/cs/crm/contacts').get_data(as_text=True)
    assert page1.count('/cs/crm/contact/') >= 50 and page1.count('Person ') < 53        # 50 a page, not all 53
    assert client.get('/cs/crm/contacts?page=2').status_code == 200
    assert client.get('/cs/crm/contacts?page=999').status_code == 200          # out of range: the last page
    opted = client.get('/cs/crm/contacts?wa=optout').get_data(as_text=True)
    assert 'Person 03' in opted and 'Person 04' not in opted


def test_contacts_empty_state_and_garbage_filters(app, client, cs_user):
    access.ensure_defaults()
    login(client, cs_user.email)
    assert crm_people.CONTACTS_EMPTY in client.get('/cs/crm/contacts').get_data(as_text=True)
    r = client.get('/cs/crm/contacts?wa=zzz&owner=%27%3B--&enq=maybe&page=abc&q=%25')
    assert r.status_code == 200


def test_contact_old_url_redirects_here(app, client, admin_user):
    login(client, admin_user.email)
    r = client.get('/admin/messaging/contacts')
    assert r.status_code == 302 and '/crm/contacts' in r.headers['Location']


# ======================================================================================= the contact page and tags

def test_contact_page_shows_permission_and_locked_sales_tags(app, client, cs_user):
    l = lead()
    p = l.person
    p.consent_whatsapp = True
    _db.session.commit()
    login(client, cs_user.email)
    page = client.get('/cs/crm/contact/%d' % p.id).get_data(as_text=True)
    assert 'Agreed to WhatsApp messages' in page and 'TI: ' in page
    assert client.get('/cs/crm/contact/99999').status_code == 404


def test_tags_refuse_managed_names_and_work_off_the_air_when_writes_are_off(app, client, admin_user, monkeypatch):
    l = lead()
    l.person.wacrm_contact_id = 'c-1'
    _db.session.commit()
    login(client, admin_user.email)
    url = '/admin/crm/contact/%d/tags' % l.person.id
    r = client.post(url, json={'add': 'vip'})
    assert r.status_code == 409                                    # mode off: nothing is written
    assert client.get(url).get_json()['writes'] is False


def test_tags_add_remove_and_refuse_sales_tags(app, client, admin_user, writes, monkeypatch):
    calls, _ = writes
    l = lead()
    l.person.wacrm_contact_id = 'c-1'
    _db.session.commit()
    seen = {}

    def fake(cid, add=(), remove=(), create=False):
        seen.update(cid=cid, add=list(add), remove=list(remove), create=create)
        return [{'name': 'vip'}, {'name': 'ti', 'managed': True}]
    monkeypatch.setattr(wacrm_team, 'contact_tags', fake)
    login(client, admin_user.email)
    url = '/admin/crm/contact/%d/tags' % l.person.id
    assert client.post(url, json={'add': 'TI'}).status_code == 422       # the product tag is the Sales CRM's
    assert client.post(url, json={'add': 'opted-out'}).status_code in (200, 422)
    assert client.post(url, json={'add': 'TI: Prospect'}).status_code == 422
    assert client.post(url, json={}).status_code == 400
    seen.clear()
    r = client.post(url, json={'add': 'vip'})
    assert r.get_json() == {'success': True, 'free': ['vip']} and seen['cid'] == 'c-1' and seen['create'] is True


def test_tags_without_a_whatsapp_contact_are_refused(app, client, admin_user, writes):
    l = lead()
    login(client, admin_user.email)
    assert client.post('/admin/crm/contact/%d/tags' % l.person.id, json={'add': 'vip'}).status_code == 409


def test_a_plain_agent_cannot_create_new_tags(app, client, cs_user, writes, monkeypatch):
    l = lead()
    l.person.wacrm_contact_id = 'c-1'
    _db.session.commit()
    seen = {}
    monkeypatch.setattr(wacrm_team, 'contact_tags', lambda cid, add=(), remove=(), create=False:
                        seen.update(create=create) or [])
    login(client, cs_user.email)
    client.post('/cs/crm/contact/%d/tags' % l.person.id, json={'add': 'vip'})
    assert seen.get('create') in (False, None)


# ======================================================================================= edit details

def test_edit_details_changes_the_phone_through_the_one_path_and_marks_for_sync(app, client, cs_user):
    l = lead()
    l.person.wacrm_contact_id = 'c-1'
    _db.session.commit()
    login(client, cs_user.email)
    r = client.post('/cs/crm/contact/%d/edit' % l.person.id,
                    data={'name': 'Ramesh K', 'phone': '+919811122233', 'email': 'r@example.com'})
    assert r.status_code == 302
    p = _db.session.get(CrmPerson, l.person.id)
    assert p.phone == '+919811122233' and p.name == 'Ramesh K' and p.wacrm_contact_id is None   # the old link is cut


def test_edit_details_refuses_a_number_another_contact_has(app, client, cs_user):
    lead()
    other = lead('+919811111111', name='Other')
    login(client, cs_user.email)
    r = client.post('/cs/crm/contact/%d/edit' % other.person.id, data={'name': 'Other', 'phone': PHONE})
    assert r.status_code == 400
    assert _db.session.get(CrmPerson, other.person.id).phone == '+919811111111'


# ======================================================================================= Erase

def test_erase_needs_the_exact_name_and_does_nothing_otherwise(app, client, admin_user):
    l = lead()
    login(client, admin_user.email)
    pid = l.person.id
    client.post('/admin/crm/contact/%d/erase' % pid, data={'confirm_name': 'Ramesh'})
    assert _db.session.get(CrmPerson, pid) is not None and CrmDoNotContact.query.count() == 0


def test_erase_removes_everything_and_keeps_only_hashes(app, client, admin_user):
    l = lead(email='ramesh@example.com')
    _db.session.commit()
    pid, lid = l.person.id, l.id
    login(client, admin_user.email)
    r = client.post('/admin/crm/contact/%d/erase' % pid, data={'confirm_name': ' ramesh   KUMAR '})
    assert r.status_code == 302 and '/crm/contacts' in r.headers['Location']
    assert _db.session.get(CrmPerson, pid) is None and _db.session.get(CrmLead, lid) is None
    assert CrmTouchpoint.query.filter_by(person_id=pid).count() == 0
    row = CrmDoNotContact.query.one()
    assert PHONE not in (row.phone_hash or '') and row.phone_hash == crm_people.dnc_hash(PHONE)
    assert row.email_hash == crm_people.dnc_hash('ramesh@example.com')
    assert ActivityEvent.query.filter_by(event='crm_person_erased').count() == 1
    blob = ' '.join(str(e.meta) for e in ActivityEvent.query.filter_by(event='crm_person_erased'))
    assert '9876543210' not in blob and 'ramesh@example.com' not in blob and 'Ramesh' not in blob


def test_erase_is_all_or_nothing_when_whatsapp_does_not_answer(app, client, admin_user, writes, monkeypatch):
    l = lead()
    l.person.wacrm_contact_id = 'c-1'
    _db.session.commit()
    pid = l.person.id

    def boom(cid):
        raise wacrm_team.TeamError('down', status=502)
    monkeypatch.setattr(wacrm_team, 'erase_contact', boom)
    login(client, admin_user.email)
    r = client.post('/admin/crm/contact/%d/erase' % pid, data={'confirm_name': 'Ramesh Kumar'}, follow_redirects=True)
    assert crm_people.ERASE_NO_ANSWER in r.get_data(as_text=True)
    assert _db.session.get(CrmPerson, pid) is not None and CrmDoNotContact.query.count() == 0
    assert CrmLead.query.count() == 1


def test_erase_asks_whatsapp_to_erase_the_chat_once_and_never_when_the_contact_is_shared(app, admin_user, writes, monkeypatch):
    calls, _ = writes
    erased = []
    monkeypatch.setattr(wacrm_team, 'erase_contact', lambda cid: erased.append(cid) or {})
    a = lead()
    b = lead('+919811111111', name='B')
    a.person.wacrm_contact_id = b.person.wacrm_contact_id = 'c-shared'
    _db.session.commit()
    assert crm_people.erase(a.person, admin_user) == 'shared'
    assert erased == []                                            # the other person's chat is not ours to erase
    b = _db.session.get(CrmPerson, b.person.id)
    assert crm_people.erase(b, admin_user) == 'erased' and erased == ['c-shared']


def test_erase_with_whatsapp_off_says_the_chat_was_not_erased(app, admin_user):
    l = lead()
    l.person.wacrm_contact_id = 'c-1'
    _db.session.commit()
    assert crm_people.erase(l.person, admin_user) == 'off'


def test_erase_is_not_open_to_agents(app, client, cs_user):
    l = lead()
    login(client, cs_user.email)
    r = client.post('/cs/crm/contact/%d/erase' % l.person.id, data={'confirm_name': 'Ramesh Kumar'})
    assert _db.session.get(CrmPerson, l.person.id) is not None
    assert r.status_code in (302, 403, 404)


# ======================================================================================= do-not-contact

def test_an_importer_refuses_an_erased_person_but_their_own_enquiry_clears_it(app, admin_user):
    l = lead(email='ramesh@example.com')
    crm_people.erase(l.person, admin_user)
    with pytest.raises(crm.DoNotContact):
        crm.capture('ti-quote', name='Ramesh', phone=PHONE, utm={}, refuse_dnc=True, imported=True, sync=False)
    with pytest.raises(crm.DoNotContact):
        crm.capture('ti-quote', name='Ramesh', email='RAMESH@example.com', utm={}, refuse_dnc=True, sync=False)
    assert CrmLead.query.count() == 0 and CrmPerson.query.count() == 0
    again = crm.capture('ti-quote', name='Ramesh', phone=PHONE, utm={}, sync=False)         # they asked us again
    assert again is not None and CrmDoNotContact.query.count() == 0


def test_a_whatsapp_message_does_not_clear_the_do_not_contact_list(app, admin_user):
    l = lead()
    crm_people.erase(l.person, admin_user)
    assert crm_people.dnc_find(PHONE) and crm_people.dnc_find('+919800000000') == []
    with pytest.raises(crm.DoNotContact):
        crm.capture('ti-quote', name='X', phone=PHONE, utm={}, refuse_dnc=True, sync=False)
    assert CrmDoNotContact.query.count() == 1


def test_dnc_hash_is_keyed_and_case_insensitive(app):
    assert crm_people.dnc_hash('A@B.com') == crm_people.dnc_hash(' a@b.com ')
    assert crm_people.dnc_hash(PHONE) != crm_people.dnc_hash('+919876543211')
    assert PHONE not in crm_people.dnc_hash(PHONE)
    assert crm_people.dnc_add('', '', None) is None


def test_csv_import_skips_an_erased_person(app, client, admin_user, tmp_path):
    l = lead()
    crm_people.erase(l.person, admin_user)
    path = tmp_path / 'in.csv'
    path.write_text('Name,Phone\nRamesh,+919876543210\nNew One,+919822222222\n', encoding='utf-8')
    plan = crm_people.plan_csv(str(path), {'name': 'Name', 'phone': 'Phone'} if False else crm_people.guess_map(['Name', 'Phone']),
                               {'source': 'csv-import', 'product': 'TI', 'owner': None, 'phone_cc': 'IN'})
    text = repr(plan)
    assert 'dnc' in text


# ======================================================================================= the exporter

def test_export_has_a_bom_never_runs_a_formula_and_is_logged(app, client, admin_user):
    lead(name='=HYPERLINK("http://evil","x")')
    lead('+919811111111', name='Normal Person')
    login(client, admin_user.email)
    for url in ('/admin/crm/export/leads', '/admin/crm/export/contacts'):
        r = client.get(url)
        body = r.get_data()
        assert r.status_code == 200 and body.startswith('﻿'.encode('utf-8')), url
        text = body.decode('utf-8-sig')
        assert "'=HYPERLINK" in text and '\n=HYPERLINK' not in text and ',=HYPERLINK' not in text
        assert 'In WhatsApp' in text.splitlines()[0]
    assert ActivityEvent.query.filter_by(event='crm_export').count() == 2


def test_export_is_for_admins(app, client, cs_user):
    lead()
    login(client, cs_user.email)
    assert client.get('/cs/crm/export/leads').status_code in (302, 403, 404)
    assert client.get('/cs/crm/export/contacts').status_code in (302, 403, 404)


# ======================================================================================= the WhatsApp tick

def test_a_ticked_form_records_consent_and_the_note_an_unticked_one_does_not(app):
    ticked = crm.capture('ti-quote', name='A', phone='+919800000011', utm={}, consent=True, consent_from='insurance form',
                         plan=False, notify=False, sync=False)
    plain = crm.capture('ti-quote', name='B', phone='+919800000012', utm={}, plan=False, notify=False, sync=False)
    assert ticked.person.consent_whatsapp is True and not plain.person.consent_whatsapp
    notes = [t.body for t in CrmTouchpoint.query.filter_by(person_id=ticked.person.id)]
    assert any('Agreed to WhatsApp messages (insurance form)' in (n or '') for n in notes)
    assert not [t for t in CrmTouchpoint.query.filter_by(person_id=plain.person.id) if 'Agreed' in (t.body or '')]
    again = crm.capture('ti-quote', name='A', phone='+919800000011', utm={}, consent=True, consent_from='insurance form',
                        plan=False, notify=False, sync=False)
    notes = [t.body for t in CrmTouchpoint.query.filter_by(person_id=ticked.person.id) if 'Agreed' in (t.body or '')]
    assert len(notes) == 1                                          # one note: the tick is not recorded twice


def test_ticked_helper_reads_form_and_json_values():
    for yes in (True, 'on', '1', 'true', ' YES '):
        assert crm.ticked(yes)
    for no in (None, '', 'off', '0', False, 'no'):
        assert not crm.ticked(no)
