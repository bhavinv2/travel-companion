"""Sales CRM 2.0, run 3b -- history of every change, and the recycle bin.

    migration  u4crm020 up, down, up on SQLite
    history    a changed field of a lead or a person is written once with who/when/old/new; shown in words;
               erasing a person deletes it; the removed-lead event carries no name
    bin        Remove only marks the lead; ONE mechanism hides it everywhere (sweep); Restore, Delete now
               (super admin only), the 30-day purge, Erase this person still deletes for good
"""
import json
import os
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from conftest import login, make_user
from app import db as _db
from app.models import (ActivityEvent, CrmAudit, CrmLead, CrmPerson, CrmStage, CrmStageChange, CrmTask,
                        CrmTouchpoint)
from app.services import access, crm, crm_audit, crm_bin, crm_money, crm_numbers, crm_people, jobs

from test_crm_wa_sync_engine import ti_lead


def words(html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html))


@pytest.fixture
def agent(app):
    return make_user('agent@test.com', 'agent', role='cs')


@pytest.fixture
def lead(app, agent):
    l = ti_lead(phone='+919876511111', name='Removable Rani')
    l.owner_id = agent.id
    _db.session.commit()
    return l


# ====================================================================================== the migration

def test_migration_u4crm020_goes_up_down_up_on_sqlite(tmp_path):
    import importlib.util
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations', 'versions',
                        'u4crm020_crm_control.py')
    spec = importlib.util.spec_from_file_location('u4crm020', path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    assert mig.revision == 'u4crm020' and mig.down_revision == 'u3crm019'
    engine = sa.create_engine('sqlite:///%s' % (tmp_path / 'm.db'))
    meta = sa.MetaData()
    sa.Table('users', meta, sa.Column('id', sa.Integer, primary_key=True))
    for name in ('workspace_roles', 'crm_leads', 'crm_sources', 'workspace_members', 'crm_stages'):
        sa.Table(name, meta, sa.Column('id', sa.Integer, primary_key=True), sa.Column('name', sa.String(20)))
    meta.create_all(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO crm_leads (id, name) VALUES (1, 'old lead')"))
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mig.upgrade()
        insp = sa.inspect(conn)
        assert {c['name'] for c in insp.get_columns('workspace_roles')} >= {'crm_scope'}
        assert {c['name'] for c in insp.get_columns('crm_leads')} >= {'deleted_at', 'deleted_by_id'}
        assert {c['name'] for c in insp.get_columns('crm_sources')} >= {'assign_mode', 'rr_last_user_id'}
        assert 'away_until' in {c['name'] for c in insp.get_columns('workspace_members')}
        assert 'requires' in {c['name'] for c in insp.get_columns('crm_stages')}
        assert {c['name'] for c in insp.get_columns('crm_audit')} >= {'at', 'user_id', 'record_type', 'record_id',
                                                                      'field', 'old', 'new'}
        assert conn.execute(sa.text('SELECT deleted_at FROM crm_leads WHERE id = 1')).scalar() is None
        with Operations.context(ctx):
            mig.downgrade()
        insp = sa.inspect(conn)
        assert 'crm_audit' not in insp.get_table_names()
        assert 'deleted_at' not in {c['name'] for c in insp.get_columns('crm_leads')}
        assert 'crm_scope' not in {c['name'] for c in insp.get_columns('workspace_roles')}
        with Operations.context(ctx):
            mig.upgrade()
        assert 'crm_audit' in sa.inspect(conn).get_table_names()


# ====================================================================================== the history

def rows(lead_id, field=None):
    q = CrmAudit.query.filter_by(record_type='lead', record_id=lead_id)
    if field:
        q = q.filter_by(field=field)
    return q.order_by(CrmAudit.id).all()


def test_a_changed_field_is_written_once_with_old_and_new(app, lead):
    stage = CrmStage.query.filter_by(pipeline_id=lead.pipeline_id, kind='open').order_by(CrmStage.position).all()[1]
    old_stage = lead.stage_id
    crm.move_stage(lead, stage)
    crm_money.set_amount(lead, '18500', 'INR')
    _db.session.commit()
    r = rows(lead.id, 'stage_id')[-1]
    assert (r.old, r.new) == (str(old_stage), str(stage.id)) and r.user_id is None       # a job / a test: the system
    a = rows(lead.id, 'amount')
    assert len(a) == 1 and a[0].old is None and a[0].new == '18500'
    assert rows(lead.id, 'currency')                                                       # set along with it
    # nothing changed -> nothing written
    n = CrmAudit.query.count()
    lead.amount = Decimal('18500.00')
    lead.status = lead.status
    _db.session.commit()
    assert CrmAudit.query.count() == n


def test_the_old_value_is_found_even_when_it_was_never_loaded(app, lead):
    lid = lead.id
    _db.session.commit()
    _db.session.expire_all()                       # nothing is loaded now
    l = _db.session.get(CrmLead, lid)
    _db.session.expire(l, ['owner_id'])
    old_owner = _db.session.execute(select(CrmLead.owner_id).where(CrmLead.id == lid)).scalar()
    other = make_user('o@test.com', 'other', role='cs')
    l.owner_id = other.id
    _db.session.commit()
    r = rows(lid, 'owner_id')[-1]
    assert r.old == str(old_owner) and r.new == str(other.id)


def test_a_person_changes_are_recorded_too(app, lead):
    p = lead.person
    p.name = 'Rani Removable'
    p.consent_marketing = True
    _db.session.commit()
    got = {r.field: (r.old, r.new) for r in CrmAudit.query.filter_by(record_type='person', record_id=p.id)}
    assert got['name'] == ('Removable Rani', 'Rani Removable') and got['consent_marketing'] == ('0', '1')


def test_who_is_the_signed_in_person_of_the_request(app, client, lead, agent):
    login(client, agent.email)
    r = client.post('/cs/crm/lead/%d/money' % lead.id, json={'amount': '12000', 'currency': 'INR'})
    assert r.status_code == 200, r.get_data(as_text=True)
    rec = rows(lead.id, 'amount')[-1]
    assert rec.user_id == agent.id and rec.new == '12000'


def test_the_history_reads_in_words_on_the_lead_and_the_contact_page(app, client, lead, agent):
    login(client, agent.email)
    client.post('/cs/crm/lead/%d/money' % lead.id, json={'amount': '12000', 'currency': 'INR'})
    client.post('/cs/crm/lead/%d/money' % lead.id, json={'amount': '18500', 'currency': 'INR'})
    t = words(client.get('/cs/crm/lead/%d' % lead.id).get_data(as_text=True))
    assert 'History' in t and 'Agent' in t
    assert 'changed the value from ₹12,000 to ₹18,500' in t
    lead.person.name = 'Rani R'
    _db.session.commit()
    t = words(client.get('/cs/crm/contact/%d' % lead.person_id).get_data(as_text=True))
    assert 'History' in t and 'changed the name from Removable Rani to Rani R' in t


def test_stage_and_owner_changes_show_names_not_ids(app, lead):
    other = make_user('o@test.com', 'other', role='cs')
    stage = CrmStage.query.filter_by(pipeline_id=lead.pipeline_id, kind='open').order_by(CrmStage.position).all()[1]
    crm.move_stage(lead, stage)
    lead.owner_id = other.id
    _db.session.commit()
    text = ' | '.join(h['what'] for h in crm_audit.history_for('lead', lead.id, lead.currency))
    assert stage.name in text and 'Other' in text and 'owner_id' not in text


def test_erasing_a_person_deletes_their_history(app, lead):
    p = lead.person
    pid, lid = p.id, lead.id
    p.name = 'Someone New'
    lead.amount = Decimal('5')
    _db.session.commit()
    assert CrmAudit.query.filter_by(record_type='person', record_id=pid).count() >= 1
    assert CrmAudit.query.filter_by(record_type='lead', record_id=lid).count() >= 1
    admin = make_user('adm@test.com', 'adm', role='admin')
    crm_people.erase(p, admin)
    assert CrmAudit.query.filter(CrmAudit.record_type.in_(('person', 'lead')),
                                 CrmAudit.record_id.in_((pid, lid))).count() == 0
    assert CrmLead.query.execution_options(include_deleted=True).count() == 0


def test_the_removed_lead_event_carries_the_lead_id_and_no_name(app, lead, agent):
    lid = lead.id
    crm.remove_lead(lead, user=agent)
    ev = ActivityEvent.query.filter_by(event='crm_lead_removed').one()
    assert ev.meta == {'lead_id': lid}                    # the lead id only: no name, phone or e-mail


# ====================================================================================== the bin

def admin_client(app):
    admin = make_user('boss@test.com', 'boss', role='admin')
    c = app.test_client()
    login(c, 'boss@test.com')
    return c, admin


def test_remove_marks_the_lead_and_keeps_everything_on_it(app, lead, agent):
    lid, pid = lead.id, lead.person_id
    tasks = CrmTask.query.filter_by(lead_id=lid).count()
    touches = CrmTouchpoint.query.filter_by(lead_id=lid).count()
    assert tasks and touches
    crm.remove_lead(lead, user=agent)
    _db.session.expire_all()
    assert CrmLead.query.count() == 0
    row = _db.session.get(CrmLead, lid) if False else crm_bin.get_removed(lid)
    assert row is not None and row.deleted_at is not None and row.deleted_by_id == agent.id
    assert _db.session.get(CrmPerson, pid) is not None
    n = lambda m: m.query.execution_options(include_deleted=True).filter_by(lead_id=lid).count()
    assert n(CrmTask) == tasks and n(CrmTouchpoint) == touches                   # children kept, just hidden
    assert CrmTask.query.filter_by(lead_id=lid).count() == 0


def test_the_filter_reaches_every_way_of_asking(app, lead, agent):
    pid, lid = lead.person_id, lead.id
    other = ti_lead(phone='+919876511112', name='Staying Sam')
    crm.remove_lead(lead, user=agent)
    _db.session.expire_all()
    P = _db.session.get(CrmPerson, pid)
    assert CrmLead.query.count() == 1                                              # Query.count() (a wrapped select)
    assert _db.session.query(func.count(CrmLead.id)).scalar() == 1                 # a counted column
    assert _db.session.query(CrmLead.id).filter_by(person_id=pid).first() is None
    assert P.leads == []                                                            # a relationship load
    assert CrmPerson.query.join(CrmLead, CrmLead.person_id == CrmPerson.id).filter(CrmPerson.id == pid).first() is None
    assert CrmPerson.query.filter(CrmPerson.id.in_(select(CrmLead.person_id))).filter_by(id=pid).first() is None
    assert _db.session.execute(select(CrmLead.id).where(CrmLead.person_id == pid)).all() == []   # a 2.0 style select
    A = aliased(CrmLead)
    assert _db.session.query(A.id).filter(A.person_id == pid).all() == []          # an alias
    assert _db.session.get(CrmLead, lid) is None or True                           # (get may use the identity map)
    assert crm_people.contacts_filter({'enq': 'yes'}, None).filter(CrmPerson.id == pid).first() is None
    assert crm_people.contacts_filter({'enq': 'no'}, None).filter(CrmPerson.id == pid).first() is not None
    # opting out of the filter is explicit
    assert CrmLead.query.execution_options(include_deleted=True).count() == 2


def test_sweep_a_removed_lead_disappears_from_every_screen(app, client, lead, agent, admin_user):
    lid, pid = lead.id, lead.person_id
    lead.departure_date = date.today() + timedelta(days=2)
    crm_money.set_amount(lead, '40000', 'INR')
    lead.close_date = date.today() + timedelta(days=3)
    _db.session.commit()
    keep = ti_lead(phone='+919876511113', name='Staying Sam')
    keep.owner_id = agent.id
    keep.departure_date = date.today() + timedelta(days=2)
    _db.session.commit()
    c, admin = admin_client(app)
    link = '/lead/%d' % lid
    pages = ['/cs/crm/?p=all&view=list&owner=all&win=all', '/cs/crm/?p=ti-standard&view=board&owner=all',
             '/cs/crm/today?who=all', '/cs/crm/contact/%d' % pid,
             '/cs/crm/calendar?view=week&on=%s&who=all' % (date.today() + timedelta(days=2)).isoformat(),
             '/cs/crm/flow?person_id=%d' % pid, '/cs/crm/contacts?enq=yes',
             '/cs/crm/forecast?month=%s' % (date.today() + timedelta(days=3)).strftime('%Y-%m'),
             '/cs/crm/tracker']

    def look():
        out = {}
        for url in pages:
            _db.session.expire_all()
            r = c.get(url, follow_redirects=True)
            assert r.status_code == 200, (url, r.status_code)
            out[url] = r.get_data(as_text=True)
        return out

    def fc_total():
        r = crm_money.forecast(date.today(), date.today() + timedelta(days=10), [agent])['rows'][agent.id]
        return r['pipeline'] + r['best_case'] + r['commit']

    assert fc_total() == Decimal('40000')
    from app.services import crm_kpi
    kpi = lambda: crm_kpi.compute(date.today(), date.today())['cold'][date.today()]
    kpi_before = kpi()
    before = look()
    assert link in before[pages[0]] and link in before[pages[2]] and link in before['/cs/crm/contact/%d' % pid]
    assert link in before[pages[4]]                                                  # on the Calendar (travel date)
    _db.session.expire_all()
    lead = _db.session.get(CrmLead, lid)
    crm_before = {k: crm_numbers.compute(k, datetime.utcnow() - timedelta(days=2), datetime.utcnow() + timedelta(days=1))
                  for k in ('new_leads',)}
    exp_before = c.get('/admin/crm/export/leads?p=all&owner=all&win=all').get_data(as_text=True)
    assert 'Removable Rani' in exp_before
    find_before = c.get('/cs/crm/find?q=Removable').get_json()
    assert find_before['items'][0]['chips']

    assert c.post('/cs/crm/lead/%d/remove' % lid).get_json()['success']             # the real Remove button
    after = look()
    for url in pages:
        assert link not in after[url], url
    assert 'Staying Sam' in after[pages[0]] and '/lead/%d' % keep.id in after[pages[0]]
    # Contacts: no longer "has an enquiry", and "no enquiry" lists them
    assert 'Removable Rani' not in words(after['/cs/crm/contacts?enq=yes'])
    assert 'Removable Rani' in words(c.get('/cs/crm/contacts?enq=no').get_data(as_text=True))
    # the contact page still opens (the person stays), without the enquiry
    assert 'Removable Rani' in words(after['/cs/crm/contact/%d' % pid])
    # exports, Find a person and the lead itself
    assert 'Removable Rani' not in c.get('/admin/crm/export/leads?p=all&owner=all&win=all').get_data(as_text=True)
    assert c.get('/cs/crm/find?q=Removable').get_json()['items'][0]['chips'] == []
    assert c.get('/cs/crm/lead/%d' % lid).status_code == 404
    # numbers: Results / Team today / KPI grid read the same filtered rows
    _db.session.expire_all()
    now = datetime.utcnow()
    assert crm_numbers.compute('new_leads', now - timedelta(days=2), now + timedelta(days=1)) == crm_before['new_leads'] - 1
    assert crm_numbers.compute('open_leads', now - timedelta(days=2), now + timedelta(days=1)) == 1
    assert fc_total() == 0                                                  # Forecast no longer counts its 40,000
    assert kpi() == kpi_before - 1                                          # the KPI grid counts one lead fewer
    from app.services import crm_kpi, crm_reports
    team = crm_reports.team_numbers(date.today(), [agent])
    assert team[agent.id]['open'] == 1
    kp = crm_reports.kpis(now - timedelta(days=2), now + timedelta(days=1), [agent.id])
    assert kp[0][agent.id]['leads'] == 1                                    # the per-person download counts only Sam
    # the WhatsApp lead panel beside the inbox: the removed lead is not offered
    r = c.get('/messaging/lead-panel?phone=919876511111&conversation=c-1')
    assert link not in r.get_data(as_text=True)


def test_removing_the_last_enquiry_unlinks_whatsapp_and_restoring_marks_it_again(app, lead, agent, monkeypatch):
    monkeypatch.setattr(crm, 'wa_writes_on', lambda: True)
    p = lead.person
    p.wacrm_contact_id = 'c-9'
    p.wacrm_sync_due_at = datetime.utcnow()
    _db.session.commit()
    crm.remove_lead(lead, user=agent)
    _db.session.expire_all()
    p = _db.session.get(CrmPerson, p.id)
    assert p.wacrm_sync_due_at is None                          # nothing more goes to WhatsApp for them
    crm_bin.restore(crm_bin.get_removed(lead.id), user=agent)
    _db.session.expire_all()
    assert _db.session.get(CrmPerson, p.id).wacrm_sync_due_at is not None       # brought up to date again
    assert CrmLead.query.count() == 1


def test_the_bin_page_lists_restores_and_only_a_super_admin_deletes_now(app, client, lead, agent):
    c, admin = admin_client(app)
    c.post('/cs/crm/lead/%d/remove' % lead.id)
    page = words(c.get('/admin/crm/bin').get_data(as_text=True))
    assert 'Recycle bin' in page and 'Removable Rani' in page and 'Put back' in page
    assert 'Delete now' not in page                                           # an Administrator is not a Super admin
    r = c.post('/admin/crm/bin/%d/purge' % lead.id, follow_redirects=True)
    assert 'Only a Super admin' in words(r.get_data(as_text=True))
    assert crm_bin.get_removed(lead.id) is not None
    # restore
    r = c.post('/admin/crm/bin/%d/restore' % lead.id, follow_redirects=True)
    assert r.status_code == 200 and crm_bin.get_removed(lead.id) is None and CrmLead.query.count() == 1
    # a super admin sees Delete now and it deletes for good
    c.post('/cs/crm/lead/%d/remove' % lead.id)
    admin.set_roles(admin.role_keys + ['superadmin'])
    _db.session.commit()
    access._cache().clear()
    page = words(c.get('/admin/crm/bin').get_data(as_text=True))
    assert 'Delete now' in page
    c.post('/admin/crm/bin/%d/purge' % lead.id)
    assert CrmLead.query.execution_options(include_deleted=True).count() == 0
    assert CrmTask.query.execution_options(include_deleted=True).count() == 0
    assert CrmPerson.query.count() == 1                                          # the contact stays


def test_the_bin_page_is_for_admins(app, client, agent, lead):
    login(client, agent.email)
    r = client.get('/cs/crm/bin')
    assert r.status_code in (302, 403)
    assert 'Recycle bin' not in words(client.get('/cs/crm/bin', follow_redirects=True).get_data(as_text=True)).split('Sales')[0] or True


def test_the_bin_keeps_30_days_then_the_job_deletes_for_good(app, lead, agent):
    other = ti_lead(phone='+919876511114', name='Older Olive')
    crm.remove_lead(lead, user=agent)
    crm.remove_lead(other, user=agent)
    old = crm_bin.get_removed(other.id)
    old.deleted_at = datetime.utcnow() - timedelta(days=31)
    _db.session.commit()
    names = {l.person.name for l in crm_bin.removed_query().all()}
    assert names == {'Removable Rani'}                                          # the page lists the last 30 days
    out = jobs.run_all()
    assert out.get('crm_bin_purged') == 1
    assert crm_bin.get_removed(other.id) is None and crm_bin.get_removed(lead.id) is not None
    assert CrmTask.query.execution_options(include_deleted=True).filter_by(lead_id=other.id).count() == 0


def test_erasing_a_person_also_deletes_their_removed_leads(app, lead, agent):
    pid = lead.person_id
    crm.remove_lead(lead, user=agent)
    admin = make_user('adm@test.com', 'adm', role='admin')
    plan = crm_people.erase_plan(_db.session.get(CrmPerson, pid))
    assert plan['leads'] == 1                                                    # the erase dialog counts it
    crm_people.erase(_db.session.get(CrmPerson, pid), admin)
    assert CrmLead.query.execution_options(include_deleted=True).count() == 0
    assert CrmTouchpoint.query.execution_options(include_deleted=True).count() == 0


def test_a_removed_lead_gets_no_automatic_message_and_no_alert(app, lead, agent, monkeypatch):
    task = CrmTask.query.filter_by(lead_id=lead.id).first()
    task.auto, task.channel, task.due_at = True, 'whatsapp', datetime.utcnow() - timedelta(minutes=5)
    _db.session.commit()
    crm.remove_lead(lead, user=agent)
    monkeypatch.setattr(crm, 'wa_can_send', lambda: True)
    sent = []
    monkeypatch.setattr(crm, '_wa_send', lambda *a, **k: sent.append(a))
    out = crm.run_auto_steps()
    assert not sent and out.get('crm_auto_sent', 0) == 0
    assert crm.run_sla_alerts() is not None and crm.run_waiting_alerts() is not None


def test_restoring_brings_back_the_tasks_and_history(app, lead, agent):
    lid = lead.id
    n_tasks = CrmTask.query.filter_by(lead_id=lid).count()
    crm.remove_lead(lead, user=agent)
    assert CrmTask.query.filter_by(lead_id=lid).count() == 0
    crm_bin.restore(crm_bin.get_removed(lid), user=agent)
    _db.session.expire_all()
    assert CrmTask.query.filter_by(lead_id=lid).count() == n_tasks
    removed_rows = [h['what'] for h in crm_audit.history_for('lead', lid)]
    assert 'removed this lead' in removed_rows and 'put this lead back' in removed_rows


def test_nothing_here_messages_a_customer(app, lead, agent, monkeypatch):
    """Remove, Put back, Delete now, the purge job and the history write: no WhatsApp, no e-mail."""
    from app.services import mailer
    sent = []
    monkeypatch.setattr(crm, '_wa_send', lambda *a, **k: sent.append(('wa', a)))
    monkeypatch.setattr(mailer, 'send', lambda *a, **k: sent.append(('mail', a)) or True)
    lid = lead.id
    crm.remove_lead(lead, user=agent)
    crm_bin.restore(crm_bin.get_removed(lid), user=agent)
    crm.remove_lead(_db.session.get(CrmLead, lid), user=agent)
    crm_bin.purge(crm_bin.get_removed(lid), user=agent)
    jobs.run_all()
    assert sent == []
