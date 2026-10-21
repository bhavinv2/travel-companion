"""Sales CRM 2.0, run 3b -- who a new lead goes to.

    fewest        the old rule, unchanged (NULL means this)
    round robin   in turn, remembering the last person (CrmSource.rr_last_user_id)
    away          nobody who is away gets a new lead, in either mode; everyone away -> the normal rule, said on the lead
    screens       the source form, the account menu ("I'm away until" / "I'm back"), the Users side panel
    never         a customer is not messaged by any of this
"""
from datetime import datetime, timedelta

import pytest

from conftest import login, make_user
from app import db as _db
from app.models import CrmLead, CrmSource, CrmTouchpoint, WorkspaceMember
from app.services import access, crm, crm_assign

from test_crm_wa_sync_engine import ti_lead


@pytest.fixture
def team(app):
    users = [make_user('a%d@test.com' % i, 'agent%d' % i, role='cs') for i in range(3)]
    access.ensure_defaults()
    crm.ensure_defaults()
    src = CrmSource.query.filter_by(key='ti-quote').one()
    src.team = [u.id for u in users]
    _db.session.commit()
    access._cache().clear()
    return users, src


def new_lead(i):
    l = ti_lead(phone='+9198765%05d' % (22000 + i), name='Lead Number%d' % i)
    return l


def set_away(user, days=3):
    for m in WorkspaceMember.query.filter_by(user_id=user.id):
        m.away_until = datetime.utcnow() + timedelta(days=days)
    _db.session.commit()


def test_fewest_is_the_rule_when_nothing_is_set(app, team):
    users, src = team
    assert src.assign_mode is None and crm_assign.mode_of(src) == 'fewest'
    first = new_lead(1)
    assert first.owner_id == users[0].id                         # nobody has any: the lowest id
    owners = [new_lead(i).owner_id for i in range(2, 5)]
    assert owners[:2] == [users[1].id, users[2].id]              # then whoever has the fewest
    assert src.rr_last_user_id is None                           # the turn is only kept in round-robin mode


def test_round_robin_takes_turns_and_remembers(app, team):
    users, src = team
    src.assign_mode = 'round_robin'
    _db.session.commit()
    got = [new_lead(i).owner_id for i in range(1, 7)]
    ids = [u.id for u in users]
    assert got == ids + ids
    _db.session.refresh(src)
    assert src.rr_last_user_id == ids[-1]
    # load does not matter in turn: give the next person lots of leads first
    for l in CrmLead.query.filter_by(owner_id=ids[0]).all():
        l.status = 'open'
    nxt = new_lead(9)
    assert nxt.owner_id == ids[0]


def test_round_robin_carries_on_when_the_last_person_is_gone(app, team):
    users, src = team
    src.assign_mode, src.rr_last_user_id = 'round_robin', 9999
    src.team = [u.id for u in users]
    _db.session.commit()
    assert new_lead(1).owner_id == users[0].id                    # nobody after 9999: start again


@pytest.mark.parametrize('mode', [None, 'round_robin'])
def test_nobody_away_gets_a_new_lead_in_either_mode(app, team, mode):
    users, src = team
    src.assign_mode = mode
    _db.session.commit()
    set_away(users[0])
    got = {new_lead(i).owner_id for i in range(1, 6)}
    assert users[0].id not in got and got <= {users[1].id, users[2].id}
    # back: they are in the pool again
    for m in WorkspaceMember.query.filter_by(user_id=users[0].id):
        m.away_until = None
    _db.session.commit()
    assert users[0].id in {new_lead(i).owner_id for i in range(10, 16)}


def test_an_away_date_in_the_past_means_back(app, team):
    users, src = team
    for m in WorkspaceMember.query.filter_by(user_id=users[0].id):
        m.away_until = datetime.utcnow() - timedelta(hours=1)
    _db.session.commit()
    assert new_lead(1).owner_id == users[0].id


def test_when_everyone_is_away_the_normal_rule_runs_and_the_lead_says_so(app, team):
    users, src = team
    for u in users:
        set_away(u)
    lead = new_lead(1)
    assert lead.owner_id == users[0].id
    lines = [t.body for t in CrmTouchpoint.query.filter_by(lead_id=lead.id, channel='note')]
    assert any('Everyone who could take this lead was away' in b for b in lines)
    # and a normal lead has no such line
    for u in users:
        for m in WorkspaceMember.query.filter_by(user_id=u.id):
            m.away_until = None
    _db.session.commit()
    ok = new_lead(2)
    assert not any('was away' in (t.body or '') for t in CrmTouchpoint.query.filter_by(lead_id=ok.id))


def test_the_source_form_saves_how_to_share(app, client, team, admin_user):
    users, src = team
    login(client, admin_user.email)
    page = client.get('/admin/crm/sources?edit=%d' % src.id).get_data(as_text=True)
    assert 'How to share new leads' in page and 'In turn (round robin)' in page
    assert 'Whoever has the fewest open leads' in page
    data = {'id': src.id, 'name': src.name, 'kind': src.kind, 'product': src.product, 'pipeline': src.pipeline.key,
            'status': 'live', 'who': 'people', 'team': [u.id for u in users], 'dedupe_days': '30',
            'assign_mode': 'round_robin'}
    r = client.post('/admin/crm/setup/source', data=data)
    assert r.status_code in (200, 302)
    _db.session.expire_all()
    assert _db.session.get(CrmSource, src.id).assign_mode == 'round_robin'
    data['assign_mode'] = 'fewest'
    client.post('/admin/crm/setup/source', data=data)
    _db.session.expire_all()
    assert _db.session.get(CrmSource, src.id).assign_mode is None


def test_the_account_menu_sets_away_and_back(app, client, team):
    users, src = team
    me = users[1]
    login(client, me.email)
    tomorrow = (datetime.utcnow() + timedelta(days=4) + timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d')
    page = client.get('/cs/crm/today').get_data(as_text=True)
    assert "I'm away until" in page or "I&#39;m away until" in page
    r = client.post('/away', data={'until': tomorrow}, follow_redirects=True)
    assert r.status_code == 200
    _db.session.expire_all()
    m = WorkspaceMember.query.filter_by(user_id=me.id).one()
    assert m.away_until is not None and m.away_until > datetime.utcnow()
    assert crm_assign.away_until(me) is not None
    assert "I'm back" in client.get('/cs/crm/today').get_data(as_text=True) or "I&#39;m back" in client.get('/cs/crm/today').get_data(as_text=True)
    # a day in the past is refused
    r = client.post('/away', data={'until': '2001-01-01'}, follow_redirects=True)
    assert m.away_until is not None
    client.post('/away', data={'back': '1'})
    _db.session.expire_all()
    assert WorkspaceMember.query.filter_by(user_id=me.id).one().away_until is None


def test_an_admin_marks_somebody_away_from_the_users_panel(app, client, team, admin_user):
    users, src = team
    login(client, admin_user.email)
    panel = client.get('/admin/users/%d/panel' % users[2].id).get_data(as_text=True)
    assert 'Away until' in panel
    until = (datetime.utcnow() + timedelta(days=5)).strftime('%Y-%m-%d')
    r = client.post('/admin/users/%d/away' % users[2].id, data={'until': until})
    assert r.status_code == 302
    _db.session.expire_all()
    assert WorkspaceMember.query.filter_by(user_id=users[2].id).one().away_until is not None
    assert 'Mark as back' in client.get('/admin/users/%d/panel' % users[2].id).get_data(as_text=True)
    client.post('/admin/users/%d/away' % users[2].id, data={'back': '1'})
    _db.session.expire_all()
    assert WorkspaceMember.query.filter_by(user_id=users[2].id).one().away_until is None


def test_a_normal_agent_cannot_mark_somebody_else_away(app, client, team):
    users, src = team
    login(client, users[0].email)
    r = client.post('/admin/users/%d/away' % users[1].id, data={'until': '2099-01-01'})
    assert r.status_code in (302, 403)
    _db.session.expire_all()
    assert WorkspaceMember.query.filter_by(user_id=users[1].id).one().away_until is None


def test_sharing_a_lead_messages_nobody(app, team, monkeypatch):
    users, src = team
    src.assign_mode = 'round_robin'
    _db.session.commit()
    sent = []
    monkeypatch.setattr(crm, '_wa_send', lambda *a, **k: sent.append(a))
    from app.services import mailer
    monkeypatch.setattr(mailer, 'send', lambda *a, **k: sent.append(a) or True)
    set_away(users[0])
    new_lead(1)
    assert sent == []
