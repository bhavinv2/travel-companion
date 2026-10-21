"""Sales CRM 2.0, run 5b -- automation rules (Set-up > Automation > Rules).

    page       the Rules tab sits in the Automation strip, with "(?) How this works"; set-up only
    editor     the When / If / Then form saves only whitelisted choices; a new rule is off; mistakes are said
    engine     events run after the commit (never for a rolled-back save), once per lead per event; chains stop at
               three; a failure goes to the rule's last problem and the save stands
    actions    a task (never a follow-up step), a bell, a rating, a stage move (a system move: what a stage needs does
               not stop it, and a follow-up that would go by itself waits for a click), round robin through
               crm_assign, a signed web address that is never called without the secret -- and never a message
    time       days without activity and dates, in the jobs runner, per workspace
    guards     the recycle bin and other workspaces are never touched
    test-run   "Which open leads would this match now?" counts and shows five; nothing runs
    conflicts  check_automation_conflicts rings once when a rule's move fights a stage's own move
    migration  u8crm024 up / down / up on SQLite with rows
"""
import hashlib
import hmac
import json
import os
import re
from datetime import date, datetime, timedelta

import pytest
from flask import g

from conftest import login, logout, make_user
from app import db as _db
from app.models import (CrmLead, CrmPipeline, CrmRule, CrmRuleRun, CrmStage, CrmStageChange, CrmTask, CrmTouchpoint,
                        Notification, User, Workspace, WorkspaceTeam)
from app.services import access, crm, crm_bin, crm_money, crm_rules, crm_scope, jobs

from test_crm_wa_sync_engine import ti_lead, sh_lead


def words(html):
    return re.sub(r'\s+', ' ', re.sub(r'<script.*?</script>|<[^>]+>', ' ', html, flags=re.S))


def stage(key, pipe='ti-standard'):
    return CrmStage.query.join(CrmPipeline).filter(CrmPipeline.key == pipe, CrmStage.key == key).one()


def fresh(model, pk):
    _db.session.expire_all()
    return _db.session.get(model, pk)


def rule(name='A rule', trigger='lead_created', args=None, conds=None, actions=None, active=True, ws=None):
    r = CrmRule(name=name, trigger=trigger, trigger_args=args, conditions=conds, actions=actions or [],
                active=active, workspace_id=ws, run_count=0, position=0)
    _db.session.add(r)
    _db.session.commit()
    crm_rules.forget()
    return r


def runs(rule_id=None):
    q = CrmRuleRun.query
    if rule_id is not None:
        q = q.filter_by(rule_id=rule_id)
    return q.all()


@pytest.fixture
def agent(app):
    access.ensure_defaults()
    u = make_user('agent@test.com', 'agent', role='cs')
    return u


# ============================================================================================ the page and the editor

def test_rules_is_a_tab_of_automation_with_its_help(app, client, admin_user):
    login(client, admin_user.email)
    r = client.get('/admin/crm/rules')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    strip = words(html.split('crm-tabstrip', 1)[1].split('</nav>', 1)[0])
    assert all(t in strip for t in ('Overview', 'Rules', 'Reply rules', 'Chatbot', 'AI replies'))
    assert '(?) How this works' in html and 'never message a customer' in words(html)
    assert 'Rules' in words(client.get('/admin/crm/automatic').get_data(as_text=True).split('crm-tabstrip', 1)[1]
                            .split('</nav>', 1)[0])
    assert 'crm_rules' in access.PAGES and access.PAGES['crm_rules']['nav'] is False
    assert 'crm_rules' in access._implied(frozenset({'crm_auto'}))


def test_an_agent_cannot_open_the_rules(app, client, agent):
    login(client, agent.email)
    r = client.get('/cs/crm/rules')
    assert r.status_code in (302, 303) and '/rules' not in r.headers['Location']
    assert client.post('/cs/crm/rules/save', data={'name': 'x'}).status_code in (302, 303, 307)
    assert CrmRule.query.count() == 0


def editor_form(**kw):
    crm.ensure_defaults()
    form = {'name': 'Quoted: call in two days', 'trigger': 'stage_changed', 't_stage': str(stage('quoted').id),
            'cf_0': 'product', 'co_0': 'is', 'cv_0_product': 'TI',
            'cf_1': 'amount', 'co_1': 'gt', 'cv_1': '10000',
            'at_0': 'create_task', 'a_title_0': 'Call them about the quote', 'a_hours_0': '48', 'a_owner_0': 'lead_owner',
            'at_1': 'notify', 'a_notify_1': 'owner', 'a_text_1': 'Quote out: call in two days',
            'at_2': 'webhook', 'a_url_2': 'https://hooks.example.com/crm'}
    form.update(kw)
    return form


def test_the_editor_saves_only_whitelisted_choices_and_starts_off(app, client, admin_user):
    login(client, admin_user.email)
    r = client.post('/admin/crm/rules/save', data=editor_form())
    assert r.status_code == 302, words(r.get_data(as_text=True))[:600]
    rl = CrmRule.query.one()
    assert rl.active is False and rl.trigger == 'stage_changed'
    assert rl.trigger_args == {'to_stage_id': stage('quoted').id}
    assert rl.conditions == [{'field': 'product', 'op': 'is', 'value': 'TI'}, {'field': 'amount', 'op': 'gt', 'value': '10000'}]
    assert [a['type'] for a in rl.actions] == ['create_task', 'notify', 'webhook']
    assert rl.actions[0] == {'type': 'create_task', 'title': 'Call them about the quote', 'due_in_hours': 48,
                             'owner': 'lead_owner'}
    page = words(client.get('/admin/crm/rules').get_data(as_text=True))
    assert 'Quoted: call in two days' in page and 'Off' in page
    assert 'When a lead moves to “Travel insurance › Quoted”' in page
    assert 'Product is Travel Insurance' in page and 'is TI' not in page      # names, never the code
    # the editor shows the saved rule again
    edit = client.get('/admin/crm/rules?edit=%d' % rl.id).get_data(as_text=True)
    assert 'value="Call them about the quote"' in edit and 'name="id" value="%d"' % rl.id in edit


@pytest.mark.parametrize('bad, said', [
    ({'t_stage': '999999'}, 'Choose a stage from the list.'),
    ({'a_url_2': 'http://plain.example.com'}, 'The web address must start with https://'),
    ({'cf_0': 'password'}, 'Choose a field from the list.'),
    ({'co_1': 'contains'}, 'cannot be checked with'),
    ({'cv_1': 'lots'}, 'needs a number'),
    ({'at_0': 'send_whatsapp'}, 'Choose what to do from the list.'),
    ({'at_0': '', 'at_1': '', 'at_2': ''}, 'Add at least one thing to do.'),
])
def test_the_editor_says_what_is_wrong_and_saves_nothing(app, client, admin_user, bad, said):
    login(client, admin_user.email)
    r = client.post('/admin/crm/rules/save', data=editor_form(**bad))
    assert r.status_code == 400 and said in words(r.get_data(as_text=True))
    assert CrmRule.query.count() == 0


def test_switch_and_delete(app, client, admin_user):
    crm.ensure_defaults()
    rl = rule(active=False, actions=[{'type': 'notify', 'to': 'owner', 'text': 'x'}])
    login(client, admin_user.email)
    client.post('/admin/crm/rules/%d/switch' % rl.id, data={'on': '1'})
    assert fresh(CrmRule, rl.id).active is True
    client.post('/admin/crm/rules/%d/switch' % rl.id, data={'on': '0'})
    assert fresh(CrmRule, rl.id).active is False
    _db.session.add(CrmRuleRun(rule_id=rl.id, lead_id=ti_lead().id, event_key='created'))
    _db.session.commit()
    client.post('/admin/crm/rules/%d/delete' % rl.id)
    assert fresh(CrmRule, rl.id) is None and CrmRuleRun.query.count() == 0


# ============================================================================================ the engine

def test_a_new_lead_runs_its_rule_after_the_commit_once(app, agent):
    crm.ensure_defaults()
    rl = rule('New TI lead', conds=[{'field': 'product', 'op': 'is', 'value': 'TI'}],
              actions=[{'type': 'create_task', 'title': 'Say hello', 'due_in_hours': 2, 'owner': 'lead_owner'},
                       {'type': 'notify', 'to': 'owner', 'text': 'A new TI lead'},
                       {'type': 'set_field', 'field': 'rating', 'value': 'warm'}])
    lead = ti_lead(name='Newcomer Neha')
    lead_id = lead.id
    l = fresh(CrmLead, lead_id)
    tasks = [t for t in l.tasks if t.title == 'Say hello']
    assert len(tasks) == 1
    t = tasks[0]
    assert t.kind == 'todo' and not t.is_step and t.auto is False and t.channel == 'todo'
    assert 'Added by the rule “New TI lead”' in t.notes
    assert l.likelihood == 'warm' and l.likelihood_manual is False
    if l.owner_id:
        assert Notification.query.filter_by(user_id=l.owner_id, type='crm_rule', title='A new TI lead').count() == 1
    assert len(runs(rl.id)) == 1
    r = fresh(CrmRule, rl.id)
    assert r.run_count == 1 and r.last_run_at is not None and r.last_error is None
    # the same person again: the same lead, no second run
    ti_lead(name='Newcomer Neha')
    assert len(runs(rl.id)) == 1 and CrmLead.query.count() == 1
    # a lead the conditions leave out
    sh_lead(phone='+919800077777')
    assert len(runs(rl.id)) == 1


def test_nothing_runs_for_a_save_that_was_rolled_back(app):
    crm.ensure_defaults()
    lead = ti_lead()
    rl = rule(actions=[{'type': 'set_field', 'field': 'rating', 'value': 'hot'}])
    crm_rules.fire('lead_created', lead, 'again')
    _db.session.rollback()
    _db.session.commit()
    assert runs(rl.id) == [] and fresh(CrmLead, lead.id).likelihood is None


def test_a_rule_move_is_a_system_move_and_holds_what_would_go_by_itself(app):
    crm.ensure_defaults()
    quoted, cold = stage('quoted'), stage('cold')
    quoted.requires = ['amount', 'close_date']                 # a person would be asked for these
    _db.session.commit()
    rule('Back to cold', 'stage_changed', {'to_stage_id': stage('prospect').id},
         actions=[{'type': 'move_stage', 'stage_id': quoted.id}])
    lead = ti_lead()
    lead.amount = lead.close_date = None
    _db.session.commit()
    crm.move_stage(lead, stage('prospect'))
    _db.session.commit()
    l = fresh(CrmLead, lead.id)
    assert l.stage_id == quoted.id and l.amount is None              # "what a stage needs" did not stop it
    last = l.stage_changes[0]
    assert last.by_id is None and last.reason == 'Moved by the rule “Back to cold”'
    # moving into a stage whose first follow-up goes by itself: it is planned, but waits for a click
    assert any(s.auto for s in cold.steps)
    rule('To cold', 'stage_changed', {'to_stage_id': quoted.id}, actions=[{'type': 'move_stage', 'stage_id': cold.id}])
    lead2 = ti_lead(phone='+919800012121', name='Second Sona')
    crm.move_stage(lead2, quoted)
    _db.session.commit()
    l2 = fresh(CrmLead, lead2.id)
    assert l2.stage_id == cold.id
    planned = [t for t in l2.tasks if t.status == 'open' and t.is_step and t.created_at and t.step and t.step.stage_id == cold.id]
    assert planned and all(t.auto is False and t.note == crm_rules.HELD_NOTE for t in planned)


def test_what_a_rule_changes_is_the_systems_doing_in_history(app, client, admin_user):
    from app.models import CrmAudit
    crm.ensure_defaults()
    rule('Prospects are warm', 'stage_changed', {'to_stage_id': stage('prospect').id},
         actions=[{'type': 'set_field', 'field': 'rating', 'value': 'warm'}])
    lead = ti_lead()
    login(client, admin_user.email)
    r = client.post('/admin/crm/lead/%d/move' % lead.id, json={'stage_id': stage('prospect').id})
    assert r.status_code == 200
    _db.session.expire_all()
    rows = {a.field: a.user_id for a in CrmAudit.query.filter_by(record_type='lead', record_id=lead.id)}
    assert rows['stage_id'] == admin_user.id                 # the person's move
    assert rows['likelihood'] is None                        # the rule's change: "The system"
    assert fresh(CrmLead, lead.id).likelihood == 'warm'


def test_chains_stop_after_three(app):
    crm.ensure_defaults()
    pros, quoted = stage('prospect'), stage('quoted')
    rule('There', 'stage_changed', {'to_stage_id': pros.id}, actions=[{'type': 'move_stage', 'stage_id': quoted.id}])
    rule('And back', 'stage_changed', {'to_stage_id': quoted.id}, actions=[{'type': 'move_stage', 'stage_id': pros.id}])
    lead = ti_lead()
    crm.move_stage(lead, pros)
    _db.session.commit()
    l = fresh(CrmLead, lead.id)
    by_rules = [c for c in l.stage_changes if (c.reason or '').startswith('Moved by the rule')]
    assert len(by_rules) == crm_rules.MAX_DEPTH == 3
    assert l.stage_id == quoted.id


def test_a_changed_value_starts_its_rule_through_the_history_listener(app, agent):
    crm.ensure_defaults()
    rl = rule('Big deal', 'field_changed', {'field': 'amount'},
              conds=[{'field': 'amount', 'op': 'gt', 'value': '50000'}],
              actions=[{'type': 'notify', 'to': agent.id, 'text': 'A big deal'}])
    lead = ti_lead()
    crm_money.change_value(lead, amount='20000', currency='INR')
    _db.session.commit()
    assert runs(rl.id) == []                                 # changed, but not big enough
    lead = fresh(CrmLead, lead.id)
    crm_money.change_value(lead, amount='90000', currency='INR')
    _db.session.commit()
    assert len(runs(rl.id)) == 1
    assert Notification.query.filter_by(user_id=agent.id, title='A big deal').count() == 1


def test_won_and_lost_start_their_rules(app, agent):
    crm.ensure_defaults()
    won = rule('Won', 'won', actions=[{'type': 'notify', 'to': agent.id, 'text': 'We won one'}])
    lost = rule('Lost', 'lost', actions=[{'type': 'notify', 'to': agent.id, 'text': 'We lost one'}])
    a = ti_lead(phone='+919800000101')
    b = ti_lead(phone='+919800000102')
    crm.move_stage(a, stage('customer'))
    crm.move_stage(b, stage('prospect_fallout'), fallout_reason='Too dear')
    _db.session.commit()
    assert [r.lead_id for r in runs(won.id)] == [a.id] and [r.lead_id for r in runs(lost.id)] == [b.id]


def test_a_failure_is_written_on_the_rule_and_the_save_stands(app):
    crm.ensure_defaults()
    rl = rule('Broken', actions=[{'type': 'move_stage', 'stage_id': 987654}])
    lead = ti_lead()
    assert fresh(CrmLead, lead.id) is not None                      # the enquiry is kept
    r = fresh(CrmRule, rl.id)
    assert 'The stage of this rule was deleted.' in r.last_error and r.last_error_at is not None
    assert [x.ok for x in runs(rl.id)] == [False]                    # not tried again and again


def test_round_robin_goes_through_crm_assign_and_skips_people_away(app):
    ws = access.ensure_defaults()
    crm.ensure_defaults()
    a = make_user('rra@test.com', 'rra', role='cs')
    b = make_user('rrb@test.com', 'rrb', role='cs')
    c = make_user('rrc@test.com', 'rrc', role='cs')
    for u in (a, b, c):
        access.add_member(ws, u, role=access.system_role(ws, 'cs'))
    team = WorkspaceTeam(workspace_id=ws.id, name='Night shift')
    team.users = [a, b, c]
    _db.session.add(team)
    _db.session.commit()
    from app.services import crm_assign
    crm_assign.set_away(b, datetime.utcnow() + timedelta(days=2))
    _db.session.commit()
    rl = rule('In turn', actions=[{'type': 'assign', 'user_id': 'round_robin', 'via': 'team:%d' % team.id}])
    owners = []
    for n in range(4):
        lead = ti_lead(phone='+91980000020%d' % n, name='Turn Taker%d' % n)
        owners.append(fresh(CrmLead, lead.id).owner_id)
    assert owners == [a.id, c.id, a.id, c.id]                      # b is away
    assert fresh(CrmRule, rl.id).actions[0]['last'] == c.id


def test_the_web_address_is_signed_and_never_called_without_the_secret(app, monkeypatch):
    crm.ensure_defaults()
    called = []
    monkeypatch.setattr(crm_rules, '_post', lambda url, body, headers: called.append((url, body, headers)) or 200)
    monkeypatch.delenv('CRM_RULES_WEBHOOK_SECRET', raising=False)
    rl = rule('Tell the hub', actions=[{'type': 'webhook', 'url': 'https://hub.example.com/in'}])
    ti_lead(phone='+919800000301', email='secret.person@example.com')
    assert called == [] and fresh(CrmRule, rl.id).last_error == crm_rules.NO_SECRET
    monkeypatch.setenv('CRM_RULES_WEBHOOK_SECRET', 's3cret')
    lead = ti_lead(phone='+919800000302', email='other.person@example.com')
    assert len(called) == 1
    url, body, headers = called[0]
    assert url == 'https://hub.example.com/in'
    assert headers['X-Signature'] == hmac.new(b's3cret', body, hashlib.sha256).hexdigest()
    data = json.loads(body)
    assert data['event'] == 'lead_created' and data['lead_id'] == lead.id and data['fields']['product'] == 'TI'
    assert b'919800000302' not in body and b'other.person' not in body          # never how to reach them


def test_no_action_ever_messages_a_customer(app, agent, monkeypatch):
    crm.ensure_defaults()
    def boom(*a, **k):
        raise AssertionError('a rule sent a message')
    for name in ('send_whatsapp', 'send_step', 'send_by_hand', 'send_social', 'send_whatsapp_link'):
        monkeypatch.setattr(crm, name, boom)
    from app.services import crm_email
    monkeypatch.setattr(crm_email, 'send', boom, raising=False)
    monkeypatch.setattr(crm_rules, '_post', lambda *a, **k: 200)
    assert set(crm_rules.ACTIONS) == {'create_task', 'assign', 'set_field', 'move_stage', 'notify', 'webhook'}
    rule('Everything', actions=[
        {'type': 'create_task', 'title': 'Do it', 'due_in_hours': 0, 'owner': agent.id},
        {'type': 'assign', 'user_id': 'round_robin', 'via': ''},
        {'type': 'set_field', 'field': 'forecast', 'value': 'commit'},
        {'type': 'set_field', 'field': 'amount', 'value': '15000'},
        {'type': 'move_stage', 'stage_id': stage('cold').id},
        {'type': 'notify', 'to': 'team_lead', 'text': 'Look'},
        {'type': 'webhook', 'url': 'https://x.example.com'}])
    lead = ti_lead()
    l = fresh(CrmLead, lead.id)
    assert l.forecast == 'commit' and l.amount == 15000
    assert not CrmTouchpoint.query.filter(CrmTouchpoint.direction == 'out', CrmTouchpoint.channel == 'whatsapp').count()


# ============================================================================================ time triggers

def test_days_without_activity_run_in_the_jobs_runner_once_per_quiet_spell(app):
    crm.ensure_defaults()
    rl = rule('Gone quiet', 'no_activity', {'days': 3},
              actions=[{'type': 'create_task', 'title': 'Check on them', 'due_in_hours': 0, 'owner': 'lead_owner'}])
    quiet = ti_lead(phone='+919800000401')
    busy = ti_lead(phone='+919800000402')
    quiet.last_activity_at = datetime.utcnow() - timedelta(days=4)
    _db.session.commit()
    out = jobs.run_all()
    assert out.get('crm_rules_ran') == 1
    assert [r.lead_id for r in runs(rl.id)] == [quiet.id]
    assert crm_rules.run_time_triggers()['crm_rules_ran'] == 0      # the same quiet spell: not again
    assert CrmTask.query.filter_by(lead_id=busy.id, title='Check on them').count() == 0


def test_a_date_of_the_lead_starts_its_rule_and_old_dates_do_not(app):
    crm.ensure_defaults()
    today = (datetime.utcnow() + crm_rules.IST).date()
    rl = rule('Three days before the trip', 'date_reached', {'field': 'departure_date', 'offset': -3},
              actions=[{'type': 'set_field', 'field': 'rating', 'value': 'hot'}])
    soon = ti_lead(phone='+919800000501')
    later = ti_lead(phone='+919800000502')
    long_ago = ti_lead(phone='+919800000503')
    soon.departure_date = today + timedelta(days=3)
    later.departure_date = today + timedelta(days=20)
    long_ago.departure_date = today - timedelta(days=60)
    _db.session.commit()
    assert crm_rules.run_time_triggers()['crm_rules_ran'] == 1
    assert fresh(CrmLead, soon.id).likelihood == 'hot'
    assert fresh(CrmLead, later.id).likelihood is None and fresh(CrmLead, long_ago.id).likelihood is None


def test_a_lead_in_the_recycle_bin_is_never_acted_on(app):
    crm.ensure_defaults()
    rl = rule('Gone quiet', 'no_activity', {'days': 1}, actions=[{'type': 'set_field', 'field': 'rating', 'value': 'cold'}])
    lead = ti_lead()
    lead.last_activity_at = datetime.utcnow() - timedelta(days=5)
    _db.session.commit()
    crm_bin.remove(lead)
    assert crm_rules.run_time_triggers()['crm_rules_ran'] == 0
    # an event noted for it before it was removed is skipped too
    assert crm_rules.process([('no_activity', lead.id, 'k', {}, 0)]) == 0
    assert runs(rl.id) == []


# ============================================================================================ workspaces

def test_a_rule_of_one_workspace_never_touches_another(app):
    a = access.ensure_defaults()
    b = access.create_workspace('Bee Care')
    _db.session.commit()
    for ws in (a, b):
        with crm_scope.use(ws.id):
            crm.ensure_defaults()
    rl = rule('Only A', actions=[{'type': 'set_field', 'field': 'rating', 'value': 'hot'}], ws=a.id)
    quiet = rule('Quiet in A', 'no_activity', {'days': 1},
                 actions=[{'type': 'set_field', 'field': 'forecast', 'value': 'commit'}], ws=a.id)
    lb = crm.capture('ti-quote', name='Bee Lead', phone='+919800000601', utm={}, workspace_id=b.id)
    assert fresh(CrmLead, lb.id).likelihood is None and runs(rl.id) == []
    la = crm.capture('ti-quote', name='Ay Lead', phone='+919800000602', utm={}, workspace_id=a.id)
    assert fresh(CrmLead, la.id).likelihood == 'hot' and [r.lead_id for r in runs(rl.id)] == [la.id]
    for l in (la, lb):
        _db.session.execute(CrmLead.__table__.update().where(CrmLead.__table__.c.id == l.id)
                            .values(last_activity_at=datetime.utcnow() - timedelta(days=3)))
    _db.session.commit()
    out = jobs.run_all()
    assert out.get('crm_rules_ran') == 1
    assert fresh(CrmLead, la.id).forecast == 'commit' and fresh(CrmLead, lb.id).forecast is None
    # run_one refuses a lead of another workspace outright
    assert crm_rules.run_one(fresh(CrmRule, rl.id), fresh(CrmLead, lb.id), 'x') == 'skip'


# ============================================================================================ test-run and conflicts

def test_the_test_run_counts_and_shows_and_runs_nothing(app, client, admin_user):
    crm.ensure_defaults()
    for n in range(7):
        ti_lead(phone='+91980000070%d' % n, name='Match%d Person' % n)
    sh_lead(phone='+919800000799')
    login(client, admin_user.email)
    form = editor_form(trigger='lead_created', cf_1='', at_2='')
    r = client.post('/admin/crm/rules/test', data=form)
    html = words(r.get_data(as_text=True))
    assert r.status_code == 200 and '7 open leads would match now' in html and 'Nothing was changed' in html
    assert html.count('Match') >= 5
    assert CrmRule.query.count() == 0 and CrmRuleRun.query.count() == 0 and CrmTask.query.filter(
        CrmTask.title == 'Call them about the quote').count() == 0


def test_the_conflict_check_rings_once_when_a_rule_fights_a_stage_move(app, client, admin_user):
    crm.ensure_defaults()
    pros, quoted = stage('prospect'), stage('quoted')
    assert pros.auto_to_id                                   # Prospect moves leads on by itself
    rl = rule('Straight to quoted', 'stage_changed', {'to_stage_id': pros.id},
              actions=[{'type': 'move_stage', 'stage_id': quoted.id}])
    out = crm.check_automation_conflicts()
    assert out.get('crm_rule_conflicts') == 1
    bells = Notification.query.filter_by(user_id=admin_user.id, type='crm_rules').all()
    assert len(bells) == 1 and 'Straight to quoted' in bells[0].body and 'Prospect' in bells[0].body
    assert fresh(CrmRule, rl.id).conflict
    crm.check_automation_conflicts()
    assert Notification.query.filter_by(user_id=admin_user.id, type='crm_rules').count() == 1     # once
    login(client, admin_user.email)
    assert 'may fight a stage’s own move' in client.get('/admin/crm/rules').get_data(as_text=True)
    assert 'may fight a stage’s own move' in client.get('/admin/crm/automatic').get_data(as_text=True)
    # a loop back is a clash too
    loop = crm_rules.stage_conflicts([CrmRule(id=99, name='Loop', trigger='stage_changed',
                                              trigger_args={'to_stage_id': stage('prospect_fallout').id},
                                              actions=[{'type': 'move_stage', 'stage_id': stage('cold').id}])])
    assert loop and 'moves them back' in loop[0]['why']


# ============================================================================================ the migration

def test_migration_u8crm024_goes_up_down_up_on_sqlite_with_rows(tmp_path):
    import importlib.util
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations', 'versions',
                        'u8crm024_rules_scoring_campaigns.py')
    spec = importlib.util.spec_from_file_location('u8crm024', path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    assert mig.revision == 'u8crm024' and mig.down_revision == 'u7crm023'
    engine = sa.create_engine('sqlite:///%s' % (tmp_path / 'm.db'))
    meta = sa.MetaData()
    sa.Table('workspaces', meta, sa.Column('id', sa.Integer, primary_key=True))
    sa.Table('users', meta, sa.Column('id', sa.Integer, primary_key=True))
    sa.Table('crm_sources', meta, sa.Column('id', sa.Integer, primary_key=True))
    sa.Table('crm_leads', meta, sa.Column('id', sa.Integer, primary_key=True), sa.Column('likelihood', sa.String(4)))
    sa.Table('crm_people', meta, sa.Column('id', sa.Integer, primary_key=True))
    sa.Table('app_settings', meta, sa.Column('key', sa.String(80), primary_key=True), sa.Column('value', sa.JSON))
    meta.create_all(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO workspaces (id) VALUES (4), (9)"))
        conn.execute(sa.text("INSERT INTO crm_leads (id, likelihood) VALUES (1, 'hot'), (2, NULL)"))
        conn.execute(sa.text("INSERT INTO crm_people (id) VALUES (1)"))
        conn.execute(sa.table('app_settings', sa.column('key'), sa.column('value', sa.JSON)).insert(),
                     [{'key': 'crm', 'value': {'channels': [['Google', 'Search ads', 'Digital', 'Ongoing'],
                                                            ['', '', 'nobody', '']]}}])
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mig.upgrade()
        insp = sa.inspect(conn)
        for t in ('crm_rules', 'crm_rule_runs', 'crm_score_rules', 'crm_campaigns'):
            assert t in insp.get_table_names(), t
        assert {'score', 'likelihood_manual', 'ai_cache'} <= {c['name'] for c in insp.get_columns('crm_leads')}
        assert {'consent_marketing_at', 'consent_marketing_how', 'consent_marketing_by_id'} <= \
            {c['name'] for c in insp.get_columns('crm_people')}
        assert [u['column_names'] for u in insp.get_unique_constraints('crm_rule_runs')] == [['rule_id', 'lead_id', 'event_key']]
        assert dict(conn.execute(sa.text('SELECT id, likelihood_manual FROM crm_leads')).all()) == {1: 1, 2: 0}
        rows = conn.execute(sa.text('SELECT workspace_id, platform, name, who, status FROM crm_campaigns')).all()
        assert [tuple(r) for r in rows] == [(4, 'Google', 'Search ads', 'Digital', 'Ongoing')]
        with Operations.context(ctx):
            mig.downgrade()
        insp = sa.inspect(conn)
        assert 'crm_rules' not in insp.get_table_names() and 'crm_campaigns' not in insp.get_table_names()
        assert 'score' not in {c['name'] for c in insp.get_columns('crm_leads')}
        assert 'consent_marketing_at' not in {c['name'] for c in insp.get_columns('crm_people')}
        with Operations.context(ctx):
            mig.upgrade()
        assert 'crm_rules' in sa.inspect(conn).get_table_names()
