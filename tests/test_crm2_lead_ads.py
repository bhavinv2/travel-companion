"""Sales CRM 2.0, run 4b -- lead-ad connectors.

    meta     the Page's `leadgen` event on /api/crm/meta-webhook: the lead is fetched (stubbed here: nothing calls out in
             tests), mapped, and captured under source meta-form-<form id> -- unrouted until an admin routes it;
             idempotent on the leadgen id
    google   POST /api/crm/google-leads: 404 while CRM_GOOGLE_LEADS_KEY is unset, 403 for a wrong key, test leads answered
             and not stored, idempotent on lead_id
    help     Lead sources links to the Integrations cards, which explain the Meta permission (leads_retrieval) and
             the webhook field (leadgen)
"""
import hashlib
import hmac
import json
import re

import pytest
import requests

from conftest import login, make_user
from app import csrf, db as _db
from app.models import CrmLead, CrmPerson, CrmSource, CrmTouchpoint
from app.services import crm, crm_lead_ads, meta

KEY = 'google-key-123'


@pytest.fixture(autouse=True)
def no_outside_calls(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError('a test tried to call an outside service')
    monkeypatch.setattr(requests, 'request', refuse)
    monkeypatch.setattr(requests, 'get', refuse)
    monkeypatch.setattr(requests, 'post', refuse)


@pytest.fixture
def meta_keys(monkeypatch):
    monkeypatch.setenv('META_APP_SECRET', 'appsecret')
    monkeypatch.setenv('META_PAGE_TOKEN', 'pagetoken')
    monkeypatch.setenv('META_VERIFY_TOKEN', 'verify-me')


def meta_post(client, payload, secret='appsecret'):
    raw = json.dumps(payload).encode()
    sig = 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post('/api/crm/meta-webhook', data=raw, headers={'X-Hub-Signature-256': sig, 'Content-Type': 'application/json'})


def leadgen(leadgen_id='L100', form_id='F55', ad_id='AD9'):
    return {'object': 'page', 'entry': [{'id': 'PAGE', 'time': 1, 'changes': [{'field': 'leadgen', 'value': {
        'leadgen_id': leadgen_id, 'form_id': form_id, 'ad_id': ad_id, 'page_id': 'PAGE', 'created_time': 1}}]}]}


FETCHED = {'created_time': '2026-10-20T10:00:00+0000', 'ad_id': 'AD9', 'form_id': 'F55', 'campaign_name': 'Diwali offer',
           'field_data': [{'name': 'full_name', 'values': ['Meena Joshi']}, {'name': 'email', 'values': ['meena@example.com']},
                          {'name': 'phone_number', 'values': ['+919876543210']},
                          {'name': 'travelling_to', 'values': ['Canada']}, {'name': 'parent_age', 'values': ['68']}]}


@pytest.fixture
def fetched(monkeypatch):
    calls = []

    def fake(leadgen_id):
        calls.append(leadgen_id)
        return dict(FETCHED)
    monkeypatch.setattr(meta, 'fetch_lead', fake)
    return calls


# ====================================================================================== Facebook and Instagram

def test_a_leadgen_event_becomes_an_unrouted_lead(app, client, meta_keys, fetched):
    r = meta_post(client, leadgen())
    assert r.status_code == 200 and r.get_json()['stored'] == 1 and fetched == ['L100']
    lead = CrmLead.query.one()
    assert lead.source.key == 'meta-form-f55' and lead.source.name == 'Facebook/Instagram form f55'
    assert lead.source.status == 'unrouted' and lead.pipeline_id is None and lead.stage_id is None
    assert lead.person.name == 'Meena Joshi' and lead.person.email == 'meena@example.com'
    assert lead.person.phone == '+919876543210'
    assert lead.utm == {'ad_id': 'AD9', 'form_id': 'F55', 'campaign': 'Diwali offer'}
    assert lead.details == {'travelling to': 'Canada', 'parent age': '68'}
    first = CrmTouchpoint.query.filter_by(lead_id=lead.id, direction='in').one()
    assert first.channel == 'form' and first.external_id == 'meta-lead-L100'
    assert not lead.tasks                                        # unrouted: no follow-up, nobody is messaged


def test_a_repeat_delivery_is_not_stored_twice(app, client, meta_keys, fetched):
    meta_post(client, leadgen())
    again = meta_post(client, leadgen())
    assert again.status_code == 200 and again.get_json()['stored'] == 0
    _db.session.expire_all()
    assert CrmLead.query.count() == 1 and CrmTouchpoint.query.filter_by(external_id='meta-lead-L100').count() == 1
    assert fetched == ['L100']                                    # the second one never even asked Meta


def test_first_and_last_name_are_joined_and_a_missing_name_is_fine(app, client, meta_keys, monkeypatch):
    monkeypatch.setattr(meta, 'fetch_lead', lambda i: {'form_id': 'F1', 'field_data': [
        {'name': 'first_name', 'values': ['Anil']}, {'name': 'last_name', 'values': ['Kapoor']},
        {'name': 'phone_number', 'values': ['9876501234']}]})
    meta_post(client, leadgen('L1', 'F1'))
    assert CrmPerson.query.one().name == 'Anil Kapoor'


def test_a_lead_with_no_way_to_reach_them_is_left_out(app, client, meta_keys, monkeypatch):
    monkeypatch.setattr(meta, 'fetch_lead', lambda i: {'field_data': [{'name': 'full_name', 'values': ['Nobody']}]})
    r = meta_post(client, leadgen('L2'))
    assert r.status_code == 200 and CrmLead.query.count() == 0


def test_when_meta_cannot_be_asked_the_delivery_is_still_answered_ok(app, client, meta_keys, monkeypatch):
    def down(i):
        raise meta.MetaError('Meta could not be reached.')
    monkeypatch.setattr(meta, 'fetch_lead', down)
    r = meta_post(client, leadgen('L3'))
    assert r.status_code == 200 and r.get_json() == {'ok': True, 'stored': 0}
    assert CrmLead.query.count() == 0


def test_the_unsigned_delivery_is_still_refused(app, client, meta_keys, fetched):
    assert meta_post(client, leadgen(), secret='wrong').status_code == 401
    assert fetched == [] and CrmLead.query.count() == 0


def test_messages_and_a_lead_form_in_one_delivery_both_work(app, client, meta_keys, fetched, monkeypatch):
    monkeypatch.setattr(meta, 'profile', lambda sid, ch: {'name': 'Anita Rao', 'username': 'anita.rao'})
    payload = leadgen()
    payload['entry'][0]['messaging'] = [{'sender': {'id': 'IG1'}, 'message': {'mid': 'm1', 'text': 'Hello there'}}]
    r = meta_post(client, payload)
    assert r.get_json()['stored'] == 2 and CrmLead.query.count() == 2


def test_once_an_admin_routes_the_form_its_next_leads_start_that_pipeline(app, client, meta_keys, monkeypatch):
    crm.ensure_defaults()
    from app.models import CrmPipeline
    monkeypatch.setattr(meta, 'fetch_lead', lambda i: {**FETCHED, 'field_data': [
        {'name': 'full_name', 'values': ['Routed Rita']}, {'name': 'phone_number', 'values': ['+919876540001']}]})
    meta_post(client, leadgen('A1'))
    src = CrmSource.query.filter_by(key='meta-form-f55').one()
    pipe = CrmPipeline.query.first()
    src.pipeline_id, src.status = pipe.id, 'live'
    _db.session.commit()
    monkeypatch.setattr(meta, 'fetch_lead', lambda i: {**FETCHED, 'field_data': [
        {'name': 'full_name', 'values': ['Second Sita']}, {'name': 'phone_number', 'values': ['+919876540002']}]})
    meta_post(client, leadgen('A2'))
    _db.session.expire_all()
    first, second = CrmLead.query.order_by(CrmLead.id).all()
    assert first.pipeline_id is None and second.pipeline_id == pipe.id


def test_the_fetch_asks_the_graph_api_for_the_lead_with_the_page_token(app, monkeypatch, meta_keys):
    seen = {}

    class R:
        status_code = 200

        def json(self):
            return {'field_data': []}

    def fake(method, url, params=None, json=None, timeout=None):
        seen.update(method=method, url=url, params=params)
        return R()
    monkeypatch.setattr(requests, 'request', fake)
    assert meta.fetch_lead('L77') == {'field_data': []}
    assert seen['method'] == 'GET' and seen['url'].endswith('/L77') and seen['params']['access_token'] == 'pagetoken'
    assert 'field_data' in seen['params']['fields']


# ====================================================================================== Google

def google(client, body, key=KEY, **kw):
    return client.post('/api/crm/google-leads', data=json.dumps({'google_key': key, **body}), content_type='application/json', **kw)


def glead(lead_id='GL1', form_id='4321', **extra):
    return {'lead_id': lead_id, 'form_id': form_id, 'campaign_id': 777, 'gcl_id': 'gclid-abc', 'is_test': False,
            'user_column_data': [{'column_id': 'FULL_NAME', 'column_name': 'Full Name', 'string_value': 'Gita Menon'},
                                 {'column_id': 'EMAIL', 'column_name': 'User Email', 'string_value': 'gita@example.com'},
                                 {'column_id': 'PHONE_NUMBER', 'column_name': 'User Phone', 'string_value': '+919876543299'},
                                 {'column_id': 'QUESTION_1', 'column_name': 'Which country?', 'string_value': 'USA'}], **extra}


def test_the_google_door_is_not_found_while_its_key_is_unset(app, client, monkeypatch):
    monkeypatch.delenv('CRM_GOOGLE_LEADS_KEY', raising=False)
    assert google(client, glead()).status_code == 404


def test_a_wrong_or_missing_key_is_refused(app, client, monkeypatch):
    monkeypatch.setenv('CRM_GOOGLE_LEADS_KEY', KEY)
    assert google(client, glead(), key='nope').status_code == 403
    assert client.post('/api/crm/google-leads', data=json.dumps(glead()), content_type='application/json').status_code == 403
    assert client.post('/api/crm/google-leads', data='not json', content_type='application/json').status_code == 400
    assert client.get('/api/crm/google-leads').status_code == 405
    assert CrmLead.query.count() == 0


def test_the_key_is_compared_in_constant_time(app, client, monkeypatch):
    monkeypatch.setenv('CRM_GOOGLE_LEADS_KEY', KEY)
    seen = []
    real = hmac.compare_digest
    monkeypatch.setattr(crm_lead_ads.hmac, 'compare_digest', lambda a, b: (seen.append((a, b)), real(a, b))[1])
    google(client, glead('K1'))
    assert seen and seen[0][1] == KEY.encode()


def test_a_google_lead_is_stored_unrouted_with_its_answers(app, client, monkeypatch):
    monkeypatch.setenv('CRM_GOOGLE_LEADS_KEY', KEY)
    r = google(client, glead())
    assert r.status_code == 200 and r.get_json()['result'] == 'stored'
    lead = CrmLead.query.one()
    assert lead.source.key == 'google-form-4321' and lead.source.name == 'Google Ads form 4321'
    assert lead.source.status == 'unrouted' and lead.pipeline_id is None
    assert lead.person.name == 'Gita Menon' and lead.person.email == 'gita@example.com' and lead.person.phone == '+919876543299'
    assert lead.details == {'Which country?': 'USA'}
    assert lead.utm == {'form_id': '4321', 'campaign': '777', 'gclid': 'gclid-abc'}
    assert CrmTouchpoint.query.filter_by(lead_id=lead.id, external_id='google-lead-GL1').count() == 1


def test_a_google_test_lead_is_answered_and_not_stored(app, client, monkeypatch):
    monkeypatch.setenv('CRM_GOOGLE_LEADS_KEY', KEY)
    r = google(client, glead('T1', is_test=True))
    assert r.status_code == 200 and r.get_json()['result'] == 'test'
    assert CrmLead.query.count() == 0 and CrmPerson.query.count() == 0 and CrmSource.query.count() == 0


def test_a_google_repeat_is_not_stored_twice(app, client, monkeypatch):
    monkeypatch.setenv('CRM_GOOGLE_LEADS_KEY', KEY)
    google(client, glead())
    r = google(client, glead())
    assert r.status_code == 200 and r.get_json()['result'] == 'seen'
    assert CrmLead.query.count() == 1 and CrmTouchpoint.query.filter_by(external_id='google-lead-GL1').count() == 1


def test_a_google_lead_with_no_contact_is_ignored(app, client, monkeypatch):
    monkeypatch.setenv('CRM_GOOGLE_LEADS_KEY', KEY)
    body = glead('NC1')
    body['user_column_data'] = [{'column_id': 'FULL_NAME', 'string_value': 'Just A Name'}]
    assert google(client, body).get_json()['result'] == 'ignored' and CrmLead.query.count() == 0


def test_both_doors_are_public_like_the_other_webhooks(app):
    from app.routes import crm_lead_ads as route, crm_quotes
    assert any(k.endswith('google_leads') for k in csrf._exempt_views) and any(k.endswith('payment_webhook') for k in csrf._exempt_views)


# ====================================================================================== the help box

def test_lead_sources_explains_what_to_set_up(app, client, admin_user, monkeypatch):
    """Lead sources says what happens to an ad form's leads and links to the two cards under Integrations, which say
    how to connect them (one home for the how-to)."""
    monkeypatch.delenv('CRM_GOOGLE_LEADS_KEY', raising=False)
    login(client, admin_user.email)

    def text(url):
        return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', client.get(url).get_data(as_text=True)))
    page = text('/admin/crm/sources')
    assert 'Lead ads' in page and 'Not switched on' in page
    html = client.get('/admin/crm/sources').get_data(as_text=True)
    assert '/admin/crm/integrations/meta' in html and '/admin/crm/integrations/google' in html
    meta_card = text('/admin/crm/integrations/meta?tab=install')
    assert 'leads_retrieval' in meta_card and 'leadgen' in meta_card and '/api/crm/meta-webhook' in meta_card
    google_card = text('/admin/crm/integrations/google?tab=install')
    assert '/api/crm/google-leads' in google_card and 'CRM_GOOGLE_LEADS_KEY' in google_card
    monkeypatch.setenv('CRM_GOOGLE_LEADS_KEY', KEY)
    assert 'Ready' in text('/admin/crm/sources') and 'Ready' in text('/admin/crm/integrations/google')
    for url in ('/admin/crm/sources', '/admin/crm/integrations/google?tab=install', '/admin/crm/integrations/google?tab=settings'):
        assert KEY not in client.get(url).get_data(as_text=True)          # the key itself is never shown
