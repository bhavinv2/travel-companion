"""Inbox checks says, person by person, what was checked. (The Reports menu: tests/test_health.py.)

    one day       crm_reports.check_report, the day Team analysis shows half hour by half hour -- for each person: the hours they worked, the half hours they ticked (late when after the half hour,
                  "Tick all" when one press ticked several), the half hours nobody fully checked while they worked,
                  a strip of the day and a plain status; then the half hours not fully checked, with who was working
                  then, and each inbox's half hours; a person's own day lists each check with its inboxes
"""
import re
from datetime import date, datetime, timedelta

from conftest import login, make_user
from app import db as _db
from app.models import CrmChannelCheck, WorkspaceRole, WorkspaceTeam
from app.services import access, crm, crm_reports

PAST = date.today() - timedelta(days=2)          # a past day: every half hour is over


def words(html):
    return ' '.join(re.sub(r'<[^>]+>', ' ', html).split())


def strip(html):
    m = re.search(r'<nav class="subtabs"[^>]*>(.*?)</nav>', html, re.S)
    return re.findall(r'>([^<]+)</a>', m.group(1)) if m else []


# ====================================================================================== what was checked

def tick(user, slot, channel, at):
    _db.session.add(CrmChannelCheck(day=PAST, slot=slot, channel=channel, user_id=user.id if user else None,
                                    checked_at=at))
    _db.session.commit()


def start_of(slot, minute=0):
    return datetime.combine(PAST, datetime.min.time()) + timedelta(minutes=30 * slot + minute) - crm_reports.IST


def test_inbox_checks_says_person_by_person_what_they_checked(app, admin_user):
    crm.ensure_defaults()
    channels = crm.crm_settings()['check_channels']
    a, b, c = (make_user('%s@test.com' % n, n, role='cs') for n in ('asha', 'bala', 'chitra'))
    first = crm_reports.slots()[0]
    t0 = start_of(first, 10)
    for i, ch in enumerate(channels):                          # Asha: every inbox in one press of Tick all
        tick(a, first, ch, t0 + timedelta(milliseconds=100 * i))
    tick(b, first + 1, channels[0], start_of(first + 1, 45))   # Bala: one inbox, after its half hour was over
    sheet = {a.id: {'first': start_of(first, 5), 'last': start_of(first + 2, 10),
                    'timeline': [(start_of(first, 12), None, 'fa-paper-plane', 'Sent')]},
             b.id: {'first': start_of(first + 1, 5), 'last': start_of(first + 1, 45), 'timeline': []},
             c.id: {'first': None, 'last': None, 'timeline': []}}
    r = crm_reports.check_report(PAST, [c, b, a], channels, sheet=sheet)
    p = {x['user'].id: x for x in r['people']}
    pa, pb, pc = p[a.id], p[b.id], p[c.id]
    # Asha worked three half hours: ticked every inbox in the first, nobody fully checked the other two
    assert pa['checked'] == 1 and pa['bulk'] == 1 and pa['late'] == 0 and pa['missed'] == 2 and pa['working_due'] == 3
    assert [x['state'] for x in pa['strip'][:4]] == ['all', 'gap', 'gap', 'off']
    assert (pa['status'], pa['label']) == ('gaps', 'Some missed')
    assert pa['start'] == (start_of(first, 5) + crm_reports.IST).strftime('%H:%M')
    oldest = pa['rows'][-1]
    assert oldest['state'] == 'all' and oldest['bulk'] and oldest['did'] == '1 message'
    assert [t['channel'] for t in oldest['ticks']] == channels
    assert pa['rows'][0]['state'] == 'gap' and pa['rows'][0]['others'] == channels      # newest first
    # Bala ticked once, late
    assert pb['late'] == 1 and (pb['status'], pb['label']) == ('late', 'Often late') and pb['rows'][-1]['ticks'][0]['late']
    # Chitra did nothing that day
    assert (pc['status'], pc['label']) == ('off', 'No activity') and {x['state'] for x in pc['strip']} == {'off'}
    assert [x['user'].id for x in r['people']] == [a.id, b.id, c.id]                   # whoever needs a word first
    gap = next(g for g in r['gaps'] if g['slot'] == first + 1)
    assert gap['missing'] == channels[1:] and sorted(gap['working']) == sorted([a.full_name, b.full_name])
    assert gap['ticked'] == [{'channel': channels[0], 'who': b.full_name,
                              'at': (start_of(first + 1, 45) + crm_reports.IST).strftime('%H:%M')}]
    assert r['full'] == 1 and r['due'] == len(crm_reports.slots()) and r['gap_count'] == r['due'] - 1
    assert r['gaps'][0]['slot'] > r['gaps'][-1]['slot'] and r['checking'] == 2 and r['late'] == 1
    by = {i['channel']: i for i in r['inboxes']}
    assert by[channels[0]]['done'] == 2 and by[channels[1]]['done'] == 1 and by[channels[0]]['due'] == r['due']


def test_a_tick_by_somebody_not_shown_is_not_named(app, admin_user):
    crm.ensure_defaults()
    channels = crm.crm_settings()['check_channels']
    a, z = make_user('asha@test.com', 'asha', role='cs'), make_user('zed@test.com', 'zed', role='cs')
    first = crm_reports.slots()[0]
    tick(z, first, channels[0], start_of(first, 3))
    tick(None, first, channels[1], start_of(first, 4))                                 # a connected inbox
    r = crm_reports.check_report(PAST, [a], channels, sheet={})
    who = {t['channel']: t['who'] for t in r['gaps'][-1]['ticked']}
    assert who == {channels[0]: 'someone in another team', channels[1]: 'ticked itself'}


def test_a_persons_day_lists_each_check_with_its_inboxes(app, admin_user):
    crm.ensure_defaults()
    channels = crm.crm_settings()['check_channels']
    a = make_user('asha@test.com', 'asha', role='cs')
    first = crm_reports.slots()[0]
    tick(a, first, channels[0], start_of(first, 5))
    tick(a, first + 2, channels[1], start_of(first + 2, 50))                                  # late
    lines = [t for _w, _l, icon, t in crm_reports.day_sheet(PAST, [a])[a.id]['timeline'] if icon == 'fa-clipboard-check']
    label = crm_reports.slot_label
    assert lines == ['Checked %s for %s–%s' % (channels[0], label(first), label(first + 1)),
                     'Checked %s for %s–%s (late, after %s)' % (channels[1], label(first + 2), label(first + 3),
                                                                label(first + 3))]


def test_one_inbox_ticked_late_among_others_on_time_is_not_a_late_half_hour(app, admin_user):
    crm.ensure_defaults()
    channels = crm.crm_settings()['check_channels']
    a = make_user('asha@test.com', 'asha', role='cs')
    first = crm_reports.slots()[0]
    tick(a, first, channels[0], start_of(first, 5))
    tick(a, first, channels[1], start_of(first, 40))                                   # a straggler, after it
    tick(a, first + 1, channels[0], start_of(first + 1, 35))                             # started only after it
    p = crm_reports.check_report(PAST, [a], channels, sheet={})['people'][0]
    states = {x['slot']: x['state'] for x in p['strip']}
    assert states[first] == 'some' and states[first + 1] == 'late' and p['late'] == 1
    assert [t['late'] for t in p['rows'][-1]['ticks']] == [False, True]                  # the straggler still shows
