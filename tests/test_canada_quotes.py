"""Canada quotes: Secure Travel's calculators read live (services/canada_quotes.py), our quotes page, the call
back, and the admin copy. No test reaches secure-travel.ca: `fetch` is replaced by pages built here with the
same calculator structure as theirs (form_structure_1, the priceCode chain, the deductible rules)."""
import json
import urllib.error
from datetime import date, timedelta

import pytest

from app import db as _db
from app.models import CrmLead, CrmSource, CrmTouchpoint, InsuranceQuote, Notification
from app.services import canada_quotes, mailer
from tests.conftest import login

BANDS = ['0 to 25', '26 to 35', '36 to 40', '41 to 54', '55 to 59', '60 to 64', '65 to 69', '70 to 74',
         '75 to 79', '80 to 84', '85 to 89']
CODES = 'abcdefghijk'
# a few of the real super visa rates (per day)
SV_RATES = {'fns30': 3.64, 'fys30': 4.44, 'fne03': 4.14, 'fye03': 4.88, 'gns30': 4.44, 'gne03': 5.05,
            'fns40': 4.62, 'gns40': 5.64, 'fne04': 5.51, 'gne04': 6.71, 'jns30': 12.23, 'kns30': 17.12}
VI_RATES = dict(SV_RATES, fns10=2.40, gns10=2.93, fne01=2.73, gne01=3.33, bns10=2.05)


def _eq(rates):
    branches = '\n'.join('%sif (priceCode == "%s") {\n    perDay = %s;\n}' % ('' if i == 0 else 'else ', c, r)
                         for i, (c, r) in enumerate(rates.items()))
    return ('(function(){\n\nvar priceCode = fieldname4+fieldname12+fieldname5+fieldname8+fieldname7;\n'
            'var perDay = 0;\nvar numDays = fieldname10;\n\n' + branches +
            '\nelse {\n    perDay = "Not Available";\n}\n\nif(perDay !== "Not Available"){\n'
            '    var subTotal = perDay * numDays;\n\n    var discount = 0;\n\n'
            '    if (["a", "b", "c", "d", "e", "f", "g", "h", "i"].indexOf(fieldname4) > -1 && ["s","e"].indexOf(fieldname5) > -1) {\n'
            '        if (fieldname6 == 0) {\n            discount = 1;\n        } else if (fieldname6 == 1000) {\n'
            '            discount = .8;\n        } else if (fieldname6 == 3000) {\n            discount = .7;\n'
            '        } else {\n            discount = 1;\n        }\n'
            '    } else if (["j", "k"].indexOf(fieldname4) > -1 && ["s","e"].indexOf(fieldname5) > -1) {\n'
            '        if (fieldname6 == 0) {\n            discount = 1;\n        } else if (fieldname6 == 1000) {\n'
            '            discount = .85;\n        } else if (fieldname6 == 3000) {\n            discount = .75;\n'
            '        } else {\n            discount = 1;\n        }\n    }\n\n'
            '    var total = subTotal * discount;\n\n    var totalString = "$" + total.toFixed(2);\n\n'
            '    return totalString;\n} else {\n    return perDay;\n}\n\n})();')


def _page(product, rates):
    sv = product == 'super_visa'
    limits = (['$100,000', '$150,000'], ['3', '4']) if sv else (['$25,000', '$100,000', '$150,000'], ['1', '3', '4'])
    monthly_eq = ('(function(){\nvar premium = 0;\n    if(fieldname1 == "Not Available") {\n        return "Not Available";\n'
                  '    } else {\n        premium = (fieldname1 / 12);\n    }\nreturn "$" + premium.toFixed(2);\n})();') if sv else \
        ('(function(){\nvar premium = 0;\n    if(fieldname1 == "Not Available") {\n        return "N/A";\n'
         '    } else if(fieldname10 == 365 && fieldname7 >= 3)  {\n        premium = (fieldname1 / 12);\n'
         '    }  else if(fieldname10 == 365 && fieldname8 >= 3)  {\n        premium = (fieldname1 / 12);\n'
         '    } else {\n        return "N/A";\n    }\nreturn "$" + premium.toFixed(2);\n})();')
    fields = [
        {'name': 'fieldname4', 'ftype': 'fdropdown', 'title': 'Age', 'choices': BANDS, 'choicesVal': list(CODES)},
        {'name': 'fieldname12', 'ftype': 'fradio', 'title': 'Preexisting Condition', 'choices': ['Yes', 'No'], 'choicesVal': ['y', 'n']},
        {'name': 'fieldname5', 'ftype': 'fdropdown', 'title': 'Plan', 'choices': ['Standard', 'Enhanced'],
         'choicesVal': ['s', 'e'], 'showDep': True, 'choicesDep': [['fieldname8'], ['fieldname7']]},
        {'name': 'fieldname8', 'ftype': 'fdropdown', 'title': 'Policy Limit - Standard', 'choices': limits[0], 'choicesVal': limits[1]},
        {'name': 'fieldname7', 'ftype': 'fdropdown', 'title': 'Policy Limit - Enhanced', 'choices': limits[0], 'choicesVal': limits[1]},
        {'name': 'fieldname6', 'ftype': 'fdropdown', 'title': 'Deductible', 'choices': ['$0', '$1000', '$3000'],
         'choicesVal': ['0', '1000', '3000']},
        {'name': 'fieldname10', 'ftype': 'fnumber', 'title': 'Number of Days - 1 Year Fixed Plan' if sv else 'Number of Days',
         'predefined': '365' if sv else '7', 'readonly': sv},
        {'name': 'fieldname1', 'ftype': 'fCalculated', 'title': 'Estimated Cost of Your Plan', 'eq': _eq(rates)},
        {'name': 'fieldname22', 'ftype': 'fCalculated', 'title': 'Monthly Premium',
         'userhelp': 'Plus $120 one time monthly option fee', 'eq': monthly_eq},
    ]
    table = '' if sv else ('<table><tr><th></th><th>Standard Plan</th><th>Enhanced Plan</th></tr>'
                           '<tr><td>Prescription Drugs</td><td>30 days up to $500</td><td>30 days up to $1,000</td></tr>'
                           '<tr><td>Hospital Allowance</td><td></td><td>$50 per day (max 10 days)</td></tr></table>')
    return ('<html><body>%s<script>form_structure_1=%s;</script></body></html>'
            % (table, json.dumps([fields, {'0': {'title': 'Insurance Plan Quote'}, 'formid': 'cp_calculatedfieldsf_pform_1'}])))


@pytest.fixture(autouse=True)
def secure_travel(monkeypatch):
    """Their two pages, as this test wants them; `pages[product] = None` makes that page fail."""
    pages = {'super_visa': _page('super_visa', SV_RATES), 'visitors': _page('visitors', VI_RATES)}

    def fetch(product):
        if pages.get(product) is None:
            raise urllib.error.URLError('down')
        return pages[product]

    canada_quotes.forget()
    monkeypatch.setattr(canada_quotes, 'fetch', fetch)
    yield pages
    canada_quotes.forget()


def _start():
    return (date.today() + timedelta(days=12)).isoformat()


def _ask(client, **kw):
    body = {'insurance_type': 'canada', 'cover': 'super_visa', 'start_date': _start(), 'citizenship': 'IND',
            'travellers': [{'age': '66'}, {'age': '62'}], 'pre_existing': 'no', 'email': 'lakshmi@example.com',
            'phone': '98765 43210', 'phone_cc': 'IN'}
    body.update(kw)
    return client.post('/api/insurance-quote', json=body)


# ------------------------------------------------------------------------------------------- the calculator

def test_parse_reads_their_calculator(app):
    t = canada_quotes.parse(_page('super_visa', SV_RATES), 'super_visa')
    assert [b.label for b in t.bands][:2] == ['0 to 25', '26 to 35'] and t.band(62).code == 'f'
    assert t.order == ['age', 'pre', 'plan', ('limit', 's'), ('limit', 'e')]
    assert [c for c, _, _ in t.limits['s']] == ['3', '4'] and t.limits['e'][0][2] == 100000
    assert t.fixed_days == 365 and t.monthly == {'months': 12, 'fee': 120}
    # the hidden limit box of the other plan counts as 0 in their price code
    assert t.code('f', 'n', 's', '3') == 'fns30' and t.code('f', 'n', 'e', '3') == 'fne03'
    assert t.price(62, 'n', 's', '3', 0, 365) == 1328.60
    assert t.price(62, 'n', 's', '3', 1000, 365) == 1062.88          # x 0.8
    assert t.price(62, 'y', 'e', '3', 0, 365) == 1781.20
    assert t.price(82, 'n', 's', '3', 1000, 365) == round(12.23 * 365 * .85, 2)   # 80+ have their own factors
    assert t.price(90, 'n', 's', '3', 0, 365) is None                # no band: not offered
    assert t.price(87, 'y', 's', '3', 0, 365) is None                # no rate on their page: not offered


def test_visitors_page_monthly_rule_and_benefits(app):
    t = canada_quotes.parse(_page('visitors', VI_RATES), 'visitors')
    assert t.fixed_days is None
    assert t.monthly['min_days'] == 365 and t.monthly['min_limit'] == 3
    assert t.monthly_ok(365, '3') and not t.monthly_ok(90, '3') and not t.monthly_ok(365, '1')
    assert t.benefits[0] == ('Prescription Drugs', '30 days up to $500', '30 days up to $1,000')
    assert t.price(30, 'n', 's', '1', 0, 30) == 61.50


def test_changed_shape_is_unavailable(app):
    with pytest.raises(canada_quotes.Unavailable):
        canada_quotes.parse('<html>no calculator here</html>', 'super_visa')


def test_pages_compared_and_changes_noticed(app, admin_user, secure_travel):
    sv, check = canada_quotes.live('super_visa')
    assert check['fresh'] and check['same'] is None                    # nothing to compare with yet
    assert canada_quotes.live('super_visa')[1]['fresh'] is False       # reused, not read again
    vi = canada_quotes.parse(_page('visitors', dict(VI_RATES, gns40=5.70)), 'visitors')
    differ = canada_quotes.compare_pages(sv, vi)
    assert len(differ) == 1 and differ[0]['super_visa'] == 5.64 and differ[0]['visitors'] == 5.70

    canada_quotes.forget()
    assert canada_quotes.live('super_visa')[1]['same'] is True         # read again: the same
    secure_travel['super_visa'] = _page('super_visa', dict(SV_RATES, fns30=3.70))
    canada_quotes.forget()
    _t, check = canada_quotes.live('super_visa')
    assert check['same'] is False
    state = canada_quotes.state()['super_visa']
    assert state['changed_at'] and state['same'] is False
    assert Notification.query.filter_by(user_id=admin_user.id, type='canada_rates').count() == 1
    # never a rate in what is kept
    assert '3.7' not in json.dumps(state)


def test_their_site_down_uses_a_recent_read(app, secure_travel):
    canada_quotes.live('super_visa')
    secure_travel['super_visa'] = None
    with canada_quotes._lock:                       # the read is old enough to be read again
        mono, at, table, same = canada_quotes._reads['super_visa']
        canada_quotes._reads['super_visa'] = (mono - canada_quotes.READ_SECONDS - 1, at, table, same)
    _t, check = canada_quotes.live('super_visa')
    assert check['stale'] is True
    canada_quotes.forget()
    with pytest.raises(canada_quotes.Unavailable):
        canada_quotes.live('super_visa')
    assert canada_quotes.state()['super_visa']['error']


# ------------------------------------------------------------------------------------------- step 1

def test_step_one_saves_the_quote_makes_a_lead_and_emails(client):
    mailer.OUTBOX.clear()
    r = _ask(client)
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d['success'] and '/travel-insurance/canada/quotes/' in d['url'] and d['ref'].startswith('CQ-')
    q = InsuranceQuote.query.one()
    assert q.insurance_type == 'canada' and q.destination == 'CAN' and q.status == 'quoted'
    assert q.end_date - q.start_date == timedelta(days=364)              # a super visa is a year
    assert q.extra == {'cover': 'super_visa', 'days': 365, 'emailed': q.extra['emailed']}
    assert q.travellers == [{'age': '66', 'pre': 'n'}, {'age': '62', 'pre': 'n'}]
    assert q.token and len(q.token) >= 16
    lead = CrmLead.query.filter_by(ref_type='insurance_quotes', ref_id=q.id).one()
    assert lead.source.key == 'ti-canada' and lead.product == 'TI'
    assert 'from $' in lead.details['quote'] and lead.details['reference'] == d['ref']
    mail = [m for m in mailer.OUTBOX if m['subject'].startswith('Your Canada insurance quotes')]
    assert len(mail) == 1 and mail[0]['recipients'] == ['lakshmi@example.com']
    # 4.44 x 365 x 0.7 + 3.64 x 365 x 0.7 = the lowest Standard total, $3,000 deductible
    assert 'Standard plan: from $2,064.44' in mail[0]['body'] and q.token in mail[0]['body']
    assert q.extra['emailed'][0]['ok'] is True


def test_step_one_checks_what_it_is_given(client):
    assert _ask(client, start_date=(date.today() - timedelta(days=1)).isoformat()).status_code == 400
    assert _ask(client, travellers=[]).status_code == 400
    assert _ask(client, email='nope').status_code == 400
    assert _ask(client, phone='').status_code == 400
    far = (date.today() + timedelta(days=12 + 400)).isoformat()
    r = _ask(client, cover='visitors', end_date=far)
    assert r.status_code == 400 and 'up to a year' in r.get_json()['error']
    assert _ask(client, cover='visitors', end_date='').status_code == 400   # a visit needs its end date
    assert InsuranceQuote.query.count() == 0


def test_visit_counts_both_days_and_per_traveller_pre_existing(client):
    end = (date.today() + timedelta(days=12 + 29)).isoformat()
    r = _ask(client, cover='visitors', end_date=end, travellers=[{'age': '66', 'pre': 'yes'}, {'age': '62'}])
    assert r.status_code == 200
    q = InsuranceQuote.query.one()
    assert q.extra['days'] == 30 and q.travellers[0]['pre'] == 'y' and q.travellers[1]['pre'] == 'n'


def test_their_site_down_still_keeps_the_request(client, secure_travel):
    secure_travel['super_visa'] = None
    secure_travel['visitors'] = None
    r = _ask(client)
    assert r.status_code == 200 and r.get_json()['success']
    q = InsuranceQuote.query.one()
    assert q.status == 'failed'
    html = client.get(r.get_json()['url']).data.decode()
    assert 'could not be read just now' in html


# ------------------------------------------------------------------------------------------- the quotes page

def test_quotes_page_shows_every_option(client):
    url = _ask(client).get_json()['url']
    r = client.get(url)
    assert r.status_code == 200
    html = r.data.decode()
    assert 'noindex' in html and 'Standard plan' in html and 'Enhanced plan' in html and 'cqData' in html
    data = json.loads(html.split('<script type="application/json" id="cqData">')[1].split('</script>')[0])
    sv = data['books']['super_visa']
    assert sv['days'] == 365 and [p['band'] for p in sv['people']] == ['65 to 69', '60 to 64']
    assert sv['people'][1]['prices']['n']['s']['3']['0'] == 1328.6
    assert sv['people'][1]['prices']['y']['e']['3']['0'] == 1781.2          # both answers, for the toggles
    assert data['books']['visitors']['days'] == 365                          # the other cover, to compare
    assert data['books']['visitors']['benefits'][0][0] == 'Prescription Drugs'
    assert client.get('/travel-insurance/canada/quotes/not-a-token').status_code == 404


# ------------------------------------------------------------------------------------------- step 2: call back

def _token(client, **kw):
    _ask(client, **kw)
    return InsuranceQuote.query.order_by(InsuranceQuote.id.desc()).first()


def test_call_back_prices_the_picks_again_and_tells_the_lead(client):
    q = _token(client)
    mailer.OUTBOX.clear()
    r = client.post('/travel-insurance/canada/quotes/%s/call-back' % q.token, json={
        'name': 'Lakshmi Rao', 'best_time': 'Evening', 'how': 'WhatsApp', 'note': 'Mother takes BP tablets',
        'pre': ['n', 'n'],
        'picks': [{'product': 'super_visa', 'plan': 's', 'limit': '3', 'deductible': 0, 'pay': 'monthly', 'total': 1}]})
    assert r.status_code == 200, r.get_json()
    q = _db.session.get(InsuranceQuote, q.id)
    assert q.status == 'callback' and q.name == 'Lakshmi Rao'
    pick = q.extra['picks'][0]
    assert pick['total'] == 2949.20 and pick['each'] == [1620.6, 1328.6]   # the server's price, not the browser's
    assert pick['pay'] == 'monthly' and pick['monthly'] == round(2949.20 / 12, 2) and pick['monthly_fee'] == 120
    assert q.extra['callback']['how'] == 'WhatsApp' and q.extra['callback']['best_time'] == 'Evening'
    lead = CrmLead.query.filter_by(ref_type='insurance_quotes', ref_id=q.id).one()
    assert CrmLead.query.count() == 1                                        # the same lead, not a second one
    assert 'Standard' in lead.details['picked'] and lead.details['call_back'] == 'WhatsApp · Evening'
    body = ' '.join(t.body or '' for t in CrmTouchpoint.query.filter_by(lead_id=lead.id).all())
    assert 'Asked for a call back' in body and 'Mother takes BP tablets' in body
    assert any(m['subject'].startswith('We will call you') for m in mailer.OUTBOX)


def test_call_back_changed_pre_existing_answer_is_priced(client):
    q = _token(client)
    r = client.post('/travel-insurance/canada/quotes/%s/call-back' % q.token, json={
        'name': 'Lakshmi', 'pre': ['n', 'y'],
        'picks': [{'product': 'super_visa', 'plan': 's', 'limit': '3', 'deductible': 0}]})
    assert r.status_code == 200
    q = _db.session.get(InsuranceQuote, q.id)
    assert q.travellers[1]['pre'] == 'y' and q.extra['picks'][0]['each'] == [1620.6, round(4.44 * 365, 2)]


def test_call_back_needs_a_name_and_real_options(client):
    q = _token(client)
    url = '/travel-insurance/canada/quotes/%s/call-back' % q.token
    assert client.post(url, json={'picks': []}).status_code == 400            # no name
    bad = {'name': 'L', 'picks': [{'product': 'super_visa', 'plan': 's', 'limit': '9', 'deductible': 0}]}
    assert client.post(url, json=bad).status_code == 400
    ok = client.post(url, json={'name': 'L', 'picks': []})                    # no pick: "let's talk it through"
    assert ok.status_code == 200 and _db.session.get(InsuranceQuote, q.id).status == 'callback'


# ------------------------------------------------------------------------------------------- change the trip, in place

def test_change_the_trip_on_the_quotes_page(client):
    q = _token(client)
    page = client.get('/travel-insurance/canada/quotes/%s' % q.token).data.decode()
    assert 'id="cqTrip"' in page and '/trip' in page                      # the form is on the page itself
    end = (date.today() + timedelta(days=12 + 20)).isoformat()
    r = client.post('/travel-insurance/canada/quotes/%s/trip' % q.token, json={
        'cover': 'visitors', 'start_date': _start(), 'end_date': end,
        'travellers': [{'age': '66', 'pre': 'y'}, {'age': '62'}, {'age': '30'}]})
    assert r.status_code == 200, r.get_json()
    q = _db.session.get(InsuranceQuote, q.id)
    assert q.extra['cover'] == 'visitors' and q.extra['days'] == 21 and len(q.travellers) == 3
    assert q.travellers[0]['pre'] == 'y' and q.extra['changes'][0]['before']['cover'].startswith('Super visa')
    assert InsuranceQuote.query.count() == 1 and CrmLead.query.count() == 1      # the same request, the same lead
    lead = CrmLead.query.one()
    body = ' '.join(t.body or '' for t in CrmTouchpoint.query.filter_by(lead_id=lead.id).all())
    assert 'Changed the trip' in body and '21 days' in body
    data = client.get('/travel-insurance/canada/quotes/%s' % q.token).data.decode()
    assert '"days": 21' in data or '"days":21' in data
    # checked like step 1
    bad = client.post('/travel-insurance/canada/quotes/%s/trip' % q.token, json={'cover': 'visitors', 'start_date': _start()})
    assert bad.status_code == 400
    assert client.post('/travel-insurance/canada/quotes/nope/trip', json={}).status_code == 404


def test_one_day_reads_as_a_day(client):
    r = _ask(client, cover='visitors', end_date=_start())
    html = client.get(r.get_json()['url']).data.decode()
    assert '1 day' in html and '1 days' not in html


# ------------------------------------------------------------------------------------------- the admin copy

def test_admin_copy_shows_picks_then_and_now(client, admin_user, secure_travel):
    q = _token(client)
    client.post('/travel-insurance/canada/quotes/%s/call-back' % q.token, json={
        'name': 'Lakshmi', 'picks': [{'product': 'super_visa', 'plan': 's', 'limit': '3', 'deductible': 0}]})
    login(client, 'admin@test.com')
    html = client.get('/admin/insurance/canada-quotes').data.decode()
    assert 'Canada quotes' in html and 'lakshmi@example.com' in html and '30NJMC' in html
    assert 'tracking_code=30NJMC' in html and '✓ same' in html and '$2,949.20' in html
    assert 'open them in the pipeline' in html
    # their price changes: the admin sees it before the call
    secure_travel['super_visa'] = _page('super_visa', dict(SV_RATES, fns30=3.70))
    canada_quotes.forget()
    html = client.get('/admin/insurance/canada-quotes').data.decode()
    assert '⚠ changed' in html and 'Changed since the check before' in html
    assert client.get('/admin/insurance/canada-quotes?status=quoted').status_code == 200
    assert 'lakshmi@example.com' not in client.get('/admin/insurance/canada-quotes?status=quoted').data.decode()
    r = client.post('/admin/insurance/canada-quotes/check')
    assert r.status_code in (301, 302)


def test_admin_copy_is_not_public(client, user):
    assert client.get('/admin/insurance/canada-quotes').status_code in (301, 302)
    login(client, 'bob@test.com')
    assert client.get('/admin/insurance/canada-quotes').status_code in (302, 403)


def test_canada_source_is_in_the_lead_sources_list(app):
    from app.services import crm_sources
    item = next(i for _g, _n, _ic, items in crm_sources.GROUPS for i in items if i.key == 'ti-canada')
    assert item.product == 'TI' and item.pipeline == 'ti-standard'
    _ = CrmSource                                       # the row itself is made when the first lead comes in
