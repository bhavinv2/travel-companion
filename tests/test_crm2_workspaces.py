"""Sales CRM 2.0, run 5a -- CRM data per workspace.

    rows        new rows get their workspace (staff, a public form's source, a person's, a job's); uniqueness of a
                phone / pipeline key / source key / product code / handle is per workspace
    sweep       a member of one workspace meets nothing of the other on any CRM screen, export, search, flow,
                forecast, report, view, calendar, bin, file or quote -- and cannot act on it by its id
    compose     workspace + "who sees which leads" (team) + the recycle bin, all on one statement
    capture     a public form lands in its SOURCE's workspace; webhooks go by the WhatsApp link / the person / the
                payment / the form's source
    jobs        each CRM job runs per workspace: an automation of A never touches B; saved numbers are per workspace
                and forgetting days forgets only that workspace's
    defaults    a new workspace gets its own pipelines, products, sources and answers; legacy staff and NULL rows
                are the default workspace's; a super admin switching workspace sees the other CRM
    whatsapp    the second workspace's WhatsApp page says which workspace WhatsApp is linked to
    migration   u7crm023 up / down / up on SQLite with rows in it
"""
import hashlib
import hmac
import io
import json
import os
import re
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from flask import g

from conftest import login, logout, make_user
from app import db as _db
from app.models import (CrmActivity, CrmAnswer, CrmAudit, CrmDailyStat, CrmFile, CrmIdentity, CrmLead, CrmPayment,
                        CrmPerson, CrmPipeline, CrmProduct, CrmQuote, CrmSavedReport, CrmSource, CrmStage, CrmTarget,
                        CrmTask, CrmTouchpoint, CrmView, Workspace, WorkspaceRole, WorkspaceTeam)
from app.services import access, crm, crm_bin, crm_numbers, crm_quotes, crm_scope, jobs

PHONE = '+919800011111'           # the same number is a contact in BOTH workspaces
DIGITS = PHONE.lstrip('+')


def words(html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html))


def as_user(client, user):
    """Sign `user` in; the app keeps the last user on `g` for the test, and the session's objects are re-read."""
    logout(client)
    g.pop('_login_user', None)
    _db.session.expire_all()
    return login(client, user.email)


def member(ws, email, username, role_key='admin', role=None):
    u = make_user(email, username, role='cs')
    access.add_member(ws, u, role=role or access.system_role(ws, role_key))
    _db.session.commit()
    access._cache().clear()
    return u


def fresh(model, pk):
    _db.session.expire_all()
    return _db.session.get(model, pk)


def every(model):
    """All rows of a model, whatever workspace (the test itself is not limited, but say it outright)."""
    return model.query.execution_options(all_workspaces=True, include_deleted=True).all()


@pytest.fixture
def two(app):
    """Workspace A (the first: the default) with Ann, workspace B with Ben -- both Administrators of their own --
    and a lead in each for the SAME phone number, plus a second lead in B."""
    a = access.ensure_defaults()
    b = access.create_workspace('Bee Care')
    _db.session.commit()
    ann = member(a, 'ann@test.com', 'ann')
    ben = member(b, 'ben@test.com', 'ben')
    with crm_scope.use(a.id):
        crm.ensure_defaults()
    with crm_scope.use(b.id):
        crm.ensure_defaults()
    la = crm.capture('ti-quote', name='Alphaname Anand', phone=PHONE, email='alpha@example.com', utm={},
                     workspace_id=a.id)
    lb = crm.capture('ti-quote', name='Bravoname Bose', phone=PHONE, email='bravo@example.com', utm={},
                     workspace_id=b.id)
    lb2 = crm.capture('ti-quote', name='Bravotwo Basu', phone='+919800022222', utm={}, workspace_id=b.id)
    return SimpleNamespace(a=a, b=b, ann=ann, ben=ben, la=la, lb=lb, lb2=lb2)


# ====================================================================================== rows and uniqueness

def test_each_workspace_gets_its_own_copy_of_the_set_up(app, two):
    a, b = two.a.id, two.b.id
    for model in (CrmPipeline, CrmProduct, CrmSource, CrmAnswer):
        rows = every(model)
        mine = [r for r in rows if r.workspace_id == a]
        theirs = [r for r in rows if r.workspace_id == b]
        assert mine and theirs and len(mine) == len(theirs), model
        assert not [r for r in rows if r.workspace_id is None], model
    # the same keys and codes exist once in each workspace
    keys = lambda ws: sorted(p.key for p in every(CrmPipeline) if p.workspace_id == ws)
    assert keys(a) == keys(b)
    codes = lambda ws: sorted(p.code for p in every(CrmProduct) if p.workspace_id == ws)
    assert codes(a) == codes(b)
    # a stage hangs on its own workspace's pipeline
    for st in CrmStage.query.execution_options(all_workspaces=True).all():
        assert st.pipeline.workspace_id in (a, b)


def test_a_lead_its_person_and_its_source_are_in_one_workspace(app, two):
    for lead, ws in ((two.la, two.a), (two.lb, two.b), (two.lb2, two.b)):
        lead = fresh(CrmLead, lead.id)
        assert lead.workspace_id == ws.id
        assert lead.person.workspace_id == ws.id
        assert lead.source.workspace_id == ws.id and lead.pipeline.workspace_id == ws.id
        assert lead.stage.pipeline_id == lead.pipeline_id
    # the same number is two contacts: one per workspace
    people = [p for p in every(CrmPerson) if p.phone == PHONE]
    assert sorted(p.workspace_id for p in people) == sorted([two.a.id, two.b.id])
    # the new lead went to somebody of ITS workspace
    assert fresh(CrmLead, two.lb.id).owner_id in (None, two.ben.id)
    assert fresh(CrmLead, two.la.id).owner_id in (None, two.ann.id)


def test_uniqueness_is_per_workspace(app, two):
    from sqlalchemy.exc import IntegrityError
    _db.session.add(CrmPerson(phone=PHONE, workspace_id=two.b.id))
    with pytest.raises(IntegrityError):
        _db.session.commit()
    _db.session.rollback()
    for model, kw in ((CrmPipeline, {'key': 'ti-standard', 'name': 'Again'}),
                      (CrmSource, {'key': 'ti-quote', 'name': 'Again'}),
                      (CrmProduct, {'code': 'TI', 'name': 'Again'})):
        _db.session.add(model(workspace_id=two.a.id, **kw))
        with pytest.raises(IntegrityError):
            _db.session.commit()
        _db.session.rollback()


def test_the_same_instagram_handle_can_be_a_contact_in_both_workspaces(app, two):
    l1 = crm.capture('instagram', name='Insta One', identities=[('instagram', '@same.handle')], channel='instagram',
                     utm={}, workspace_id=two.a.id)
    l2 = crm.capture('instagram', name='Insta Two', identities=[('instagram', 'same.handle')], channel='instagram',
                     utm={}, workspace_id=two.b.id)
    assert l1.person_id != l2.person_id
    rows = [i for i in every(CrmIdentity) if i.value == 'same.handle']
    assert sorted(i.workspace_id for i in rows) == sorted([two.a.id, two.b.id])
    # inside one workspace it is still one person
    l3 = crm.capture('instagram', name='Insta Again', identities=[('instagram', 'same.handle')], channel='instagram',
                     utm={}, workspace_id=two.b.id)
    assert l3.person_id == l2.person_id


def test_rows_made_by_a_signed_in_member_get_their_workspace(app, client, two):
    as_user(client, two.ben)
    r = client.post('/cs/crm/add', data={'name': 'Handmade Bhatt', 'phone': '+919800033333', 'source': 'call',
                                         'product': 'TI', 'owner': 'me'}, follow_redirects=True)
    assert r.status_code == 200
    p = next(p for p in every(CrmPerson) if p.name == 'Handmade Bhatt')
    assert p.workspace_id == two.b.id
    lead = next(l for l in every(CrmLead) if l.person_id == p.id)
    assert lead.workspace_id == two.b.id and lead.owner_id == two.ben.id
    # a history row about B's lead is B's
    client.post('/cs/crm/lead/%d/update' % lead.id, json={'likelihood': 'hot'})
    rows = [r for r in every(CrmAudit) if r.record_type == 'lead' and r.record_id == lead.id]
    assert rows and all(r.workspace_id == two.b.id for r in rows)


# ====================================================================================== the sweep

GETS = ('/cs/crm/?p=all&view=list&owner=all', '/cs/crm/?view=board&owner=all', '/cs/crm/?p=all&view=list&q=%s',
        '/cs/crm/contacts', '/cs/crm/contacts?q=%s', '/cs/crm/contacts?dups=1', '/cs/crm/today?who=all',
        '/cs/crm/calendar?who=all', '/cs/crm/calendar?tab=list&who=all', '/cs/crm/tracker', '/cs/crm/insights',
        '/cs/crm/forecast', '/cs/crm/flow', '/cs/crm/reports/build?run=1&what=leads&group=owner',
        '/admin/crm/export/leads?p=all&owner=all&win=all&reason=backup', '/admin/crm/export/contacts?reason=backup', '/admin/crm/insights.csv?reason=backup',
        '/admin/crm/insights-people.csv?reason=backup', '/cs/crm/forecast.csv?reason=backup', '/cs/crm/reports/build.csv?what=leads&group=source&reason=backup',
        '/admin/crm/bin', '/admin/crm/sources', '/admin/crm/pipelines', '/admin/crm/data', '/cs/crm/quick-replies',
        '/admin/crm/targets')


CONTROLS = ('/cs/crm/?p=all&view=list&owner=all', '/cs/crm/?view=board&owner=all', '/cs/crm/contacts',
            '/admin/crm/export/leads?p=all&owner=all&win=all&reason=backup', '/admin/crm/export/contacts?reason=backup')


def _sweep(client, user, query, hidden, shown, own=None):
    """Every screen and download: none of `hidden` (the other workspace's names and e-mail) shows, a search for
    `query` (a piece of them, echoed back by the search box) included. `own`: the member's own lead, whose contact
    has the same phone number as one in the other workspace."""
    as_user(client, user)
    extra = ()
    if own is not None:
        extra = ('/cs/crm/lead/%d' % own.id, '/cs/crm/lead/%d/live' % own.id, '/cs/crm/contact/%d' % own.person_id,
                 '/cs/crm/contact/%d/merge?q=%s' % (own.person_id, query), '/cs/crm/add?phone=%s' % PHONE)
    for url in GETS + extra:
        url = url % query if '%s' in url else url
        r = client.get(url, follow_redirects=True)
        assert r.status_code == 200, (url, r.status_code)
        page = r.get_data(as_text=True)
        for h in hidden:
            assert h not in page, (url, h)
    for url in CONTROLS:                                    # the control: these screens do list their own
        assert shown in words(client.get(url, follow_redirects=True).get_data(as_text=True)), url
    assert client.get('/cs/crm/find?q=%s' % query).get_json()['items'] == []
    assert shown in json.dumps(client.get('/cs/crm/find?q=%s' % shown).get_json())
    assert client.get('/cs/crm/flow/find?q=%s' % query).get_json()['items'] == []


def test_sweep_a_member_of_a_meets_nothing_of_b(app, client, two):
    _sweep(client, two.ann, 'Bravo', ('Bravoname', 'Bravotwo', 'bravo@example.com', '98000 22222'), 'Alphaname',
           own=two.la)


def test_sweep_a_member_of_b_meets_nothing_of_a(app, client, two):
    _sweep(client, two.ben, 'Alpha', ('Alphaname', 'alpha@example.com'), 'Bravoname', own=two.lb)


def test_sweep_the_other_workspaces_records_do_not_exist_by_their_id(app, client, two):
    lb, pid = two.lb, two.lb.person_id
    with crm_scope.use(two.b.id):
        q = crm_quotes.create(lb, {'title': 'Cover', 'amount': '1000', 'currency': 'INR'}, two.ben)
        pay = crm_quotes.add_payment(lb, {'amount': '1000', 'reference': 'bee-ref-1', 'provider': 'Test'}, two.ben)
        task = CrmTask(person_id=pid, title='Call Bravo', kind='todo', due_at=datetime.utcnow(), owner_id=two.ben.id)
        _db.session.add(task)
        _db.session.commit()
        qid, payid, tid = q.id, pay.id, task.id
    as_user(client, two.ann)
    for url in ('/cs/crm/lead/%d' % lb.id, '/cs/crm/lead/%d/live' % lb.id, '/cs/crm/contact/%d' % pid,
                '/cs/crm/contact/%d/edit' % pid, '/cs/crm/contact/%d/merge' % pid,
                '/cs/crm/email/compose?lead_id=%d' % lb.id):
        assert client.get(url).status_code == 404, url
    for url, body in (('/cs/crm/lead/%d/move' % lb.id, {'stage_id': lb.stage_id}),
                      ('/cs/crm/lead/%d/note' % lb.id, {'text': 'hello'}),
                      ('/cs/crm/lead/%d/remove' % lb.id, {}),
                      ('/cs/crm/lead/%d/call' % lb.id, {'outcome': 'connected'}),
                      ('/cs/crm/lead/%d/send' % lb.id, {'text': 'hello'}),
                      ('/cs/crm/tasks/add', {'lead_id': lb.id, 'title': 'x', 'kind': 'todo'}),
                      ('/cs/crm/tasks/add', {'person_id': pid, 'title': 'x', 'kind': 'todo'}),
                      ('/cs/crm/tasks/%d/edit' % tid, {'title': 'mine now'}),
                      ('/cs/crm/tasks/%d/delete' % tid, {}),
                      ('/cs/crm/task/%d/done' % tid, {}),
                      ('/cs/crm/email/send', {'lead_id': lb.id, 'subject': 's', 'body': 'b'})):
        assert client.post(url, json=body).status_code == 404, url
    for url in ('/cs/crm/quote/%d/status' % qid, '/cs/crm/quote/%d/delete' % qid,
                '/cs/crm/payment/%d/status' % payid, '/cs/crm/lead/%d/quote' % lb.id,
                '/cs/crm/contact/%d/merge' % pid, '/cs/crm/contact/%d/family/add' % pid):
        assert client.post(url, data={'status': 'paid', 'other_id': two.la.person_id}).status_code == 404, url
    # merging A's contact with B's by its id: refused, nothing moves
    r = client.post('/cs/crm/contact/%d/merge' % two.la.person_id, data={'other_id': pid, 'keep': 'this'})
    assert r.status_code in (302, 400, 404)
    assert fresh(CrmPerson, pid) is not None and fresh(CrmLead, lb.id).person_id == pid
    assert fresh(CrmLead, lb.id).deleted_at is None and fresh(CrmTask, tid).title == 'Call Bravo'
    assert fresh(CrmQuote, qid).status != 'deleted' and fresh(CrmPayment, payid).status == 'pending'


def test_sweep_files_views_and_saved_reports_stay_in_their_workspace(app, client, two):
    as_user(client, two.ben)
    r = client.post('/cs/crm/file/upload', data={'person_id': two.lb.person_id,
                                                 'file': (io.BytesIO(b'hello bee'), 'bee-note.txt')},
                    content_type='multipart/form-data')
    assert r.status_code == 302
    f = next(f for f in every(CrmFile) if f.filename == 'bee-note.txt')
    assert client.get('/cs/crm/file/%d/download' % f.id).status_code == 200
    client.post('/cs/crm/views/save', data={'scope': 'crm_leads', 'name': 'Bee hot ones', 'shared': 'on',
                                            'f_view': 'list', 'f_rating': 'hot'})
    client.post('/cs/crm/reports/save', data={'name': 'Bee by source', 'shared': 'on',
                                              'c_what': 'leads', 'c_group': 'source', 'c_measure': 'count'})
    client.get('/cs/crm/?p=all&view=list')                     # the "Saved" messages are read here, by Ben
    views = [v for v in every(CrmView) if v.name == 'Bee hot ones']
    reports = [r for r in every(CrmSavedReport) if r.name == 'Bee by source']
    assert views and views[0].workspace_id == two.b.id
    assert reports and reports[0].workspace_id == two.b.id
    as_user(client, two.ann)
    assert client.get('/cs/crm/file/%d/download' % f.id).status_code == 404
    assert client.post('/cs/crm/file/%d/delete' % f.id).status_code == 404
    for url in ('/cs/crm/?p=all&view=list', '/cs/crm/insights', '/cs/crm/reports/build'):
        t = client.get(url).get_data(as_text=True)
        assert 'Bee hot ones' not in t and 'Bee by source' not in t, url
    assert client.post('/cs/crm/views/%d/delete' % views[0].id).status_code in (403, 404) \
        or fresh(CrmView, views[0].id) is not None
    assert fresh(CrmView, views[0].id) is not None


def test_the_bin_and_forgetting_saved_days_stay_in_one_workspace(app, client, two):
    for l in every(CrmLead):
        l.created_at = datetime.utcnow() - timedelta(days=2)
    _db.session.commit()
    day = crm_numbers.today_ist() - timedelta(days=1)
    for wid in (two.a.id, two.b.id):
        with crm_scope.use(wid):
            crm_numbers.snapshot_day(day)
    rows = lambda wid: [r for r in every(CrmDailyStat) if r.workspace_id == wid and r.day == day]
    assert rows(two.a.id) and rows(two.b.id)
    as_user(client, two.ben)
    r = client.post('/cs/crm/lead/%d/remove' % two.lb2.id, json={})
    assert r.status_code in (200, 302)
    assert fresh(CrmLead, two.lb2.id) is None or fresh(CrmLead, two.lb2.id).deleted_at is not None
    assert rows(two.a.id) and not rows(two.b.id)                # B forgot its own days only
    t = client.get('/admin/crm/bin').get_data(as_text=True)
    assert 'Bravotwo' in t
    as_user(client, two.ann)
    assert 'Bravotwo' not in client.get('/admin/crm/bin').get_data(as_text=True)
    assert client.post('/admin/crm/bin/%d/restore' % two.lb2.id).status_code == 404


# ====================================================================================== composing the filters

def test_team_scope_workspace_and_bin_compose_on_one_statement(app, client, two):
    a = two.a
    team_role = WorkspaceRole(workspace_id=a.id, name='Team only', pages=sorted(access.CS_ROLE_PAGES), crm_scope='team')
    _db.session.add(team_role)
    _db.session.commit()
    tia = member(a, 'tia@test.com', 'tia', role=team_role)
    mate = member(a, 'mate@test.com', 'mate', role_key='cs')
    stranger = member(a, 'stranger@test.com', 'stranger', role_key='cs')
    team = WorkspaceTeam(workspace_id=a.id, name='North')
    _db.session.add(team)
    _db.session.flush()
    team.users.extend([tia, mate])
    _db.session.commit()

    def lead(name, phone, owner):
        l = crm.capture('ti-quote', name=name, phone=phone, utm={}, workspace_id=a.id)
        l.owner_id = owner.id
        _db.session.commit()
        return l
    lead('Tiaown Lead', '+919800044441', tia)
    lead('Mateteam Lead', '+919800044442', mate)
    lead('Strangerhidden Lead', '+919800044443', stranger)
    binned = lead('Tiabinned Lead', '+919800044444', tia)
    crm_bin.remove(binned)
    # B's lead given to tia's id would still be B's
    lb = fresh(CrmLead, two.lb.id)
    lb.owner_id = tia.id
    _db.session.commit()
    as_user(client, tia)
    t = words(client.get('/cs/crm/?p=all&view=list&owner=all').get_data(as_text=True))
    assert 'Tiaown' in t and 'Mateteam' in t
    assert 'Strangerhidden' not in t and 'Bravo' not in t and 'Tiabinned' not in t
    assert client.get('/cs/crm/lead/%d' % lb.id).status_code == 404
    # the same three on one ORM statement inside the request
    with app.test_request_context('/cs/crm/'):
        g._login_user = tia
        names = {l.person.name for l in CrmLead.query.all()}
        assert names == {'Tiaown Lead', 'Mateteam Lead'}


# ====================================================================================== captures and webhooks

def test_a_public_form_lands_in_its_sources_workspace(app, client, two):
    with crm_scope.use(two.b.id):
        pipe = CrmPipeline.query.filter_by(key='ti-standard').first() or CrmPipeline.query.first()
        _db.session.add(CrmSource(key='bee-landing', name='Bee landing page', kind='form', product='TI',
                                  pipeline=pipe, status='live'))
        _db.session.commit()
    r = client.post('/api/leads', json={'source': 'bee-landing', 'name': 'Formfill Bee', 'phone': '+919800055555'})
    assert r.status_code == 201
    lead = next(l for l in every(CrmLead) if l.person.name == 'Formfill Bee')
    assert lead.workspace_id == two.b.id and lead.person.workspace_id == two.b.id
    assert lead.source.key == 'bee-landing' and lead.pipeline.workspace_id == two.b.id
    assert lead.owner_id in (None, two.ben.id)
    # a key both workspaces have (the site's own forms): the first workspace
    r = client.post('/api/leads', json={'source': 'ti-quote', 'name': 'Siteform Default', 'phone': '+919800055556'})
    assert r.status_code == 201
    lead = next(l for l in every(CrmLead) if l.person.name == 'Siteform Default')
    assert lead.workspace_id == two.a.id
    # a key nobody has: made unrouted in the first workspace
    client.post('/api/leads', json={'source': 'brand-new-page', 'name': 'Newpage Person', 'phone': '+919800055557'})
    src = next(s for s in every(CrmSource) if s.key == 'brand-new-page')
    assert src.workspace_id == two.a.id and src.status == 'unrouted'


def test_the_whatsapp_webhook_goes_to_the_workspace_linked_to_whatsapp(app, client, two, monkeypatch):
    from app.services import wacrm, wacrm_team
    monkeypatch.setenv('WACRM_WEBHOOK_SECRET', 'whsec_test')

    def no_call(*a, **k):
        raise AssertionError('called the WhatsApp CRM')
    monkeypatch.setattr(wacrm, '_call', no_call)
    monkeypatch.setattr(wacrm_team, '_api', no_call)
    two.b.wacrm = {'account_id': 'acc-1', 'name': 'Bee Care'}           # WhatsApp is B's
    _db.session.commit()
    raw = json.dumps({'event': 'message.received', 'data': {
        'contact_id': 'c-1', 'conversation_id': 'conv-1', 'contact_phone': DIGITS, 'contact_name': 'Bravo',
        'content_type': 'text', 'text': 'Hello from WhatsApp', 'whatsapp_message_id': 'wamid.bee1'}}).encode()
    t = int(time.time())
    sig = hmac.new(b'whsec_test', str(t).encode() + b'.' + raw, hashlib.sha256).hexdigest()
    r = client.post('/api/crm/wacrm-webhook', data=raw,
                    headers={'X-Wacrm-Signature': 't=%d,v1=%s' % (t, sig), 'Content-Type': 'application/json'})
    assert r.status_code == 200 and r.get_json()['ok']
    tp = next(tp for tp in every(CrmTouchpoint) if tp.external_id == 'wamid.bee1')
    assert tp.person_id == two.lb.person_id                     # B's contact, not A's with the same number
    assert not [x for x in every(CrmTouchpoint) if x.person_id == two.la.person_id and x.channel == 'whatsapp']


def test_an_email_goes_to_the_person_it_comes_from_and_a_stranger_to_the_default(app, client, two, monkeypatch):
    monkeypatch.setenv('CRM_INBOUND_EMAIL_TOKEN', 'tok-123')
    r = client.post('/api/crm/email-inbound?token=tok-123',
                    data={'from': 'Bravo <bravo@example.com>', 'subject': 'Hi', 'text': 'About my cover'})
    assert r.get_json()['result'] == 'logged'
    assert r.get_json()['person_id'] == two.lb.person_id
    r = client.post('/api/crm/email-inbound?token=tok-123',
                    data={'from': 'New One <newone@example.com>', 'subject': 'Hi', 'text': 'A question'})
    assert r.get_json()['result'] == 'new_lead'
    assert fresh(CrmLead, r.get_json()['lead_id']).workspace_id == two.a.id


def test_a_google_lead_form_routed_in_b_lands_in_b(app, client, two, monkeypatch):
    monkeypatch.setenv('CRM_GOOGLE_LEADS_KEY', 'gkey')
    with crm_scope.use(two.b.id):
        _db.session.add(CrmSource(key='google-form-4321', name='Bee Google form', kind='form', product='TI',
                                  status='unrouted'))
        _db.session.commit()
    body = {'google_key': 'gkey', 'lead_id': 'GL-bee', 'form_id': '4321', 'is_test': False,
            'user_column_data': [{'column_id': 'FULL_NAME', 'string_value': 'Googly Bee'},
                                 {'column_id': 'PHONE_NUMBER', 'string_value': '+919800066666'}]}
    r = client.post('/api/crm/google-leads', data=json.dumps(body), content_type='application/json')
    assert r.status_code == 200
    lead = next(l for l in every(CrmLead) if l.person.name == 'Googly Bee')
    assert lead.workspace_id == two.b.id and lead.source.workspace_id == two.b.id
    assert len([s for s in every(CrmSource) if s.key == 'google-form-4321']) == 1


def test_a_payment_webhook_finds_its_payment_in_any_workspace(app, client, two, monkeypatch):
    monkeypatch.setenv('CRM_PAYMENT_WEBHOOK_SECRET', 'paysecret')
    with crm_scope.use(two.b.id):
        crm_quotes.add_payment(two.lb, {'amount': '1000', 'reference': 'bee-pay-9', 'provider': 'Test'}, two.ben)
        _db.session.commit()
    raw = json.dumps({'reference': 'bee-pay-9', 'status': 'paid'}).encode()
    sig = hmac.new(b'paysecret', raw, hashlib.sha256).hexdigest()
    r = client.post('/api/crm/payment-webhook', data=raw, headers={'X-Signature': sig}, content_type='application/json')
    assert r.status_code == 200
    assert fresh(CrmLead, two.lb.id).status == 'won'
    assert fresh(CrmLead, two.la.id).status == 'open'


# ====================================================================================== jobs

def test_an_automation_of_a_never_touches_bs_leads(app, two, monkeypatch):
    def first_two(ws):
        with crm_scope.use(ws.id):
            pipe = CrmPipeline.query.filter_by(key=fresh(CrmLead, two.la.id).pipeline.key).one()
            opens = [s for s in pipe.stages if s.kind == 'open']
            return opens[0], opens[1]
    a_from, a_to = first_two(two.a)
    # A's "no reply in 1 day" rule; B's same stage (same key) has none
    a_from.auto_kind, a_from.auto_days, a_from.auto_to_id, a_from.auto_reason = 'no_reply', 1, a_to.id, 'No reply'
    for l in every(CrmLead):
        l.entered_stage_at = datetime.utcnow() - timedelta(days=3)
    _db.session.commit()
    seen = []

    def spy(name):
        def run(*a, **k):
            seen.append((name, crm_scope.current_id(), sorted(l.id for l in CrmLead.query.all())))
            return {name: 1}
        return run
    monkeypatch.setattr(crm, 'run_waiting_alerts', spy('crm_waiting_alerts'))
    monkeypatch.setattr(crm, 'run_auto_steps', spy('crm_auto_sent'))
    out = jobs.run_all()
    assert out['crm_auto_moved'] == 1
    assert out['crm_waiting_alerts'] == 2 and out['crm_auto_sent'] == 2      # once per workspace, added up
    assert fresh(CrmLead, two.la.id).stage_id == a_to.id
    for l in (two.lb, two.lb2):
        lb = fresh(CrmLead, l.id)
        assert lb.stage.position == 0 or lb.stage.kind != 'open' or lb.stage_id != a_to.id
        assert not CrmLead.query.execution_options(all_workspaces=True).filter(
            CrmLead.id == l.id, CrmLead.stage_id == a_to.id).count()
    # each run saw only its own workspace's leads
    for name in ('crm_waiting_alerts', 'crm_auto_sent'):
        assert sorted(s[1:] for s in seen if s[0] == name) == sorted(
            [(two.a.id, [two.la.id]), (two.b.id, sorted([two.lb.id, two.lb2.id]))])


def test_saved_numbers_are_per_workspace_and_results_read_only_the_current_one(app, client, two):
    yesterday = datetime.utcnow() - timedelta(days=1)
    for l in every(CrmLead):
        l.created_at = yesterday
    _db.session.commit()
    out = crm_scope.each_workspace(crm_numbers.snapshot_missing_days, limit_days=1)
    assert out['crm_snapshot_days'] == 2                          # one day saved in each workspace
    day = crm_numbers.ist_day(yesterday)
    company = lambda wid: next(r.value for r in every(CrmDailyStat) if r.workspace_id == wid and r.day == day
                               and r.metric == 'new_leads' and r.user_id is None and r.pipeline_id is None)
    assert company(two.a.id) == 1 and company(two.b.id) == 2
    since, until = crm_numbers.day_bounds(day)
    with crm_scope.use(two.a.id):
        assert crm_numbers.compute('new_leads', since, until) == 1
    with crm_scope.use(two.b.id):
        assert crm_numbers.compute('new_leads', since, until) == 2
    for u in (two.ann, two.ben):
        as_user(client, u)
        assert client.get('/cs/crm/insights', follow_redirects=True).status_code == 200


# ====================================================================================== defaults and switching

def test_a_new_workspace_from_the_flow_gets_its_own_crm_set_up(app, client, two, admin_user):
    as_user(client, admin_user)
    plan = {'name': 'Cee Clinic', 'description': '', 'modules': ['crm'], 'phone': '+91 98765 43299', 'people': [],
            'invites': [],
            'teams': [], 'send_links': False}
    r = client.post('/admin/workspace/new', data={'plan': json.dumps(plan)})
    assert r.status_code in (200, 302)
    cee = Workspace.query.filter_by(name='Cee Clinic').one()
    for model in (CrmPipeline, CrmProduct, CrmSource, CrmAnswer):
        assert [r for r in every(model) if r.workspace_id == cee.id], model
    assert not [l for l in every(CrmLead) if l.workspace_id == cee.id]


def test_legacy_staff_and_old_rows_without_a_workspace_are_the_default_ones(app, client, two):
    old = crm.capture('ti-quote', name='Oldrow Person', phone='+919800077777', utm={}, workspace_id=two.a.id)
    for model, rid in ((CrmLead, old.id), (CrmPerson, old.person_id)):     # rows from before workspaces
        _db.session.execute(model.__table__.update().where(model.__table__.c.id == rid).values(workspace_id=None))
    _db.session.commit()
    legacy = make_user('legacy@test.com', 'legacy', role='cs')     # staff in no workspace
    as_user(client, legacy)
    t = words(client.get('/cs/crm/?p=all&view=list&owner=all').get_data(as_text=True))
    assert 'Oldrow' in t and 'Alphaname' in t and 'Bravo' not in t
    assert client.get('/cs/crm/lead/%d' % old.id).status_code == 200
    assert client.get('/cs/crm/lead/%d' % two.lb.id).status_code == 404
    as_user(client, two.ben)
    assert 'Oldrow' not in client.get('/cs/crm/?p=all&view=list&owner=all').get_data(as_text=True)
    assert client.get('/cs/crm/lead/%d' % old.id).status_code == 404


def test_a_super_admin_switching_workspace_sees_the_other_crm(app, client, two, admin_user):
    as_user(client, admin_user)
    t = words(client.get('/cs/crm/?p=all&view=list&owner=all').get_data(as_text=True))
    assert 'Alphaname' in t and 'Bravo' not in t                  # the first workspace to start with
    client.get('/admin/workspace/switch/%d' % two.b.id)
    t = words(client.get('/cs/crm/?p=all&view=list&owner=all').get_data(as_text=True))
    assert 'Bravoname' in t and 'Alphaname' not in t
    assert client.get('/cs/crm/lead/%d' % two.lb.id).status_code == 200
    assert client.get('/cs/crm/lead/%d' % two.la.id).status_code == 404


def test_settings_stay_global(app, two):
    crm.save_settings(None, waiting_alert_minutes=45)
    _db.session.commit()
    with crm_scope.use(two.b.id):
        assert crm.crm_settings()['waiting_alert_minutes'] == 45


# ====================================================================================== WhatsApp

def test_the_second_workspaces_whatsapp_page_says_where_whatsapp_is(app, client, two, monkeypatch):
    for k, v in (('WACRM_URL', 'https://crm.example/crm'), ('WACRM_API_KEY', 'k'), ('WACRM_PORTAL_SECRET', 'x' * 40)):
        monkeypatch.setenv(k, v)
    from app.services import wacrm, wacrm_team
    calls = []

    def no_wa(*a, **k):
        calls.append(a)
        raise wacrm.WacrmError('not in tests')

    def no_team(*a, **k):
        calls.append(a)
        raise wacrm_team.TeamError('not in tests')
    monkeypatch.setattr(wacrm, '_call', no_wa)
    monkeypatch.setattr(wacrm_team, '_api', no_team)
    two.a.wacrm = {'account_id': 'acc-1', 'name': two.a.name}
    crm.save_settings(None, whatsapp_mode='contacts')
    _db.session.commit()
    as_user(client, two.ben)
    r = client.get('/admin/crm/connection')
    assert r.status_code == 200
    t = words(r.get_data(as_text=True))
    assert 'WhatsApp is linked to %s' % two.a.name in t
    assert client.get('/admin/crm/connection/checks').get_json() == {'cards': '', 'rules': ''}
    # nothing about WhatsApp is changed from here
    client.post('/admin/crm/setup/whatsapp', data={'action': 'mode', 'mode': 'off'})
    assert crm.crm_settings()['whatsapp_mode'] == 'contacts'
    with crm_scope.use(two.b.id):
        assert crm.wa_mode() == 'off' and not crm.wa_writes_on()
        assert not crm.mark_wa_due(fresh(CrmPerson, two.lb.person_id))
    with crm_scope.use(two.a.id):
        assert crm.wa_writes_on()
    # B's lead page draws without errors, and never asks WhatsApp about B's contact
    assert client.get('/cs/crm/lead/%d' % two.lb.id).status_code == 200
    assert not [c for c in calls if DIGITS in json.dumps(c, default=str)]
    as_user(client, two.ann)
    assert 'WhatsApp is linked to' not in words(client.get('/admin/crm/connection').get_data(as_text=True))


# ====================================================================================== the migration

def test_migration_u7crm023_goes_up_down_up_on_sqlite_with_rows(tmp_path):
    import importlib.util
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations', 'versions',
                        'u7crm023_crm_per_workspace.py')
    spec = importlib.util.spec_from_file_location('u7crm023', path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    assert mig.revision == 'u7crm023' and mig.down_revision == 'u6crm022'
    engine = sa.create_engine('sqlite:///%s' % (tmp_path / 'm.db'))
    meta = sa.MetaData()
    sa.Table('workspaces', meta, sa.Column('id', sa.Integer, primary_key=True), sa.Column('name', sa.String(20)))
    for t in mig.TABLES:                                # the tables as the earlier migrations left them
        cols = [sa.Column('id', sa.Integer, primary_key=True)]
        if t == 'crm_people':
            cols.append(sa.Column('phone', sa.String(20), unique=True))          # unnamed, as p1crm001 made it
        if t in ('crm_pipelines', 'crm_sources'):
            cols.append(sa.Column('key', sa.String(20), unique=True))
        if t == 'crm_products':
            cols += [sa.Column('code', sa.String(8)), sa.UniqueConstraint('code', name='uq_crm_product_code')]
        if t == 'crm_identities':
            cols += [sa.Column('person_id', sa.Integer), sa.Column('kind', sa.String(20)),
                     sa.Column('value', sa.String(20)), sa.UniqueConstraint('kind', 'value', name='uq_crm_identity')]
        if t == 'crm_channel_checks':
            cols += [sa.Column('day', sa.Date), sa.Column('slot', sa.Integer), sa.Column('channel', sa.String(20)),
                     sa.UniqueConstraint('day', 'slot', 'channel', name='uq_crm_check')]
        sa.Table(t, meta, *cols)
    meta.create_all(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO workspaces (id, name) VALUES (3, 'First'), (5, 'Second')"))
        conn.execute(sa.text("INSERT INTO crm_people (id, phone) VALUES (1, '+911'), (2, '+912')"))
        conn.execute(sa.text("INSERT INTO crm_identities (id, person_id, kind, value) VALUES (1, 1, 'instagram', 'x')"))
        conn.execute(sa.text("INSERT INTO crm_pipelines (id, key) VALUES (1, 'ti')"))
        conn.execute(sa.text("INSERT INTO crm_products (id, code) VALUES (1, 'TI')"))
        conn.execute(sa.text("INSERT INTO crm_leads (id) VALUES (1), (2)"))
        conn.execute(sa.text("INSERT INTO crm_daily_stats (id) VALUES (1)"))
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mig.upgrade()
        insp = sa.inspect(conn)
        for t in mig.TABLES:
            assert 'workspace_id' in {c['name'] for c in insp.get_columns(t)}, t
            assert 'ix_%s_workspace_id' % t in {i['name'] for i in insp.get_indexes(t)}, t
            assert any(fk['referred_table'] == 'workspaces' for fk in insp.get_foreign_keys(t)), t
        for t in ('crm_people', 'crm_identities', 'crm_pipelines', 'crm_products', 'crm_leads', 'crm_daily_stats'):
            assert {r[0] for r in conn.execute(sa.text('SELECT workspace_id FROM %s' % t))} == {3}, t
        assert [u['column_names'] for u in insp.get_unique_constraints('crm_people')] == [['workspace_id', 'phone']]
        assert [u['column_names'] for u in insp.get_unique_constraints('crm_identities')] == \
            [['workspace_id', 'kind', 'value']]
        # the same number in the second workspace is fine; twice in one is not
        conn.execute(sa.text("INSERT INTO crm_people (id, phone, workspace_id) VALUES (3, '+911', 5)"))
        with pytest.raises(sa.exc.IntegrityError):
            with conn.begin_nested():
                conn.execute(sa.text("INSERT INTO crm_people (id, phone, workspace_id) VALUES (4, '+911', 5)"))
        conn.execute(sa.text('DELETE FROM crm_people WHERE id = 3'))
        with Operations.context(ctx):
            mig.downgrade()
        insp = sa.inspect(conn)
        assert 'workspace_id' not in {c['name'] for c in insp.get_columns('crm_people')}
        uq = {t: [(u['name'], u['column_names']) for u in insp.get_unique_constraints(t)] for t in mig.UNIQUES}
        assert uq['crm_people'] == [('crm_people_phone_key', ['phone'])]
        assert uq['crm_products'] == [('uq_crm_product_code', ['code'])]
        assert uq['crm_identities'] == [('uq_crm_identity', ['kind', 'value'])]
        assert conn.execute(sa.text('SELECT count(*) FROM crm_people')).scalar() == 2
        with Operations.context(ctx):
            mig.upgrade()
        assert [u['name'] for u in sa.inspect(conn).get_unique_constraints('crm_people')] == ['uq_crm_people_ws_phone']

@pytest.fixture(autouse=True)
def _leads_shared_out(monkeypatch):
    """These tests were written when a source gave a new lead to whoever had the fewest open leads unless told
    otherwise. Since 2026-10-23 nothing set means nobody (crm_assign.DEFAULT; tests/test_crm2_assign.py)."""
    from app.services import crm_assign
    monkeypatch.setattr(crm_assign, 'DEFAULT', 'fewest')
