"""Leads' filter panel: the filters moved from the row above the board into a panel on the right, and gained
a date (came in, last activity, closes, travels on; ready-made ranges in India days or picked dates), where
they came from, how likely, and "Nothing planned".

    panel      the board and the list draw it on the right; the old row above the board is gone
    date       each date and range finds the right leads; India midnight is the edge of a day; picked dates
               count both days in either order; a range the date does not have is dropped; a date range shows
               won and lost leads older than 30 days
    more       came from (a source or "Not known"), how likely, nothing planned
    chips      every filter that is on is a chip that takes it off; the Filters button counts them
    carried    Download this list and Save this view carry the new words; a saved range stays rolling
    remembered "Any" chat beats the remembered chat; Clear filters keeps the product and Board / List
"""
import csv
import io
import re
from datetime import date, datetime, time, timedelta

import pytest
from flask import g

from conftest import login, logout, make_user
from app import db as _db
from app.models import CrmTask
from app.services import crm, crm_views

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


def listing(client, **args):
    args = {'p': 'all', 'view': 'list', 'owner': 'all', **args}
    return words(client.get('/cs/crm/?' + '&'.join('%s=%s' % (k, v) for k, v in args.items())).get_data(as_text=True))


def shown(html, *names):
    return {n: (n in html) for n in names}


def chips(html):
    m = re.search(r'<p class="active-filters"[^>]*>(.*?)</p>', html, re.S)
    return words(m.group(1)) if m else ''


def today_ist():
    return (datetime.utcnow() + crm.IST).date()


# ====================================================================================== the panel

def test_the_filters_are_a_panel_on_the_right_of_the_board_and_the_list(app, client, admin_user):
    mk('Panel Pia', '+919876610001', admin_user)
    as_user(client, admin_user)
    for view in ('board', 'list'):
        html = client.get('/admin/crm/?view=%s' % view).get_data(as_text=True)
        assert 'id="leads-side"' in html and 'data-lf-form' in html and 'crm-filters.js' in html, view
        assert 'toolbar leads-filters' not in html and 'quick-filters' not in html, view
        # the leads first, then the panel: it sits on their right
        assert html.index('class="leads-main"') < html.index('id="leads-side"')
        for group in ('Looked after by', 'Date', 'Status', 'Follow-up', 'Chat', 'How likely', 'Came from', 'Money'):
            assert '>%s<' % group in html, (view, group)


# ====================================================================================== date

def test_the_date_filter_finds_leads_by_when_they_came_in_were_active_close_and_travel(app, client, agent):
    now, today = datetime.utcnow(), today_ist()
    new = mk('New Nadia', '+919876610011', agent, last_activity_at=now, close_date=today + timedelta(days=3),
             departure_date=today + timedelta(days=40))
    old = mk('Old Omkar', '+919876610012', agent, created_at=now - timedelta(days=20),
             last_activity_at=now - timedelta(days=20), close_date=today - timedelta(days=2),
             departure_date=today + timedelta(days=10))
    as_user(client, agent)
    names = ('New Nadia', 'Old Omkar')
    only_new, only_old, both = {'New Nadia': True, 'Old Omkar': False}, {'New Nadia': False, 'Old Omkar': True}, \
        {'New Nadia': True, 'Old Omkar': True}
    assert shown(listing(client, dr='7d'), *names) == only_new
    assert shown(listing(client, dr='30d'), *names) == both
    assert shown(listing(client, dt='activity', dr='today'), *names) == only_new
    assert shown(listing(client, dt='close', dr='next7'), *names) == only_new
    assert shown(listing(client, dt='close', dr='passed'), *names) == only_old
    assert shown(listing(client, dt='travel', dr='next30'), *names) == only_old
    # picked dates: both days count, typed in either order
    first, last = today - timedelta(days=21), today - timedelta(days=19)
    assert shown(listing(client, dr='custom', d1=last.isoformat(), d2=first.isoformat()), *names) == only_old
    assert shown(listing(client, dr='custom', d1=(today - timedelta(days=20)).isoformat()), *names) == both
    # a range this date does not have is dropped, not guessed
    assert shown(listing(client, dt='close', dr='yesterday'), *names) == both


def test_a_day_starts_at_midnight_in_india(app, client, agent):
    today = today_ist()
    start = datetime.combine(today, time.min) - crm.IST                      # 00:00 India time, in UTC
    mk('Just After Midnight', '+919876610021', agent, created_at=start + timedelta(minutes=30))
    mk('Late Last Night', '+919876610022', agent, created_at=start - timedelta(minutes=30))
    as_user(client, agent)
    names = ('Just After Midnight', 'Late Last Night')
    assert shown(listing(client, dr='today'), *names) == {'Just After Midnight': True, 'Late Last Night': False}
    assert shown(listing(client, dr='yesterday'), *names) == {'Just After Midnight': False, 'Late Last Night': True}


def test_a_date_range_shows_won_leads_older_than_the_30_day_window(app, client, agent):
    now = datetime.utcnow()
    won = mk('Won Long Ago', '+919876610031', agent)
    crm.move_stage(won, next(s for s in won.pipeline.stages if s.kind == 'won'), user=agent, reason='Paid')
    won.created_at, won.closed_at = now - timedelta(days=50), now - timedelta(days=40)
    _db.session.commit()
    as_user(client, agent)
    assert 'Won Long Ago' not in listing(client)                             # the last 30 days only
    picked = (now + crm.IST - timedelta(days=50)).date().isoformat()
    html = client.get('/cs/crm/?p=all&view=list&owner=all&dr=custom&d1=%s&d2=%s' % (picked, picked)).get_data(as_text=True)
    assert 'Won Long Ago' in words(html)
    assert 'All of them show while a date or money filter is on.' in words(html)


def test_the_date_words_are_checked_and_month_edges_are_right(app):
    now = datetime(2027, 1, 10, 6, 0)                                        # 11:30 on 10 January, India time
    w, kw = crm.lead_more_words({'dt': 'close', 'dr': 'yesterday'}, now)
    assert w['dr'] is None and kw['date_on'] is None
    w, kw = crm.lead_more_words({'d1': '2027-01-05', 'd2': '2027-01-01'}, now)   # typed, "Pick dates" not chosen
    assert w['dr'] == 'custom' and (kw['date_from'], kw['date_until']) == (date(2027, 1, 1), date(2027, 1, 6))
    w, kw = crm.lead_more_words({'dt': 'bogus', 'dr': 'lastmonth', 'src': 'x1', 'lk': 'boiling', 'd1': 'soon'}, now)
    assert w['dt'] is None and w['d1'] is None and w['src'] is None and w['lk'] is None
    assert (kw['date_on'], kw['date_from'], kw['date_until']) == ('created', date(2026, 12, 1), date(2027, 1, 1))
    w, kw = crm.lead_more_words({'dr': 'custom'}, now)                       # "Pick dates" with no date
    assert w['dr'] is None and kw['date_on'] is None
    end = date(2026, 12, 31)
    assert crm.date_span('nextmonth', end) == (date(2027, 1, 1), date(2027, 2, 1))
    assert crm.date_span('month', end) == (date(2026, 12, 1), date(2027, 1, 1))
    assert crm.date_span('7d', end) == (date(2026, 12, 25), date(2027, 1, 1))
    assert crm.date_span('next7', end) == (end, date(2027, 1, 7))
    assert crm.date_span('passed', end) == (None, end)
    assert crm.date_words_text({'dt': 'travel', 'dr': 'next7'}) == 'Travels on: Next 7 days'
    assert crm.date_words_text({'dr': 'custom', 'd1': '2020-03-01'}) == 'Came in: from 1 Mar 2020'


# ====================================================================================== more filters

def test_came_from_how_likely_and_nothing_planned(app, client, agent):
    hot = mk('Hot Hari', '+919876610041', agent, likelihood='hot')
    cold = mk('Cold Chitra', '+919876610042', agent, likelihood='cold', source_id=None)
    _db.session.add(CrmTask(lead=hot, title='Call back', channel='call', due_at=datetime.utcnow() + timedelta(days=1),
                            owner_id=agent.id, status='open', kind='todo'))
    _db.session.commit()
    as_user(client, agent)
    names = ('Hot Hari', 'Cold Chitra')
    assert shown(listing(client, lk='hot'), *names) == {'Hot Hari': True, 'Cold Chitra': False}
    assert shown(listing(client, src=hot.source_id), *names) == {'Hot Hari': True, 'Cold Chitra': False}
    assert shown(listing(client, src='none'), *names) == {'Hot Hari': False, 'Cold Chitra': True}
    assert shown(listing(client, follow='none'), *names) == {'Hot Hari': False, 'Cold Chitra': True}
    html = client.get('/cs/crm/?p=all&view=list&owner=all').get_data(as_text=True)
    assert 'name="src"' in html and 'value="%d"' % hot.source_id in html      # the source is offered


# ====================================================================================== chips, download, views

def test_every_filter_on_is_a_chip_and_goes_with_the_download_and_a_saved_view(app, client, admin_user):
    mk('Chip Chandra', '+919876610051', admin_user, likelihood='warm')
    mk('Chip Old', '+919876610052', admin_user, likelihood='warm', created_at=datetime.utcnow() - timedelta(days=20))
    as_user(client, admin_user)
    html = client.get('/admin/crm/?p=all&view=list&owner=all&dr=7d&lk=warm&follow=none&q=Chip').get_data(as_text=True)
    on = chips(html)
    for chip in ('Came in: Last 7 days', 'Thinking about it', 'Nothing planned', 'Find: “Chip”', 'Clear filters'):
        assert chip in on, chip
    assert re.search(r'class="lf-n"[^>]*>(\d+)<', html).group(1) == '4'
    # each chip takes its own filter off and leaves the others
    rm = re.search(r'href="([^"]*)"[^>]*title="Remove this filter">Thinking about it', html).group(1).replace('&amp;', '&')
    assert 'lk=' not in rm and 'dr=7d' in rm and 'follow=none' in rm
    href = re.search(r'href="([^"]*export/leads[^"]*)"', html).group(1).replace('&amp;', '&')
    assert 'dr=7d' in href and 'lk=warm' in href and 'follow=none' in href
    rows = list(csv.reader(io.StringIO(client.get(href).get_data(as_text=True).lstrip('﻿'))))
    flat = ' '.join(' '.join(r) for r in rows)
    assert 'Chip Chandra' in flat and 'Chip Old' not in flat
    # Save this view keeps the panel's words; a ready-made range stays a word, so the view keeps rolling
    assert 'name="f_dr" value="7d"' in html and 'name="f_lk" value="warm"' in html
    assert crm_views.clean(crm_views.LEADS, {'dt': 'travel', 'dr': 'next30', 'd1': '2026-10-01', 'd2': 'junk',
                                             'src': '12', 'lk': 'hot', 'follow': 'none'}) == \
        {'dt': 'travel', 'dr': 'next30', 'd1': '2026-10-01', 'src': '12', 'lk': 'hot', 'follow': 'none'}
    assert crm_views.clean(crm_views.LEADS, {'dr': 'someday', 'src': '1; drop', 'lk': 'x'}) == {}
    built = {k: p for k, _l, p in crm_views.builtins(crm_views.LEADS)}
    assert built['new-week'] == {'owner': 'all', 'dr': '7d'}
    assert built['travel-soon']['dt'] == 'travel' and built['travel-soon']['dr'] == 'next30'


def test_any_chat_beats_the_remembered_chat_and_clear_filters_keeps_the_product_and_view(app, client, admin_user):
    mk('Remember Rani', '+919876610061', admin_user)
    as_user(client, admin_user)
    client.get('/admin/crm/?p=all&view=list&chat=waiting&owner=none')
    html = client.get('/admin/crm/').get_data(as_text=True)                  # remembered for the session
    assert 'Waiting on us' in chips(html) and 'Looked after by: Not given to anyone' in chips(html)
    # the chip that takes the chat off says "any chat" out loud, so the remembered one does not come back
    rm = re.search(r'href="([^"]*)"[^>]*title="Remove this filter">Waiting on us', html).group(1).replace('&amp;', '&')
    assert 'chat=&' in rm or rm.endswith('chat=')
    client.get(rm)
    assert 'Waiting on us' not in chips(client.get('/admin/crm/').get_data(as_text=True))
    r = client.get('/admin/crm/?reset=1')
    assert r.status_code == 302
    html = client.get('/admin/crm/').get_data(as_text=True)
    assert chips(html) == '' and 'crm-table' in html                         # still the list
    assert re.search(r'class="on"[^>]*>\s*<i class="fa-solid fa-layer-group"></i> All', html)   # still All
