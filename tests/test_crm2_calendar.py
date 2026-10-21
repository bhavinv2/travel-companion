"""Sales CRM 2.0, run 3a -- the Calendar (month, week, phone day list) and its List tab.

    the page   in the menu after Leads, comes with My day; month and week grids; ‹ › Today; phone day list
    items      tasks, calls, meetings with their time; follow-up steps due; travel and cover-end dates as all-day
    who        Mine / My team / Everyone follow the same visibility rules as Team today
    list       Late / Today / This week / Later, filters, Done in one click
"""
import re
from datetime import datetime, timedelta

import pytest

from conftest import login, make_user
from app import db as _db
from app.models import CrmLead, CrmPerson, CrmTask
from app.services import access, crm, crm_tasks

from test_crm2_money import _team_world, member
from test_crm_wa_sync_engine import ti_lead

IST = timedelta(hours=5, minutes=30)


def today():
    return (datetime.utcnow() + IST).date()


def when(day, hh=10, mm=0):
    """A UTC moment for India day `day` at hh:mm."""
    return datetime.combine(day, datetime.min.time()) + timedelta(hours=hh, minutes=mm) - IST


_n = [0]


def new_lead(owner, **kw):
    _n[0] += 1
    l = ti_lead(phone='+9198200%05d' % _n[0], name='Cal Person %d' % _n[0])
    crm.set_owner(l, owner.id if owner else None, ring=False, mark=False)
    for k, v in kw.items():
        setattr(l, k, v)
    _db.session.commit()
    return l


def task(owner, lead=None, person=None, kind='todo', title='A task', due=None, priority='normal', **kw):
    t = CrmTask(lead_id=lead.id if lead else None, person_id=(lead.person_id if lead else (person.id if person else None)), title=title,
                kind=kind, channel=kind, due_at=due or when(today()), owner_id=owner.id, created_by_id=owner.id,
                priority=priority, status='open', **kw)
    _db.session.add(t)
    _db.session.commit()
    return t


@pytest.fixture
def agent(app):
    return make_user('agent@test.com', 'agent', role='cs')


@pytest.fixture
def me(client, agent):
    login(client, 'agent@test.com')
    return agent


def page(client, qs=''):
    r = client.get('/cs/crm/calendar' + qs)
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    return r.get_data(as_text=True)


# ====================================================================================== the page and the menu

def test_the_calendar_is_in_daily_work_right_after_leads():
    sub = next(s for sec in access.SECTIONS for s in sec.get('subs', ()) if s['key'] == 'daily')
    pages = list(sub['pages'])
    assert pages.index('crm_calendar') == pages.index('crm_board') + 1
    p = access.PAGES['crm_calendar']
    assert p['label'] == 'Calendar' and p['with'] == frozenset({'crm_today'}) and p['nav']
    assert p['links'] == {'admin': 'admin_crm.calendar', 'cs': 'crm.calendar'}


def test_whoever_has_my_day_has_the_calendar_and_it_is_not_stored_on_a_role(app):
    a = member('a@test.com', 'ann')
    assert access.can(a, 'crm_today') and access.can(a, 'crm_calendar')
    assert 'crm_calendar' not in access.CS_ROLE_PAGES


def test_the_menu_line_shows_up_for_an_agent(client, me):
    html = page(client)
    assert 'href="/cs/crm/calendar"' in html and 'Calendar' in html


def test_the_page_opens_in_both_consoles(client, admin_user):
    login(client, 'admin@test.com')
    assert client.get('/admin/crm/calendar').status_code == 200
    assert client.get('/admin/crm/calendar?view=week').status_code == 200
    assert client.get('/admin/crm/calendar?tab=list').status_code == 200


# ====================================================================================== items

def test_month_view_shows_tasks_calls_meetings_with_their_times_and_links(client, me):
    lead = new_lead(me)
    d = today()
    task(me, lead, kind='meeting', title='Office visit', due=when(d, 15, 30), ends_at=when(d, 16, 15))
    task(me, lead, kind='call', title='Ring about renewal', due=when(d, 9, 5))
    task(me, lead, kind='todo', title='Send forms', due=when(d, 11, 0))
    html = page(client)
    assert 'Office visit' in html and '15:30-16:15' in html and '09:05' in html and 'Send forms' in html
    assert 'href="/cs/crm/lead/%d"' % lead.id in html
    # in time order inside the day
    assert html.index('Ring about renewal') < html.index('Send forms') < html.index('Office visit')


def test_a_task_on_a_person_links_to_the_contact_page(client, me):
    person = CrmPerson(name='Lone', email='lone@x.com')
    _db.session.add(person)
    _db.session.commit()
    task(me, person=person, title='Phone Lone')
    assert 'href="/cs/crm/contact/%d"' % person.id in page(client)


def test_follow_up_steps_due_show_up_too(client, me):
    lead = new_lead(me)
    step = CrmTask.query.filter_by(lead_id=lead.id, kind='step', status='open').first()
    step.due_at = when(today(), 12, 0)
    _db.session.commit()
    html = page(client)
    assert step.title in html and 'k-step' in html


def test_travel_and_cover_end_dates_of_open_leads_are_all_day_items(client, me):
    d = today()
    lead = new_lead(me, departure_date=d + timedelta(days=1), ends_on=d + timedelta(days=2))
    closed = new_lead(me, departure_date=d + timedelta(days=1), status='lost')
    html = page(client)
    assert html.count('k-departure') == 2 and html.count('k-cover_end') == 2        # the grid and the phone list, the open lead only
    assert 'Travels' in html and 'Cover ends' in html
    assert lead.person.display_name in html
    assert closed.status == 'lost'


def test_done_items_are_struck_through_and_other_months_are_not_mixed_in(client, me):
    d = today()
    t = task(me, title='Finished thing')
    t.status = 'done'
    _db.session.commit()
    far = task(me, title='Next year thing', due=when(d + timedelta(days=400)))
    html = page(client)
    assert 'cal-it k-todo done' in html and 'Next year thing' not in html


# ====================================================================================== navigation and views

def test_month_grid_starts_on_monday_and_covers_whole_weeks(app):
    weeks = crm_tasks.month_grid(datetime(2026, 10, 21).date())
    assert weeks[0][0].weekday() == 0 and weeks[-1][-1].weekday() == 6
    assert all(len(w) == 7 for w in weeks)
    assert weeks[0][0] <= datetime(2026, 10, 1).date() and weeks[-1][-1] >= datetime(2026, 10, 31).date()
    assert [w[0] for w in crm_tasks.month_grid(datetime(2026, 2, 5).date())][0].month in (1, 2)


def test_previous_next_and_today_links(client, me):
    html = page(client, '?on=2026-10-15')
    assert 'October 2026' in html
    assert 'on=2026-09-01' in html and 'on=2026-11-01' in html          # ‹ and ›
    assert re.search(r'href="[^"]*calendar(\?[^"]*)?"[^>]*>Today<', html)
    wk = page(client, '?view=week&on=2026-10-15')
    assert '12 Oct - 18 Oct 2026' in wk and 'on=2026-10-05' in wk and 'on=2026-10-19' in wk
    assert page(client, '?on=nonsense')            # a bad date falls back to today


def test_week_view_has_seven_days_and_the_items_of_that_week(client, me):
    d = today()
    monday = d - timedelta(days=d.weekday())
    task(me, title='This week thing', due=when(monday + timedelta(days=2)))
    task(me, title='Far thing', due=when(monday + timedelta(days=20)))
    html = page(client, '?view=week&on=%s' % d.isoformat())
    assert 'This week thing' in html and 'Far thing' not in html
    assert html.count('role="gridcell"') == 7


def test_a_phone_gets_a_day_list_instead_of_the_grid(client, me):
    task(me, title='Phone day thing')
    html = page(client)
    assert 'cal-daylist' in html and 'cal-grid' in html
    css = open('app/static/css/crm.css', encoding='utf-8').read()
    mark = '@media (max-width: 760px) {' + chr(10) + '  .cal-grid'
    phone = css[css.index(mark):]
    assert '.cal-grid { display: none; }' in phone and '.cal-daylist { display: block; }' in phone
    assert '.cal-daylist { display: none; }' in css.split(mark)[0]


# ====================================================================================== whose

def test_mine_team_everyone_follow_the_visibility_rules(client, admin_user):
    lead_, a, b, c, north = _team_world(admin_user)
    la, lb, lc = new_lead(a), new_lead(b), new_lead(c)
    task(a, la, title='Anitas job')
    task(b, lb, title='Bhanus job')
    task(c, lc, title='Charans job')
    login(client, a.email)
    mine = page(client)
    assert 'Anitas job' in mine and 'Bhanus job' not in mine and 'Charans job' not in mine
    team = page(client, '?who=team')
    assert 'Anitas job' in team and 'Bhanus job' in team and 'Charans job' not in team
    # an agent asking for everyone gets their own, and is not offered the choice
    forced = page(client, '?who=all')
    assert 'Charans job' not in forced and 'Bhanus job' not in forced
    assert '>Everyone<' not in forced
    client.post('/auth/logout')
    login(client, 'admin@test.com')
    everyone = client.get('/admin/crm/calendar?who=all').get_data(as_text=True)
    assert all(x in everyone for x in ('Anitas job', 'Bhanus job', 'Charans job')) and '>Everyone<' in everyone
    client.post('/auth/logout')
    login(client, lead_.email)
    assert '>Everyone<' in client.get('/cs/crm/calendar').get_data(as_text=True)          # a team lead may look at all


def test_travel_dates_follow_whose_leads_they_are(client, admin_user):
    lead_, a, b, c, north = _team_world(admin_user)
    d = today()
    new_lead(a, departure_date=d)
    other = new_lead(c, departure_date=d)
    login(client, a.email)
    assert other.person.display_name not in page(client)
    assert other.person.display_name not in page(client, '?who=team')


# ====================================================================================== the List tab

def test_list_groups_late_today_week_later_and_done_is_one_click(client, me):
    now = datetime.utcnow()
    lead = new_lead(me)
    end_today = crm_tasks.end_of_today()
    late = task(me, lead, title='Late job', due=now - timedelta(days=2))
    tod = task(me, lead, title='Later today job', due=min(end_today - timedelta(minutes=1), now + timedelta(hours=8)) if end_today > now + timedelta(minutes=2) else now + timedelta(seconds=30))
    wk = task(me, lead, title='Week job', due=end_today + timedelta(days=3))
    lat = task(me, lead, title='Much later job', due=end_today + timedelta(days=30))
    html = page(client, '?tab=list')
    for label in ('Late (1)', 'This week (1)', 'Later (1)'):
        assert label in html
    assert html.index('Late job') < html.index('Week job') < html.index('Much later job')
    chunk = html[html.index('id="task-%d"' % lat.id):]
    chunk = chunk[:chunk.index('</article>')]
    assert chunk.count('data-act') == 1 and 'data-act="done"' in chunk
    assert client.post('/cs/crm/task/%d/done' % late.id).status_code == 200
    assert 'Late job' not in page(client, '?tab=list')


def test_list_filters_by_type_and_priority(client, me):
    lead = new_lead(me)
    task(me, lead, kind='call', title='Call job', priority='high')
    task(me, lead, kind='meeting', title='Meeting job', priority='low')
    task(me, lead, kind='todo', title='Todo job')
    base = page(client, '?tab=list')
    assert all(x in base for x in ('Call job', 'Meeting job', 'Todo job'))
    calls = page(client, '?tab=list&kind=call')
    assert 'Call job' in calls and 'Meeting job' not in calls and 'Todo job' not in calls
    high = page(client, '?tab=list&priority=high')
    assert 'Call job' in high and 'Meeting job' not in high
    both = page(client, '?tab=list&kind=meeting&priority=high')
    assert 'job' not in both.split('Late (')[0] and 'Call job' not in both and 'Meeting job' not in both


def test_list_follows_whose_and_never_shows_steps(client, admin_user):
    lead_, a, b, c, north = _team_world(admin_user)
    la, lb = new_lead(a), new_lead(b)
    task(a, la, title='Anitas listed')
    task(b, lb, title='Bhanus listed')
    login(client, a.email)
    assert 'Bhanus listed' not in page(client, '?tab=list')
    assert 'Bhanus listed' in page(client, '?tab=list&who=team')
    steps = CrmTask.query.filter_by(kind='step', status='open').all()
    assert steps
    html = page(client, '?tab=list&who=team')
    assert all(s.title not in html for s in steps if s.title not in ('Anitas listed', 'Bhanus listed'))


def test_the_calendar_asks_for_a_bounded_number_of_queries(client, me, app):
    from sqlalchemy import event
    lead = new_lead(me, departure_date=today())
    for i in range(30):
        task(me, lead, title='Many %d' % i, due=when(today() + timedelta(days=i % 20)))
    count = [0]

    def tick(*a, **k):
        count[0] += 1
    event.listen(_db.engine, 'before_cursor_execute', tick)
    try:
        page(client)
    finally:
        event.remove(_db.engine, 'before_cursor_execute', tick)
    assert count[0] < 40
