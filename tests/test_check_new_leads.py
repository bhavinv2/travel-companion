"""The half-hourly check's new leads (cs/crm/checks.html, crm_reports.new_leads): the day's leads by product and by
where they came from, every number a link to exactly those leads on Leads › List -- and Leads' Product filter
(`prd`) the product links use."""
import html as _html
import re
from urllib.parse import parse_qs, urlparse

from conftest import login
from app.models import CrmSource
from app.services import crm, crm_reports


def bring_in():
    crm.capture('ti-quote', name='Asha Insure', phone='+919811100001', utm={})
    crm.capture('ti-quote', name='Bala Insure', phone='+919811100002', utm={})
    crm.capture('contact-sahayak', name='Chitra Sahayak', phone='+919811100003', utm={})
    crm.capture('tawk', name='Dev Tawk', phone='+919811100004', utm={}, channel='chat')


def hrefs(page):
    return [_html.unescape(h) for h in re.findall(r'href="([^"]+)"', page)]


def names(client, href):
    page = client.get(href).get_data(as_text=True)
    return {n for n in ('Asha Insure', 'Bala Insure', 'Chitra Sahayak', 'Dev Tawk') if n in page}


def test_the_day_by_product_and_where_from(app):
    bring_in()
    day = crm_reports.current()[0]
    new = crm_reports.new_leads(day)
    assert new['total'] == 4 and new['none'] == 0
    assert dict(new['products'])['TI'] == 2 and dict(new['products'])['SH'] == 1
    groups = {g['key']: g for g in new['groups']}
    assert groups['web']['n'] == 3 and groups['calls']['n'] == 1 and groups['web']['link']
    assert [(x['label'], x['n']) for x in groups['web']['sources']][0] == ('Travel insurance site · Search quote', 2)
    assert crm_reports.new_leads(day.replace(year=day.year - 1))['total'] == 0


def test_every_number_on_the_check_opens_its_leads(app, client, cs_user):
    bring_in()
    login(client, cs_user.email)
    page = client.get('/cs/crm/checks').get_data(as_text=True)
    assert 'New leads today' in page and 'By product' in page and 'By where they came from' in page
    links = hrefs(page)

    def find(**words):
        for h in links:
            q = {k: v[0] for k, v in parse_qs(urlparse(h).query, keep_blank_values=True).items()}
            narrow = {k: q[k] for k in ('src', 'prd') if k in q}
            if (urlparse(h).path.endswith('/crm/') and q.get('dr') == 'today'
                    and narrow == {k: v for k, v in words.items() if k != 'dr'}):
                assert q['view'] == 'list' and q['p'] == 'all' and q['owner'] == 'all' and q['chat'] == ''
                return h
        raise AssertionError('no link with %r' % words)

    everyone = {'Asha Insure', 'Bala Insure', 'Chitra Sahayak', 'Dev Tawk'}
    assert names(client, find(dr='today')) == everyone
    assert names(client, find(prd='TI')) == {'Asha Insure', 'Bala Insure'}
    assert names(client, find(prd='SH')) == {'Chitra Sahayak'}
    assert names(client, find(src='g:web')) == {'Asha Insure', 'Bala Insure', 'Chitra Sahayak'}
    quote = CrmSource.query.filter_by(key='ti-quote').one()
    assert names(client, find(src=str(quote.id))) == {'Asha Insure', 'Bala Insure'}
    # the Tawk inbox's tile: its new lead, as a link beside the tile's button (never inside it)
    tawk = CrmSource.query.filter_by(key='tawk').one()
    assert names(client, find(src=str(tawk.id))) == {'Dev Tawk'}
    assert re.search(r'</button>\s*<a class="hc-leads" href="[^"]*src=%d' % tawk.id, page)


def test_a_quiet_day_says_so(app, client, cs_user):
    login(client, cs_user.email)
    page = client.get('/cs/crm/checks').get_data(as_text=True)
    assert 'New leads today' in page and 'By product' not in page and 'See all' not in page


def test_leads_product_filter(app, client, admin_user):
    bring_in()
    login(client, admin_user.email)
    page = client.get('/admin/crm/?p=all&view=list&owner=all&chat=&prd=TI').get_data(as_text=True)
    assert 'Asha Insure' in page and 'Chitra Sahayak' not in page and 'Dev Tawk' not in page
    assert 'name="prd" value="TI" checked' in page                    # the pill under More filters is on
    assert 'Clear all' in page
    # a product that is not one is ignored
    page = client.get('/admin/crm/?p=all&view=list&owner=all&chat=&prd=NOPE').get_data(as_text=True)
    assert 'Asha Insure' in page and 'Chitra Sahayak' in page
    w, kw = crm.lead_more_words({'prd': 'ti'})
    assert w['prd'] == 'TI' and kw['product'] == 'TI'


def test_health_product_bars_open_their_leads(app, client, admin_user):
    bring_in()
    login(client, admin_user.email)
    page = client.get('/admin/health').get_data(as_text=True)
    assert any('prd=TI' in h for h in hrefs(page))
