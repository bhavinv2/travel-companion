"""Sales CRM 2.0, run 5b -- campaign cost and return (Lead sources > Marketing activities, one home).

    tab        the activities are rows of crm_campaigns now (per workspace); each can carry a campaign key, a lead
               source, dates and a cost with its currency; How we sell still lists them; the old text form saves too
    results    Sales results > Campaigns: leads, won, won value, cost, cost per lead, cost per customer, return -- in
               the reporting currency; a currency with no rate is named
    guards     who sees which leads, the recycle bin and workspaces hold
    builder    the report builder groups leads by campaign
"""
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from conftest import login, make_user
from app import db as _db
from app.models import CrmCampaign, CrmCurrencyRate, CrmLead, CrmPipeline, CrmSource, CrmStage, WorkspaceRole
from app.services import access, crm, crm_bin, crm_campaigns, crm_report_builder as rb, crm_scope

from test_crm_wa_sync_engine import ti_lead


def words(html):
    return re.sub(r'\s+', ' ', re.sub(r'<script.*?</script>|<[^>]+>', ' ', html, flags=re.S))


def won_stage():
    return CrmStage.query.join(CrmPipeline).filter(CrmPipeline.key == 'ti-standard', CrmStage.key == 'customer').one()


def campaign_lead(phone, key='diwali-ti', won=None, created_days_ago=1, source='ti-quote'):
    lead = crm.capture(source, name='Camp ' + phone[-4:], phone=phone, utm={'utm_campaign': key} if key else {})
    lead.created_at = datetime.utcnow() - timedelta(days=created_days_ago)
    if won is not None:
        lead.amount, lead.currency = Decimal(won[0]), won[1]
        crm.move_stage(lead, won_stage())
    _db.session.commit()
    return lead


def form(rows):
    """The tab's aligned lists for these rows."""
    keys = ('act_id', 'platform', 'activity', 'who', 'status', 'utm', 'source', 'starts', 'ends', 'cost', 'currency')
    return {k: [r.get(k, '') for r in rows] for k in keys}


def test_the_tab_saves_activities_with_their_campaign_details(app, client, admin_user):
    crm.ensure_defaults()
    login(client, admin_user.email)
    page = client.get('/admin/crm/sources?tab=activities').get_data(as_text=True)
    assert 'Organic posting in groups' in page                         # the starting list until the first save
    assert '(?) How this works' in page and 'utm_campaign' in page
    src = CrmSource.query.filter_by(key='ti-quote').one()
    r = client.post('/admin/crm/sources/activities', data=form([
        {'platform': 'Google', 'activity': 'Diwali search ads', 'who': 'Digital', 'status': 'Ongoing',
         'utm': 'diwali-ti', 'source': str(src.id), 'starts': '2026-10-01', 'ends': '2026-11-15', 'cost': '50,000',
         'currency': 'INR'},
        {'platform': 'Facebook', 'activity': 'Groups', 'who': 'Sales', 'status': 'Ongoing'},
        {}]))
    assert r.status_code == 302
    rows = CrmCampaign.query.order_by(CrmCampaign.position).all()
    assert [(c.platform, c.name) for c in rows] == [('Google', 'Diwali search ads'), ('Facebook', 'Groups')]
    c = rows[0]
    assert c.cost == Decimal('50000.00') and c.currency == 'INR' and c.source_id == src.id
    assert (c.starts_on, c.ends_on, c.utm_campaign) == (date(2026, 10, 1), date(2026, 11, 15), 'diwali-ti')
    assert rows[1].cost is None and rows[1].currency is None
    # How we sell lists them
    assert 'Diwali search ads' in words(client.get('/admin/crm/process').get_data(as_text=True))
    # editing keeps the row (its id), a row taken off the screen goes
    r = client.post('/admin/crm/sources/activities', data=form([
        {'act_id': str(c.id), 'platform': 'Google', 'activity': 'Diwali search ads', 'cost': '60000', 'currency': 'INR'}]))
    rows = CrmCampaign.query.all()
    assert len(rows) == 1 and rows[0].id == c.id and rows[0].cost == Decimal('60000.00')


@pytest.mark.parametrize('bad, said', [({'cost': 'a lot'}, 'type the cost as a number'),
                                       ({'starts': '2026-12-01', 'ends': '2026-11-01'}, 'last day is before the first'),
                                       ({'source': '99999'}, 'choose a lead source'),
                                       ({'platform': '', 'activity': '', 'cost': '100'}, 'give it a platform')])
def test_the_tab_says_what_is_wrong(app, client, admin_user, bad, said):
    crm.ensure_defaults()
    login(client, admin_user.email)
    row = {'platform': 'Google', 'activity': 'Ads', **bad}
    r = client.post('/admin/crm/sources/activities', data=form([row]), follow_redirects=True)
    assert said in r.get_data(as_text=True)
    assert CrmCampaign.query.count() == 0


def test_the_old_text_form_saves_into_the_table(app, client, admin_user):
    crm.ensure_defaults()
    login(client, admin_user.email)
    client.post('/admin/crm/process', data={'what': 'channels', 'channels': 'Facebook | Groups | Sales | Ongoing'})
    assert crm_campaigns.channels() == [['Facebook', 'Groups', 'Sales', 'Ongoing']]


def test_results_shows_cost_and_return_per_campaign(app, client, admin_user):
    crm.ensure_defaults()
    _db.session.add(CrmCurrencyRate(code='USD', rate=Decimal('80')))
    _db.session.add(CrmCampaign(platform='Google', name='Diwali search ads', utm_campaign='Diwali-TI', cost=Decimal('500'),
                                currency='USD', starts_on=date.today() - timedelta(days=20), position=0))
    _db.session.add(CrmCampaign(platform='Meta', name='Reels', utm_campaign='reels', cost=Decimal('1000'), currency='AED',
                                position=1))
    _db.session.commit()
    campaign_lead('+919800002001', won=('30000', 'INR'))
    campaign_lead('+919800002002', won=('100', 'USD'))
    campaign_lead('+919800002003')
    campaign_lead('+919800002004')
    campaign_lead('+919800002005', key='something-else')
    campaign_lead('+919800002006', created_days_ago=40)                 # before the campaign began
    login(client, admin_user.email)
    page = client.get('/admin/crm/insights').get_data(as_text=True)
    text = words(page)
    assert 'Campaigns' in text and 'Diwali search ads · Google' in text
    got = crm_campaigns.results(admin_user)
    row = next(r for r in got['rows'] if r['name'] == 'Diwali search ads · Google')
    assert (row['leads'], row['won']) == (4, 2)
    assert row['won_value'] == Decimal('38000')                         # ₹30,000 + $100 at 80
    assert row['cost'] == Decimal('40000')                              # $500 at 80
    assert row['per_lead'] == Decimal('10000') and row['per_customer'] == Decimal('20000')
    assert crm_campaigns.ret_text(row['ret']) == '0.95×'
    assert '₹40,000' in text and '₹10,000' in text and '0.95×' in text
    assert 'No exchange rate for AED' in text                           # named, counted as 0


def test_the_campaigns_table_respects_visibility_the_bin_and_workspaces(app):
    ws = access.ensure_defaults()
    crm.ensure_defaults()
    _db.session.add(CrmCampaign(name='Diwali', utm_campaign='diwali-ti', cost=Decimal('1000'), currency='INR'))
    _db.session.commit()
    own = make_user('own@test.com', 'own', role='cs')
    role = WorkspaceRole(workspace_id=ws.id, name='Own only', pages=sorted(access.CS_ROLE_PAGES), crm_scope='own')
    _db.session.add(role)
    _db.session.flush()
    access.add_member(ws, own, role=role)
    _db.session.commit()
    access._cache().clear()
    mine = campaign_lead('+919800002101')
    theirs = campaign_lead('+919800002102')
    gone = campaign_lead('+919800002103')
    other = make_user('other@test.com', 'other', role='cs')
    mine.owner_id, theirs.owner_id, gone.owner_id = own.id, other.id, own.id
    _db.session.commit()
    crm_bin.remove(gone)
    admin = make_user('boss@test.com', 'boss', role='admin')
    assert crm_campaigns.results(admin)['rows'][0]['leads'] == 2         # the removed lead never counts
    assert crm_campaigns.results(own)['rows'][0]['leads'] == 1           # only what their role shows them
    # another workspace's leads with the same key are not this workspace's campaign's
    b = access.create_workspace('Bee Care')
    _db.session.commit()
    with crm_scope.use(b.id):
        crm.ensure_defaults()
    crm.capture('ti-quote', name='Bee Camp', phone='+919800002104', utm={'utm_campaign': 'diwali-ti'}, workspace_id=b.id)
    with crm_scope.use(ws.id):
        assert crm_campaigns.results(admin)['rows'][0]['leads'] == 2
    with crm_scope.use(b.id):
        assert crm_campaigns.results(admin)['rows'] == []               # B has no campaigns of its own


def test_the_report_builder_groups_leads_by_campaign(app, admin_user):
    crm.ensure_defaults()
    _db.session.add(CrmCampaign(name='Diwali', platform='Google', utm_campaign='diwali-ti', position=0))
    _db.session.commit()
    campaign_lead('+919800002201')
    campaign_lead('+919800002202')
    campaign_lead('+919800002203', key=None)
    res = rb.run(rb.clean_config({'what': 'leads', 'group': 'campaign'}), admin_user)
    table = {r['label']: r['total'] for r in res['rows']}
    assert table == {'Diwali · Google': 2, 'No campaign': 1}
    assert 'campaign' in rb.GROUPS['leads'] and rb.GROUPS['leads']['campaign'] == 'Campaign'
