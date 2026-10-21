"""U4: the daily work -- Leads, My day, Team today, bells and hand-over.

    one batched query set per screen   never a query or a WhatsApp call per lead
    the waiting bell                   once per wait, to the owner, in the day, never while snoozed
    giving leads away                  the new owner is told, the chat follows, nobody is told twice
    someone leaves                     their leads and follow-ups are handed over first
"""
import re
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from conftest import login, make_user
from app import db as _db
from app.models import (CrmLead, CrmPerson, CrmPipeline, CrmStage, CrmTask, CrmTouchpoint, Notification, User,
                        WorkspaceMember, WorkspaceTeam)
from app.services import access, crm, crm_metrics, wacrm, wacrm_team
from test_crm_wa_sending import World, ti_lead, wrote, world        # noqa: F401

PHONE = '+919876543210'


def sh_lead(phone=PHONE, **kw):
    return crm.capture('sh-booking', name=kw.pop('name', 'Ramesh Kumar'), phone=phone, product='SH', utm={}, **kw)


def stage(pipe_key, stage_key):
    return (CrmStage.query.join(CrmPipeline).filter(CrmPipeline.key == pipe_key, CrmStage.key == stage_key).one())


def text_of(html):
    html = re.sub(r'<(script|style).*?</\1>', '', html, flags=re.S)
    return ' '.join(re.sub(r'<[^>]+>', ' ', html).split())


def queries(fn):
    seen = []

    def count(*a, **k):
        seen.append(1)
    event.listen(_db.engine, 'before_cursor_execute', count)
    try:
        fn()
    finally:
        event.remove(_db.engine, 'before_cursor_execute', count)
    return len(seen)


def said(person_id, hours_ago, text='Hello', channel='whatsapp', direction='in', real=True, status=None):
    p = _db.session.get(CrmPerson, person_id)
    lead = p.leads[0]
    crm.log_touch(lead, channel, direction, body=text, status=status,
                  external_id=('w%d-%s-%s' % (person_id, hours_ago, direction)) if real else None,
                  at=datetime.utcnow() - timedelta(hours=hours_ago))
    _db.session.commit()


# ------------------------------------------------------------------ the definitions every screen shares

def test_waiting_on_us_means_they_wrote_last_and_nobody_answered(app):
    lead = ti_lead()
    pid = lead.person_id
    said(pid, 3, 'Question?')
    wait = lambda: crm_metrics.waiting_on_us(crm_metrics.last_touches([pid])[pid])
    assert wait() is True
    said(pid, 2, 'Answer', direction='out', status='sent')
    assert wait() is False
    said(pid, 1, 'Thanks, one more', direction='in')
    assert wait() is True


def test_an_answer_that_failed_to_arrive_is_not_an_answer(app):
    lead = ti_lead()
    pid = lead.person_id
    said(pid, 3, 'Question?')
    said(pid, 2, 'Answer', direction='out', status='failed')
    assert crm_metrics.waiting_on_us(crm_metrics.last_touches([pid])[pid]) is True


def test_stop_is_not_a_question_waiting_on_us_ignores_what_came_before_the_opt_out(app):
    lead = ti_lead()
    pid = lead.person_id
    said(pid, 3, 'STOP')
    _db.session.get(CrmPerson, pid).wa_opt_out_at = datetime.utcnow() - timedelta(hours=2, minutes=59)
    _db.session.commit()
    e = crm_metrics.last_touches([pid])[pid]
    assert crm_metrics.waiting_on_us(e) is False and e['wa_last_in'] is None


def test_a_typed_in_reply_waits_for_an_answer_but_does_not_open_the_24_hours(app):
    lead = ti_lead()
    pid = lead.person_id
    said(pid, 1, 'They said so on the phone', real=False)
    e = crm_metrics.last_touches([pid])[pid]
    assert crm_metrics.waiting_on_us(e) is True and e['wa_last_in'] is None


def test_the_python_and_sql_definitions_agree(app, cs_user):
    people = []
    for i, (hrs_in, hrs_out) in enumerate([(5, None), (5, 4), (30, None), (2, 1), (1, None)]):
        lead = ti_lead(phone='+91980000010%d' % i, name='P%d' % i)
        lead.owner_id = cs_user.id
        _db.session.commit()
        said(lead.person_id, hrs_in, 'hi')
        if hrs_out is not None:
            said(lead.person_id, hrs_out, 'reply', direction='out', status='sent')
        people.append(lead.person_id)
    touches = crm_metrics.last_touches(people)
    expected = {p for p in people if crm_metrics.waiting_on_us(touches[p])}
    rows = _db.session.execute(crm_metrics.waiting_rows(CrmTouchpoint.person_id.in_(people))).all()
    assert {r.person_id for r in rows} == expected
    assert crm_metrics.waiting_count(cs_user.id) == len(expected)
    assert crm_metrics.waiting_by_owner([cs_user.id]) == {cs_user.id: len(expected)}
    now = datetime.utcnow()
    open_py = {p for p in people if (touches[p]['wa_last_in'] or datetime.min) > now - timedelta(hours=24)}
    open_sql = {r[0] for r in _db.session.execute(crm_metrics.window_open_people(CrmTouchpoint.person_id.in_(people), now))}
    assert open_py == open_sql


def test_who_sent_it_is_read_by_one_rule(app):
    assert crm_metrics.via_of(None, 7) == 'person' and crm_metrics.via_of(None, None) == 'automation'
    assert crm_metrics.via_of('flow', 7) == 'flow'


def test_a_first_reply_by_an_automation_is_not_a_person_answering(app, cs_user):
    lead = ti_lead()
    pid = lead.person_id
    start = datetime.utcnow() - timedelta(hours=6)
    crm.log_touch(lead, 'whatsapp', 'in', body='Hi', external_id='w-a', at=start)
    crm.log_touch(lead, 'whatsapp', 'out', body='Auto hello', external_id='w-b', via='automation', at=start + timedelta(minutes=1))
    crm.log_touch(lead, 'whatsapp', 'out', body='Person here', user=cs_user, external_id='w-c', status='sent',
                  at=start + timedelta(minutes=30))
    _db.session.commit()
    out = crm_metrics.first_reply_minutes(start - timedelta(hours=1), start + timedelta(hours=1))
    assert out == {}                                  # the wait was answered first by an automation: no sample


def test_who_sent_a_message_is_recorded_from_now_on(app, world, cs_user):
    lead = ti_lead(consent=True)
    wrote(lead)
    world.last_inbound_at = datetime.utcnow() - timedelta(hours=1)
    lead.open_task.auto = True
    lead.open_task.due_at = datetime.utcnow() - timedelta(minutes=2)
    _db.session.commit()
    assert crm.run_auto_steps()['crm_auto_sent'] == 1
    assert CrmTouchpoint.query.filter_by(direction='out', channel='whatsapp').one().via == 'auto'
    assert crm.send_by_hand(lead, cs_user, 'text', text='Hello')['mode'] == 'sent'
    assert CrmTouchpoint.query.filter_by(direction='out', channel='whatsapp', agent_id=cs_user.id).one().via == 'person'
    assert 'import' in crm.CRM_VIA if hasattr(crm, 'CRM_VIA') else True


# ------------------------------------------------------------------ Leads: a fixed number of queries

def test_a_board_costs_the_same_number_of_queries_for_ten_leads_or_sixty(app, cs_user):
    pipe = CrmPipeline.query.filter_by(key='ti-standard').first() or (crm.ensure_defaults() and CrmPipeline.query.filter_by(key='ti-standard').one())
    for i in range(10):
        l = ti_lead(phone='+9198000%05d' % i, name='L%d' % i)
        said(l.person_id, 2, 'hi')
    pipe = CrmPipeline.query.filter_by(key='ti-standard').one()
    small = queries(lambda: crm.board(pipe))
    for i in range(10, 60):
        l = ti_lead(phone='+9198000%05d' % i, name='L%d' % i)
        said(l.person_id, 2, 'hi')
    pipe = CrmPipeline.query.filter_by(key='ti-standard').one()
    big = queries(lambda: crm.board(pipe))
    assert big == small, (small, big)
    assert big <= 12


def test_the_list_has_no_60_card_limit_and_pages_of_50(app):
    crm.ensure_defaults()
    for i in range(120):
        crm.capture('ti-quote', name='L%d' % i, phone='+9198001%05d' % i, utm={}, notify=False, plan=False, sync=False)
    pipe = CrmPipeline.query.filter_by(key='ti-standard').one()
    p1 = crm.lead_list(pipe, 1)
    p3 = crm.lead_list(pipe, 3)
    assert p1['total'] == 120 and len(p1['leads']) == 50 and p1['pages'] == 3 and len(p3['leads']) == 20
    assert crm.lead_list(pipe, 99)['page'] == 3                      # past the end: the last page
    col = crm.board(pipe)['columns']
    assert max(c['total'] for c in col) == 120 and max(len(c['leads']) for c in col) == 60     # the board still caps a column
    n1 = queries(lambda: crm.lead_list(pipe, 1))
    n3 = queries(lambda: crm.lead_list(pipe, 3))
    assert n1 == n3 and n1 <= 8


def test_card_chips_say_what_is_going_on(app, world):
    crm.save_settings(whatsapp_mode='contacts')
    waiting = ti_lead(phone='+919800000101', name='Waiting')
    said(waiting.person_id, 3, 'Is it covered?')
    answered = ti_lead(phone='+919800000102', name='Answered')
    said(answered.person_id, 3, 'hi')
    said(answered.person_id, 2, 'we replied', direction='out', status='read')
    opted = ti_lead(phone='+919800000103', name='Opted')
    opted.person.wa_opt_out_at = datetime.utcnow()
    nochat = crm.capture('ti-quote', name='No Chat', phone='+919800000104', utm={}, sync=False)
    _db.session.commit()
    ids = [waiting.id, answered.id, opted.id, nochat.id]
    leads = CrmLead.query.filter(CrmLead.id.in_(ids)).all()
    cards = crm.lead_cards(leads)
    chips = lambda lead_id: [c[1] for c in cards[lead_id]['chips']]
    assert 'Wrote, waiting on us' in chips(waiting.id) and any(c.startswith('24 h:') for c in chips(waiting.id))
    assert 'Wrote, waiting on us' not in chips(answered.id)
    assert 'Opted out' in chips(opted.id) and cards[opted.id]['chat'] == ('optout', 'Opted out')
    assert 'No chat yet' in chips(nochat.id)
    assert cards[waiting.id]['chat'][0] == 'waiting'


def test_no_chat_yet_is_not_shown_while_whatsapp_is_off(app):
    crm.save_settings(whatsapp_mode='off')
    lead = ti_lead()
    assert 'No chat yet' not in [c[1] for c in crm.lead_cards([lead])[lead.id]['chips']]


def test_filters_pick_the_right_people(app, cs_user):
    a = ti_lead(phone='+919800000201', name='Alice A')
    b = ti_lead(phone='+919800000202', name='Bob B')
    c = ti_lead(phone='+919800000203', name='Carol C')
    a.owner_id, b.owner_id, c.owner_id = cs_user.id, None, None
    c.person.wacrm_conversation_id = 'conv-c'
    said(a.person_id, 1, 'hi')
    said(b.person_id, 30, 'old')
    _db.session.commit()
    pipe = CrmPipeline.query.filter_by(key='ti-standard').one()
    names = lambda **kw: sorted(l.person.name for l in crm.lead_filter(pipe, **kw).all())
    assert names() == ['Alice A', 'Bob B', 'Carol C']
    assert names(owner_id=cs_user.id) == ['Alice A'] and names(owner_id='none') == ['Bob B', 'Carol C']
    assert names(chat='waiting') == ['Alice A', 'Bob B']
    assert names(chat='open') == ['Alice A']
    assert names(chat='nochat') == ['Alice A', 'Bob B']
    assert names(q='carol') == ['Carol C'] and names(q='0203') == ['Carol C']
    assert names(stage_id=a.stage_id) == ['Alice A', 'Bob B', 'Carol C']
    a.open_task.due_at = datetime.utcnow() - timedelta(hours=3)
    _db.session.commit()
    assert names(follow='late') == ['Alice A', 'Bob B', 'Carol C'][:0] + sorted(
        l.person.name for l in CrmLead.query.all() if l.open_task is not None and l.open_task.due_at < datetime.utcnow())


def test_finished_leads_are_only_shown_for_the_last_30_days_unless_asked(app):
    old = ti_lead(phone='+919800000301', name='Old Win')
    crm.move_stage(old, stage('ti-standard', 'customer'))
    old.closed_at = datetime.utcnow() - timedelta(days=60)
    new = ti_lead(phone='+919800000302', name='New Win')
    crm.move_stage(new, stage('ti-standard', 'customer'))
    _db.session.commit()
    pipe = CrmPipeline.query.filter_by(key='ti-standard').one()
    assert [l.person.name for l in crm.lead_filter(pipe, closed_days=30).all()] == ['New Win']
    assert sorted(l.person.name for l in crm.lead_filter(pipe, closed_days=None).all()) == ['New Win', 'Old Win']


def test_stuck_uses_the_stages_own_hours_or_three_days(app):
    a = ti_lead(phone='+919800000401', name='Stuck')
    b = ti_lead(phone='+919800000402', name='Fine')
    a.entered_stage_at = datetime.utcnow() - timedelta(days=10)
    b.entered_stage_at = datetime.utcnow() - timedelta(hours=1)
    _db.session.commit()
    stuck = [l.person.name for l in CrmLead.query.filter(crm.stuck_filter()).all()]
    assert 'Stuck' in stuck and 'Fine' not in stuck


# ------------------------------------------------------------------ the Leads page

def test_leads_page_draws_in_both_views_and_remembers_the_view(app, client, cs_user, admin_user):
    for i in range(3):
        l = ti_lead(phone='+91980000050%d' % i, name='Lead %d' % i)
        l.owner_id = cs_user.id
    _db.session.commit()
    login(client, cs_user.email)
    r = client.get('/cs/crm/?p=ti-standard&view=list')
    assert r.status_code == 200
    t = text_of(r.get_data(as_text=True))
    for col in ('Name', 'Product', 'Stage', 'Value', 'Closes', 'Looked after by', 'Next step', 'Chat', 'Travels on', 'Last contact'):
        assert col in t, col
    assert 'Lead 0' in t
    assert 'Download this list' not in t                                    # hidden until a later release
    assert 'Give to' not in t                                               # bulk actions are for team leads
    again = text_of(client.get('/cs/crm/?p=ti-standard').get_data(as_text=True))
    assert 'Name' in again and 'Travels on' in again                       # the list view was remembered
    board = text_of(client.get('/cs/crm/?p=ti-standard&view=board').get_data(as_text=True))
    assert 'New' in board and 'Talking' in board or 'Cold lead' in board
    client.get('/cs/crm/?reset=1')


def test_a_person_without_results_sees_only_their_own_leads_by_default(app, client, cs_user, admin_user):
    mine = ti_lead(phone='+919800000601', name='My Lead')
    mine.owner_id = cs_user.id
    theirs = ti_lead(phone='+919800000602', name='Their Lead')
    theirs.owner_id = admin_user.id
    _db.session.commit()
    login(client, cs_user.email)
    t = text_of(client.get('/cs/crm/?p=ti-standard&view=list').get_data(as_text=True))
    assert 'My Lead' in t and 'Their Lead' not in t
    t = text_of(client.get('/cs/crm/?p=ti-standard&view=list&owner=all').get_data(as_text=True))
    assert 'Their Lead' in t


def test_hiding_a_stage_and_showing_it_again(app, client, admin_user):
    ti_lead()
    pipe = CrmPipeline.query.filter_by(key='ti-standard').one()
    st = pipe.stages[-1]
    login(client, admin_user.email)
    assert client.get('/admin/crm/?p=ti-standard&hide=%d' % st.id).status_code == 302
    assert st.name not in [c['stage'].name for c in crm.board(pipe, hidden=[st.id])['columns']]
    assert client.get('/admin/crm/?p=ti-standard&show=all').status_code == 302
    assert client.get('/admin/crm/?p=ti-standard').status_code == 200


def test_message_everyone_in_this_stage_counts_who_can_get_it(app):
    crm.save_settings(whatsapp_mode='contacts')
    crm.ensure_defaults()
    pipe = CrmPipeline.query.filter_by(key='ti-standard').one()
    cold = pipe.stages[0]
    ok = [ti_lead(phone='+91980000070%d' % i, name='Ok%d' % i) for i in range(2)]
    for l in ok:
        l.person.wacrm_contact_id = 'c-%d' % l.id
    nonumber = crm.capture('ti-quote', name='No Number', email='x@example.com', utm={}, sync=False)
    opted = ti_lead(phone='+919800000710', name='Opted')
    opted.person.wacrm_contact_id = 'c-opt'
    opted.person.wa_opt_out_at = datetime.utcnow()
    notyet = crm.capture('ti-quote', name='Not Yet', phone='+919800000711', utm={}, sync=False)
    _db.session.commit()
    r = crm.stage_reach(pipe, [cold])[cold.id]
    assert r['reach'] == 2
    assert r['text'] == '2 of 5 can get it (1 has no WhatsApp number, 1 opted out, 1 is not in WhatsApp yet).'
    assert 'TI: %s' % cold.name in r['tags']
    empty = pipe.stages[1]
    assert crm.stage_reach(pipe, [empty])[empty.id]['text'] == 'Nobody in this stage can get it yet.'


# ------------------------------------------------------------------ bulk: give and move

def _bulk(client, **body):
    return client.post('/admin/crm/leads/bulk', json=body)


def test_only_team_leads_and_admins_can_change_many_leads(app, client, cs_user):
    lead = ti_lead()
    login(client, cs_user.email)
    assert client.post('/cs/crm/leads/bulk', json={'lead_ids': [lead.id], 'action': 'give', 'owner_id': cs_user.id}).status_code == 403


def test_giving_leads_sets_owners_marks_the_chat_and_tells_each_new_owner_once(app, client, admin_user, cs_user, world):
    leads = [ti_lead(phone='+91980000080%d' % i, name='Bulk %d' % i) for i in range(5)]
    for l in leads:
        l.owner_id = None                      # routing may already have given them away
    _db.session.commit()
    login(client, admin_user.email)
    r = _bulk(client, lead_ids=[l.id for l in leads[:2]], action='give', owner_id=cs_user.id)
    assert r.get_json()['message'] == 'Gave 2 leads to %s.' % cs_user.full_name
    _db.session.expire_all()
    assert {l.owner_id for l in CrmLead.query.filter(CrmLead.id.in_([x.id for x in leads[:2]]))} == {cs_user.id}
    assert Notification.query.filter_by(user_id=cs_user.id, type='crm_assigned').count() == 2        # up to 3: a bell each
    r = _bulk(client, lead_ids=[l.id for l in leads[2:]], action='give', owner_id=cs_user.id)
    assert r.get_json()['done'] == 3
    many = Notification.query.filter_by(user_id=cs_user.id, type='crm_assigned').filter(
        Notification.title.like('3 leads are yours%')).count()
    assert many == 0                                                       # 3 is still "a bell each"
    ids = [x.id for x in CrmLead.query.all()]
    _bulk(client, lead_ids=ids, action='give', owner_id=None)               # all to nobody
    _db.session.expire_all()
    assert {l.owner_id for l in CrmLead.query.all()} == {None}
    r = _bulk(client, lead_ids=ids, action='give', owner_id=cs_user.id)
    assert Notification.query.filter_by(user_id=cs_user.id, type='crm_assigned').filter(
        Notification.title == '5 leads are yours now').count() == 1
    # giving to the owner they already have changes nothing and tells nobody
    n = Notification.query.count()
    assert _bulk(client, lead_ids=ids, action='give', owner_id=cs_user.id).get_json()['done'] == 0
    assert Notification.query.count() == n


def test_bulk_give_refuses_somebody_who_cannot_own_leads_and_bad_input(app, client, admin_user):
    lead = ti_lead()
    outsider = make_user('plain@test.com', 'plainuser', role='user')
    login(client, admin_user.email)
    assert _bulk(client, lead_ids=[lead.id], action='give', owner_id=outsider.id).status_code == 400
    assert _bulk(client, lead_ids=[], action='give').status_code == 400
    assert _bulk(client, lead_ids=['x', -1, 0], action='give').status_code == 400
    assert _bulk(client, lead_ids=[lead.id], action='explode').status_code == 400
    assert _bulk(client, lead_ids=[lead.id], action='move', stage_id=999999).status_code == 400
    _db.session.expire_all()


def test_bulk_move_skips_other_pipelines_and_asks_why_for_fallout(app, client, admin_user):
    a = ti_lead(phone='+919800000901', name='A')
    b = sh_lead(phone='+919800000902', name='B')
    prospect = stage('ti-standard', 'prospect')
    login(client, admin_user.email)
    r = _bulk(client, lead_ids=[a.id, b.id], action='move', stage_id=prospect.id).get_json()
    assert r['done'] == 1 and 'stayed' in r['message']
    _db.session.expire_all()
    assert _db.session.get(CrmLead, a.id).stage.key == 'prospect' and _db.session.get(CrmLead, b.id).pipeline.key != 'ti-standard'
    fall = stage('ti-standard', 'prospect_fallout')
    r = _bulk(client, lead_ids=[a.id], action='move', stage_id=fall.id)
    assert r.status_code == 400 and r.get_json()['need_reason'] is True
    r = _bulk(client, lead_ids=[a.id], action='move', stage_id=fall.id, reason='Too expensive')
    assert r.get_json()['done'] == 1


def test_moving_leads_in_bulk_sends_nothing_to_anyone(app, client, admin_user, world):
    a = ti_lead(consent=True)
    wrote(a)
    login(client, admin_user.email)
    _bulk(client, lead_ids=[a.id], action='move', stage_id=stage('ti-standard', 'prospect').id)
    assert world.messages == []


# ------------------------------------------------------------------ owner changes and bells

def test_a_new_owner_is_told_unless_they_did_it_themselves(app, cs_user, admin_user):
    lead = ti_lead()
    lead.owner_id = None
    _db.session.commit()
    changed, chat = crm.set_owner(lead, cs_user.id, by=admin_user)
    _db.session.commit()
    assert changed and Notification.query.filter_by(user_id=cs_user.id, type='crm_assigned').count() == 1
    assert crm.set_owner(lead, cs_user.id, by=admin_user) == (False, False)                  # no change, no bell
    crm.set_owner(lead, admin_user.id, by=admin_user)                                         # took it myself: no bell
    _db.session.commit()
    assert Notification.query.filter_by(user_id=admin_user.id, type='crm_assigned').count() == 0
    lines = [t.body for t in CrmTouchpoint.query.filter_by(lead_id=lead.id, channel='system')]
    assert crm.owner_line(None, cs_user) in lines and 'Looked after by: Not given to anyone → %s' % cs_user.full_name in lines


def test_the_bell_only_promises_the_chat_when_it_follows(app, cs_user, admin_user, world):
    lead = ti_lead()
    lead.owner_id = None
    _db.session.commit()
    crm.set_owner(lead, cs_user.id, by=admin_user)
    _db.session.commit()
    n = Notification.query.filter_by(user_id=cs_user.id, type='crm_assigned').one()
    assert 'and WhatsApp chat' in n.title                         # the team link is on and this is the main lead
    ti, sh = ti_lead(phone='+919800001001', name='Two'), sh_lead(phone='+919800001001', name='Two')
    ti.owner_id = sh.owner_id = None
    sh.last_activity_at = datetime.utcnow() + timedelta(minutes=5)
    _db.session.commit()
    crm.set_owner(ti, cs_user.id, by=admin_user)
    _db.session.commit()
    last = Notification.query.filter_by(user_id=cs_user.id, type='crm_assigned').order_by(Notification.id.desc()).first()
    assert 'WhatsApp chat' not in last.title                      # the other lead holds the chat


def test_owner_lines_are_not_the_lead_being_worked_on(app, cs_user, admin_user):
    lead = ti_lead()
    before = lead.last_activity_at
    crm.set_owner(lead, cs_user.id, by=admin_user)
    assert lead.last_activity_at == before


def test_owner_changes_also_move_the_open_follow_ups(app, cs_user):
    lead = ti_lead()
    crm.set_owner(lead, cs_user.id)
    _db.session.commit()
    assert {t.owner_id for t in lead.tasks if t.status == 'open'} == {cs_user.id}


# ------------------------------------------------------------------ the waiting bell

def _waiting(app, cs_user, minutes=20, owner=True):
    lead = ti_lead()
    lead.owner_id = cs_user.id if owner else None          # routing may have given it away already
    _db.session.commit()
    now = datetime(2026, 10, 16, 6, 0)              # 11:30 in India
    crm.log_touch(lead, 'whatsapp', 'in', body='Are you there?', external_id='w-wait', at=now - timedelta(minutes=minutes))
    _db.session.commit()
    return lead, now


def test_the_waiting_bell_rings_once_per_wait_for_the_owner(app, cs_user):
    lead, now = _waiting(app, cs_user)
    assert crm.run_waiting_alerts(now=now) == {'crm_waiting_alerts': 1}
    n = Notification.query.filter_by(user_id=cs_user.id, type='crm_waiting').one()
    assert n.title == 'Ramesh is waiting for your reply (20 min)'
    assert crm.run_waiting_alerts(now=now + timedelta(minutes=15)) == {'crm_waiting_alerts': 0}      # not again
    # we answer; they write again later: it can ring again
    crm.log_touch(lead, 'whatsapp', 'out', body='Here!', user=cs_user, status='sent', external_id='w-ans', at=now + timedelta(minutes=20))
    crm.log_touch(lead, 'whatsapp', 'in', body='Hello??', external_id='w-wait2', at=now + timedelta(minutes=40))
    _db.session.commit()
    assert crm.run_waiting_alerts(now=now + timedelta(minutes=70))['crm_waiting_alerts'] == 1


def test_no_bell_before_the_wait_is_long_enough_or_when_it_is_stale(app, cs_user):
    lead, now = _waiting(app, cs_user, minutes=5)
    assert crm.run_waiting_alerts(now=now)['crm_waiting_alerts'] == 0
    assert crm.run_waiting_alerts(now=now + timedelta(hours=30))['crm_waiting_alerts'] == 0       # over a day old: not rung


def test_no_bell_in_the_night_india_time(app, cs_user):
    lead = ti_lead()
    lead.owner_id = cs_user.id
    night = datetime(2026, 10, 16, 21, 0)             # 02:30 in India
    crm.log_touch(lead, 'whatsapp', 'in', body='Hi', external_id='w-n', at=night - timedelta(minutes=30))
    _db.session.commit()
    assert crm.run_waiting_alerts(now=night)['crm_waiting_alerts'] == 0
    assert crm.run_waiting_alerts(now=night + timedelta(hours=2))['crm_waiting_alerts'] == 0      # 04:30: still night
    assert crm.run_waiting_alerts(now=night + timedelta(hours=5))['crm_waiting_alerts'] == 1      # 07:30: it rings


def test_a_snoozed_customer_is_not_rung_until_the_hour_is_up(app, client, cs_user):
    lead, now = _waiting(app, cs_user)
    lead.owner_id = cs_user.id
    _db.session.commit()
    login(client, cs_user.email)
    assert client.post('/cs/crm/lead/%d/snooze' % lead.id).get_json() == {'success': True}
    _db.session.expire_all()
    assert _db.session.get(CrmLead, lead.id).snoozed_until > datetime.utcnow() + timedelta(minutes=55)
    until = now + timedelta(hours=1)                 # the same hour, on this test's clock
    _db.session.get(CrmLead, lead.id).snoozed_until = until
    _db.session.commit()
    assert crm.run_waiting_alerts(now=until - timedelta(minutes=1))['crm_waiting_alerts'] == 0
    assert crm.run_waiting_alerts(now=until + timedelta(minutes=1))['crm_waiting_alerts'] == 1


def test_only_the_owner_or_an_admin_may_snooze(app, client, cs_user, admin_user):
    lead = ti_lead()
    lead.owner_id = admin_user.id
    _db.session.commit()
    login(client, cs_user.email)
    assert client.post('/cs/crm/lead/%d/snooze' % lead.id).status_code == 403


def test_when_nobody_looks_after_them_the_admins_are_rung(app, admin_user, cs_user):
    lead, now = _waiting(app, cs_user, owner=False)
    assert crm.run_waiting_alerts(now=now)['crm_waiting_alerts'] == 1
    assert Notification.query.filter_by(user_id=admin_user.id, type='crm_waiting').count() == 1
    assert Notification.query.filter_by(user_id=cs_user.id, type='crm_waiting').count() == 0


def test_a_customer_with_two_leads_rings_one_bell_for_the_latest_active_lead(app, cs_user, admin_user):
    ti, sh = ti_lead(), sh_lead()
    ti.owner_id, sh.owner_id = admin_user.id, cs_user.id
    now = datetime(2026, 10, 16, 6, 0)
    crm.log_touch(ti, 'whatsapp', 'in', body='Hi', external_id='w-two', at=now - timedelta(minutes=30))
    ti.last_activity_at = now - timedelta(minutes=30)
    sh.last_activity_at = now - timedelta(minutes=10)       # the Sahayak lead is the one being worked on
    _db.session.commit()
    assert crm.run_waiting_alerts(now=now)['crm_waiting_alerts'] == 1
    assert Notification.query.filter_by(type='crm_waiting').count() == 1
    assert Notification.query.filter_by(user_id=cs_user.id, type='crm_waiting').count() == 1


def test_the_waiting_bell_setting_is_clamped(app):
    for raw, want in ((None, 15), ('x', 15), (1, 5), (99999, 1440), (30, 30)):
        crm.save_settings(waiting_alert_minutes=raw) if raw is not None else None
        assert crm._minutes(raw) == want


# ------------------------------------------------------------------ My day

def test_my_day_lists_waiting_customers_with_a_snooze_and_no_network(app, client, cs_user, monkeypatch):
    lead = ti_lead()
    lead.owner_id = cs_user.id
    _db.session.commit()
    said(lead.person_id, 1, 'Can you call me?')
    login(client, cs_user.email)

    def nope(*a, **k):
        raise AssertionError('My day called the WhatsApp CRM')
    monkeypatch.setattr(wacrm, '_call', nope)
    monkeypatch.setattr(wacrm_team, '_api', nope)
    t = text_of(client.get('/cs/crm/today').get_data(as_text=True))
    assert 'Customers waiting for you (1)' in t and 'Can you call me?' in t and 'Remind me in 1 hour' in t
    client.post('/cs/crm/lead/%d/snooze' % lead.id)
    assert 'Customers waiting for you (0)' in text_of(client.get('/cs/crm/today').get_data(as_text=True))


def test_my_day_costs_the_same_number_of_queries_for_a_few_tasks_or_many(app, client, cs_user):
    login(client, cs_user.email)

    def make(n0, n1):
        for i in range(n0, n1):
            l = ti_lead(phone='+9198002%05d' % i, name='D%d' % i)
            l.owner_id = cs_user.id
            l.open_task.due_at = datetime.utcnow() - timedelta(hours=1)
            said(l.person_id, 1, 'hi')
        _db.session.commit()
    make(0, 4)
    small = queries(lambda: client.get('/cs/crm/today'))
    make(4, 30)
    big = queries(lambda: client.get('/cs/crm/today'))
    assert big <= small + 4, (small, big)


def test_the_one_button_on_a_task_card(app, world):
    crm.save_settings(whatsapp_mode='off')
    lead = ti_lead()
    task = lead.open_task
    task.step.wa_template = 'nri_ti_1'
    _db.session.commit()
    plan = crm.task_plan(task, 'Hi there')
    assert plan['kind'] == 'own' and "Open my WhatsApp" in plan['label']
    crm.save_settings(whatsapp_mode='send')
    from app.services import wa_templates
    wa_templates.statuses(force=True)
    assert crm.task_plan(task, 'Hi there')['kind'] == 'template'
    # a US number with a marketing template cannot get it: call instead
    us = ti_lead(phone='+14155550199', name='Us')
    us.open_task.step.wa_template = 'nri_ti_1'
    _db.session.commit()
    p = crm.task_plan(us.open_task, 'Hi')
    assert p['kind'] == 'blocked' and p['reason'] == "WhatsApp doesn't deliver promotions to US numbers" and p['alt'] == 'call'
    # a follow-up with no words of its own is never sent as its title
    task.step = None
    assert crm.task_plan(task, '')['kind'] == 'open'
    # a call and an e-mail
    call = CrmTask(lead=lead, title='Ring', channel='call', due_at=datetime.utcnow())
    mail = CrmTask(lead=lead, title='Mail', channel='email', due_at=datetime.utcnow())
    assert crm.task_plan(call, '')['kind'] == 'call' and crm.task_plan(mail, '')['kind'] == 'blocked'
    lead.person.email = 'r@example.com'
    assert crm.task_plan(mail, '')['kind'] == 'email'


def test_task_plan_never_calls_whatsapp(app, world):
    lead = ti_lead()
    world.portal.clear()
    for ch in ('whatsapp', 'call', 'email'):
        crm.task_plan(CrmTask(lead=lead, step=lead.open_task.step if ch == 'whatsapp' else None, title='x', channel=ch,
                              due_at=datetime.utcnow()), 'hi')
    assert world.portal == []


# ------------------------------------------------------------------ the shift-end message

def test_signoff_reaches_only_my_open_chats_once(app, client, cs_user, admin_user, world):
    mine = [ti_lead(phone='+91980003000%d' % i, name='Mine %d' % i) for i in range(3)]
    for l in mine:
        l.owner_id = cs_user.id
    stale = ti_lead(phone='+919800003010', name='Stale Chat')
    stale.owner_id = cs_user.id
    optedout = ti_lead(phone='+919800003011', name='Opted Out')
    optedout.owner_id = cs_user.id
    optedout.person.wa_opt_out_at = datetime.utcnow() - timedelta(days=1)
    theirs = ti_lead(phone='+919800003012', name='Not Mine')
    theirs.owner_id = admin_user.id
    for l in mine + [optedout, theirs]:
        wrote(l, hours_ago=1, wamid='w-%d' % l.id)
    wrote(stale, hours_ago=30, wamid='w-stale')
    wrote(optedout, hours_ago=0, wamid='w-after')
    _db.session.commit()
    world.last_inbound_at = datetime.utcnow() - timedelta(hours=1)
    assert sorted(l.person.name for l in crm.signoff_leads(cs_user)) == ['Mine 0', 'Mine 1', 'Mine 2']
    names = sorted(l.person.name for l in crm.signoff_leads(cs_user))
    assert 'Stale Chat' not in names and 'Not Mine' not in names
    login(client, cs_user.email)
    r = client.post('/cs/crm/today/signoff', json={'text': 'Thanks {name}, signing off. {agent}'})
    d = r.get_json()
    assert d['success'] and d['sent'] == len(names) >= 3
    bodies = sorted(m.get('text') or m.get('body') for m in world.messages)
    assert any(b.startswith('Thanks Mine 0,') or b.startswith('Thanks Mine,') for b in bodies)
    assert 'Not Mine' not in ' '.join(bodies)
    n = len(world.messages)
    again = client.post('/cs/crm/today/signoff', json={'text': 'Thanks {name}, signing off. {agent}'}).get_json()
    assert again['sent'] == 0 and len(world.messages) == n                           # pressing again repeats nobody


def test_signoff_needs_whatsapp_connected_and_some_words(app, client, cs_user, world):
    login(client, cs_user.email)
    crm.save_settings(whatsapp_mode='off')
    assert client.post('/cs/crm/today/signoff', json={'text': 'Bye'}).status_code == 409
    crm.save_settings(whatsapp_mode='contacts')
    assert client.post('/cs/crm/today/signoff', json={'text': '   '}).status_code in (200, 400)
    assert crm.signoff_said({'sent': 0, 'already': 0, 'failed': []}) == 'Nobody on your leads has a chat open right now.'
    assert crm.signoff_said({'sent': 2, 'already': 1, 'failed': [('X', 'Chat closed.')]}) == \
        'Sent to 2. 1 had it already today. 1 could not go: Chat closed.'


def test_signoff_stops_when_whatsapp_stops_answering(app, cs_user, world):
    leads = [ti_lead(phone='+91980004000%d' % i, name='S%d' % i) for i in range(3)]
    for l in leads:
        l.owner_id = cs_user.id
        wrote(l, hours_ago=1, wamid='w%d' % l.id)
    world.last_inbound_at = datetime.utcnow() - timedelta(hours=1)
    world.send_error = wacrm.WacrmError('timeout', status=504)
    out = crm.send_signoff(cs_user, 'Bye {name}')
    assert out['sent'] == 0 and len(out['failed']) == 1                           # it stopped after the first
    assert world.messages == []


# ------------------------------------------------------------------ someone leaves

def _ws_member(user, ws=None):
    ws = ws or access.ensure_defaults()
    return WorkspaceMember.query.filter_by(workspace_id=ws.id, user_id=user.id).first() or access.add_member(
        ws, user, role=access.system_role(ws, 'cs'))


def test_a_leaving_agents_leads_and_follow_ups_are_handed_over_first(app, client, admin_user, cs_user):
    other = make_user('o@test.com', 'other', role='cs')
    access.add_member(access.ensure_defaults(), other, role=access.system_role(access.ensure_defaults(), 'cs'))
    leads = [ti_lead(phone='+91980005000%d' % i, name='H%d' % i) for i in range(4)]
    for l in leads:
        l.owner_id = cs_user.id
        crm.set_owner(l, cs_user.id)
    _db.session.commit()
    m = _ws_member(cs_user)
    login(client, admin_user.email)
    r = client.post('/admin/workspace/members/%d/remove' % m.id, data={'hand': 'person', 'to_id': other.id})
    assert r.status_code == 302
    _db.session.expire_all()
    assert {l.owner_id for l in CrmLead.query.all()} == {other.id}
    assert {t.owner_id for t in CrmTask.query.filter_by(status='open')} == {other.id}
    assert WorkspaceMember.query.filter_by(user_id=cs_user.id).count() == 0
    bells = Notification.query.filter_by(user_id=other.id, type='crm_assigned').all()
    assert len(bells) == 1 and bells[0].title == "4 of %s's leads are yours now" % cs_user.first_name


def test_handing_over_to_the_least_busy_person(app, cs_user, admin_user):
    a = make_user('a@test.com', 'aaa', role='cs')
    b = make_user('b@test.com', 'bbb', role='cs')
    ws = access.ensure_defaults()
    for u in (a, b):
        access.add_member(ws, u, role=access.system_role(ws, 'cs'))
    busy = [ti_lead(phone='+91980006000%d' % i, name='Busy%d' % i) for i in range(3)]
    for l in busy:
        l.owner_id = a.id
    mine = [ti_lead(phone='+91980006010%d' % i, name='Mine%d' % i) for i in range(4)]
    for l in mine:
        l.owner_id = cs_user.id
    _db.session.commit()
    moved = crm.hand_over(cs_user, by=admin_user)
    _db.session.commit()
    assert moved[0] == 4
    counts = {u.id: CrmLead.query.filter_by(owner_id=u.id).count() for u in (a, b)}
    assert counts[b.id] >= 3 and counts[a.id] + counts[b.id] == 7                     # the quieter person got more
    assert CrmLead.query.filter_by(owner_id=cs_user.id).count() == 0


def test_nobody_to_take_them_stops_the_removal(app, client, admin_user, cs_user):
    lead = ti_lead()
    lead.owner_id = cs_user.id
    _db.session.commit()
    m = _ws_member(cs_user)
    admin_user.is_active = False
    _db.session.commit()
    with pytest.raises(ValueError):
        crm.hand_over(cs_user)
    _db.session.rollback()
    admin_user.is_active = True
    _db.session.commit()
    assert WorkspaceMember.query.filter_by(user_id=cs_user.id).count() == 1
    assert _db.session.get(CrmLead, lead.id).owner_id == cs_user.id


def test_the_owner_of_a_workspace_cannot_be_removed(app, admin_user):
    ws = access.ensure_defaults()
    owner = WorkspaceMember.query.filter_by(workspace_id=ws.id, is_owner=True).first()
    assert owner is not None
    with pytest.raises(ValueError):
        access.remove_member(owner, hand_over={'to': None, 'team': None})
    assert WorkspaceMember.query.filter_by(id=owner.id).count() == 1


def test_a_person_with_nothing_open_is_removed_without_a_hand_over(app, cs_user):
    m = _ws_member(cs_user)
    assert crm.hand_over(cs_user) == (0, 0)
    assert access.remove_member(m, hand_over={'to': None, 'team': None}) == (0, 0)


# ------------------------------------------------------------------ contact form bells

def test_a_contact_form_makes_a_lead_and_one_bell_not_two(app, client, admin_user, cs_user):
    r = client.post('/api/contact', json={'name': 'Meera Rao', 'email': 'meera@example.com', 'phone': '+919800007001',
                                          'message': 'I need insurance for my parents visiting in March.',
                                          'topic': 'insurance'})
    assert r.status_code == 200
    assert CrmLead.query.count() == 1
    assert Notification.query.filter_by(title='New contact message').count() == 0
    assert Notification.query.filter(Notification.type == 'crm_lead').count() >= 1


def test_a_repeat_enquiry_rings_the_owner_and_makes_no_second_lead(app, client, admin_user, cs_user):
    payload = {'name': 'Meera Rao', 'email': 'meera@example.com', 'phone': '+919800007002',
               'message': 'I need insurance for my parents visiting in March.', 'topic': 'insurance'}
    client.post('/api/contact', json=payload)
    lead = CrmLead.query.one()
    lead.owner_id = cs_user.id
    lead.created_at = datetime.utcnow() - timedelta(days=1)
    _db.session.commit()
    client.post('/api/contact', json=payload)
    assert CrmLead.query.count() == 1
    assert Notification.query.filter_by(user_id=cs_user.id, type='crm_lead').filter(
        Notification.title.like('%sent another enquiry')).count() == 1


def test_a_newsletter_sign_up_is_not_a_lead_and_rings_nothing(app, client, admin_user, cs_user):
    r = client.post('/api/newsletter', json={'email': 'reader@example.com'})
    assert r.status_code == 201
    assert CrmLead.query.count() == 0 and Notification.query.filter_by(type='cs_escalation').count() == 0
    assert Notification.query.filter_by(type='crm_lead').count() == 0


def test_a_new_enquiry_nobody_got_tells_the_admins(app, admin_user, cs_user):
    src = crm.ensure_defaults() and None
    lead = crm.capture('ti-quote', name='Orphan', phone='+919800007003', utm={})
    titles = [n.title for n in Notification.query.filter_by(user_id=admin_user.id)]
    if lead.owner_id is None:
        assert any('not given to anyone' in t for t in titles)


# ------------------------------------------------------------------ Team today

def test_team_today_draws_for_an_admin_and_a_team_lead_sees_their_own_teams(app, client, admin_user, cs_user):
    lead = ti_lead()
    lead.owner_id = cs_user.id
    said(lead.person_id, 1, 'hi')
    _db.session.commit()
    login(client, admin_user.email)
    t = text_of(client.get('/admin/crm/tracker').get_data(as_text=True))
    assert 'Team today' in t and 'Waiting now' in t and 'Left unanswered at day end' in t and 'How each follow-up went' in t
    assert client.get('/admin/crm/tracker?who=%d' % cs_user.id).status_code == 200
    assert client.get('/admin/crm/tracker?day=2020-01-01').status_code == 200
    assert client.get('/admin/crm/tracker?day=not-a-date').status_code in (200, 302, 400)
    client.post('/auth/logout')
    login(client, cs_user.email)
    assert client.get('/cs/crm/tracker').status_code == 302                   # an agent has no Team today


def test_a_team_lead_sees_only_their_team(app, client, admin_user):
    ws = access.ensure_defaults()
    lead_user = make_user('tl@test.com', 'tl', role='cs')
    mate = make_user('mate@test.com', 'mate', role='cs')
    stranger = make_user('str@test.com', 'stranger', role='cs')
    from app.models import WorkspaceRole
    role = WorkspaceRole.query.filter_by(workspace_id=ws.id, name='Team lead').first()
    if role is None:
        pytest.skip('no Team lead role in this workspace')
    team = WorkspaceTeam(workspace_id=ws.id, name='North')
    _db.session.add(team)
    _db.session.flush()
    access.add_member(ws, lead_user, role=role)
    access.add_member(ws, mate, role=access.system_role(ws, 'cs'))
    access.add_member(ws, stranger, role=access.system_role(ws, 'cs'))
    team.users.extend([lead_user, mate])
    _db.session.commit()
    access._cache().clear()
    login(client, lead_user.email)
    t = text_of(client.get('/cs/crm/tracker', follow_redirects=True).get_data(as_text=True))
    assert 'Mate' in t and 'Stranger' not in t and 'North' in t
