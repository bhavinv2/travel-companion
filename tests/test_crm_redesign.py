"""Sales CRM, fourth part: the redesign for people who are not technical.

Customer service sees the day's work only; the admin gets the daily tracker, dashboard and set-up.
My day walks through the day step by step. Anything the site already has becomes a lead in one
click, a wrong move or a lead added by mistake can be undone, and the pipeline symbol shows on
every screen that shows a person."""
from datetime import date, datetime, timedelta

from conftest import login, make_user
from app import db as _db
from app.models import (ContactMessage, CrmLead, CrmPerson, CrmPipeline, CrmStage, CrmTask, InsuranceQuote,
                        SahayakBooking)
from app.services import crm, crm_reports


def stage(pipe_key, stage_key):
    return (CrmStage.query.join(CrmPipeline).filter(CrmPipeline.key == pipe_key, CrmStage.key == stage_key)
            .one())


def ti_lead(phone='+919876543210', **kw):
    return crm.capture('ti-quote', name=kw.pop('name', 'Ramesh Kumar'), phone=phone, utm={}, **kw)


# ============================================================================================ who sees what

def test_customer_service_sees_only_the_days_work(app, client, cs_user):
    login(client, cs_user.email)
    page = client.get('/cs/crm/today').get_data(as_text=True)
    for label in ('My day', 'Leads', 'Add a lead', 'Half-hourly check', 'How we sell'):   # U2 renamed Inbox check
        assert label in page, label
    for label in ('Team today', 'Results', 'Where leads come from', 'Site dashboard'):
        assert label not in page, label


def test_the_admin_sees_the_management_screens(app, client, admin_user):
    login(client, admin_user.email)
    page = client.get('/admin/crm/today').get_data(as_text=True)
    assert 'Team today' in page and 'Site dashboard' in page and 'Set-up' in page
    # an admin who opens a management screen in the CS console lands in the admin portal
    r = client.get('/cs/crm/setup?tab=answers')
    assert r.status_code == 307 and r.headers['Location'].endswith('/admin/crm/setup?tab=answers')


# ============================================================================================ my day

def test_my_day_in_steps(app, client, cs_user):
    lead = ti_lead()                                   # a new lead: its first message is due now
    other = ti_lead(phone='+919876543211', name='Sunita Rao')
    crm.record_reply(other, 'Yes please')              # a prospect: a follow-up, not a welcome
    other.open_task.due_at = datetime.utcnow() - timedelta(hours=1)
    _db.session.commit()
    login(client, cs_user.email)
    page = client.get('/cs/crm/today').get_data(as_text=True)
    # U4: new section titles
    assert 'Welcome new leads' in page and 'Follow-ups for today' in page and 'Half-hourly check' in page
    welcome = page.split('Welcome new leads', 1)[1].split('Follow-ups for today', 1)[0]
    assert 'Ramesh Kumar' in welcome and 'Sunita Rao' not in welcome
    assert 'Sunita Rao' in page.split('Follow-ups for today', 1)[1]
    assert 'Before you finish' in page


def test_saving_todays_numbers_from_my_day(app, client, cs_user):
    login(client, cs_user.email)
    today = (datetime.utcnow() + crm.IST).date()
    r = client.post('/cs/crm/insights/log', data={'day': today.isoformat(), 'back': 'today', 'google_reviews': '3'})
    assert r.headers['Location'].endswith('/cs/crm/today#finish')


# ============================================================================================ the daily tracker

def test_the_daily_tracker(app, client, admin_user, cs_user):
    lead = ti_lead()
    login(client, cs_user.email)
    client.post('/cs/crm/lead/%d/send' % lead.id, json={'text': 'Hello', 'task_id': lead.open_task.id})
    missed = ti_lead(phone='+919876543299', name='Missed Person')
    today = (datetime.utcnow() + crm.IST).date()
    # overdue but still inside today's India day: "2 hours ago" falls on yesterday between midnight and 02:00 IST
    day_start = datetime.combine(today, datetime.min.time()) - crm.IST
    missed.open_task.due_at = max(datetime.utcnow() - timedelta(hours=2), day_start + timedelta(seconds=1))
    _db.session.commit()
    sheet = crm_reports.day_sheet(today, [cs_user])[cs_user.id]
    assert sheet['counts']['done'] == 1 and sheet['counts']['missed'] == 1 and sheet['counts']['messages'] == 1
    states = {lead_.person.name: [i['state'] for i in items] for lead_, items in sheet['checklist']}
    assert states['Ramesh Kumar'] == ['done'] and states['Missed Person'] == ['missed']
    assert any('Sent TI #1' in text for _, _, _, text in sheet['timeline'])

    client.post('/auth/logout')
    login(client, admin_user.email)
    page = client.get('/admin/crm/tracker').get_data(as_text=True)
    assert 'Team today' in page and cs_user.full_name in page
    page = client.get('/admin/crm/tracker?who=%d' % cs_user.id).get_data(as_text=True)
    assert 'Checklist, customer by customer' in page and 'Missed Person' in page and 'Hour by hour' in page
    assert client.get('/admin/crm/tracker?day=%s' % (today - timedelta(days=1)).isoformat()).status_code == 200


# ============================================================================================ existing data -> leads

def test_existing_data_becomes_a_lead(app, client, cs_user):
    q = InsuranceQuote(email='kiran@example.com', phone='+919000000001', insurance_type='visitors', citizenship='IND',
                       start_date=date.today() + timedelta(days=20), end_date=date.today() + timedelta(days=80),
                       travellers=[{'age': '66'}])
    m = ContactMessage(name='Kiran Rao', email='kiran@example.com', phone='+919000000001',
                       message='Need cover for my parents', topic='insurance')
    _db.session.add_all([q, m])
    _db.session.commit()
    login(client, cs_user.email)
    page = client.get('/cs/crm/add?from=existing&q=kiran').get_data(as_text=True)
    assert 'Insurance quote' in page and 'Contact message' in page and 'Make a lead' in page
    r = client.post('/cs/crm/add/record', data={'kind': 'insurance_quote', 'id': q.id})
    lead = CrmLead.query.one()
    assert r.headers['Location'].endswith('/cs/crm/lead/%d' % lead.id)
    assert lead.ref_type == 'insurance_quotes' and lead.owner_id == cs_user.id and lead.created_by_id == cs_user.id
    assert lead.open_task is not None and lead.ends_on
    # the same quote again is the same lead
    client.post('/cs/crm/add/record', data={'kind': 'insurance_quote', 'id': q.id})
    assert CrmLead.query.count() == 1
    assert 'Make a lead' not in client.get('/cs/crm/add?from=existing&q=kiran@').get_data(as_text=True).split('Insurance quote', 1)[1].split('</div>\n    </div>', 1)[0]


def test_a_site_account_becomes_a_lead(app, client, cs_user, user):
    user.phone = '+919000000077'
    _db.session.commit()
    lead, created = crm.lead_from_record('user', user.id, user=cs_user)
    assert created and lead.ref_type == 'users' and lead.person.user_id == user.id


# ============================================================================================ undo, reopen, remove

def test_undo_a_wrong_move(app, client, cs_user):
    lead = ti_lead()
    login(client, cs_user.email)
    quoted = stage('ti-standard', 'quoted')
    client.post('/cs/crm/lead/%d/move' % lead.id, json={'stage_id': quoted.id})
    d = client.post('/cs/crm/lead/%d/undo' % lead.id).get_json()
    assert d['stage'] == 'Cold lead'
    _db.session.expire_all()
    assert _db.session.get(CrmLead, lead.id).stage.key == 'cold'


def test_reopen_a_lost_lead(app, client, cs_user):
    lead = ti_lead()
    crm.move_stage(lead, stage('ti-standard', 'prospect'))
    crm.move_stage(lead, stage('ti-standard', 'prospect_fallout'), fallout_reason='No response')
    _db.session.commit()
    login(client, cs_user.email)
    assert client.post('/cs/crm/lead/%d/reopen' % lead.id).get_json()['stage'] == 'Prospect'
    _db.session.expire_all()
    lead = _db.session.get(CrmLead, lead.id)
    assert lead.status == 'open' and lead.fallout_reason is None
    assert client.post('/cs/crm/lead/%d/reopen' % lead.id).status_code == 400


def test_remove_a_lead_added_by_mistake(app, client, cs_user):
    other_agent = make_user('o@test.com', 'other', role='cs')
    lead = ti_lead()
    lead.owner_id, lead.created_by_id = other_agent.id, other_agent.id
    _db.session.commit()
    login(client, cs_user.email)
    assert client.post('/cs/crm/lead/%d/remove' % lead.id).status_code == 403     # not theirs
    lead.owner_id = cs_user.id
    _db.session.commit()
    d = client.post('/cs/crm/lead/%d/remove' % lead.id).get_json()
    assert d['success'] and CrmLead.query.count() == 0 and CrmPerson.query.count() == 1      # the contact stays (release 2)


# ============================================================================================ the pipeline symbol everywhere

def test_the_pipeline_symbol_on_other_screens(app, client, cs_user):
    q = InsuranceQuote(email='a@example.com', phone='+919000000001', insurance_type='visitors', citizenship='IND',
                       start_date=date.today() + timedelta(days=20), end_date=date.today() + timedelta(days=80),
                       travellers=[{'age': '66'}])
    b = SahayakBooking(service_key='phlebotomy', service_name='Blood test', patient_name='Amma', phone='+919000000004',
                       address='Delhi', when_type='asap')
    _db.session.add_all([q, b])
    _db.session.commit()
    crm.lead_from_record('insurance_quote', q.id)
    login(client, cs_user.email)
    page = client.get('/cs/insurance-quotes').get_data(as_text=True)
    assert 'crm-pill r-cold' in page and 'Cold lead' in page
    page = client.get('/cs/sahayak').get_data(as_text=True)
    assert 'crm-pill add' in page                              # not a lead yet: one click makes it one
    r = client.post('/cs/crm/add/record', data={'kind': 'sahayak_booking', 'id': b.id, 'next': '/cs/sahayak'})
    assert r.headers['Location'].endswith('/cs/sahayak')
    assert 'crm-pill r-cold' in client.get('/cs/sahayak').get_data(as_text=True)


def test_every_kind_of_record_becomes_a_lead_from_add_a_lead(app, client, cs_user):
    """A trip post used to 500 here (capture_trip got created_by_id twice): every kind is checked, and the
    lead remembers which member of staff added it."""
    from app.models import CompanionRequest
    owner = make_user('trav@test.com', 'trav')
    owner.phone = '+919812340099'
    trip = CompanionRequest(user_id=owner.id, travel_type='air', trip_type='one_way', role='seeking_help',
                            flying_from='Hyderabad (HYD)', destination='Dallas (DFW)',
                            from_date=date.today() + timedelta(days=30), source='organic')
    trip.set_status('open')
    bare = CompanionRequest(user_id=None, travel_type='air', trip_type='one_way', role='offering_help',
                            flying_from='Delhi (DEL)', destination='Chicago (ORD)',
                            from_date=date.today() + timedelta(days=20), source='facebook')
    bare.set_status('open')
    m = ContactMessage(name='Asha', email='asha@example.com', topic='general', status='new', message='call me')
    _db.session.add_all([trip, bare, m])
    _db.session.commit()
    login(client, cs_user.email)
    for kind, rid in (('trip', trip.id), ('contact_message', m.id), ('user', owner.id)):
        r = client.post('/cs/crm/add/record', data={'kind': kind, 'id': rid})
        assert r.status_code == 302 and '/cs/crm/lead/' in r.headers['Location'], kind
        lead = crm.lead_for_record(kind, rid)
        assert lead is not None and lead.created_by_id == cs_user.id, kind
    r = client.post('/cs/crm/add/record', data={'kind': 'trip', 'id': bare.id})        # nobody to reach: said, not a 500
    assert r.status_code == 302 and crm.lead_for_record('trip', bare.id) is None


def test_the_stage_pill_colours(app):
    crm.ensure_defaults()
    roles = {s.key: crm.stage_role(s) for s in CrmPipeline.query.filter_by(key='ti-standard').one().stages}
    assert roles == {'cold': 'cold', 'prospect': 'prospect', 'quoted': 'pipeline', 'pipeline': 'pipeline',
                     'customer': 'customer', 'prospect_fallout': 'lost', 'pipeline_fallout': 'lost'}
