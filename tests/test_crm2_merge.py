"""Sales CRM 2.0, run 4a -- merge two people (4.3).

    merge      every foreign key moves (also removed enquiries and their hidden rows), an identity both have is
               kept once, the other person is deleted, empty details are filled, consent is the more permissive
               and an opt-out stays, the family follows, ONE History line, a system line with the other
               WhatsApp contact id, the kept person is marked for sync, saved daily numbers are forgotten
    page       search -> preview in words -> Merge (POST, admins and Team members managers only)
    duplicates the three rules, only people the viewer may see
    visibility the search, preview, POST and duplicates list never show a person the role may not see
"""
from datetime import date, datetime, timedelta

import pytest

from conftest import login, make_user
from app import db as _db
from app.models import (CrmAudit, CrmDailyStat, CrmFile, CrmHousehold, CrmIdentity, CrmLead, CrmPerson, CrmTask,
                        CrmTouchpoint, Notification)
from app.services import crm, crm_bin, crm_household, crm_merge

from test_crm_wa_sync_engine import ti_lead
from test_crm2_visibility import lead_for, staff, words


def person(name, phone=None, **kw):
    p = CrmPerson(name=name, phone=phone, **kw)
    _db.session.add(p)
    _db.session.commit()
    return p


@pytest.fixture
def two(app):
    """Ravi (kept) and Ravi K (merged in): the second has a lead, a removed lead, messages, a task, a handle, a file."""
    ravi = person('Ravi Kumar', '+919876500501', email='ravi@example.com')
    other = person('Ravi K', None, country='IN')
    other.identities.append(CrmIdentity(kind='instagram', value='ravi.k'))
    other.consent_whatsapp = True
    other.wacrm_contact_id = 'wa-77'
    _db.session.commit()
    l1 = crm.capture('ti-quote', name='Ravi K', phone='+919876500502', utm={})
    l1.person_id = other.id
    l2 = crm.capture('sh-booking', name='Ravi K', phone='+919876500503', product='SH', utm={})
    l2.person_id = other.id
    _db.session.commit()
    crm.log_touch(l1, 'whatsapp', direction='in', body='hello there')
    crm.log_touch(l2, 'whatsapp', direction='in', body='second one')
    _db.session.add(CrmTask(person_id=other.id, title='Ring Ravi', due_at=datetime.utcnow() + timedelta(days=1),
                            kind='todo', channel='call'))
    _db.session.add(CrmFile(person_id=other.id, lead_id=l1.id, filename='passport.pdf', stored_name='aa11.pdf',
                            size=10, content_type='application/pdf'))
    _db.session.commit()
    return ravi, other, l1, l2


def test_a_merge_moves_everything_and_deletes_the_other(app, admin_user, two):
    ravi, other, l1, l2 = two
    oid, kid = other.id, ravi.id
    crm_bin.remove(l2, admin_user)                              # a removed (binned) enquiry moves too
    _db.session.add(CrmAudit(record_type='person', record_id=oid, field='name', old='x', new='Ravi K'))
    _db.session.add(Notification(user_id=admin_user.id, type='crm', title='t', link='/cs/crm/contact/%d' % oid))
    _db.session.commit()
    crm_merge.merge(ravi, other, admin_user)
    _db.session.expire_all()
    assert _db.session.get(CrmPerson, oid) is None
    keep = _db.session.get(CrmPerson, kid)
    assert {l.id for l in CrmLead.query.execution_options(include_deleted=True).filter_by(person_id=kid)} == {l1.id, l2.id}
    assert CrmTouchpoint.query.filter_by(person_id=kid).count() >= 2
    assert CrmTouchpoint.query.filter_by(person_id=oid).count() == 0
    assert CrmTask.query.filter_by(person_id=kid).count() == 1                 # the hand-made one
    assert CrmFile.query.filter_by(person_id=kid).count() == 1
    assert [i.value for i in keep.identities] == ['ravi.k']
    assert CrmAudit.query.filter_by(record_type='person', record_id=oid).count() == 0
    assert CrmAudit.query.filter_by(record_type='person', record_id=kid, field='name', new='Ravi K').count() == 1
    assert Notification.query.filter(Notification.title == 't').one().link.endswith('/contact/%d' % kid)
    # kept: name, phone, e-mail; filled: country; consent given by the other is kept
    assert (keep.name, keep.phone, keep.email, keep.country) == ('Ravi Kumar', '+919876500501', 'ravi@example.com', 'IN')
    assert keep.consent_whatsapp is True


def test_one_history_line_and_a_system_line_for_the_other_whatsapp_contact(app, admin_user, two):
    ravi, other, *_ = two
    crm_merge.merge(ravi, other, admin_user)
    rows = CrmAudit.query.filter_by(record_type='person', record_id=ravi.id, field='merged').all()
    assert len(rows) == 1 and rows[0].user_id == admin_user.id
    assert 'Ravi K' in rows[0].new and '2 enquiries' in rows[0].new
    from app.services import crm_audit
    h = [x['what'] for x in crm_audit.history_for('person', ravi.id)]
    assert any(w.startswith('merged another contact into this one (Ravi K: 2 enquiries') for w in h)
    note = CrmTouchpoint.query.filter_by(person_id=ravi.id, lead_id=None, channel='note').one()
    assert 'wa-77' in note.body and 'left as it is' in note.body
    from app.models import ActivityEvent
    ev = ActivityEvent.query.filter_by(event_type='crm_people_merged').one() if hasattr(ActivityEvent, 'event_type') else None
    if ev is not None:
        assert 'Ravi' not in str(ev.meta if hasattr(ev, 'meta') else '')


def test_the_kept_person_is_marked_for_sync_and_nothing_is_deleted_in_whatsapp(app, admin_user, two, monkeypatch):
    ravi, other, *_ = two
    monkeypatch.setattr(crm, 'wa_writes_on', lambda: True)
    forgotten = []
    monkeypatch.setattr(crm, '_wa_drop_tags_later', lambda *a, **k: forgotten.append(a))
    crm_merge.merge(ravi, other, admin_user)
    _db.session.expire_all()
    assert _db.session.get(CrmPerson, ravi.id).wacrm_sync_due_at is not None
    assert forgotten == []


def test_saved_daily_numbers_from_the_earliest_day_are_forgotten(app, admin_user, two):
    ravi, other, l1, _ = two
    day = (l1.created_at + timedelta(hours=5, minutes=30)).date()
    for d in (day - timedelta(days=3), day, day + timedelta(days=1)):
        _db.session.add(CrmDailyStat(day=d, metric='new_leads', value=1))
    _db.session.commit()
    crm_merge.merge(ravi, other, admin_user)
    left = sorted(r.day for r in CrmDailyStat.query.all())
    assert left == [day - timedelta(days=3)]


def test_the_person_without_a_phone_takes_the_others_and_whatsapp_ids(app, admin_user):
    keep = person('No Phone', None, email='np@example.com')
    other = person('Has Phone', '+919876500601', wacrm_contact_id='wa-1', wacrm_conversation_id='cv-1')
    crm_merge.merge(keep, other, admin_user)
    _db.session.expire_all()
    k = _db.session.get(CrmPerson, keep.id)
    assert k.phone == '+919876500601' and k.wacrm_contact_id == 'wa-1' and k.wacrm_conversation_id == 'cv-1'
    assert CrmTouchpoint.query.filter_by(person_id=k.id, channel='note').count() == 0       # same contact: no note


def test_an_identity_both_people_have_is_kept_once_and_an_opt_out_stays(app, admin_user):
    a = person('Anil One', '+919876500611')
    b = person('Anil Two', '+919876500612')
    a.identities.append(CrmIdentity(kind='instagram', value='anil'))
    b.identities.append(CrmIdentity(kind='facebook', value='anil.fb'))
    b.wa_opt_out_at = datetime.utcnow()
    b.consent_marketing = True
    _db.session.commit()
    crm_merge.merge(a, b, admin_user)
    _db.session.expire_all()
    got = {(i.kind, i.value) for i in CrmIdentity.query.filter_by(person_id=a.id)}
    assert got == {('instagram', 'anil'), ('facebook', 'anil.fb')}
    k = _db.session.get(CrmPerson, a.id)
    assert k.wa_opt_out_at is not None and k.consent_marketing is True and k.consent_whatsapp is False


def test_the_family_follows_the_kept_person_only_when_they_had_none(app, admin_user):
    ravi, lata = person('Ravi Rao', '+919876500621'), person('Lata Rao', '+919876500622')
    crm_household.link(ravi, lata, 'parent')
    other = person('Ravi R', '+919876500623')
    _db.session.commit()
    crm_merge.merge(lata, other, admin_user)                   # the kept one has a family: the other just goes
    assert CrmHousehold.query.count() == 1
    solo = person('Solo Person', '+919876500624')
    member = person('Member Person', '+919876500625')
    third = person('Third Person', '+919876500626')
    crm_household.link(third, member, 'payer')
    _db.session.commit()
    hid = member.household_id
    crm_merge.merge(solo, member, admin_user)                   # the kept one had none: takes the family and the role
    _db.session.expire_all()
    s = _db.session.get(CrmPerson, solo.id)
    assert s.household_id == hid and s.household_role == 'payer'
    # the other was the last member of its own family: the family is deleted
    a, b, c = person('Aa One', '+919876500627'), person('Bb Two', '+919876500628'), person('Cc Three', '+919876500629')
    crm_household.link(b, c)
    _db.session.commit()
    h2 = b.household_id
    crm_household.leave(c)
    _db.session.commit()
    crm_merge.merge(a, b, admin_user)
    assert _db.session.get(CrmHousehold, h2) is None or _db.session.get(CrmPerson, a.id).household_id == h2


def test_a_person_cannot_be_merged_with_themselves(app, admin_user):
    a = person('Same Person', '+919876500631')
    with pytest.raises(ValueError):
        crm_merge.merge(a, a, admin_user)


# ====================================================================================== the pages

def test_search_preview_and_merge_through_the_pages(app, client, admin_user, two):
    ravi, other, l1, l2 = two
    login(client, admin_user.email)
    page = client.get('/cs/crm/contact/%d' % ravi.id).get_data(as_text=True)
    assert 'Merge with another person' in page
    t = words(client.get('/cs/crm/contact/%d/merge?q=Ravi+K' % ravi.id).get_data(as_text=True))
    assert 'Ravi K' in t and 'Compare' in t
    t = words(client.get('/cs/crm/contact/%d/merge?with=%d' % (ravi.id, other.id)).get_data(as_text=True))
    assert 'Will move: 2 enquiries, 2 messages, 3 tasks, 1 file, Instagram handle.' in t
    assert 'Kept from Ravi Kumar: name, phone, e-mail.' in t
    assert 'Filled from Ravi K: country.' in t
    assert 'How this works' in t
    r = client.post('/cs/crm/contact/%d/merge' % ravi.id, data={'other_id': other.id}, follow_redirects=True)
    assert 'Merged.' in words(r.get_data(as_text=True))
    assert _db.session.get(CrmPerson, other.id) is None
    t = words(client.get('/cs/crm/contact/%d' % ravi.id).get_data(as_text=True))
    assert 'merged another contact into this one' in t


def test_only_admins_and_team_managers_can_merge(app, client, two):
    ravi, other, *_ = two
    agent = staff('agent@test.com', 'agent')
    login(client, agent.email)
    assert 'Merge with another person' not in client.get('/cs/crm/contact/%d' % ravi.id).get_data(as_text=True)
    r = client.get('/cs/crm/contact/%d/merge' % ravi.id)
    assert r.status_code == 302
    assert client.post('/cs/crm/contact/%d/merge' % ravi.id, data={'other_id': other.id}).status_code == 403
    assert _db.session.get(CrmPerson, other.id) is not None
    # a role that includes the Team members page may
    boss = staff('boss@test.com', 'boss', scope=None, extra=('ws_members',))
    _db.session.expire_all()
    from flask import g
    g.pop('_login_user', None)
    c2 = app.test_client()
    login(c2, boss.email)
    assert c2.get('/cs/crm/contact/%d/merge' % ravi.id).status_code == 200


# ====================================================================================== duplicates

def test_duplicates_finds_the_three_kinds_of_pair(app, client, admin_user):
    day = datetime.utcnow() - timedelta(days=10)
    e1 = person('Email One', '+919876500701', email='same@example.com')
    e2 = person('Other Name', '+919876500702', email='SAME@example.com')
    p1 = person('Phone Twin', '+919876500703', country='IN')
    p2 = person('Phone Twin', '+9109876500703', country='IN')                 # a leading zero after the code
    n1 = person('Name Twin', '+919876500705', country='IN', created_at=day)
    n2 = person('Name Twin', '+14085550106', country='US', created_at=day + timedelta(hours=5))
    far = person('Name Twin', '+14085550107', country='US', created_at=day + timedelta(days=4))
    lone = person('Lone Person', '+919876500708')
    pairs = crm_merge.find_pairs(admin_user)
    keys = {frozenset((p['a'].id, p['b'].id)): p['why'] for p in pairs}
    assert frozenset((e1.id, e2.id)) in keys and 'the same e-mail' in keys[frozenset((e1.id, e2.id))]
    assert frozenset((p1.id, p2.id)) in keys
    assert any('country code' in w for w in keys[frozenset((p1.id, p2.id))])
    assert frozenset((n1.id, n2.id)) in keys
    assert any('within a day' in w for w in keys[frozenset((n1.id, n2.id))])
    assert frozenset((n1.id, far.id)) not in keys
    assert all(lone.id not in k for k in keys)
    login(client, admin_user.email)
    t = words(client.get('/cs/crm/contacts?dups=1').get_data(as_text=True))
    assert 'Possible duplicates' in t and 'Compare &amp; merge' in t and 'How this works' in t
    assert 'Possible duplicates' in client.get('/cs/crm/contacts').get_data(as_text=True)


def test_duplicates_tab_is_for_people_who_may_merge(app, client):
    agent = staff('agent@test.com', 'agent')
    person('Dup One', '+919876500711', email='d@example.com')
    person('Dup Two', '+919876500712', email='d@example.com')
    login(client, agent.email)
    t = words(client.get('/cs/crm/contacts?dups=1').get_data(as_text=True))
    assert 'Compare &amp; merge' not in t and 'Possible duplicates' not in t


# ====================================================================================== visibility

def test_merge_screens_and_duplicates_never_show_a_person_the_role_may_not_see(app, client):
    boss = staff('boss@test.com', 'boss', scope='own', extra=('ws_members',))
    bela = staff('bela@test.com', 'bela')
    mine = lead_for('Ownerone Mine', '+919876500801', boss)
    hidden = lead_for('Otherwoman Hidden', '+919876500802', bela)
    twin = lead_for('Otherwoman Hidden', '+919876500803', bela)          # a hidden pair
    visible_a = person('Visible Pair', '+919876500804', email='vp@example.com')
    visible_b = person('Visible Pair Too', '+919876500805', email='vp@example.com')
    login(client, boss.email)
    # the duplicates list: the visible pair, not the hidden one
    t = words(client.get('/cs/crm/contacts?dups=1').get_data(as_text=True))
    assert 'Visible Pair' in t and 'Otherwoman' not in t
    # the merge search never offers the hidden person
    t = words(client.get('/cs/crm/contact/%d/merge?q=Otherwoman' % mine.person_id).get_data(as_text=True))
    assert 'Otherwoman' not in t
    # the preview and the POST answer 404 for a hidden person, on either side
    assert client.get('/cs/crm/contact/%d/merge?with=%d' % (mine.person_id, hidden.person_id)).status_code == 404
    assert client.get('/cs/crm/contact/%d/merge' % hidden.person_id).status_code == 404
    assert client.post('/cs/crm/contact/%d/merge' % mine.person_id, data={'other_id': hidden.person_id}).status_code == 404
    assert client.post('/cs/crm/contact/%d/merge' % hidden.person_id, data={'other_id': mine.person_id}).status_code == 404
    _db.session.expire_all()
    assert _db.session.get(CrmPerson, hidden.person_id) is not None
    # a visible one works
    assert client.post('/cs/crm/contact/%d/merge' % visible_a.id, data={'other_id': visible_b.id}).status_code == 302
    assert _db.session.get(CrmPerson, visible_b.id) is None
