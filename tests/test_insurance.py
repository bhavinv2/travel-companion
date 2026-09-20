"""Travel-insurance quote endpoint: validation, per-product partner payloads, and the lead row.

The partner call is stubbed everywhere — these tests must never reach the network. The payload
assertions are the regression guard that matters: each product needs its own section/coverage
pair, and sending the wrong one makes the partner answer with an HTML error page, not JSON.
"""
import json
import urllib.request
from datetime import date, timedelta

import pytest

from conftest import login
from app.models import InsuranceQuote

START = (date.today() + timedelta(days=10)).isoformat()
END = (date.today() + timedelta(days=40)).isoformat()


def payload(**over):
    body = {'start_date': START, 'end_date': END, 'citizenship': 'IND',
            'travellers': [{'name': 'Ramesh Kumar', 'age': '65'},
                           {'name': 'Lakshmi Kumar', 'age': '62'}],
            'insurance_type': 'visitors', 'email': 'ramesh@example.com',
            'phone': '+91 98765 43210'}
    body.update(over)
    return body


class _Resp:
    def __init__(self, data):
        self._data = json.dumps(data).encode()

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def partner(monkeypatch):
    """Stub the partner API and record what we sent it."""
    sent = {}

    def fake_urlopen(req, timeout=None):
        sent['url'] = req.full_url
        sent['referer'] = req.headers.get('Referer')
        sent['body'] = json.loads(req.data.decode())
        if sent.get('fail'):
            raise OSError('partner down')
        return _Resp({'status': 'success', 'data': {'redirectToBN': '/retrieve-insurance-quotes/?id=42'}})

    monkeypatch.setattr(urllib.request, 'urlopen', fake_urlopen)
    return sent


def test_visitors_quote_sends_partner_params_and_stores_lead(client, db, partner):
    r = client.post('/api/insurance-quote', json=payload())
    assert r.get_json()['success']
    assert r.get_json()['url'].endswith('/retrieve-insurance-quotes/?id=42')

    body = partner['body']
    assert body['section'] == 'visitorUSA'
    assert body['coverageArea'] == '5'
    assert body['primaryDestination'] == 'USA'
    assert [t['age'] for t in body['travelerInfos']] == ['65', '62']
    assert 'visitors-insurance' in partner['referer']

    q = InsuranceQuote.query.one()
    # the lead's name is the first traveller — we no longer ask for a separate contact name
    assert (q.name, q.email, q.insurance_type, q.status) == ('Ramesh Kumar', 'ramesh@example.com', 'visitors', 'quoted')
    assert q.travellers == [{'name': 'Ramesh Kumar', 'age': '65'}, {'name': 'Lakshmi Kumar', 'age': '62'}]
    assert q.age_list == ['65', '62'] and q.traveller_count == 2


def test_schengen_uses_its_own_section_and_no_destination(client, db, partner):
    """Schengen prices off home country with coverageArea 3; visitors is the mirror image."""
    r = client.post('/api/insurance-quote', json=payload(insurance_type='schengen'))
    assert r.get_json()['success']

    body = partner['body']
    assert body['section'] == 'schengen'
    assert body['coverageArea'] == '3'
    assert body['policyMaximum'] == '20'
    assert body['homeCountry'] == 'IND'
    assert 'primaryDestination' not in body
    assert 'schengen-visa-insurance' in partner['referer']
    assert InsuranceQuote.query.one().insurance_type == 'schengen'


def test_travel_medical_prices_the_chosen_destination(client, db, partner):
    """The only product that takes a country — the other two imply their region."""
    r = client.post('/api/insurance-quote', json=payload(insurance_type='health', destination='GBR'))
    assert r.get_json()['success']

    body = partner['body']
    assert body['section'] == 'travelOutsideUSA'
    assert body['primaryDestination'] == 'GBR'
    assert body['coverageArea'] == '1'
    assert body['homeCountry'] == 'IND'
    assert partner['referer'].endswith('/travel-health-insurance/')   # no /widget1/ for this one

    q = InsuranceQuote.query.one()
    assert (q.insurance_type, q.destination) == ('health', 'GBR')


def test_travel_medical_needs_a_real_destination(client, db, partner):
    for bad in (None, '', 'EUR', 'ZZZ', 'Britain'):
        InsuranceQuote.query.delete()
        body = payload(insurance_type='health')
        if bad is not None:
            body['destination'] = bad
        else:
            body.pop('destination', None)
        r = client.post('/api/insurance-quote', json=body)
        assert r.status_code == 400, bad
        assert 'travelling to' in r.get_json()['error']
        assert InsuranceQuote.query.count() == 0


def test_destination_is_ignored_for_the_fixed_region_products(client, db, partner):
    """Visitors is the USA and schengen is the Schengen area — a stray country must not leak in."""
    client.post('/api/insurance-quote', json=payload(insurance_type='visitors', destination='THA'))
    assert partner['body']['primaryDestination'] == 'USA'
    assert InsuranceQuote.query.one().destination is None

    InsuranceQuote.query.delete()
    client.post('/api/insurance-quote', json=payload(insurance_type='schengen', destination='THA'))
    assert 'primaryDestination' not in partner['body']
    assert InsuranceQuote.query.one().destination is None


def test_more_than_two_travellers_are_all_priced(client, db, partner):
    """The partner's own iframe stops at two — our form is the reason to not embed it."""
    four = [{'name': n, 'age': a} for n, a in
            (('Ramesh', '65'), ('Lakshmi', '62'), ('Arun', '38'), ('Meera', '9'))]
    r = client.post('/api/insurance-quote', json=payload(travellers=four))
    assert r.get_json()['success']
    assert [t['age'] for t in partner['body']['travelerInfos']] == ['65', '62', '38', '9']
    assert InsuranceQuote.query.one().traveller_count == 4


def test_unknown_product_falls_back_to_visitors(client, db, partner):
    r = client.post('/api/insurance-quote', json=payload(insurance_type='travel-health'))
    assert r.get_json()['success']
    assert partner['body']['section'] == 'visitorUSA'
    assert InsuranceQuote.query.one().insurance_type == 'visitors'


def test_partner_outage_still_records_the_lead(client, db, partner):
    partner['fail'] = True
    r = client.post('/api/insurance-quote', json=payload())
    assert r.status_code == 502 and not r.get_json()['success']
    q = InsuranceQuote.query.one()
    assert q.status == 'failed' and q.quote_url is None


@pytest.mark.parametrize('bad, field', [
    ({'travellers': []}, 'no travellers'),
    ({'travellers': [{'name': 'A', 'age': 'abc'}]}, 'age not a number'),
    ({'travellers': [{'name': '', 'age': '40'}]}, 'missing name'),
    ({'travellers': [{'name': 'A', 'age': ''}]}, 'missing age'),
    ({'travellers': [{'name': 'A', 'age': '1'}] * 9}, 'over max'),
    ({'email': 'nope'}, 'email'),
    ({'email': ''}, 'email missing'),
    ({'citizenship': 'XX'}, 'citizenship'),
    ({'start_date': (date.today() - timedelta(days=1)).isoformat()}, 'start'),
    ({'end_date': (date.today() + timedelta(days=2)).isoformat(),
      'start_date': (date.today() + timedelta(days=9)).isoformat()}, 'end'),
])
def test_validation_rejects_and_stores_nothing(client, db, partner, bad, field):
    r = client.post('/api/insurance-quote', json=payload(**bad))
    assert r.status_code == 400, field
    assert not r.get_json()['success']
    assert InsuranceQuote.query.count() == 0


def test_admin_leads_page_lists_and_filters(client, db, admin_user, partner):
    client.post('/api/insurance-quote', json=payload())
    client.post('/api/insurance-quote', json=payload(
        insurance_type='schengen', email='lakshmi@example.com',
        travellers=[{'name': 'Lakshmi Iyer', 'age': '62'}]))
    login(client, 'admin@test.com')

    html = client.get('/admin/insurance-quotes').data.decode()
    assert 'Ramesh Kumar' in html and 'Lakshmi Iyer' in html
    assert 'Visitors Medical' in html and 'Schengen Visa' in html

    # filters narrow the list
    assert 'Lakshmi Iyer' not in client.get('/admin/insurance-quotes?type=visitors').data.decode()
    assert 'Ramesh Kumar' not in client.get('/admin/insurance-quotes?q=lakshmi').data.decode()
    assert 'Ramesh Kumar' not in client.get('/admin/insurance-quotes?status=failed').data.decode()


def test_admin_leads_page_is_admin_only(client, db, user):
    assert client.get('/admin/insurance-quotes').status_code in (301, 302)   # anonymous -> login
    login(client, 'bob@test.com')
    assert client.get('/admin/insurance-quotes').status_code in (302, 403)
