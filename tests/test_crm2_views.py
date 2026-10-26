"""Sales CRM 2.0, run 4b -- saved views on Leads and Contacts.

    choice     a views table of its own (crm_views), not SavedFilter + a scope: SavedFilter is bound to the post
               listings' filter engine (see services/crm_views.py)
    built-ins  My open leads, Due today, Late, Quoted this week, Won this month, No value yet -- each finds the right leads
    mine       save, rename, share, delete; names are unique per person; a colleague can use a shared view but not change it
    safe       only whitelisted filter words are kept; a scoped viewer sees only their leads through any view; the
               download follows the view's filters
"""
import csv
import io
import re
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from flask import g

from conftest import login, logout, make_user
from app import db as _db
from app.models import CrmLead, CrmQuote, CrmTask, CrmTouchpoint, CrmView, WorkspaceRole
from app.services import access, crm, crm_views

from test_crm_wa_sync_engine import ti_lead


def as_user(client, user):
    logout(client)
    g.pop('_login_user', None)
    _db.session.expire_all()
    return login(client, user.email)


def words(html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html))


@pytest.fixture
def agent(app):
    return make_user('agent@test.com', 'agent', role='cs')


def mk(name, phone, owner, **kw):
    l = ti_lead(phone=phone, name=name)
    l.owner_id = owner.id if owner is not None else None
    for k, v in kw.items():
        setattr(l, k, v)
    CrmTask.query.filter_by(lead_id=l.id).delete()          # a new lead's welcome step is due now: start clean
    _db.session.commit()
    return l


def task(lead, due, owner, status='open'):
    t = CrmTask(lead=lead, title='Call back', channel='call', due_at=due, owner_id=owner.id, status=status, kind='todo')
    _db.session.add(t)
    _db.session.commit()
    return t


def listing(client, **args):
    args = {'p': 'all', 'view': 'list', 'owner': 'all', **args}
    return words(client.get('/cs/crm/?' + '&'.join('%s=%s' % (k, v) for k, v in args.items())).get_data(as_text=True))


def shown(html, *names):
    return {n: (n in html) for n in names}


# ====================================================================================== the menu

def test_the_views_menu_lists_the_built_in_views_on_leads_and_contacts(app, client, agent, admin_user):
    mk('Menu Maya', '+919876600001', agent)
    as_user(client, agent)
    leads = words(client.get('/cs/crm/').get_data(as_text=True))
    for label in ('My open leads', 'Due today', 'Late', 'Quoted this week', 'Won this month', 'No value yet',
                  'Save this view'):
        assert label in leads, label
    as_user(client, admin_user)
    contacts = words(client.get('/admin/crm/contacts').get_data(as_text=True))
    assert 'Views' in contacts and 'My contacts' in contacts and 'Opted out' in contacts


def test_the_views_menu_uses_no_confirm_dialog(app, client, agent):
    mk('Dialog Dev', '+919876600002', agent)
    as_user(client, agent)
    v = crm_views.create(agent, crm_views.LEADS, 'Mine to delete', {'owner': 'mine'})
    html = client.get('/cs/crm/').get_data(as_text=True)
    menu = html.split('class="vw-menu"')[1].split('</details>\n')[0] if 'vw-menu' in html else ''
    assert 'Yes, delete' in html and 'confirm(' not in html.split('vw-menu')[1].split('class="crm-legend"')[0]
    assert v.name in html


# ====================================================================================== the built-ins

def test_due_today_and_late_find_the_leads_with_an_open_task_then(app, client, agent):
    now = datetime.utcnow()
    due = mk('Due Today Dev', '+919876600011', agent)
    late = mk('Late Lata', '+919876600012', agent)
    later = mk('Later Lakshmi', '+919876600013', agent)
    start = datetime.combine((now + crm.IST).date(), datetime.min.time()) - crm.IST
    task(due, start + timedelta(hours=10), agent)
    task(late, start - timedelta(days=2), agent)
    task(later, start + timedelta(days=3), agent)
    as_user(client, agent)
    names = ('Due Today Dev', 'Late Lata', 'Later Lakshmi')
    today = shown(listing(client, follow='today'), *names)
    assert today['Due Today Dev'] and not today['Late Lata'] and not today['Later Lakshmi']
    lateness = shown(listing(client, follow='late'), *names)
    assert lateness['Late Lata'] and not lateness['Later Lakshmi']
    # the board shows them too, not only the list
    board = words(client.get('/cs/crm/?p=%s&view=board&owner=all&follow=today' % due.pipeline.key).get_data(as_text=True))
    assert 'Due Today Dev' in board and 'Later Lakshmi' not in board


def test_quoted_this_week_counts_the_quote_line_and_a_quote_marked_as_sent(app, client, agent):
    a = mk('Quoted By Button', '+919876600021', agent)
    b = mk('Quoted By Row', '+919876600022', agent)
    c = mk('Never Quoted', '+919876600023', agent)
    d = mk('Quoted Long Ago', '+919876600024', agent)
    crm.mark_event(a, 'Q', user=agent)
    _db.session.add(CrmQuote(lead=b, title='Q', amount=Decimal('1'), currency='INR', status='sent', sent_at=datetime.utcnow()))
    crm.mark_event(d, 'Q', user=agent)
    for tp in CrmTouchpoint.query.filter_by(lead_id=d.id, code='Q'):
        tp.created_at = datetime.utcnow() - timedelta(days=30)
    _db.session.commit()
    as_user(client, agent)
    got = shown(listing(client, quoted='week'), 'Quoted By Button', 'Quoted By Row', 'Never Quoted', 'Quoted Long Ago')
    assert got == {'Quoted By Button': True, 'Quoted By Row': True, 'Never Quoted': False, 'Quoted Long Ago': False}


def test_won_this_month_and_no_value_yet_and_my_open_leads(app, client, agent):
    mine = mk('Mine Open Mira', '+919876600031', agent, amount=Decimal('100'), currency='INR')
    other = mk('Other Open Omar', '+919876600032', None, amount=Decimal('100'), currency='INR')
    empty = mk('No Value Nina', '+919876600033', agent, amount=None)
    won = mk('Won Winnie', '+919876600034', agent, amount=Decimal('500'), currency='INR')
    won_stage = next(s for s in won.pipeline.stages if s.kind == 'won')
    crm.move_stage(won, won_stage, user=agent, reason='Paid')
    _db.session.commit()
    as_user(client, agent)
    month = '%04d-%02d' % ((datetime.utcnow() + crm.IST).year, (datetime.utcnow() + crm.IST).month)
    built = {k: p for k, _l, p in crm_views.builtins(crm_views.LEADS)}
    got = shown(listing(client, status='open', owner='mine'), 'Mine Open Mira', 'Other Open Omar', 'Won Winnie')
    assert got['Mine Open Mira'] and not got['Other Open Omar'] and not got['Won Winnie']
    assert built['mine-open'] == {'owner': 'mine', 'status': 'open'}
    wm = shown(listing(client, status='won', forecast='won', closes=month), 'Won Winnie', 'Mine Open Mira')
    assert wm['Won Winnie'] and not wm['Mine Open Mira']
    assert built['won-month']['closes'] == month
    nv = shown(listing(client, status='open', no_value=1), 'No Value Nina', 'Mine Open Mira')
    assert nv['No Value Nina'] and not nv['Mine Open Mira']


# ====================================================================================== my views

def test_save_a_view_then_it_is_in_the_menu_and_opens_the_same_leads(app, client, agent):
    mk('Saved Sana', '+919876600041', agent)
    mk('Saved Other', '+919876600042', None)
    as_user(client, agent)
    r = client.post('/cs/crm/views/save', data={'scope': 'crm_leads', 'name': 'My stuff', 'f_owner': 'mine',
                                                'f_status': 'open', 'f_p': 'all', 'f_view': 'list', 'junk': 'x'})
    assert r.status_code == 302 and 'owner=mine' in r.headers['Location']
    v = CrmView.query.one()
    assert v.name == 'My stuff' and v.owner_id == agent.id and not v.shared
    assert v.params == {'owner': 'mine', 'status': 'open', 'p': 'all', 'view': 'list'}
    html = client.get('/cs/crm/?p=all&view=list').get_data(as_text=True)
    assert 'My stuff' in html
    link = re.search(r'href="([^"]*)">My stuff', html).group(1).replace('&amp;', '&')
    page = words(client.get(link).get_data(as_text=True))
    assert 'Saved Sana' in page and 'Saved Other' not in page


def test_a_saved_view_keeps_only_whitelisted_filter_words(app, agent):
    got = crm_views.clean(crm_views.LEADS, {'owner': 'mine', 'status': 'open; DROP TABLE crm_leads', 'closes': '2026-13',
                                            'follow': 'today', 'q': '  Rao   family ', 'stage': '12abc', 'evil': '1',
                                            'forecast': 'commit', 'no_value': '1', 'quoted': 'week', 'p': 'all'})
    assert got == {'owner': 'mine', 'follow': 'today', 'q': 'Rao family', 'forecast': 'commit', 'no_value': '1',
                   'quoted': 'week', 'p': 'all'}
    assert crm_views.clean(crm_views.CONTACTS, {'tag': 'TI', 'wa': 'optout', 'enq': 'maybe', 'owner': '7', 'view': 'list'}) \
        == {'tag': 'ti', 'wa': 'optout', 'owner': '7'}


def test_a_view_needs_a_name_a_filter_and_a_name_nobody_else_of_yours_has(app, client, agent):
    as_user(client, agent)
    post = lambda **d: client.post('/cs/crm/views/save', data={'scope': 'crm_leads', **d}, follow_redirects=True)   # noqa: E731
    assert 'Give the view a name' in post(f_owner='mine', name=' ').get_data(as_text=True)
    assert 'Choose at least one filter' in post(name='Empty').get_data(as_text=True)
    post(name='Twice', f_owner='mine')
    assert 'already have a view called' in post(name='Twice', f_owner='all').get_data(as_text=True)
    assert CrmView.query.count() == 1


def test_rename_share_and_delete_are_mine_only(app, client, agent):
    other = make_user('other@test.com', 'other', role='cs')
    mine = crm_views.create(agent, crm_views.LEADS, 'Private one', {'owner': 'mine'})
    shared = crm_views.create(agent, crm_views.LEADS, 'Team one', {'owner': 'all'}, shared=True)
    as_user(client, other)
    html = client.get('/cs/crm/').get_data(as_text=True)
    assert 'Team one' in html and 'Private one' not in html and 'Shared by colleagues' in html
    r = client.post('/cs/crm/views/%d/rename' % shared.id, data={'scope': 'crm_leads', 'name': 'Mine now'}, follow_redirects=True)
    assert 'not yours to change' in r.get_data(as_text=True)
    r = client.post('/cs/crm/views/%d/delete' % shared.id, data={'scope': 'crm_leads'}, follow_redirects=True)
    assert 'not yours to delete' in r.get_data(as_text=True)
    assert CrmView.query.count() == 2
    as_user(client, agent)
    client.post('/cs/crm/views/%d/rename' % mine.id, data={'scope': 'crm_leads', 'name': 'Renamed', 'shared_present': '1', 'shared': 'on'})
    _db.session.expire_all()
    assert _db.session.get(CrmView, mine.id).name == 'Renamed' and _db.session.get(CrmView, mine.id).shared
    client.post('/cs/crm/views/%d/delete' % mine.id, data={'scope': 'crm_leads'})
    assert CrmView.query.count() == 1


def test_contacts_have_their_own_views(app, client, agent, admin_user):
    mk('Contact Chitra', '+919876600051', agent)
    as_user(client, admin_user)
    client.post('/admin/crm/views/save', data={'scope': 'crm_contacts', 'name': 'Opted out ones', 'f_wa': 'optout'})
    v = CrmView.query.one()
    assert v.scope == 'crm_contacts' and v.params == {'wa': 'optout'}
    contacts = client.get('/admin/crm/contacts').get_data(as_text=True)
    assert 'Opted out ones' in contacts
    assert 'Opted out ones' not in client.get('/admin/crm/').get_data(as_text=True)          # not on the other page


# ====================================================================================== downloads and visibility

def test_the_download_follows_the_views_filters(app, client, admin_user, agent):
    mk('Export Eva', '+919876600061', agent, amount=None)
    mk('Export Esha', '+919876600062', agent, amount=Decimal('900'), currency='INR')
    as_user(client, admin_user)
    html = client.get('/admin/crm/?p=all&view=list&owner=all&no_value=1').get_data(as_text=True)
    href = re.search(r'href="([^"]*export/leads[^"]*)"', html).group(1).replace('&amp;', '&')
    assert 'no_value=1' in href
    rows = list(csv.reader(io.StringIO(client.get(href + '&reason=backup').get_data(as_text=True).lstrip('﻿'))))
    flat = ' '.join(' '.join(r) for r in rows)
    assert 'Export Eva' in flat and 'Export Esha' not in flat
    # the contacts download carries the contact filters
    html = client.get('/admin/crm/contacts?owner=mine').get_data(as_text=True)
    assert 'export/contacts' in html and 'owner=mine' in html


def test_a_scoped_agent_sees_only_their_leads_through_any_view_and_download(app, client, admin_user):
    ws = access.ensure_defaults()
    role = WorkspaceRole(workspace_id=ws.id, name='Own only', pages=sorted(access.CS_ROLE_PAGES | {'crm_export', 'crm_people'}),
                         crm_scope='own')
    _db.session.add(role)
    _db.session.flush()
    ws.roles.append(role)
    asha = make_user('asha@test.com', 'asha', role='cs')
    access.add_member(ws, asha, role=role)
    bela = make_user('bela@test.com', 'bela', role='cs')
    access.add_member(ws, bela, role=access.system_role(ws, 'cs'))
    _db.session.commit()
    access._cache().clear()
    mk('Asha Own Lead', '+919876600071', asha)
    mk('Bela Hidden Lead', '+919876600072', bela)
    # a view an admin shared, pointing at everyone's leads
    crm_views.create(admin_user, crm_views.LEADS, 'Everyone', {'owner': 'all', 'p': 'all', 'view': 'list'}, shared=True)
    as_user(client, asha)
    html = client.get('/cs/crm/?owner=all&p=all&view=list').get_data(as_text=True)
    link = re.search(r'href="([^"]*)">Everyone', html).group(1).replace('&amp;', '&')
    page = words(client.get(link).get_data(as_text=True))
    assert 'Asha Own Lead' in page and 'Bela Hidden Lead' not in page
    # a view built on bela's id gives asha nothing of bela's
    other = words(client.get('/cs/crm/?p=all&view=list&owner=%d' % bela.id).get_data(as_text=True))
    assert 'Bela Hidden Lead' not in other
    # the contacts through a view
    contacts = words(client.get('/cs/crm/contacts').get_data(as_text=True))
    assert 'Asha Own Lead' in contacts and 'Bela Hidden Lead' not in contacts
