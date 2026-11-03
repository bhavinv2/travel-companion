"""Leads nobody looks after yet are every salesperson's to pick up (crm_access): a sales agent who sees only their own
leads opens Leads on "Anyone" -- for them their own plus the ones not given to anyone -- and can open them. Somebody
else's lead stays out of sight."""
from conftest import login, make_user
from app import db as _db
from app.models import CrmLead, WorkspaceRole
from app.services import access, crm, role_rights


def sales_agent(ws, email, name):
    u = make_user(email, name, role='cs')
    p = role_rights.PROFILE_BY_KEY['sales_agent']
    r = WorkspaceRole(workspace_id=ws.id, name='Sales agent ' + name, pages=sorted(role_rights.profile_pages(p)),
                      crm_scope='own', rights={'profile': 'sales_agent', 'view': [], 'remove': True, 'mask': True})
    _db.session.add(r)
    _db.session.flush()
    access.add_member(ws, u, role=r)
    _db.session.commit()
    access._cache().clear()
    return u


def test_a_sales_agent_sees_the_leads_nobody_looks_after(app, client, admin_user):
    ws = access.ensure_defaults()
    asha, ravi = sales_agent(ws, 'asha@test.com', 'asha'), sales_agent(ws, 'ravi@test.com', 'ravi')
    free = crm.capture('ti-quote', name='Nobody Has Me', phone='+919811100009', utm={})
    taken = crm.capture('ti-quote', name='Ravi Has Me', phone='+919811100010', utm={})
    free.owner_id, taken.owner_id = None, ravi.id
    _db.session.commit()
    login(client, asha.email)
    page = client.get('/cs/crm/?p=all&view=list').get_data(as_text=True)          # no filter chosen
    assert 'Nobody Has Me' in page and 'Ravi Has Me' not in page
    assert 'name="owner" value="all" checked' in page and 'Clear all' not in page   # it is the default, not a filter
    page = client.get('/cs/crm/?p=all&view=list&owner=none&chat=').get_data(as_text=True)
    assert 'Nobody Has Me' in page
    # the lead page opens; its number waits behind Show, as for any lead not theirs (crm_mask)
    assert 'Nobody Has Me' in client.get('/cs/crm/lead/%d' % free.id).get_data(as_text=True)
    # once Ravi takes it, it is his: out of Asha's list
    free.owner_id = ravi.id
    _db.session.commit()
    assert 'Nobody Has Me' not in client.get('/cs/crm/?p=all&view=list').get_data(as_text=True)
