"""Release 1, round-1 gaps: the connection page, hidden compose buttons, quick replies that follow saves
and removals (with remove_titles and conflicts), live refresh on wacrm:activity, and the help-label check."""
import copy
import os
import re

import pytest

from conftest import login
from app.models import CrmAnswer
from app.services import access, crm, jobs, wa_templates, wacrm, wacrm_team

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(HERE, *parts), encoding='utf8') as f:
        return f.read()


@pytest.fixture
def team(app, monkeypatch):
    """The WhatsApp CRM connected with the mode on 'Keep leads in step'; every portal call recorded and answered."""
    monkeypatch.setenv('WACRM_URL', 'https://crm.example/crm')
    monkeypatch.setenv('WACRM_API_KEY', 'wacrm_live_test')
    monkeypatch.setenv('WACRM_PORTAL_SECRET', 'x' * 40)
    wa_templates.forget()
    calls = []
    state = {'conflicts': [], 'fail': None}

    def fake_api(method, path, payload=None, params=None):
        calls.append((method, path, copy.deepcopy(payload)))
        if path == 'quick-replies':
            if state['fail']:
                raise state['fail']
            n = len((payload or {}).get('items') or [])
            return {'created': n, 'updated': 0, 'removed': len((payload or {}).get('remove_titles') or []),
                    'conflicts': state['conflicts']}
        return {}

    monkeypatch.setattr(wacrm_team, '_api', fake_api)
    monkeypatch.setattr(wacrm, '_call', lambda *a, **k: {})
    crm.save_settings(whatsapp_mode='contacts')
    return calls, state


def quick_calls(calls):
    return [c for c in calls if c[1] == 'quick-replies']


def answer(client, **kw):
    data = {'title': 'Do you ship gifts?', 'body': 'Yes, we do.', 'product': 'GH'}
    data.update(kw)
    return client.post('/admin/crm/setup/answer', data=data)


# ---------------------------------------------------------------- G1: the connection page draws

def test_the_connection_page_draws_without_keys(app, client, admin_user, monkeypatch):
    """_connect_context() and _common() both had a wa_mode: the page was a 500."""
    for k in ('WACRM_URL', 'WACRM_API_KEY', 'WACRM_PORTAL_SECRET'):
        monkeypatch.delenv(k, raising=False)
    crm.save_settings(whatsapp_mode='contacts')
    login(client, admin_user.email)
    assert client.get('/admin/crm/connection').status_code == 200
    assert client.get('/cs/crm/connection').status_code < 400


def test_the_radio_follows_the_saved_choice(app, client, admin_user, monkeypatch):
    monkeypatch.setenv('WACRM_URL', 'https://crm.example/crm')
    monkeypatch.setenv('WACRM_API_KEY', 'wacrm_live_test')
    crm.save_settings(whatsapp_mode='send')
    login(client, admin_user.email)
    html = client.get('/admin/crm/connection').get_data(as_text=True)
    checked = re.findall(r'<input type="radio" name="mode" value="(\w+)" checked', html)
    assert checked == ['send']


# ---------------------------------------------------------------- G4: nothing that does nothing

def test_put_it_in_the_chat_is_hidden_until_the_whatsapp_side_exists(app, client, cs_user):
    assert crm.WA_COMPOSE is False
    access.ensure_defaults()
    lead = crm.capture('ti-quote', name='Ramesh Kumar', phone='+919876543210', utm={})
    login(client, cs_user.email)
    html = client.get('/admin/messaging/lead-panel?conversation=conv-7&phone=919876543210').get_data(as_text=True)
    assert 'Put it in the chat' not in html
    page = client.get('/cs/crm/lead/%d' % lead.id).get_data(as_text=True)
    assert 'Put it in the chat' not in page
    assert 'Put in the chat. Check it' not in read('app', 'static', 'js', 'crm.js')       # no toast for nothing


# ---------------------------------------------------------------- G5: quick replies follow saves and removals

def test_saving_a_quick_reply_copies_it_to_whatsapp(app, client, admin_user, team):
    calls, _ = team
    login(client, admin_user.email)
    answer(client)
    out = quick_calls(calls)
    assert out and any(i['title'] == 'Do you ship gifts?' and i['text'] == 'Yes, we do.' for i in out[-1][2]['items'])
    assert wa_templates.quick_state()['titles'] == ['Do you ship gifts?']
    assert wa_templates.quick_state()['due'] is False


def test_removing_a_quick_reply_sends_its_old_title_in_remove_titles(app, client, admin_user, team):
    calls, _ = team
    login(client, admin_user.email)
    answer(client)
    a = CrmAnswer.query.filter_by(title='Do you ship gifts?').one()
    del calls[:]
    client.post('/admin/crm/setup/answer', data={'op': 'delete', 'id': a.id})
    body = quick_calls(calls)[-1][2]
    assert body['remove_titles'] == ['Do you ship gifts?']
    assert not any(i['title'] == 'Do you ship gifts?' for i in body['items'])
    assert wa_templates.quick_state()['titles'] == [i['title'] for i in body['items']]


def test_renaming_a_quick_reply_removes_the_old_title(app, client, admin_user, team):
    calls, _ = team
    login(client, admin_user.email)
    answer(client)
    a = CrmAnswer.query.filter_by(title='Do you ship gifts?').one()
    del calls[:]
    answer(client, id=a.id, title='Can you courier a gift?')
    body = quick_calls(calls)[-1][2]
    assert body['remove_titles'] == ['Do you ship gifts?']
    assert any(i['title'] == 'Can you courier a gift?' for i in body['items'])


def test_nothing_goes_to_whatsapp_while_the_switch_is_off(app, client, admin_user, team):
    calls, _ = team
    crm.save_settings(whatsapp_mode='off')
    login(client, admin_user.email)
    answer(client)
    assert quick_calls(calls) == []
    assert CrmAnswer.query.filter_by(title='Do you ship gifts?').count() == 1       # still saved here


def test_a_failed_copy_stays_marked_and_the_jobs_runner_finishes_it(app, client, admin_user, team):
    calls, state = team
    state['fail'] = wacrm_team.TeamError('WhatsApp CRM did not answer', 503)
    login(client, admin_user.email)
    r = answer(client)
    assert r.status_code == 302                                     # the save itself never fails
    st = wa_templates.quick_state()
    assert st['due'] is True and st['error']
    state['fail'] = None
    del calls[:]
    with app.test_request_context('/internal/jobs/run', method='POST'):
        out = wa_templates.run_quick_replies()
    assert out == {'crm_wa_quick': 'copied'} and wa_templates.quick_state()['due'] is False
    assert quick_calls(calls)
    with app.test_request_context('/internal/jobs/run', method='POST'):
        assert wa_templates.run_quick_replies() == {}                # nothing waits now


def test_a_whatsapp_crm_without_quick_replies_leaves_nothing_waiting(app, client, admin_user, team):
    calls, state = team
    state['fail'] = wacrm_team.TeamError('not found', 404)
    login(client, admin_user.email)
    answer(client)
    assert wa_templates.quick_state()['due'] is False


def test_the_jobs_runner_calls_the_quick_reply_retry(app, monkeypatch):
    seen = []
    monkeypatch.setattr(wa_templates, 'run_quick_replies', lambda: seen.append(1) or {'crm_wa_quick': 'copied'})
    with app.test_request_context('/internal/jobs/run', method='POST'):
        out = jobs.run_all()
    assert seen and out.get('crm_wa_quick') == 'copied'


# ---------------------------------------------------------------- G6: conflicts are reported

def test_the_client_adds_up_conflicts_across_parts(app, monkeypatch):
    monkeypatch.setenv('WACRM_URL', 'https://crm.example/crm')
    monkeypatch.setenv('WACRM_PORTAL_SECRET', 'x' * 40)
    replies = iter([{'created': 1, 'updated': 0, 'removed': 0, 'conflicts': ['Yes']},
                    {'created': 1, 'updated': 0, 'removed': 0, 'conflicts': ['Yes', 'No']}])
    monkeypatch.setattr(wacrm_team, '_api', lambda *a, **k: next(replies))
    out = wacrm_team.push_quick_replies([{'title': 'T%d' % i, 'text': 'x'} for i in range(250)])
    assert out['conflicts'] == ['Yes', 'No'] and out['created'] == 2


def test_the_push_button_tells_about_conflicts(app, client, admin_user, team):
    calls, state = team
    state['conflicts'] = ['Yes']
    crm.ensure_defaults()
    login(client, admin_user.email)
    r = client.post('/admin/crm/setup/templates/quick-replies', follow_redirects=True)
    text = r.get_data(as_text=True)
    assert 'not copied' in text and 'Rename one of them' in text
    assert wa_templates.quick_state()['conflicts'] == ['Yes']


def test_conflict_words_are_short_and_plain():
    said = wa_templates.conflict_words(['A', 'B', 'C', 'D', 'E', 'F'])
    assert said.startswith('6 not copied') and said.count(',') >= 5 and '…' in said


# ---------------------------------------------------------------- G7: the panel follows wacrm:activity

def test_the_frame_and_the_lead_page_refresh_on_activity():
    assert 'wacrm:activity' in read('app', 'templates', 'messaging', 'frame.html')
    assert 'wacrm:activity' in read('app', 'static', 'js', 'crm.js')


# ---------------------------------------------------------------- G9: tags help

def test_the_tags_screen_warns_about_the_tags_the_sales_crm_writes():
    from app.routes import messaging
    assert any('stage, product or source tags' in line for line in messaging.SCREENS['tags']['help'])


# ---------------------------------------------------------------- G11: every menu line explains itself

def test_every_menu_line_has_a_tooltip_and_a_label():
    """The Sales, Messaging, Reports, Set-up and Team lines (the redesigned ones) each explain themselves;
    the older site lines fall back to their label."""
    new_sections = ('sales', 'messaging', 'automatic', 'reports', 'setup', 'team')
    for key, p in access.PAGES.items():
        if p['nav'] and p['section'] in new_sections:
            assert p['tip'].strip(), '%s has no tooltip' % key
            assert p['label'].strip(), key


def test_every_sales_page_has_a_page_head_with_a_helper_line(app, client, admin_user):
    login(client, admin_user.email)
    checked = 0
    for key, p in access.PAGES.items():
        ep = p['links'].get('admin')
        if not p['nav'] or not ep or not ep.startswith(('crm.', 'admin_crm.')):
            continue
        from flask import url_for
        with app.test_request_context():
            path = url_for(ep, **p['args'])
        html = client.get(path).get_data(as_text=True)
        assert 'class="ui-helper"' in html, '%s (%s) has no helper line under its heading' % (key, path)
        checked += 1
    assert checked >= 8


def test_the_framed_screens_have_a_bar_with_a_helper_line():
    from app.routes import messaging
    for name, s in messaging.SCREENS.items():
        assert s.get('heading'), name
        assert s.get('helper'), '%s has no helper line' % name
        assert s.get('help'), '%s has no how-it-works lines' % name
