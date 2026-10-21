"""Sales CRM 2.0, run 5b -- "OK to send offers" (CrmPerson.consent_marketing).

    contact    the contact page's switch, with when and how it was given or taken back (and History says so)
    forms      a public form's own offers tick sets it; the WhatsApp tick never does, and the other way round
    lists      the downloads carry it; the report builder filters and groups by it
    broadcasts the framed Broadcasts page has one line about it (the WhatsApp CRM itself is not changed)
    merge      given on either is kept; a "no" said on either always stays
"""
import csv
import io
import re

import pytest
from flask import g

from conftest import login, logout, make_user
from app import db as _db
from app.models import CrmAudit, CrmLead, CrmPerson
from app.services import crm, crm_consent, crm_merge, crm_report_builder as rb

from test_crm_wa_sync_engine import ti_lead


def words(html):
    import html as _html
    return _html.unescape(re.sub(r'\s+', ' ', re.sub(r'<script.*?</script>|<[^>]+>', ' ', html, flags=re.S)))


def fresh(pid):
    _db.session.expire_all()
    return _db.session.get(CrmPerson, pid)


def test_the_contact_page_switch_keeps_when_and_how(app, client, admin_user):
    crm.ensure_defaults()
    lead = ti_lead(name='Offer Olga')
    pid = lead.person_id
    login(client, admin_user.email)
    page = words(client.get('/admin/crm/contact/%d' % pid).get_data(as_text=True))
    assert 'OK to send offers' in page and 'Not given' in page
    client.post('/admin/crm/contact/%d/offers' % pid, data={'on': '1'})
    p = fresh(pid)
    assert p.consent_marketing is True and p.consent_marketing_at is not None
    assert p.consent_marketing_how == 'contact page' and p.consent_marketing_by_id == admin_user.id
    assert p.consent_whatsapp is False                               # never the WhatsApp permission
    page = words(client.get('/admin/crm/contact/%d' % pid).get_data(as_text=True))
    assert re.search(r'Given \d+ \w{3} \d{4} · on the contact page, by Admin', page)
    client.post('/admin/crm/contact/%d/offers' % pid, data={'on': '0'})
    p = fresh(pid)
    assert p.consent_marketing is False and crm_consent.withdrawn(p)
    assert 'Not given · taken back' in words(client.get('/admin/crm/contact/%d' % pid).get_data(as_text=True))
    rows = CrmAudit.query.filter_by(record_type='person', record_id=pid, field='consent_marketing').all()
    assert [(r.old, r.new) for r in rows] == [('0', '1'), ('1', '0')]
    assert 'permission to send offers' in words(client.get('/admin/crm/contact/%d' % pid).get_data(as_text=True))


def test_an_agent_who_cannot_see_the_person_cannot_switch_it(app, client):
    from app.services import access
    from app.models import WorkspaceRole
    ws = access.ensure_defaults()
    crm.ensure_defaults()
    own = make_user('own@test.com', 'own', role='cs')
    role = WorkspaceRole(workspace_id=ws.id, name='Own only', pages=sorted(access.CS_ROLE_PAGES), crm_scope='own')
    _db.session.add(role)
    _db.session.flush()
    access.add_member(ws, own, role=role)
    other = make_user('oth@test.com', 'oth', role='cs')
    lead = ti_lead(name='Hidden Hema')
    lead.owner_id = other.id
    _db.session.commit()
    access._cache().clear()
    login(client, own.email)
    assert client.post('/cs/crm/contact/%d/offers' % lead.person_id, data={'on': '1'}).status_code == 404
    assert fresh(lead.person_id).consent_marketing is False


def test_a_forms_offers_tick_sets_it_and_the_whatsapp_tick_does_not(app, client):
    crm.ensure_defaults()
    r = client.post('/api/leads', json={'source': 'ti-quote', 'name': 'Tick Tara', 'phone': '+919800003001',
                                        'offers_consent': True})
    assert r.status_code == 201
    p = CrmPerson.query.filter_by(phone='+919800003001').one()
    assert p.consent_marketing is True and p.consent_whatsapp is False
    assert p.consent_marketing_how == 'form: lead form' and p.consent_marketing_by_id is None
    assert 'ticked on the form “lead form”' in crm_consent.line(p)
    assert any((t.body or '').startswith('OK to send offers') for t in p.leads[0].touchpoints)
    client.post('/api/leads', json={'source': 'ti-quote', 'name': 'Wa Wani', 'phone': '+919800003002', 'consent': True})
    q = CrmPerson.query.filter_by(phone='+919800003002').one()
    assert q.consent_whatsapp is True and q.consent_marketing is False
    # a form never takes it back: an enquiry without the tick leaves it given
    client.post('/api/leads', json={'source': 'ti-quote', 'name': 'Tick Tara', 'phone': '+919800003001'})
    assert fresh(p.id).consent_marketing is True
    js = open('app/static/js/lead-capture.js', encoding='utf-8').read()
    assert "'offers_consent'" in js


def test_the_downloads_carry_it(app, client, admin_user):
    crm.ensure_defaults()
    yes = ti_lead(phone='+919800003101', name='Yes Yamini')
    ti_lead(phone='+919800003102', name='No Nalini')
    crm_consent.set_offers(yes.person, True, crm_consent.HOW_PAGE, by=admin_user)
    _db.session.commit()
    login(client, admin_user.email)
    for url in ('/admin/crm/export/leads', '/admin/crm/export/contacts'):
        body = client.get(url).get_data(as_text=True).lstrip('﻿')
        rows = list(csv.reader(io.StringIO(body)))
        head = rows[0]
        assert head[-2:] == ['OK to send offers', 'Offers OK since'], url
        by_name = {r[0]: r for r in rows[1:]}
        assert by_name['Yes Yamini'][-2] == 'Yes' and by_name['Yes Yamini'][-1]
        assert by_name['No Nalini'][-2:] == ['No', '']


def test_the_report_builder_filters_and_groups_by_it(app, admin_user):
    crm.ensure_defaults()
    a = ti_lead(phone='+919800003201')
    ti_lead(phone='+919800003202')
    ti_lead(phone='+919800003203')
    crm_consent.set_offers(a.person, True, crm_consent.HOW_PAGE)
    _db.session.commit()
    run = lambda **kw: rb.run(rb.clean_config(kw), admin_user)
    assert run(what='leads', group='product', offers='yes')['total'] == 1
    assert run(what='leads', group='product', offers='no')['total'] == 2
    assert run(what='people', group='country', offers='yes')['total'] == 1
    table = {r['label']: r['total'] for r in run(what='people', group='offers')['rows']}
    assert table == {'OK to send offers': 1, 'Not OK to send offers': 2}
    with pytest.raises(rb.ReportError):
        rb.clean_config({'what': 'leads', 'offers': 'maybe'})
    assert rb.clean_config({'what': 'activities', 'offers': 'yes'})['offers'] == ''


def test_the_report_builder_page_has_the_filter(app, client, admin_user):
    crm.ensure_defaults()
    login(client, admin_user.email)
    page = client.get('/admin/crm/reports/build?what=people&run=1&group=offers&offers=yes').get_data(as_text=True)
    assert 'name="offers"' in page and 'OK to send offers' in words(page)


def test_broadcasts_says_only_send_offers_to_people_who_said_yes(app, client, admin_user):
    login(client, admin_user.email)
    page = words(client.get('/admin/messaging/broadcasts').get_data(as_text=True))
    assert "Only send offers to people with 'OK to send offers'." in page
    assert "Only send offers" not in words(client.get('/admin/messaging/templates').get_data(as_text=True))


def test_a_merge_keeps_a_yes_and_never_loses_a_no(app):
    crm.ensure_defaults()
    keep = ti_lead(phone='+919800003301', name='Keep Kavya').person
    other = ti_lead(phone='+919800003302', name='Other Kavya').person
    crm_consent.set_offers(other, True, crm_consent.HOW_FORM + 'Diwali offer')
    _db.session.commit()
    assert any('OK to send offers' in n for n in crm_merge.plan(keep, other)['notes'])
    crm_merge.merge(keep, other)
    k = fresh(keep.id)
    assert k.consent_marketing is True and k.consent_marketing_how == 'form: Diwali offer'
    # a "no" on either side stays
    k2 = ti_lead(phone='+919800003303', name='Keep Two').person
    o2 = ti_lead(phone='+919800003304', name='Other Two').person
    crm_consent.set_offers(k2, True, crm_consent.HOW_PAGE)
    crm_consent.set_offers(o2, True, crm_consent.HOW_PAGE)
    _db.session.commit()
    crm_consent.set_offers(o2, False, crm_consent.HOW_PAGE)
    _db.session.commit()
    assert any('“no” to offers stays' in n for n in crm_merge.plan(k2, o2)['notes'])
    crm_merge.merge(k2, o2)
    k2 = fresh(k2.id)
    assert k2.consent_marketing is False and crm_consent.withdrawn(k2)
