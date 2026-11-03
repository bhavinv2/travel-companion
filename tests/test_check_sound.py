"""The half-hour sound (services/check_sound.py, templates/_check_sound.html, static/js/check-sound.js): each person's
own on / off, hours and days, sound, loudness, ringing again and desktop notice, kept with their notification
preferences; the speaker in the header and "Sound" on the half-hourly check open its settings; only for people who
may open the check."""
import json
import re

from conftest import login, make_user
from app import db as _db
from app.models import CrmChannelCheck
from app.services import check_sound, crm, crm_reports


def cfg_of(page):
    m = re.search(r"check-sound\.js[^\"]*\" data-cfg='([^']*)'", page)
    return json.loads(m.group(1).replace('&#34;', '"')) if m else None


def test_off_until_they_turn_it_on_and_on_every_staff_page(app, client, cs_user):
    login(client, cs_user.email)
    page = client.get('/cs/crm/today').get_data(as_text=True)
    assert 'data-sound-open title="Half-hour sound: Off"' in page                  # the speaker in the header
    assert 'id="sndDialog"' in page and 'check-sound.js' in page
    assert cfg_of(page) == check_sound.DEFAULTS
    check = client.get('/cs/crm/checks').get_data(as_text=True)
    assert 'Sound: <span data-sound-says>Off</span>' in check                   # the check's own button


def test_their_hours_days_and_sound_are_kept_for_them(app, client, cs_user):
    login(client, cs_user.email)
    r = client.post('/my/check-sound', json={'on': True, 'all_day': False, 'from': '09:00', 'to': '18:00',
                                             'days': [0, 1, 2, 3, 4, 5], 'sound': 'bell', 'volume': 40,
                                             'again': 10, 'notice': True})
    d = r.get_json()
    assert r.status_code == 200 and d['says'] == 'On · 09:00–18:00, Mon–Sat'
    _db.session.refresh(cs_user)
    s = check_sound.of(cs_user)
    assert s['on'] and s['sound'] == 'bell' and s['volume'] == 40 and s['again'] == 10 and s['days'] == [0, 1, 2, 3, 4, 5]
    page = client.get('/cs/crm/today').get_data(as_text=True)
    assert 'Half-hour sound: On · 09:00–18:00, Mon–Sat' in page and 'fa-volume-high' in page
    assert cfg_of(page)['from'] == '09:00' and cfg_of(page)['notice'] is True
    # off again, and the rest stays as chosen
    client.post('/my/check-sound', json={'on': False})
    _db.session.refresh(cs_user)
    assert not check_sound.of(cs_user)['on'] and check_sound.of(cs_user)['sound'] == 'bell'


def test_what_cannot_be_is_said(app, client, cs_user):
    login(client, cs_user.email)
    for bad, says in (({'all_day': False, 'from': '10:00', 'to': '10:00'}, 'the same time'),
                      ({'days': []}, 'at least one day'), ({'sound': 'siren'}, 'Choose one of the sounds'),
                      ({'from': '25:00'}, 'like 09:00'), ({'again': 7}, 'Ring again')):
        r = client.post('/my/check-sound', json=bad)
        assert r.status_code == 400 and says in r.get_json()['error']
    assert check_sound.of(cs_user) == check_sound.DEFAULTS
    assert check_sound.says(dict(check_sound.DEFAULTS, on=True, days=[0, 2, 3, 4, 6])) == \
        'On · every half hour, Mon, Wed–Fri, Sun'


def test_saving_notification_settings_keeps_the_sound(app, client, cs_user):
    login(client, cs_user.email)
    client.post('/my/check-sound', json={'on': True, 'sound': 'pop'})
    client.post('/settings/notifications', data={'email': 'on'})
    _db.session.refresh(cs_user)
    assert cs_user.notify_prefs['email'] is True and check_sound.of(cs_user)['sound'] == 'pop'


def test_ringing_again_asks_whether_every_inbox_is_ticked(app, client, cs_user, monkeypatch):
    from datetime import datetime
    monkeypatch.setattr(crm_reports, 'ist_now', lambda: datetime(2026, 11, 2, 10, 40))
    login(client, cs_user.email)
    assert client.get('/my/check-sound/now').get_json() == {'done': False}
    for ch in crm.crm_settings()['check_channels']:
        _db.session.add(CrmChannelCheck(day=datetime(2026, 11, 2).date(), slot=21, channel=ch, user_id=cs_user.id))
    _db.session.commit()
    assert client.get('/my/check-sound/now').get_json() == {'done': True}


def test_not_for_somebody_who_does_not_do_the_check(app, client):
    agent = make_user('nocheck@test.com', 'nocheck', role='cs')
    agent.cs_access = ['home']
    _db.session.commit()
    login(client, agent.email)
    page = client.get('/cs/').get_data(as_text=True)
    assert 'data-sound-open' not in page and 'sndDialog' not in page
    assert client.post('/my/check-sound', json={'on': True}).status_code == 403
    assert client.get('/my/check-sound/now').status_code == 403
