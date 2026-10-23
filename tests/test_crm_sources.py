"""The lead sources' one list (services/crm_sources, 2026-10-23).

    the list      every item is a source; a capture under an old key is filed under the item it became
    tidy          an old source's leads, campaigns and rules move onto the list once, and it goes
    origin        organic (came by itself), manual (added by staff), imported -- and who, and when in India time
    screens       Leads shows where each lead came from; Add a lead offers the list; Lead sources shows its groups
"""
from datetime import datetime

from conftest import login, make_user
from app import db as _db
from app.models import CrmCampaign, CrmLead, CrmRule, CrmSource
from app.services import crm, crm_sources


def src(key):
    return CrmSource.query.filter_by(key=key).one()


def test_every_item_on_the_list_is_a_source_with_the_list_name(app):
    crm.ensure_defaults()
    for key, (group, it) in crm_sources.ITEMS.items():
        s = src(key)
        assert s.name == it.name and s.kind == it.kind, key
    # a name changed by hand comes back to the list's
    src('tawk').name = 'Something else'
    _db.session.commit()
    crm.ensure_defaults()
    assert src('tawk').name == 'Tawk chat'
    assert [g for g, *_ in crm_sources.GROUPS] == ['calls', 'social', 'reference', 'staff', 'other', 'imports', 'web']


def test_old_keys_are_filed_under_the_item_they_became(app):
    assert crm.capture('instagram', name='Ig', phone='+919876500001', utm={}).source.key == 'meta'
    assert crm.capture('ti-support', name='Sup', phone='+919876500002', utm={}).source.key == 'ti-expert'
    assert crm.capture('call', name='Usa', phone='+12025550111', utm={}).source.key == 'usa-call'
    assert crm.capture('call', name='Ind', phone='+919876500003', utm={}).source.key == 'company-call'
    assert crm.capture('reference', name='Ref', phone='+12025550112', utm={}).source.key == 'ref-usa'
    assert crm.capture('csv-import', name='Csv', phone='+919876500004', utm={}).source.key == 'import-other'


def test_tidy_moves_an_old_sources_leads_campaigns_and_rules_onto_the_list(app):
    # the leads are there before the old sources are tidied (making a lead tidies first)
    a = crm.capture('other', name='A', phone='+919876500011', utm={})
    b = crm.capture('other', name='B', phone='+12025550113', utm={})
    c = crm.capture('other', name='C', phone='+919876500012', utm={})
    ig = CrmSource(key='instagram', name='Instagram DMs and comments', kind='chat', product='GEN', lead_count=3)
    ref = CrmSource(key='reference', name='Reference / friends and family', kind='manual', product='GEN')
    _db.session.add_all([ig, ref])
    _db.session.flush()
    a.source_id, b.source_id, c.source_id = ig.id, ref.id, ref.id
    camp = CrmCampaign(name='Reels', source_id=ig.id)
    rule = CrmRule(name='Ig leads', trigger='new_lead', conditions=[{'field': 'source', 'op': 'is', 'value': ig.id}],
                   actions=[{'type': 'assign', 'user_id': 'round_robin', 'via': 'source:%d' % ig.id}])
    _db.session.add_all([camp, rule])
    _db.session.commit()
    ig_id = ig.id
    crm.ensure_defaults()
    _db.session.expire_all()
    assert CrmSource.query.filter(CrmSource.key.in_(['instagram', 'reference'])).count() == 0
    meta = src('meta')
    assert _db.session.get(CrmLead, a.id).source_id == meta.id and meta.lead_count >= 3
    assert _db.session.get(CrmLead, b.id).source.key == 'ref-usa'          # a +1 number: the USA side
    assert _db.session.get(CrmLead, c.id).source.key == 'ref-india'
    assert _db.session.get(CrmCampaign, camp.id).source_id == meta.id
    rule = _db.session.get(CrmRule, rule.id)
    assert rule.conditions[0]['value'] == meta.id and rule.actions[0]['via'] == 'source:%d' % meta.id
    assert ig_id != meta.id


def test_how_a_lead_came_who_added_it_and_when(app, cs_user):
    organic = crm.capture('ti-quote', name='Web', phone='+919876500021', utm={})
    manual = crm.capture('company-call', name='Rang', phone='+919876500022', utm={}, created_by_id=cs_user.id)
    customer = make_user('cust@test.com', 'customer', role='user')
    own_post = crm.capture('tc-trip-post', name='Poster', phone='+919876500023', utm={}, created_by_id=customer.id)
    imported = crm.capture('import-ti', name='Sheet', phone='+919876500024', utm={}, imported=True)
    organic.created_at = datetime(2026, 10, 23, 8, 35)          # 14:05 in India
    _db.session.commit()
    cf = crm_sources.came_from(organic)
    assert (cf['group'], cf['short'], cf['origin'], cf['origin_word']) == ('web', 'Search quote', 'organic', 'Organic')
    assert cf['at'] == '23 Oct 2026, 14:05' and cf['by'] is None
    cf = crm_sources.came_from(manual)
    assert cf['origin'] == 'manual' and cf['by'] == cs_user.full_name and cf['group_name'] == 'Calls & chats'
    assert crm_sources.origin(own_post) == 'organic'                    # a customer's own post is not "added by staff"
    assert crm_sources.origin(imported) == 'imported'


def test_leads_show_and_filter_where_they_came_from(app, client, admin_user):
    crm.ensure_defaults()
    a = crm.capture('wa-usa', name='Usa Chat', phone='+12025550131', utm={})
    b = crm.capture('company-call', name='Typed In', phone='+919876500031', utm={}, created_by_id=admin_user.id)
    login(client, admin_user.email)
    page = client.get('/cs/crm/?view=list&p=all&owner=all').get_data(as_text=True)
    assert 'Came from' in page and 'Added (IST)' in page
    assert 'USA number · chat' in page and 'Company number · call' in page
    assert 'Organic' in page and 'Manual' in page and 'by %s' % admin_user.full_name in page
    only = client.get('/cs/crm/?view=list&p=all&owner=all&how=manual').get_data(as_text=True)
    assert 'Typed In' in only and 'Usa Chat' not in only
    calls = client.get('/cs/crm/?view=list&p=all&owner=all&src=g:calls').get_data(as_text=True)
    assert 'Typed In' in calls and 'Usa Chat' in calls
    lead_page = client.get('/cs/crm/lead/%d' % a.id).get_data(as_text=True)
    assert 'Calls &amp; chats' in lead_page and 'came in by itself' in lead_page and 'IST' in lead_page
    assert b.id


def test_add_a_lead_offers_the_list_without_the_imports(app, client, admin_user):
    crm.ensure_defaults()
    login(client, admin_user.email)
    page = client.get('/cs/crm/add').get_data(as_text=True)
    assert 'Where did this lead come from?' in page and 'How it will show on Leads' in page
    for key in ('wa-india-call', 'canada-call', 'meta', 'ref-usa', 'tc-cs-post', 'other', 'contact-other', 'sh-request'):
        assert 'value="%s"' % key in page, key
    assert 'value="import-ti"' not in page and 'value="tc-import"' not in page
    r = client.post('/cs/crm/add', data={'source': 'canada-chat', 'name': 'Canada Person', 'phone': '+14165550101',
                                         'product': 'TI', 'note': 'Wants cover'})
    lead = CrmLead.query.order_by(CrmLead.id.desc()).first()
    assert r.status_code == 302 and lead.source.key == 'canada-chat' and crm_sources.origin(lead) == 'manual'
    # an import source cannot be posted in by hand
    r = client.post('/cs/crm/add', data={'source': 'import-ti', 'name': 'Sneaky', 'phone': '+919876500041'})
    assert b'Choose where the lead came from' in r.data


def test_lead_sources_shows_the_groups_and_moves_an_old_sources_leads(app, client, admin_user):
    crm.ensure_defaults()
    stray = CrmSource(key='diwali-page', name='Diwali page', kind='form', product='GEN', status='unrouted')
    _db.session.add(stray)
    _db.session.flush()
    lead = crm.capture('other', name='Stray', phone='+919876500051', utm={})
    lead.source_id = stray.id
    _db.session.commit()
    login(client, admin_user.email)
    page = client.get('/admin/crm/sources').get_data(as_text=True)
    for g in ('Calls &amp; chats', 'Social media', 'Personal references', 'Added by staff', 'Imports', 'Websites',
              'Not in the list'):
        assert g in page, g
    assert 'Contact us' in page and 'Travel insurance site' in page and 'Diwali page' in page
    assert '+ New source' not in page
    r = client.post('/admin/crm/setup/source/%d/move' % stray.id, data={'to': 'web-other'})
    assert r.status_code == 302
    _db.session.expire_all()
    assert _db.session.get(CrmLead, lead.id).source.key == 'web-other'
    assert _db.session.get(CrmSource, stray.id) is None
    # a source on the list keeps its name when saved
    meta = src('meta')
    client.post('/admin/crm/setup/source', data={'id': meta.id, 'name': 'Renamed', 'kind': 'form', 'product': 'GEN',
                                                 'pipeline': 'general', 'status': 'live', 'who': 'anyone',
                                                 'dedupe_days': '30'})
    _db.session.expire_all()
    assert src('meta').name == 'Meta · Instagram & Facebook' and src('meta').kind == 'chat'


def test_the_standard_inboxes_are_the_calls_and_chats(app, client, admin_user):
    crm.ensure_defaults()
    login(client, admin_user.email)
    client.post('/admin/crm/sources/inboxes/standard')
    rows = crm.crm_settings()['check_rows']
    assert [r['source_key'] for r in rows] == ['wa-india', 'wa-india-call', 'company-call', 'wa-usa', 'usa-call',
                                               'canada-chat', 'canada-call', 'tawk', 'meta', 'telegram']
    assert rows[0]['auto'] is True and not any(r['auto'] for r in rows[1:])
