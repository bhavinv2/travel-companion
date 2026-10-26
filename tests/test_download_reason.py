"""Every sales download asks why first, and the answer is in the audit log (Staff Console 2.0, 2026-10-26)."""
from conftest import login
from app.models import ActivityEvent
from app.services import access, crm


def test_a_download_asks_why_first_and_logs_the_answer(app, client, admin_user):
    access.ensure_defaults()
    crm.ensure_defaults()
    crm.capture('ti-quote', name='Download Dev', phone='+919811100401', utm={})
    login(client, admin_user.email)
    r = client.get('/admin/crm/export/contacts?owner=mine')
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and 'Why are you downloading this?' in html
    assert 'name="owner" value="mine"' in html                                   # the same list, after the answer
    assert ActivityEvent.query.filter_by(event='crm_export').count() == 0        # nothing left yet
    # "Something else" needs its words
    again = client.get('/admin/crm/export/contacts?reason=other').get_data(as_text=True)
    assert 'Say what it is for' in again
    r = client.get('/admin/crm/export/contacts?reason=other&why=Insurer+renewal+list')
    assert r.headers['Content-Type'].startswith('text/csv') and 'Download Dev' in r.get_data(as_text=True)
    ev = ActivityEvent.query.filter_by(event='crm_export').one()
    assert ev.meta['reason'] == 'Something else: Insurer renewal list'
    log = client.get('/admin/security/?tab=log').get_data(as_text=True)
    assert 'Downloaded data' in log and 'reason: Something else: Insurer renewal list' in log


def test_every_sales_download_asks(app, client, admin_user):
    access.ensure_defaults()
    login(client, admin_user.email)
    for url in ('/admin/crm/export/leads?p=all', '/admin/crm/insights.csv?days=7', '/admin/crm/insights-people.csv',
                '/admin/crm/forecast.csv', '/admin/crm/reports/build.csv?what=leads&group=owner',
                '/admin/crm/analysis?period=7d&format=csv'):
        assert 'Why are you downloading this?' in client.get(url).get_data(as_text=True), url
        sep = '&' if '?' in url else '?'
        assert client.get(url + sep + 'reason=report').headers['Content-Type'].startswith('text/csv'), url
