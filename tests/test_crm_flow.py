"""Visual Flow (E26): the whole CRM lifecycle on one screen, and for the customers picked, where each one is,
how they got there and what to do next.

    access   it comes with My day, Leads or Contacts -- never granted on its own, never on the Roles screen
    guide    with nobody picked: the lifecycle and every active pipeline, stage by stage
    people   a card each: the next follow-up, the next stage, the path with its reasons
    links    the lead page shows it, and the lead page's sections can be linked to
"""
from datetime import datetime, timedelta
from html import unescape

import pytest

from conftest import login
from app import db as _db
from app.models import CrmPipeline, CrmTask, WorkspaceMember, WorkspaceRole
from app.services import access, crm

from test_crm_wa_sync_engine import PHONE, stage, ti_lead


def lead(phone=PHONE, **kw):
    return ti_lead(phone, plan=False, notify=False, sync=False, **kw)


def give_role(ws, user, pages):
    r = WorkspaceRole(workspace_id=ws.id, name='Only ' + ' '.join(pages), pages=pages)
    _db.session.add(r)
    WorkspaceMember.query.filter_by(workspace_id=ws.id, user_id=user.id).one().role = r
    _db.session.commit()


def menu(html):
    return html.split('admin-nav-items', 1)[1].split('</nav>', 1)[0]


def card(html, person_id):
    return html.split('id="who-%d"' % person_id, 1)[1].split('</article>', 1)[0]


# ============================================================================================ access

def test_it_comes_with_working_leads_and_is_never_granted_on_its_own(client, app, cs_user):
    ws = access.ensure_defaults()
    login(client, cs_user.email)
    for pages in (['crm_board'], ['crm_today'], ['crm_people']):
        give_role(ws, cs_user, pages)
        r = client.get('/cs/crm/flow')
        assert r.status_code == 200, pages
        assert 'Visual flow' in r.data.decode() and 'data-title="Visual flow"' not in menu(r.data.decode()), pages
    give_role(ws, cs_user, ['home'])
    assert client.get('/cs/crm/flow').status_code == 302
    assert client.get('/cs/crm/flow/find?q=Ramesh').status_code == 302
    assert 'Visual flow' not in menu(client.get('/cs/').data.decode())


def test_the_roles_screen_does_not_offer_it_and_a_save_does_not_store_it(client, app, admin_user, cs_user):
    ws = access.ensure_defaults()
    login(client, admin_user.email)
    page = client.get('/admin/workspace/roles/%d' % access.system_role(ws, 'cs').id).data.decode()
    assert 'value="crm_people"' in page and 'value="crm_flow"' not in page
    client.post('/admin/workspace/roles/save', data={'name': 'Sales', 'pages': ['crm_board', 'crm_flow']})
    assert WorkspaceRole.query.filter_by(name='Sales').one().pages == ['crm_board']


def test_travellers_cannot_open_it(client, app, user):
    login(client, user.email)
    assert client.get('/cs/crm/flow').status_code in (302, 403)
    assert client.get('/cs/crm/flow/find?q=Ramesh').status_code in (302, 403)


# ============================================================================================ the guide

def test_with_nobody_picked_it_is_the_whole_lifecycle_stage_by_stage(client, app, cs_user):
    crm.ensure_defaults()
    login(client, cs_user.email)
    html = unescape(client.get('/cs/crm/flow').data.decode())
    assert 'The CRM lifecycle, end to end' in html
    for p in CrmPipeline.query.filter_by(is_active=True):
        assert 'id="flow-%s"' % p.key in html
        for st in p.stages:
            assert 'id="st-%d"' % st.id in html, (p.key, st.key)
    st = next(s for p in CrmPipeline.query.order_by(CrmPipeline.id) for s in p.stages if s.steps)
    assert crm.step_sentence(st.steps[0]) in html
    auto = next((s for p in CrmPipeline.query for s in p.stages if s.auto_kind and s.auto_to), None)
    if auto is not None:
        assert 'It %s.' % crm.auto_sentence(auto) in html
    ti = CrmPipeline.query.filter_by(key='ti-standard').one()
    assert all(r in html for r in ti.fallout_reasons)


# ============================================================================================ people

def test_a_customer_card_says_what_to_do_next_and_how_they_got_here(client, app, cs_user):
    l = lead()
    crm.move_stage(l, stage('ti-standard', 'prospect'), reason='They replied', plan=False, sync=False)
    _db.session.add(CrmTask(lead_id=l.id, title='Follow up on the quote', channel='whatsapp',
                            due_at=datetime.utcnow() - timedelta(hours=2)))
    _db.session.commit()
    login(client, cs_user.email)
    html = unescape(client.get('/cs/crm/flow?person_id=%d' % l.person_id).data.decode())
    c = card(html, l.person_id)
    assert 'Do this next' in c and 'Follow up on the quote' in c and 'was due' in c
    assert 'flow-next late' in html.split('id="who-%d"' % l.person_id, 1)[1]
    assert '/cs/crm/lead/%d#box' % l.id in c
    assert 'Next stage: <b>Quoted</b>' in c
    assert 'Came in' in c and '“They replied”' in c
    strip = html.split('id="flow-ti-standard"', 1)[1].split('flow-guide-wrap', 1)[0]
    here = strip.split('#st-%d"' % stage('ti-standard', 'prospect').id, 1)[1].split('flow-stage ', 1)[0]
    assert '/cs/crm/lead/%d#journey' % l.id in here
    # the pipeline they are in comes first, with its step-by-step guide open
    assert html.index('id="flow-ti-standard"') < html.index('id="flow-general"')
    assert '<details class="flow-guide-wrap" open>' in html.split('id="flow-ti-standard"', 1)[1].split('</section>', 1)[0]


def test_a_lost_lead_says_why_and_how_to_bring_it_back(client, app, cs_user):
    l = lead()
    crm.move_stage(l, stage('ti-standard', 'prospect_fallout'), fallout_reason='Price too high', plan=False, sync=False)
    _db.session.commit()
    login(client, cs_user.email)
    c = card(unescape(client.get('/cs/crm/flow?person_id=%d' % l.person_id).data.decode()), l.person_id)
    assert 'Closed as lost: Price too high.' in c and 'Work on it again' in c and 'Do this next' not in c


def test_several_people_at_once_and_the_search_finds_only_people(client, app, cs_user):
    a, b = lead(), lead('+919811111111', name='Sita Devi')
    login(client, cs_user.email)
    html = client.get('/cs/crm/flow?person_id=%d&person_id=%d&person_id=999999' % (a.person_id, b.person_id)).data.decode()
    assert 'id="who-%d"' % a.person_id in html and 'id="who-%d"' % b.person_id in html
    assert html.count('class="flow-person"') == 2                       # an unknown id is left out
    assert [i['name'] for i in client.get('/cs/crm/flow/find?q=Sita').get_json()['items']] == ['Sita Devi']
    assert client.get('/cs/crm/flow/find?q=S').get_json() == {'items': []}


# ============================================================================================ links

def test_the_lead_page_shows_it_and_its_sections_can_be_linked_to(client, app, cs_user):
    l = lead()
    login(client, cs_user.email)
    html = client.get('/cs/crm/lead/%d' % l.id).data.decode()
    assert '/cs/crm/flow?person_id=%d' % l.person_id in html
    for anchor in ('id="journey"', 'id="conversation"', 'id="box"'):
        assert anchor in html
