"""Hidden contact details (Staff Console 2.0, 2026-10-26): a role that hides other people's numbers and e-mails.

    hidden    on leads they do not look after, the number and e-mail are masked on the lead page, the contact page,
              Contacts and Find, with no tel: or mailto: in the page; their own leads are not
    show      Show reveals them for the rest of the sign-in, and the audit log says who looked at whose
    others    a role that does not hide them, and admins, see everything as before
"""
import re

from conftest import login, make_user
from app import db as _db
from app.models import ActivityEvent, WorkspaceRole
from app.services import access, crm, crm_mask

THEIRS, MINE = '+919811100501', '+919811100502'


def masked_agent(ws, email='mask@test.com'):
    agent = make_user(email, email.split('@')[0], role='cs')
    role = WorkspaceRole(workspace_id=ws.id, name='Masked ' + email, pages=sorted(access.CS_ROLE_PAGES),
                         rights={'view': [], 'remove': True, 'mask': True})
    _db.session.add(role)
    _db.session.flush()
    access.add_member(ws, agent, role=role)
    _db.session.commit()
    access._cache().clear()
    return agent


def lead(name, phone, owner, email=None):
    l = crm.capture('ti-quote', name=name, phone=phone, email=email, utm={})
    l.owner_id = owner.id if owner is not None else None
    _db.session.commit()
    return l


def test_the_masked_words():
    assert crm_mask.phone('+919876543210') == '+91 98•••••210'
    assert crm_mask.email('ravi.kumar@gmail.com') == 'r•••@gmail.com'
    assert crm_mask.phone(None) == '' and crm_mask.email('') == ''


def test_a_lead_they_do_not_look_after_hides_the_number_until_show(app, client, admin_user):
    ws = access.ensure_defaults()
    crm.ensure_defaults()
    agent = masked_agent(ws)
    other = make_user('other@test.com', 'other', role='cs')
    theirs = lead('Hidden Hari', THEIRS, None, email='hari@example.com')        # nobody's yet: everyone sees the lead
    mine = lead('Open Ooma', MINE, agent)
    login(client, agent.email)
    page = client.get('/cs/crm/lead/%d' % theirs.id).get_data(as_text=True)
    assert 'tel:%s' % THEIRS not in page and 'mailto:hari@example.com' not in page and '98•••••501' in page
    assert '/cs/crm/contact/%d/show' % theirs.person_id in page
    contact = client.get('/cs/crm/contact/%d' % theirs.person_id).get_data(as_text=True)
    assert 'tel:%s' % THEIRS not in contact and 'h•••@example.com' in contact
    listing = client.get('/cs/crm/contacts').get_data(as_text=True)
    assert 'tel:%s' % THEIRS not in listing and 'tel:%s' % MINE in listing           # their own: as before
    found = client.get('/cs/crm/find?q=Hidden').get_json()['items'][0]
    assert found['phone'] == '+91 98•••••501' and found['email'] == 'h•••@example.com'
    # Show: back to the page, the number there, and the audit log has it
    r = client.post('/cs/crm/contact/%d/show' % theirs.person_id,
                    headers={'Referer': 'http://localhost/cs/crm/lead/%d' % theirs.id})
    assert r.status_code == 302 and r.headers['Location'].endswith('/cs/crm/lead/%d' % theirs.id)
    assert 'tel:%s' % THEIRS in client.get('/cs/crm/lead/%d' % theirs.id).get_data(as_text=True)
    ev = ActivityEvent.query.filter_by(event='contact_shown').one()
    assert ev.meta['person'] == 'Hidden Hari' and ev.actor_id == agent.id
    assert mine.id and other.id


def test_a_role_that_does_not_hide_and_an_admin_see_everything(app, client, admin_user):
    ws = access.ensure_defaults()
    crm.ensure_defaults()
    plain = make_user('plain@test.com', 'plain', role='cs')
    access.add_member(ws, plain, role=access.system_role(ws, 'cs'))
    access._cache().clear()
    l = lead('Seen Sita', THEIRS, None)
    login(client, plain.email)
    assert 'tel:%s' % THEIRS in client.get('/cs/crm/lead/%d' % l.id).get_data(as_text=True)
    client.post('/auth/logout')
    login(client, admin_user.email)
    assert 'tel:%s' % THEIRS in client.get('/admin/crm/lead/%d' % l.id).get_data(as_text=True)
    assert not re.search(r'contact/\d+/show', client.get('/admin/crm/lead/%d' % l.id).get_data(as_text=True))
