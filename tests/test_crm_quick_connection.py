"""Release 2, U8: Quick replies, the WhatsApp connection page, What goes out by itself, Results.

    quick replies   one title each; WhatsApp gets the title without the code; a reply that needs the lead is
                    never pushed; a rename or delete sends the old title in remove_titles; nothing while off
    connection      drawing the page makes no call; switching to sending shows what would go first;
                    a follow-up stuck "sending" is only ever settled by a person, never sent again
    results         draws with any filter, for admins only
"""
import importlib.util
import os
from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa

from conftest import login
from app import db as _db
from app.models import CrmAnswer, CrmTask
from app.services import access, crm, crm_connection, wa_templates, wacrm, wacrm_team

from test_crm_f1_gaps import answer, quick_calls, team  # noqa: F401  (the connected WhatsApp CRM, recorded)
from test_crm_wa_sync_engine import ti_lead


def titles(call):
    return [i['title'] for i in call[2]['items']]


# ======================================================================================= quick replies

def test_a_title_goes_without_its_code_and_help_questions_go_along(app, client, admin_user, team):
    calls, _ = team
    login(client, admin_user.email)
    answer(client)
    sent = titles(quick_calls(calls)[-1])
    assert 'Do you ship gifts?' in sent and len(sent) > 1                  # the Help & FAQ rows are pushed too
    assert not [t for t in sent if ' · ' in t]
    assert len(sent) == len({t.lower() for t in sent})                      # one of each


def test_a_reply_that_needs_the_lead_is_saved_but_not_pushed(app, client, admin_user, team):
    calls, _ = team
    login(client, admin_user.email)
    r = client.post('/admin/crm/setup/answer', data={'title': 'Your trip date', 'body': 'You fly on {departure}.',
                                                     'product': 'GH'}, follow_redirects=True)
    assert 'needs a trip date' in r.get_data(as_text=True)
    assert CrmAnswer.query.filter_by(title='Your trip date').count() == 1
    assert all('Your trip date' not in titles(c) for c in quick_calls(calls))


def test_two_replies_cannot_share_a_title_whatever_the_case_or_spaces(app, client, admin_user, team):
    login(client, admin_user.email)
    answer(client)
    r = client.post('/admin/crm/setup/answer', data={'title': '  DO YOU SHIP GIFTS?  ', 'body': 'Other.', 'product': 'GH'})
    assert r.status_code == 200 and 'already asks this' in r.get_data(as_text=True)
    assert CrmAnswer.query.filter(sa.func.lower(CrmAnswer.title) == 'do you ship gifts?').count() == 1
    a = CrmAnswer.query.filter_by(title='Do you ship gifts?').one()
    r = client.post('/admin/crm/setup/answer', data={'id': a.id, 'title': 'Do you ship gifts?', 'body': 'Changed.',
                                                     'product': 'GH'})
    assert r.status_code == 302 and _db.session.get(CrmAnswer, a.id).body == 'Changed.'      # its own title is fine


def test_an_empty_title_or_body_is_not_saved(app, client, admin_user, team):
    login(client, admin_user.email)
    before = CrmAnswer.query.count()
    for data in ({'title': '', 'body': 'x'}, {'title': 'x', 'body': '   '}):
        assert client.post('/admin/crm/setup/answer', data=data).status_code == 200
    assert CrmAnswer.query.count() == before


def test_a_rename_and_a_delete_send_the_old_title_in_remove_titles(app, client, admin_user, team):
    calls, _ = team
    login(client, admin_user.email)
    answer(client)
    a = CrmAnswer.query.filter_by(title='Do you ship gifts?').one()
    del calls[:]
    client.post('/admin/crm/setup/answer', data={'id': a.id, 'title': 'Can you ship gifts?', 'body': 'Yes.', 'product': 'GH'})
    last = quick_calls(calls)[-1]
    assert 'Do you ship gifts?' in (last[2].get('remove_titles') or []) and 'Can you ship gifts?' in titles(last)
    del calls[:]
    client.post('/admin/crm/setup/answer', data={'id': a.id, 'op': 'delete'})
    assert 'Can you ship gifts?' in (quick_calls(calls)[-1][2].get('remove_titles') or [])
    assert CrmAnswer.query.filter_by(id=a.id).count() == 0


def test_nothing_is_written_to_whatsapp_while_the_switch_is_off(app, client, admin_user, team):
    calls, _ = team
    crm.save_settings(whatsapp_mode='off')
    login(client, admin_user.email)
    r = client.post('/admin/crm/setup/answer', data={'title': 'Hello there', 'body': 'Hi!', 'product': 'GH'},
                    follow_redirects=True)
    assert wa_templates.QR_SAVED_OFF in r.get_data(as_text=True)
    assert quick_calls(calls) == []
    r = client.post('/admin/crm/quick-replies/push', follow_redirects=True)
    assert crm.WA_WRITES_OFF in r.get_data(as_text=True) and quick_calls(calls) == []


def test_a_title_in_a_button_reply_is_reported_as_a_conflict(app, client, admin_user, team):
    calls, state = team
    state['conflicts'] = ['Hello there']
    login(client, admin_user.email)
    login(client, admin_user.email)
    client.post('/admin/crm/setup/answer', data={'title': 'Hello there', 'body': 'Hi!', 'product': 'GH'})
    assert wa_templates.quick_state()['conflicts'] == ['Hello there']
    page = client.get('/admin/crm/quick-replies').get_data(as_text=True).replace('&#39;', "'").replace('&#34;', '"')
    assert 'Hello there' in page and 'Rename one of them' in page


def test_a_push_that_whatsapp_refuses_is_said_plainly_and_changes_nothing_here(app, client, admin_user, team):
    calls, state = team
    state['fail'] = wacrm_team.TeamError('too big', status=422, code='rule_too_large')
    login(client, admin_user.email)
    r = client.post('/admin/crm/quick-replies/push', follow_redirects=True)
    assert wa_templates.QUICK_TOO_MANY[:30] in r.get_data(as_text=True)


def test_only_admins_push_or_bring_in_replies(app, client, cs_user, team):
    calls, _ = team
    access.ensure_defaults()
    login(client, cs_user.email)
    for url in ('/cs/crm/quick-replies/push', '/cs/crm/quick-replies/import'):
        assert client.post(url).status_code in (302, 403, 404)
    assert quick_calls(calls) == []


def test_bringing_in_whatsapps_own_replies_adds_text_ones_and_lists_buttons(app, client, admin_user, team, monkeypatch):
    rows = [{'title': 'Opening hours', 'type': 'text', 'body': 'Hi {{contact.first_name}}, we open at 9. {{agent.name}}'},
            {'title': 'Pick one', 'type': 'interactive', 'body': 'Yes or no?'},
            {'title': 'do you ship gifts?', 'type': 'text', 'body': 'dup'}, {'title': '', 'type': 'text', 'body': 'x'}]
    login(client, admin_user.email)
    answer(client)
    monkeypatch.setattr(wacrm_team, 'quick_replies_unmanaged', lambda: rows)
    client.post('/admin/crm/quick-replies/import')
    a = CrmAnswer.query.filter_by(title='Opening hours').one()
    assert a.code is None and '{name}' in a.body and '{agent}' in a.body and '{{' not in a.body
    assert CrmAnswer.query.filter_by(title='Pick one').count() == 0                    # buttons stay in WhatsApp
    assert wa_templates.quick_state()['buttons'][0]['title'] == 'Pick one'
    assert CrmAnswer.query.filter(sa.func.lower(CrmAnswer.title) == 'do you ship gifts?').count() == 1


def test_an_older_whatsapp_crm_gets_a_plain_message_on_import(app, client, admin_user, team, monkeypatch):
    def old():
        raise wacrm_team.TeamError('Not found', status=404)
    monkeypatch.setattr(wacrm_team, 'quick_replies_unmanaged', old)
    login(client, admin_user.email)
    r = client.post('/admin/crm/quick-replies/import', follow_redirects=True)
    assert 'Needs the WhatsApp CRM update' in r.get_data(as_text=True)
    assert wa_templates.quick_state()['import_missing'] is True


def test_lead_only_words_are_found_and_static_ones_are_not(app):
    assert wa_templates.lead_only('Hi {name}, call {helplines} or see {insurance_link}') == []
    assert wa_templates.lead_only('Fly on {departure}, {days} days, {departure}') == ['departure', 'days']
    assert wa_templates.works_in('Hi {name}') == wa_templates.WORKS_CHATS
    assert wa_templates.works_in('on {departure}') == wa_templates.WORKS_LEAD_DATE


def test_a_help_question_an_own_reply_already_asks_is_not_listed_twice(app):
    rows = wa_templates.help_rows([])
    assert rows and len({r['title'].lower() for r in rows}) == len(rows)
    first = rows[0]['title']
    assert first.lower() not in {r['title'].lower() for r in wa_templates.help_rows([first.upper() + ' '])}


def test_a_reply_counts_for_the_owner_or_the_one_who_sent_it(app, cs_user, admin_user):
    crm.ensure_defaults()
    lead = ti_lead(owner_id=cs_user.id) if False else ti_lead()
    lead.owner_id = cs_user.id
    a = CrmAnswer(title='Typed hello', body='Hello {name}, this is {agent}.', product='TI', code='XQ')
    _db.session.add(a)
    _db.session.commit()
    first = (cs_user.first_name or cs_user.username).split()[0]
    assert crm.ready_message_code(lead, 'Hello Ramesh, this is %s.' % first) == 'XQ'
    other = (admin_user.first_name or admin_user.username).split()[0]
    assert crm.ready_message_code(lead, 'Hello Ramesh, this is %s.' % other, user=admin_user) == 'XQ'
    assert crm.ready_message_code(lead, 'Hello Ramesh, this is Somebody Else.') is None
    assert crm.ready_message_code(lead, '') is None


def test_the_type_of_a_reply_gives_it_a_unique_code(app):
    crm.ensure_defaults()
    assert crm.answer_code('', 'GH') is None
    assert crm.answer_code('not-a-kind', 'GH', current='ZZ') == 'ZZ'
    first = crm.answer_code('birthday', 'GH')
    _db.session.add(CrmAnswer(title='bday copy', body='x', product='GH', code=first))
    _db.session.commit()
    second = crm.answer_code('birthday', 'GH')
    assert second and second != first


def test_the_duplicate_title_revision_renames_later_ones_and_is_safe_twice(tmp_path):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations', 'versions',
                        's7crm011_quick_replies.py')
    spec = importlib.util.spec_from_file_location('s7', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.down_revision == 's6crm010'
    engine = sa.create_engine('sqlite:///' + str(tmp_path / 'q.db').replace(os.sep, '/'))
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE crm_answers (id INTEGER PRIMARY KEY, title VARCHAR(160))')
        for t in ('Hello', 'hello ', 'HELLO', 'Hello (2)', 'Other'):
            conn.exec_driver_sql('INSERT INTO crm_answers (title) VALUES (?)', (t,))
        for _ in range(2):
            with Operations.context(MigrationContext.configure(conn)):
                mod.upgrade()
        out = [r[0] for r in conn.exec_driver_sql('SELECT title FROM crm_answers ORDER BY id')]
    assert out[0] == 'Hello' and out[4] == 'Other' and out[3] == 'Hello (2)'
    assert len({t.strip().lower() for t in out}) == 5                       # all different now, the oldest unchanged
    assert out[1].strip().lower() != 'hello' and out[2].lower() != 'hello'


def test_there_is_still_one_alembic_head_after_release_two():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    mig = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations')
    cfg = Config()
    cfg.set_main_option('script_location', mig)
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ['b1mkt033']             # Promotion dashboards, over WhatsApp numbers of our own
    for rev, down in (('b1mkt033', 'a2chan032'), ('a2chan032', 'z1fav031'), ('z1fav031', 'y1side030'), ('y1side030', 'x1rights029'), ('x1rights029', 'w1sec028'), ('w1sec028', 'v3blog027'), ('v3blog027', 'v2blog026'), ('v2blog026', 'v1blog025'), ('v1blog025', 'u8crm024'), ('u8crm024', 'u7crm023'), ('u7crm023', 'u6crm022'), ('u6crm022', 'u5crm021'), ('u5crm021', 'u4crm020'), ('u4crm020', 'u3crm019'), ('u3crm019', 'u2crm018'), ('u2crm018', 'u1crm017'), ('u1crm017', 't5bl016'), ('t5bl016', 't4su015'), ('t4su015', 't3ws014'), ('t3ws014', 't2su013'), ('t2su013', 't1ws012'), ('t1ws012', 's7crm011'), ('s7crm011', 's6crm010'),
                      ('s6crm010', 's5crm009'), ('s5crm009', 's4crm008')):
        assert script.get_revision(rev).down_revision == down


# ======================================================================================= the connection page

def test_drawing_the_connection_page_calls_nothing(app, client, admin_user, monkeypatch):
    for k, v in (('WACRM_URL', 'https://crm.example/crm'), ('WACRM_API_KEY', 'k'), ('WACRM_PORTAL_SECRET', 'x' * 40)):
        monkeypatch.setenv(k, v)

    def boom(*a, **k):
        raise AssertionError('the page called WhatsApp while drawing')
    monkeypatch.setattr(wacrm_team, '_api', boom)
    monkeypatch.setattr(wacrm, '_call', boom)
    login(client, admin_user.email)
    r = client.get('/admin/crm/connection')
    assert r.status_code == 200 and 'crm-connection.js' in r.get_data(as_text=True)


def test_the_live_checks_answer_even_when_whatsapp_is_down(app, client, admin_user, monkeypatch):
    for k, v in (('WACRM_URL', 'https://crm.example/crm'), ('WACRM_API_KEY', 'k'), ('WACRM_PORTAL_SECRET', 'x' * 40)):
        monkeypatch.setenv(k, v)

    def down(*a, **k):
        raise wacrm.WacrmError('down', status=502)
    monkeypatch.setattr(wacrm, 'me', down)
    monkeypatch.setattr(wacrm, 'list_webhooks', down)
    monkeypatch.setattr(wacrm_team, '_api', lambda *a, **k: (_ for _ in ()).throw(wacrm_team.TeamError('down', status=502)))
    login(client, admin_user.email)
    r = client.get('/admin/crm/connection/checks')
    assert r.status_code == 200 and set(r.get_json()) == {'cards', 'rules'}


def test_the_connection_and_automatic_pages_are_for_admins(app, client, cs_user):
    access.ensure_defaults()
    login(client, cs_user.email)
    for url in ('/cs/crm/connection', '/cs/crm/connection/checks', '/cs/crm/automatic'):
        assert client.get(url).status_code in (302, 403, 404), url
    for url in ('/cs/crm/setup/whatsapp', '/cs/crm/connection/retry/1', '/cs/crm/connection/settle/1'):
        assert client.post(url, data={'action': 'mode', 'mode': 'send'}).status_code in (302, 403, 404), url
    assert crm.wa_mode() == 'off'


def test_switching_to_sending_first_says_what_would_go_and_saves_nothing(app, client, admin_user, team):
    crm.save_settings(whatsapp_mode='contacts')
    lead = ti_lead()
    task = lead.open_task
    task.auto, task.channel, task.due_at = True, 'whatsapp', datetime.utcnow() - timedelta(hours=1)
    _db.session.commit()
    assert crm.auto_send_preview() == {'now': 1, 'older': 0}
    login(client, admin_user.email)
    r = client.post('/admin/crm/setup/whatsapp', data={'action': 'mode', 'mode': 'send'})
    assert r.status_code == 200 and 'Yes, switch on sending' in r.get_data(as_text=True)
    assert crm.crm_settings()['whatsapp_mode'] == 'contacts'                     # not switched yet
    client.post('/admin/crm/setup/whatsapp', data={'action': 'mode', 'mode': 'send', 'confirm': '1'})
    assert crm.crm_settings()['whatsapp_mode'] == 'send'


def test_a_follow_up_overdue_by_a_day_is_counted_as_older_not_as_going_now(app):
    lead = ti_lead()
    task = lead.open_task
    task.auto, task.channel, task.due_at = True, 'whatsapp', datetime.utcnow() - timedelta(days=3)
    _db.session.commit()
    assert crm.auto_send_preview() == {'now': 0, 'older': 1}


def test_a_garbage_mode_is_refused(app, client, admin_user):
    login(client, admin_user.email)
    assert client.post('/admin/crm/setup/whatsapp', data={'action': 'mode', 'mode': 'blast'}).status_code == 400
    assert crm.wa_mode() == 'off'


def test_the_consent_setting_is_kept_and_defaults_on(app, client, admin_user, team):
    assert crm.crm_settings()['wa_first_needs_ok'] is True
    login(client, admin_user.email)
    client.post('/admin/crm/setup/whatsapp', data={'action': 'mode', 'mode': 'contacts', 'first_ok_sent': '1'})
    assert crm.crm_settings()['wa_first_needs_ok'] is False
    client.post('/admin/crm/setup/whatsapp', data={'action': 'mode', 'mode': 'contacts', 'first_ok_sent': '1', 'first_ok': '1'})
    assert crm.crm_settings()['wa_first_needs_ok'] is True
    client.post('/admin/crm/setup/whatsapp', data={'action': 'mode', 'mode': 'off'})        # no field sent: untouched
    assert crm.crm_settings()['wa_first_needs_ok'] is True


def stuck(lead, minutes=30):
    task = lead.open_task
    task.status, task.done_at = 'sending', datetime.utcnow() - timedelta(minutes=minutes)
    _db.session.commit()
    return task


def test_a_stuck_follow_up_is_listed_and_a_person_settles_it(app, client, admin_user):
    lead = ti_lead()
    task = stuck(lead)
    assert [t.id for t in crm.stuck_sends()] == [task.id]
    fresh = ti_lead('+919811111111', name='Fresh')
    stuck(fresh, minutes=2)
    assert [t.id for t in crm.stuck_sends()] == [task.id]                        # two minutes is just a slow send
    login(client, admin_user.email)
    client.post('/admin/crm/connection/settle/%d' % task.id, data={'went': '0'})
    t = _db.session.get(CrmTask, task.id)
    assert t.status == 'open' and t.auto is False and t.note == 'Checked: it did not go'
    client.post('/admin/crm/connection/settle/%d' % task.id, data={'went': '1'})      # no longer stuck: no change
    assert _db.session.get(CrmTask, task.id).status == 'open'


def test_settling_as_sent_completes_it_and_a_missing_task_is_a_404(app, client, admin_user):
    task = stuck(ti_lead())
    login(client, admin_user.email)
    client.post('/admin/crm/connection/settle/%d' % task.id, data={'went': '1'})
    assert _db.session.get(CrmTask, task.id).status == 'done'
    assert client.post('/admin/crm/connection/settle/9999', data={'went': '1'}).status_code == 404


def test_a_stuck_step_is_never_sent_by_the_automatic_run(app, team):
    calls, _ = team
    crm.save_settings(whatsapp_mode='send')
    task = stuck(ti_lead())
    task.auto = True
    _db.session.commit()
    crm.run_auto_steps()
    assert _db.session.get(CrmTask, task.id).status == 'sending'


def test_retrying_a_person_only_marks_them_and_says_nothing_when_writes_are_off(app, client, admin_user, team):
    lead = ti_lead()
    calls, _ = team
    login(client, admin_user.email)
    before = len(calls)
    r = client.post('/admin/crm/connection/retry/%d' % lead.person.id, follow_redirects=True)
    assert 'Trying again' in r.get_data(as_text=True) and len(calls) == before          # a mark: no call yet
    crm.save_settings(whatsapp_mode='off')
    r = client.post('/admin/crm/connection/retry/%d' % lead.person.id, follow_redirects=True)
    assert crm.WA_WRITES_OFF in r.get_data(as_text=True)
    assert client.post('/admin/crm/connection/retry/9999').status_code == 404


# ======================================================================================= What goes out by itself

def test_the_automatic_page_draws_for_admins_with_nothing_set_up(app, client, admin_user):
    crm.ensure_defaults()
    login(client, admin_user.email)
    r = client.get('/admin/crm/automatic')
    assert r.status_code == 200 and 'What goes out by itself' in r.get_data(as_text=True)


def test_a_reply_rule_that_sends_on_a_sales_tag_is_flagged(app):
    crm.ensure_defaults()
    mine = 'ti'                                  # a product tag is the Sales CRM's
    assert crm.is_sales_tag('TI: Prospect') and crm.is_sales_tag(mine) and not crm.is_sales_tag('vip')
    flagged = crm.rule_conflicts([{'id': 1, 'name': 'Welcome', 'active': True, 'trigger_type': 'tag_added',
                                   'trigger_tags': [mine], 'sends': True},
                                  {'id': 2, 'name': 'Paused', 'active': False, 'trigger_type': 'tag_added',
                                   'trigger_tags': [mine], 'sends': True},
                                  {'id': 3, 'name': 'Other tag', 'active': True, 'trigger_type': 'tag_added',
                                   'trigger_tags': ['vip'], 'sends': True},
                                  {'id': 4, 'name': 'No send', 'active': True, 'trigger_type': 'tag_added',
                                   'trigger_tags': [mine], 'sends': False}])
    assert [c['name'] for c in flagged] == ['Welcome']
    assert crm.rule_strip([]) == '' and 'Welcome' in crm.rule_strip(flagged)
    many = [{'id': str(i), 'name': 'R%d' % i, 'why': 'x'} for i in range(5)]
    assert '…' in crm.rule_strip(many) and '5' in crm.rule_strip(many)


# ======================================================================================= Results

def test_results_draws_with_every_filter_and_junk_filters(app, client, admin_user, cs_user):
    lead = ti_lead()
    crm.mark_event(lead, 'Q')
    login(client, admin_user.email)
    for q in ('', '?days=7', '?days=90', '?days=5', '?days=abc', '?who=%d' % cs_user.id, '?who=99999',
              '?pipeline=1', '?pipeline=x', '?days=30&pipeline=1&who=%d' % cs_user.id):
        r = client.get('/admin/crm/insights' + q)
        assert r.status_code == 200, q
    page = client.get('/admin/crm/insights').get_data(as_text=True)
    assert 'Log today' not in page and 'Leads that came in these days' in page


def test_results_is_not_for_agents(app, client, cs_user):
    access.ensure_defaults()
    login(client, cs_user.email)
    assert client.get('/cs/crm/insights').status_code in (302, 403, 404)


def test_the_log_work_form_comes_back_to_my_day(app, client, cs_user):
    access.ensure_defaults()
    login(client, cs_user.email)
    r = client.post('/cs/crm/insights/log', data={'day': 'garbage'})
    assert r.status_code == 302 and '/today' in r.headers['Location']


def test_every_result_number_has_a_definition(app):
    from app.services import crm_metrics
    for key in ('funnel', 'sources', 'campaigns', 'by_sender', 'milestones', 'lost'):
        assert crm_metrics.DEFINITIONS.get(key)


def test_results_cards_count_only_this_period_and_this_person(app, cs_user, admin_user):
    from app.services import crm_results
    lead = ti_lead()
    lead.owner_id = cs_user.id
    _db.session.commit()
    now = datetime.utcnow()
    mine = crm_results.counts(now - timedelta(days=1), now + timedelta(days=1), None, cs_user.id)
    theirs = crm_results.counts(now - timedelta(days=1), now + timedelta(days=1), None, admin_user.id)
    past = crm_results.counts(now - timedelta(days=40), now - timedelta(days=30), None, cs_user.id)
    assert sum(v for v in mine.values() if isinstance(v, (int, float))) > sum(v for v in theirs.values() if isinstance(v, (int, float)))
    assert sum(v for v in past.values() if isinstance(v, (int, float))) == 0
