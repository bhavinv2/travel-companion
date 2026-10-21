"""Sales CRM 2.0, run 3a -- tasks, calls and meetings anywhere.

    migration  crm_tasks.lead_id may be empty (up, down, up on SQLite); old rows are steps
    adding     + Task on a lead and on a contact; defaults, checks, the owner list, the bell
    rights     edit, done and delete: the owner, whoever made it, or an admin
    steps      a hand-made task is never "the next step", is not skipped by a stage move, and plans nothing
    My day     due today or late, meetings show their time, high priority first, one Done button
    numbers    a finished task counts as a follow-up done (the registry)
"""
import os
from datetime import datetime, timedelta

import pytest

from conftest import login, make_user
from app import db as _db
from app.models import ActivityEvent, CrmLead, CrmPerson, CrmTask, CrmTouchpoint, Notification
from app.services import crm, crm_numbers, crm_tasks, mailer

from test_crm_wa_sync_engine import ti_lead

IST = timedelta(hours=5, minutes=30)


def ist_text(utc, minutes=0):
    return (utc + IST + timedelta(minutes=minutes)).strftime('%Y-%m-%dT%H:%M')


@pytest.fixture
def agent(app):
    return make_user('agent@test.com', 'agent', role='cs')


@pytest.fixture
def mate(app):
    return make_user('mate@test.com', 'mate', role='cs')


@pytest.fixture
def lead(app, agent):
    l = ti_lead(phone='+919876501111', name='Meera Rao')
    l.owner_id = agent.id
    _db.session.commit()
    return l


@pytest.fixture
def me(client, agent):
    login(client, 'agent@test.com')
    return agent


@pytest.fixture
def solo(app):
    person = CrmPerson(name='Solo', email='solo@x.com')
    _db.session.add(person)
    _db.session.commit()
    return person


def add(client, **body):
    return client.post('/cs/crm/tasks/add', json=body)


# ====================================================================================== the migration

def test_the_migration_makes_lead_id_empty_able_and_keeps_old_rows_as_steps(tmp_path):
    import importlib.util
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations', 'versions',
                        'u3crm019_crm_tasks_anywhere.py')
    spec = importlib.util.spec_from_file_location('u3crm019', path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    engine = sa.create_engine('sqlite:///%s' % (tmp_path / 'm.db'))
    meta = sa.MetaData()
    for name in ('users', 'crm_people', 'crm_leads', 'crm_playbook_steps'):
        sa.Table(name, meta, sa.Column('id', sa.Integer, primary_key=True))
    sa.Table('crm_tasks', meta,
             sa.Column('id', sa.Integer, primary_key=True),
             sa.Column('lead_id', sa.Integer, sa.ForeignKey('crm_leads.id'), nullable=False, index=True),
             sa.Column('step_id', sa.Integer, sa.ForeignKey('crm_playbook_steps.id'), nullable=True),
             sa.Column('title', sa.String(160), nullable=False),
             sa.Column('due_at', sa.DateTime, nullable=False))
    meta.create_all(engine)
    with engine.begin() as conn:
        conn.execute(sa.text('INSERT INTO crm_leads (id) VALUES (1)'))
        conn.execute(sa.text("INSERT INTO crm_tasks (id, lead_id, title, due_at) VALUES (1, 1, 'old', '2026-01-01 10:00:00')"))
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mig.upgrade()
        cols = {c['name']: c for c in sa.inspect(conn).get_columns('crm_tasks')}
        assert {'person_id', 'kind', 'ends_at', 'location', 'notes', 'created_by_id', 'priority'} <= set(cols)
        assert cols['lead_id']['nullable'] is True
        assert conn.execute(sa.text('SELECT kind FROM crm_tasks WHERE id = 1')).scalar() == 'step'
        conn.execute(sa.text("INSERT INTO crm_tasks (id, lead_id, title, due_at) VALUES (2, NULL, 'no lead', '2026-01-01 10:00:00')"))
        with Operations.context(ctx):
            mig.downgrade()
        cols = {c['name']: c for c in sa.inspect(conn).get_columns('crm_tasks')}
        assert 'kind' not in cols and cols['lead_id']['nullable'] is False
        assert [r[0] for r in conn.execute(sa.text('SELECT id FROM crm_tasks'))] == [1]          # the lead-less one went
        with Operations.context(ctx):
            mig.upgrade()
        assert sa.inspect(conn).get_columns('crm_tasks')


# ====================================================================================== adding

def test_a_task_on_a_lead_gets_its_defaults(client, me, lead):
    r = add(client, lead_id=lead.id, title='Send the brochure')
    assert r.status_code == 200, r.get_json()
    t = _db.session.get(CrmTask, r.get_json()['id'])
    assert (t.kind, t.priority, t.owner_id, t.created_by_id) == ('todo', 'normal', me.id, me.id)
    assert t.lead_id == lead.id and t.person_id == lead.person_id and t.channel == 'todo' and t.auto is False
    today = (datetime.utcnow() + IST).date()
    assert crm_tasks.from_utc(t.due_at) == datetime.combine(today + timedelta(days=1), datetime.min.time()) + timedelta(hours=10)


def test_a_task_on_a_contact_with_no_lead(client, me, solo):
    r = add(client, person_id=solo.id, title='Call about the policy', kind='call', priority='high')
    assert r.status_code == 200
    t = _db.session.get(CrmTask, r.get_json()['id'])
    assert t.lead_id is None and t.person_id == solo.id and t.kind == 'call' and t.priority == 'high'
    page = client.get('/cs/crm/contact/%d' % solo.id)
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'Call about the policy' in html and 'data-tk-new' in html and 'data-email-open' in html


def test_the_lead_page_shows_the_task_box_and_the_form(client, me, lead):
    soon = datetime.utcnow() + timedelta(days=1)
    add(client, lead_id=lead.id, title='Ring Meera at lunch', kind='meeting', location='https://meet.example/x',
        due=ist_text(soon), ends=ist_text(soon, 45))
    html = client.get('/cs/crm/lead/%d' % lead.id).get_data(as_text=True)
    assert 'Ring Meera at lunch' in html and 'meet.example' in html
    for needle in ('Date and time', 'Place or video link', 'Priority', 'Notes', 'Insert a ready answer', 'data-tk-new'):
        assert needle in html


def test_a_meeting_has_an_end_and_a_place(client, me, lead):
    due = datetime.utcnow() + timedelta(days=2)
    r = add(client, lead_id=lead.id, title='Visit', kind='meeting', due=ist_text(due), ends=ist_text(due, 90), location='Office')
    t = _db.session.get(CrmTask, r.get_json()['id'])
    assert t.ends_at - t.due_at == timedelta(minutes=90) and t.location == 'Office'
    bad = add(client, lead_id=lead.id, title='Backwards', kind='meeting', due=ist_text(due), ends=ist_text(due, -30))
    assert bad.status_code == 400 and 'end before' in bad.get_json()['error']


def test_bad_input_is_refused_in_plain_words(client, me, lead):
    assert add(client, lead_id=lead.id, title='  ').get_json()['error'] == crm_tasks.TITLE_NEEDED
    assert add(client, lead_id=lead.id, title='x', due='next week').get_json()['error'] == crm_tasks.BAD_TIME
    assert add(client, title='x').status_code == 400
    assert add(client, lead_id=lead.id, title='x', owner_id=999999).get_json()['error'] == crm_tasks.NOT_STAFF
    assert CrmTask.query.filter(CrmTask.kind != 'step').count() == 0


def test_the_owner_list_is_sales_staff_and_a_gift_rings_a_bell(client, me, mate, lead):
    customer = make_user('nobody@test.com', 'nobody')                # a customer account, not staff
    assert add(client, lead_id=lead.id, title='x', owner_id=customer.id).status_code == 400
    r = add(client, lead_id=lead.id, title='Call Meera back', kind='call', owner_id=mate.id)
    assert r.status_code == 200
    bell = Notification.query.filter_by(user_id=mate.id, type='crm_task').one()
    assert 'gave you a call' in bell.title and 'Call Meera back' in bell.body and bell.link.endswith('/lead/%d' % lead.id)
    add(client, lead_id=lead.id, title='My own', owner_id=me.id)
    assert Notification.query.filter_by(user_id=me.id, type='crm_task').count() == 0
    assert 'value="%d"' % mate.id in client.get('/cs/crm/lead/%d' % lead.id).get_data(as_text=True)


def test_priority_must_be_one_of_three(client, me, lead):
    t = _db.session.get(CrmTask, add(client, lead_id=lead.id, title='x', priority='urgent!!').get_json()['id'])
    assert t.priority == 'normal'


def test_adding_and_finishing_never_write_to_a_customer(client, me, lead):
    before = CrmTouchpoint.query.count()
    mailer.OUTBOX.clear()
    r = add(client, lead_id=lead.id, title='Call', kind='call')
    client.post('/cs/crm/task/%d/done' % r.get_json()['id'])
    assert CrmTouchpoint.query.count() == before and mailer.OUTBOX == []


# ====================================================================================== rights

def test_edit_done_and_delete_belong_to_the_owner_the_maker_and_admins(client, me, mate, lead, admin_user):
    tid = add(client, lead_id=lead.id, title='Mine', owner_id=me.id).get_json()['id']
    gift = add(client, lead_id=lead.id, title='Given', owner_id=mate.id).get_json()['id']
    # the maker may change what they gave away
    assert client.post('/cs/crm/tasks/%d/edit' % gift, json={'title': 'Given, renamed'}).status_code == 200
    assert _db.session.get(CrmTask, gift).title == 'Given, renamed'
    client.post('/auth/logout')
    login(client, 'mate@test.com')
    assert client.post('/cs/crm/tasks/%d/edit' % tid, json={'title': 'Hijack'}).status_code == 403
    assert client.post('/cs/crm/tasks/%d/delete' % tid).status_code == 403
    assert client.post('/cs/crm/task/%d/done' % tid).status_code == 403
    assert _db.session.get(CrmTask, tid).title == 'Mine' and _db.session.get(CrmTask, tid).status == 'open'
    assert client.post('/cs/crm/task/%d/done' % gift).status_code == 200            # theirs
    client.post('/auth/logout')
    login(client, 'admin@test.com')
    assert client.post('/cs/crm/tasks/%d/edit' % tid, json={'title': 'Admin edit'}).status_code == 200
    assert client.post('/cs/crm/tasks/%d/delete' % tid).status_code == 200
    assert _db.session.get(CrmTask, tid) is None


def test_edit_changes_every_field_and_a_new_owner_gets_a_bell(client, me, mate, lead):
    tid = add(client, lead_id=lead.id, title='Plan').get_json()['id']
    due = datetime.utcnow() + timedelta(days=3)
    r = client.post('/cs/crm/tasks/%d/edit' % tid, json={'title': 'Plan B', 'kind': 'meeting', 'priority': 'low',
                    'due': ist_text(due), 'ends': ist_text(due, 30), 'location': 'Cafe', 'notes': 'bring forms',
                    'owner_id': mate.id})
    assert r.status_code == 200
    t = _db.session.get(CrmTask, tid)
    assert (t.title, t.kind, t.priority, t.location, t.notes, t.owner_id) == ('Plan B', 'meeting', 'low', 'Cafe', 'bring forms', mate.id)
    assert Notification.query.filter_by(user_id=mate.id, type='crm_task').count() == 1


def test_a_step_cannot_be_edited_or_deleted_as_a_task(client, me, lead):
    step = CrmTask.query.filter_by(lead_id=lead.id).first()
    assert step is not None and step.kind == 'step'
    assert client.post('/cs/crm/tasks/%d/edit' % step.id, json={'title': 'x'}).status_code == 404
    assert client.post('/cs/crm/tasks/%d/delete' % step.id).status_code == 404


def test_no_audit_text_holds_the_persons_name(client, me, lead):
    add(client, lead_id=lead.id, title='Call Meera Rao')
    events = ActivityEvent.query.filter(ActivityEvent.event.like('crm_task%')).all()
    assert events
    for ev in events:
        assert 'Meera' not in str(ev.meta)


# ====================================================================================== the lead's steps are left alone

def test_a_hand_made_task_is_not_the_next_step(client, me, lead):
    step = lead.open_task
    assert step is not None
    add(client, lead_id=lead.id, title='Soon', due=ist_text(datetime.utcnow() - timedelta(hours=1)))
    _db.session.expire_all()
    assert _db.session.get(CrmLead, lead.id).open_task.id == step.id


def test_moving_the_stage_keeps_hand_made_tasks_and_skips_the_steps(client, me, lead):
    tid = add(client, lead_id=lead.id, title='Keep me').get_json()['id']
    old_steps = [t.id for t in CrmTask.query.filter_by(lead_id=lead.id, kind='step', status='open')]
    assert old_steps
    nxt = next(s for s in lead.pipeline.stages if s.id != lead.stage_id and s.kind == 'open')
    assert crm.move_stage(lead, nxt, user=me)
    _db.session.commit()
    _db.session.expire_all()
    assert _db.session.get(CrmTask, tid).status == 'open'
    assert all(_db.session.get(CrmTask, i).status == 'skipped' for i in old_steps)


def test_a_hand_made_task_does_not_stop_the_next_step_being_planned(client, me, lead):
    add(client, lead_id=lead.id, title='Keep me')
    _db.session.expire_all()
    lead = _db.session.get(CrmLead, lead.id)
    step = lead.open_task
    crm.complete_task(step, user=me)
    _db.session.commit()
    _db.session.expire_all()
    lead = _db.session.get(CrmLead, lead.id)
    assert lead.open_task is not None and lead.open_task.id != step.id          # the next step was planned


def test_finishing_a_task_plans_nothing_and_leaves_the_lead_alone(client, me, lead):
    before = CrmTask.query.filter_by(lead_id=lead.id, kind='step').count()
    stamp = _db.session.get(CrmLead, lead.id).last_activity_at
    tid = add(client, lead_id=lead.id, title='x').get_json()['id']
    assert client.post('/cs/crm/task/%d/done' % tid).status_code == 200
    t = _db.session.get(CrmTask, tid)
    assert t.status == 'done' and t.done_by_id == me.id and t.done_at is not None
    assert CrmTask.query.filter_by(lead_id=lead.id, kind='step').count() == before
    assert _db.session.get(CrmLead, lead.id).last_activity_at == stamp


def test_giving_a_lead_to_someone_else_does_not_take_a_given_task_away(client, me, mate, lead):
    tid = add(client, lead_id=lead.id, title='Mine to keep', owner_id=me.id).get_json()['id']
    crm.set_owner(lead, mate.id, by=me)
    _db.session.commit()
    assert _db.session.get(CrmTask, tid).owner_id == me.id
    assert all(t.owner_id == mate.id for t in CrmTask.query.filter_by(lead_id=lead.id, kind='step', status='open'))


def test_handing_over_somebodys_work_copes_with_a_task_that_has_no_lead(client, me, mate, solo):
    add(client, person_id=solo.id, title='No lead here')
    moved = crm.hand_over(me, to=mate)
    _db.session.commit()
    assert moved[1] >= 1
    assert CrmTask.query.filter_by(title='No lead here').one().owner_id == mate.id


def test_the_automatic_sender_never_picks_up_a_hand_made_task(client, me, lead):
    tid = add(client, lead_id=lead.id, title='Due', due=ist_text(datetime.utcnow() - timedelta(hours=3))).get_json()['id']
    t = _db.session.get(CrmTask, tid)
    assert t.auto is False and t.channel == 'todo'
    due = CrmTask.query.filter(CrmTask.status == 'open', CrmTask.auto.is_(True), CrmTask.channel == 'whatsapp').all()
    assert t not in due


# ====================================================================================== My day

def test_my_day_shows_my_tasks_due_today_or_late_with_one_done_button(client, me, mate, lead):
    now = datetime.utcnow()
    add(client, lead_id=lead.id, title='Late one', due=ist_text(now - timedelta(days=1)))
    meet = add(client, lead_id=lead.id, title='Meeting with Meera', kind='meeting',
               due=ist_text(now - timedelta(minutes=1)), ends=ist_text(now, 30)).get_json()['id']
    add(client, lead_id=lead.id, title='Next week', due=ist_text(now + timedelta(days=7)))
    add(client, lead_id=lead.id, title='Someone elses', owner_id=mate.id, due=ist_text(now))
    html = client.get('/cs/crm/today').get_data(as_text=True)
    assert 'My tasks (' in html
    assert 'Late one' in html and 'Meeting with Meera' in html
    assert 'Next week' not in html and 'Someone elses' not in html
    chunk = html[html.index('id="task-%d"' % meet):]
    chunk = chunk[:chunk.index('</article>')]
    assert chunk.count('data-act') == 1 and 'data-act="done"' in chunk                 # one button: Done
    t = _db.session.get(CrmTask, meet)
    start = crm_tasks.from_utc(t.due_at).strftime('%H:%M')
    end = crm_tasks.from_utc(t.ends_at).strftime('%H:%M')
    assert '%s-%s' % (start, end) in chunk                                              # the meeting shows its time


def test_my_day_sorts_high_priority_first_at_the_same_time(client, me, lead):
    due = ist_text(datetime.utcnow() - timedelta(hours=2))
    add(client, lead_id=lead.id, title='AAA normal', due=due)
    add(client, lead_id=lead.id, title='BBB low', due=due, priority='low')
    add(client, lead_id=lead.id, title='CCC high', due=due, priority='high')
    html = client.get('/cs/crm/today').get_data(as_text=True)
    assert html.index('CCC high') < html.index('AAA normal') < html.index('BBB low')


def test_my_day_copes_with_a_task_that_has_no_lead_and_done_removes_it(client, me, solo):
    tid = add(client, person_id=solo.id, title='Solo task', due=ist_text(datetime.utcnow() - timedelta(hours=1))).get_json()['id']
    html = client.get('/cs/crm/today').get_data(as_text=True)
    assert 'Solo task' in html and '/contact/%d' % solo.id in html
    assert client.post('/cs/crm/task/%d/done' % tid).status_code == 200
    assert 'Solo task' not in client.get('/cs/crm/today').get_data(as_text=True)
    assert 'Solo task' not in client.get('/cs/crm/today?who=all').get_data(as_text=True)


def test_everybodys_view_on_my_day_lists_other_peoples_tasks(client, admin_user, me, mate, lead):
    add(client, lead_id=lead.id, title='Mates job', owner_id=mate.id, due=ist_text(datetime.utcnow() - timedelta(hours=1)))
    client.post('/auth/logout')
    login(client, 'admin@test.com')
    assert 'Mates job' not in client.get('/admin/crm/today').get_data(as_text=True)
    assert 'Mates job' in client.get('/admin/crm/today?who=all').get_data(as_text=True)


def test_a_hand_made_task_is_not_a_board_cards_next_step(client, me, lead):
    add(client, lead_id=lead.id, title='Hand made', due=ist_text(datetime.utcnow() - timedelta(days=1)))
    cards = crm.lead_cards([_db.session.get(CrmLead, lead.id)])
    t = cards[lead.id]['task']
    assert t is None or t.kind == 'step'


# ====================================================================================== the numbers

def test_a_finished_task_counts_as_a_follow_up_done(client, me, lead, solo):
    start = datetime.utcnow() - timedelta(hours=1)
    end = datetime.utcnow() + timedelta(hours=1)
    sc = crm_numbers.scope(owner_ids=[me.id])
    before = crm_numbers.compute('followups_done', start, end, sc)
    t1 = add(client, lead_id=lead.id, title='Counted').get_json()['id']
    t2 = add(client, person_id=solo.id, title='No lead counted').get_json()['id']
    client.post('/cs/crm/task/%d/done' % t1)
    client.post('/cs/crm/task/%d/done' % t2)
    assert crm_numbers.compute('followups_done', start, end, sc) - before == 2


def test_team_today_copes_with_lead_less_tasks(client, admin_user, me, solo):
    t = add(client, person_id=solo.id, title='Solo').get_json()['id']
    client.post('/cs/crm/task/%d/done' % t)
    client.post('/auth/logout')
    login(client, 'admin@test.com')
    assert client.get('/admin/crm/tracker').status_code == 200


# ====================================================================================== erasing

def test_erasing_a_person_removes_their_tasks_too(client, me, lead, solo, admin_user):
    add(client, person_id=solo.id, title='Person task')
    add(client, lead_id=lead.id, title='Lead task')
    from app.services import crm_people
    assert crm_people.erase_plan(solo)['tasks'] == 1
    assert crm_people.erase_plan(lead.person)['tasks'] >= 2
    pid, lead_person = solo.id, lead.person_id
    crm_people.erase(solo, admin_user)
    assert CrmTask.query.filter_by(person_id=pid).count() == 0
    crm_people.erase(_db.session.get(CrmPerson, lead_person), admin_user)
    assert CrmTask.query.filter_by(title='Lead task').count() == 0
