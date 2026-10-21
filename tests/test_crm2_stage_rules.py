"""Sales CRM 2.0, run 3b -- what a stage needs before a lead moves in.

    editor     "Before a lead moves here, ask for" saves CrmStage.requires (built-in fields and the pipeline's own)
    a move     a person's move (drag, stage bar, milestone button) with something missing is answered with what it
               needs; posting the values moves it; filled-in leads move straight away
    in bulk    Move to... skips the leads that miss values and says how many, with a link to exactly those
    by itself  jobs, replies and "lost by no reply" are never blocked
"""
import re
from datetime import date, datetime, timedelta

import pytest

from conftest import login, make_user
from app import db as _db
from app.models import CrmField, CrmLead, CrmPipeline, CrmStage
from app.services import crm, crm_stage_rules

from test_crm_pipelines_custom import posted, save
from test_crm_wa_sync_engine import ti_lead


def words(html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html))


def stage(key):
    return CrmStage.query.join(CrmPipeline).filter(CrmPipeline.key == 'ti-standard', CrmStage.key == key).one()


@pytest.fixture
def agent(app):
    return make_user('agent@test.com', 'agent', role='cs')


@pytest.fixture
def lead(app, agent):
    l = ti_lead(phone='+919876533331', name='Needy Nita')
    l.owner_id = agent.id
    _db.session.commit()
    return l


def need(key, *fields):
    st = stage(key)
    st.requires = list(fields)
    _db.session.commit()
    return st


# ====================================================================================== the editor

def test_the_editor_asks_what_a_stage_needs_and_saves_it(app, client, admin_user):
    crm.ensure_defaults()
    pipe = CrmPipeline.query.filter_by(key='ti-standard').one()
    login(client, admin_user.email)
    page = client.get('/admin/crm/pipelines/%d' % pipe.id).get_data(as_text=True)
    assert 'Before a lead moves here, ask for' in words(page)
    for label in ('Value', 'Close date', 'Travels on', 'Cover ends'):
        assert label in words(page)
    quoted = stage('quoted')
    data = posted(pipe)
    for s in data['stages']:
        if s['id'] == quoted.id:
            s['requires'] = ['amount', 'close_date', 'not_a_field', 'amount']
    r = save(client, pipe, data)
    assert r.status_code == 200, r.get_data(as_text=True)
    _db.session.expire_all()
    assert stage('quoted').requires == ['amount', 'close_date']                 # unknown and repeated keys dropped
    # a payload that says nothing leaves it alone; an empty list clears it
    assert save(client, pipe, posted(pipe)).status_code == 200
    _db.session.expire_all()
    assert stage('quoted').requires == ['amount', 'close_date']
    data = posted(pipe)
    for s in data['stages']:
        if s['id'] == quoted.id:
            s['requires'] = []
    assert save(client, pipe, data).status_code == 200
    _db.session.expire_all()
    assert not stage('quoted').requires


def test_the_pipelines_own_fields_can_be_asked_for_too(app, client, admin_user):
    crm.ensure_defaults()
    pipe = CrmPipeline.query.filter_by(key='ti-standard').one()
    f = CrmField(pipeline_id=pipe.id, key='passport_no', label='Passport number', type='text')
    _db.session.add(f)
    _db.session.commit()
    assert 'passport_no' in [k for k, _, _ in crm_stage_rules.choices(pipe)]
    login(client, admin_user.email)
    assert 'Passport number' in words(client.get('/admin/crm/pipelines/%d' % pipe.id).get_data(as_text=True))
    data = posted(pipe)
    for s in data['stages']:
        if s['id'] == stage('quoted').id:
            s['requires'] = ['passport_no']
    assert save(client, pipe, data).status_code == 200
    _db.session.expire_all()
    assert stage('quoted').requires == ['passport_no']


# ====================================================================================== a person's move

def test_a_move_with_something_missing_asks_for_it(app, client, lead, agent):
    quoted = need('quoted', 'amount', 'close_date')
    lead.close_date = None
    lead.amount = None
    _db.session.commit()
    login(client, agent.email)
    before = lead.stage_id
    r = client.post('/cs/crm/lead/%d/move' % lead.id, json={'stage_id': quoted.id})
    assert r.status_code == 400
    d = r.get_json()
    assert [m['key'] for m in d['need_fields']] == ['amount', 'close_date']
    assert d['stage_name'] == quoted.name and 'we need' in d['error']
    _db.session.expire_all()
    assert _db.session.get(CrmLead, lead.id).stage_id == before                    # it did not move


def test_posting_the_values_moves_it_and_stores_them(app, client, lead, agent):
    quoted = need('quoted', 'amount', 'close_date', 'departure_date')
    lead.close_date = lead.amount = lead.departure_date = None
    _db.session.commit()
    login(client, agent.email)
    r = client.post('/cs/crm/lead/%d/move' % lead.id,
                    json={'stage_id': quoted.id, 'fields': {'amount': '18500', 'close_date': '2031-05-01',
                                                            'departure_date': '2031-05-04'}})
    assert r.status_code == 200, r.get_data(as_text=True)
    _db.session.expire_all()
    l = _db.session.get(CrmLead, lead.id)
    assert l.stage_id == quoted.id and str(l.amount) == '18500.00'
    assert l.close_date == date(2031, 5, 1) and l.departure_date == date(2031, 5, 4)


def test_a_wrong_value_or_a_partial_answer_moves_nothing(app, client, lead, agent):
    quoted = need('quoted', 'amount', 'close_date')
    lead.close_date = lead.amount = None
    _db.session.commit()
    login(client, agent.email)
    before = lead.stage_id
    r = client.post('/cs/crm/lead/%d/move' % lead.id, json={'stage_id': quoted.id, 'fields': {'amount': 'lots'}})
    assert r.status_code == 400 and r.get_json()['need_fields']
    r = client.post('/cs/crm/lead/%d/move' % lead.id, json={'stage_id': quoted.id, 'fields': {'amount': '500'}})
    assert r.status_code == 400 and [m['key'] for m in r.get_json()['need_fields']] == ['close_date']
    r = client.post('/cs/crm/lead/%d/move' % lead.id,
                    json={'stage_id': quoted.id, 'fields': {'amount': '500', 'close_date': 'tomorrow'}})
    assert r.status_code == 400
    _db.session.expire_all()
    l = _db.session.get(CrmLead, lead.id)
    assert l.stage_id == before and l.amount is None                              # nothing half-saved


def test_a_lead_that_has_everything_moves_straight_away(app, client, lead, agent):
    quoted = need('quoted', 'amount')
    lead.amount = 900
    _db.session.commit()
    login(client, agent.email)
    assert client.post('/cs/crm/lead/%d/move' % lead.id, json={'stage_id': quoted.id}).status_code == 200


def test_a_stage_that_needs_nothing_is_untouched(app, client, lead, agent):
    quoted = stage('quoted')
    assert not quoted.requires
    login(client, agent.email)
    assert client.post('/cs/crm/lead/%d/move' % lead.id, json={'stage_id': quoted.id}).status_code == 200


def test_a_custom_field_is_asked_for_and_kept_on_the_lead(app, client, lead, agent):
    pipe = CrmPipeline.query.filter_by(key='ti-standard').one()
    _db.session.add(CrmField(pipeline_id=pipe.id, key='passport_no', label='Passport number', type='text'))
    _db.session.commit()
    quoted = need('quoted', 'passport_no')
    login(client, agent.email)
    r = client.post('/cs/crm/lead/%d/move' % lead.id, json={'stage_id': quoted.id})
    assert r.status_code == 400 and r.get_json()['need_fields'][0]['label'] == 'Passport number'
    r = client.post('/cs/crm/lead/%d/move' % lead.id, json={'stage_id': quoted.id, 'fields': {'passport_no': 'P1234567'}})
    assert r.status_code == 200
    _db.session.expire_all()
    assert _db.session.get(CrmLead, lead.id).details['passport_no'] == 'P1234567'


def test_a_milestone_button_goes_through_the_same_check(app, client, lead, agent):
    quoted = stage('quoted')
    assert quoted.button_label                                                     # "Did you send the quote?"
    quoted.requires = ['amount']
    lead.amount = None
    _db.session.commit()
    login(client, agent.email)
    r = client.post('/cs/crm/lead/%d/move' % lead.id, json={'stage_id': quoted.id, 'log_milestone': True})
    assert r.status_code == 400 and r.get_json()['need_fields']
    r = client.post('/cs/crm/lead/%d/move' % lead.id,
                    json={'stage_id': quoted.id, 'log_milestone': True, 'fields': {'amount': '7000'}})
    assert r.status_code == 200 and r.get_json()['logged'] is True


# ====================================================================================== in bulk

def test_bulk_move_skips_the_leads_that_miss_values_and_links_to_them(app, client, agent, admin_user):
    crm.ensure_defaults()
    quoted = need('quoted', 'amount')
    ok = ti_lead(phone='+919876533341', name='Has Amount')
    ok.amount = 100
    no1 = ti_lead(phone='+919876533342', name='Lacks One')
    no2 = ti_lead(phone='+919876533343', name='Lacks Two')
    _db.session.commit()
    login(client, admin_user.email)
    r = client.post('/admin/crm/leads/bulk', json={'lead_ids': [ok.id, no1.id, no2.id], 'action': 'move',
                                                   'stage_id': quoted.id})
    d = r.get_json()
    assert r.status_code == 200 and d['done'] == 1 and d['not_moved'] == 2
    assert '2 not moved: they need value' in d['message']
    assert 'ids=%d,%d' % (no1.id, no2.id) in d['not_moved_url']
    _db.session.expire_all()
    assert _db.session.get(CrmLead, ok.id).stage_id == quoted.id
    assert _db.session.get(CrmLead, no1.id).stage_id != quoted.id
    # the link opens a list of exactly those leads
    page = client.get(d['not_moved_url']).get_data(as_text=True)
    assert 'Lacks One' in page and 'Lacks Two' in page and 'Has Amount' not in page
    assert 'that were not moved' in words(page)


# ====================================================================================== by itself

def test_what_the_system_does_by_itself_is_never_blocked(app, lead):
    quoted = need('quoted', 'amount', 'close_date')
    lead.amount = lead.close_date = None
    _db.session.commit()
    assert crm.move_stage(lead, quoted, user=None, reason='Replied') is True        # replies, jobs, no-reply losses
    _db.session.commit()
    assert lead.stage_id == quoted.id


def test_a_stage_automation_still_moves_a_lead_into_a_stage_that_needs_values(app, lead):
    cold = stage('cold')
    prospect = need('prospect', 'amount')
    cold.auto_kind, cold.auto_days, cold.auto_to_id = 'in_stage', 1, prospect.id
    lead.amount = None
    lead.entered_stage_at = datetime.utcnow() - timedelta(days=3)
    _db.session.commit()
    assert lead.stage_id == cold.id
    crm.run_stage_automations()
    _db.session.expire_all()
    assert _db.session.get(CrmLead, lead.id).stage_id == prospect.id


def test_the_dialog_script_is_shipped(app):
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = open(os.path.join(root, 'app', 'static', 'js', 'crm.js'), encoding='utf-8').read()
    assert 'need_fields' in js and 'askFields' in js and 'not_moved_url' in js
