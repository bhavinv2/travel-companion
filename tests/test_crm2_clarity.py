"""Sales CRM 2.0, phase 0 -- the clarity pass.

    menu     fewer lines, no Help section; the screens that lost their line are tabs of a host line
    tabs     the strip shows only the tabs a person may open; a role holding one tab sees the host line
    words    codes (Q, PLS, TI #3 ...) and "fell out" are words on screen; the stored data keeps its codes
    board    compact cards, "Show N more", the cap note
    results  two "won" numbers named apart, and one Excel download that is what the screen shows
"""
import json
import re
from datetime import datetime, timedelta

from conftest import login
from app import db as _db
from app.models import CrmLead, CrmPipeline, CrmTask, WorkspaceMember, WorkspaceRole
from app.services import access, crm, crm_words

from test_crm_wa_sync_engine import ti_lead


def give_role(ws, user, pages):
    r = WorkspaceRole(workspace_id=ws.id, name='Only ' + ' '.join(pages), pages=pages)
    _db.session.add(r)
    WorkspaceMember.query.filter_by(workspace_id=ws.id, user_id=user.id).one().role = r
    _db.session.commit()
    access._cache().clear()


def words(html):
    """What a person reads: the page without its tags (and so without attributes such as data-code)."""
    return re.sub(r'\s+', ' ', re.sub(r'<script.*?</script>|<style.*?</style>|<[^>]+>', ' ', html, flags=re.S))


def nav_labels(app, user):
    with app.test_request_context('/cs/crm/today'):
        from flask_login import login_user
        login_user(user)
        return {g['key']: [i['label'] for i in g['items']] for g in access.nav(user)}


# ================================================================================================ the menu

def test_the_sales_menu_has_daily_work_and_set_up_only(app, admin_user):
    groups = {g['key']: g for g in _groups(app, admin_user)}
    sales = groups['sales']
    assert [s['label'] for s in sales['subs']] == ['Daily work', 'Set-up']
    assert [i['label'] for i in sales['subs'][0]['items']] == ['My day', 'WhatsApp chats', 'Leads', 'Calendar', 'Contacts']
    assert [i['label'] for i in sales['subs'][1]['items']] == [
        'Pipelines & products', 'Automation', 'Messages', 'Lead sources', 'Targets', 'WhatsApp', 'Import & export']
    overview = [i['label'] for i in groups['overview']['items']]
    # Health opens the menu; the reports are a menu of their own (tests/test_health.py)
    assert overview[0] == 'Health' and 'Sales results' not in overview and 'Team today' not in overview
    assert [i['label'] for i in groups['reports']['items']][:3] == ['Sales results', 'Team today', 'Report builder']


def _groups(app, user):
    with app.test_request_context('/cs/crm/today'):
        from flask_login import login_user
        login_user(user)
        return access.nav(user)


def test_pages_that_lost_their_line_are_not_menu_lines_but_are_still_pages():
    for key in ('crm_flow', 'crm_checks', 'crm_forecast', 'crm_team', 'wa_templates', 'wa_broadcasts', 'wa_tags',
                'wa_automations', 'wa_flows', 'wa_ai', 'wa_settings'):
        assert access.PAGES[key]['nav'] is False and key in access.MENU_ORDER, key
    assert access.PAGES['crm_quick']['label'] == 'Messages'
    assert access.PAGES['crm_auto']['label'] == 'Automation'
    assert access.PAGES['crm_connection']['label'] == 'WhatsApp'


def test_a_host_line_comes_with_its_tab_pages_and_can_still_be_given_on_its_own(app):
    got = access._implied(frozenset({'wa_broadcasts'}))
    assert 'crm_quick' in got
    assert 'crm_auto' in access._implied(frozenset({'wa_ai'}))
    assert 'crm_connection' in access._implied(frozenset({'wa_settings'}))
    assert {'crm_flow', 'crm_process', 'crm_checks'} <= access._implied(frozenset({'crm_today'}))
    # grantable: kept when a role is saved; tabs without a line too; the flow stays never granted on its own
    kept = access.clean_pages(['crm_quick', 'crm_auto', 'crm_connection', 'crm_checks', 'crm_process',
                               'wa_templates', 'wa_settings', 'crm_flow'])
    assert 'crm_flow' not in kept
    assert {'crm_quick', 'crm_auto', 'crm_connection', 'crm_checks', 'crm_process', 'wa_templates',
            'wa_settings'} <= set(kept)


def test_the_roles_screen_offers_the_hosts_and_the_tabs_but_not_the_flow(client, app, admin_user):
    ws = access.ensure_defaults()
    login(client, admin_user.email)
    page = client.get('/admin/workspace/roles/%d' % access.system_role(ws, 'cs').id).get_data(as_text=True)
    for key in ('crm_quick', 'crm_auto', 'crm_connection', 'crm_checks', 'crm_process', 'wa_templates',
                'wa_broadcasts', 'wa_tags', 'wa_automations', 'wa_flows', 'wa_ai', 'wa_settings'):
        assert 'value="%s"' % key in page, key
    assert 'value="crm_flow"' not in page


def test_a_saved_menu_with_the_old_help_section_and_removed_lines_keeps_working():
    layout = access.default_layout()
    layout['sections'] = [s for s in layout['sections'] if s['key'] != 'help']      # saved with the first Help
    layout['sections'].append({'key': 'help', 'label': 'Help', 'icon': 'fa-circle-question',
                               'pages': ['crm_flow', 'crm_process', 'crm_auto']})
    for s in layout['sections']:
        for sub in s.get('subs') or ():
            if sub['key'] == 'daily':
                sub['pages'] += ['crm_checks']
            if sub['key'] == 'setup':
                sub['pages'] += ['wa_tags']
    out = access.clean_layout(json.loads(json.dumps(layout)))
    placed = [k for s in out['sections'] for h in (s.get('subs') or [s]) for k in h['pages']]
    assert sorted(placed) == sorted(access.MENU_PAGES) and len(placed) == len(set(placed))
    assert 'crm_flow' not in placed and 'crm_checks' not in placed and 'wa_tags' not in placed
    assert 'crm_auto' in placed                       # a line that still exists is placed once, wherever it was
    # How we sell is a line again and stays where it was saved; the Help screens the old menu did not place join
    # it, in the order the menu in code has them
    help_ = next(s for s in out['sections'] if s['key'] == 'help')
    assert help_['pages'] == ['guide', 'crm_process', 'metrics', 'help', 'help_insurance', 'help_sahayak']


def test_a_line_new_since_a_menu_was_saved_goes_back_where_the_code_has_it():
    layout = access.default_layout()
    overview = next(s for s in layout['sections'] if s['key'] == 'overview')
    overview['pages'] = [k for k in overview['pages'] if k != 'health']
    out = access.clean_layout(json.loads(json.dumps(layout)))
    assert next(s for s in out['sections'] if s['key'] == 'overview')['pages'][0] == 'health'


def test_an_old_saved_layout_with_the_old_sub_menus_still_draws(app, client, admin_user):
    ws = access.ensure_defaults()
    old = access.default_layout()
    sales = next(s for s in old['sections'] if s['key'] == 'sales')
    sales['subs'] = [{'key': 'messaging', 'label': 'Messaging', 'icon': 'fa-comments', 'pages': ['crm_quick']},
                     {'key': 'setup', 'label': 'Set-up', 'icon': 'fa-sliders', 'pages': ['crm_pipelines']}]
    ws.menu = old
    _db.session.commit()
    login(client, admin_user.email)
    page = client.get('/admin/crm/today').get_data(as_text=True)
    assert 'data-title="Messages"' in page and 'data-title="My day"' in page


def test_home_and_the_first_page_for_an_agent_is_still_my_day(app, cs_user):
    with app.test_request_context('/'):
        from flask_login import login_user
        login_user(cs_user)
        assert access.home_url(cs_user).endswith('/crm/today')


# ================================================================================================ the tabs

def test_a_role_holding_only_broadcasts_sees_messages_and_can_open_broadcasts(client, app, cs_user):
    ws = access.ensure_defaults()
    give_role(ws, cs_user, ['wa_broadcasts'])
    login(client, cs_user.email)
    page = client.get('/cs/', follow_redirects=True).get_data(as_text=True)      # their first line is Messages
    assert 'data-title="Messages"' in page
    assert client.get('/admin/messaging/broadcasts').status_code == 200
    framed = client.get('/admin/messaging/broadcasts').get_data(as_text=True)
    assert 'crm-tabstrip' in framed and 'Broadcasts' in framed
    assert client.get('/admin/messaging/tags', follow_redirects=False).status_code == 302   # not theirs


def test_the_strip_lists_only_the_tabs_the_person_may_open(client, app, cs_user):
    ws = access.ensure_defaults()
    give_role(ws, cs_user, ['crm_quick', 'wa_broadcasts', 'wa_tags'])
    login(client, cs_user.email)
    html = client.get('/cs/crm/quick-replies').get_data(as_text=True)
    strip = html.split('crm-tabstrip', 1)[1].split('</nav>', 1)[0]
    assert 'Quick replies' in strip and 'Broadcasts' in strip and 'Tags' in strip
    assert 'WhatsApp templates' not in strip
    assert 'class="on"' in strip.split('Quick replies', 1)[0][-40:] or 'aria-current' in strip


def test_one_tab_makes_no_strip(client, app, cs_user):
    ws = access.ensure_defaults()
    give_role(ws, cs_user, ['crm_quick'])
    login(client, cs_user.email)
    assert 'crm-tabstrip' not in client.get('/cs/crm/quick-replies').get_data(as_text=True)


def test_every_tab_page_carries_the_strip_for_an_admin(client, app, admin_user):
    login(client, admin_user.email)
    expect = {'/admin/crm/quick-replies': ('Quick replies', 'WhatsApp templates', 'Broadcasts', 'Tags'),
              '/admin/crm/automatic': ('Overview', 'Reply rules', 'Chatbot', 'AI replies'),
              '/admin/crm/connection': ('Connection', 'Number'),
              '/admin/messaging/templates': ('Quick replies', 'WhatsApp templates', 'Broadcasts', 'Tags'),
              '/admin/messaging/automations': ('Overview', 'Reply rules', 'Chatbot', 'AI replies'),
              '/admin/messaging/settings': ('Connection', 'Number')}
    for url, tabs in expect.items():
        r = client.get(url)
        assert r.status_code == 200, url
        strip = r.get_data(as_text=True).split('crm-tabstrip', 1)[1].split('</nav>', 1)[0]
        text = words(strip)
        assert all(t in text for t in tabs), (url, text)


def test_a_tab_lights_its_menu_line(app, admin_user):
    with app.test_request_context('/admin/messaging/broadcasts'):
        from flask import request
        from flask_login import login_user
        login_user(admin_user)
        assert request.endpoint == 'messaging.broadcasts'
        assert access.active_page() == 'crm_quick'
    with app.test_request_context('/admin/crm/flow'):
        login_user(admin_user)
        assert access.active_page() == 'crm_board'


def test_leads_has_a_view_switch_with_flow_and_how_we_sell(client, app, admin_user):
    ti_lead()
    login(client, admin_user.email)
    board = client.get('/admin/crm/?p=ti-standard&view=board&owner=all').get_data(as_text=True)
    seg = board.split('class="seg"', 1)[1].split('</div>', 1)[0]
    assert all(w in seg for w in ('Board', 'List', 'Flow', 'How we sell'))
    for url, on in (('/admin/crm/flow', 'Flow'), ('/admin/crm/process', 'How we sell')):
        html = client.get(url).get_data(as_text=True)
        seg = html.split('class="seg"', 1)[1].split('</div>', 1)[0]
        assert all(w in seg for w in ('Board', 'List', 'Flow', 'How we sell')), url
        assert re.search(r'class="on" href="[^"]*">%s<' % on, seg), url


# ================================================================================================ words

def test_message_codes_have_words():
    assert crm_words.message_word('BW') == 'Birthday wish'
    assert crm_words.message_word('om #2') == 'Festival message'
    assert crm_words.message_word('HJ') == 'Happy journey'
    assert crm_words.message_word('SE') == 'Shift-end message'
    assert crm_words.message_word('TI #3') == 'Follow-up' and crm_words.message_word(None) == 'Follow-up'
    assert crm_words.message_name('TI #3', 'Quote nudge') == 'Quote nudge'
    assert crm_words.message_name('CM', None) == 'Casual check-in'
    assert crm_words.milestone_word('PLS') == 'Payment link sent' and crm_words.milestone_word('Q') == 'Quote sent'
    assert crm_words.reply_word(None) == 'Not replied yet' and crm_words.reply_word('R') == 'Replied'
    assert crm_words.reply_word('DL') == 'Wrong number'


def test_a_source_shows_the_product_name_but_is_stored_with_its_code(app):
    assert crm_words.source_display('TC: trip posted on the site') == 'Travel Companion — trip posted on the site'
    assert crm_words.source_display('TI: quote request') == 'Travel Insurance — quote request'
    assert crm_words.source_display('Facebook ad') == 'Facebook ad'
    assert crm_words.source_display('XX: whatever') == 'XX: whatever'


def test_the_lead_page_team_today_and_results_show_words_not_codes(client, app, admin_user, cs_user):
    lead = ti_lead()
    lead.owner_id = cs_user.id
    crm.log_touch(lead, 'whatsapp', 'out', body='Hello', code='TI #3', user=cs_user, status='sent')
    crm.log_touch(lead, 'system', 'none', body='I sent the quote', code='Q', user=cs_user)
    crm.log_touch(lead, 'system', 'none', body='I sent the payment link', code='PLS', user=cs_user)
    task = CrmTask(lead_id=lead.id, code='TI #3', title='Send the quote', channel='whatsapp', status='done',
                   due_at=datetime.utcnow(), done_at=datetime.utcnow(), done_by_id=cs_user.id, owner_id=cs_user.id)
    _db.session.add(task)
    _db.session.commit()
    login(client, admin_user.email)
    pages = {
        'lead': client.get('/admin/crm/lead/%d' % lead.id).get_data(as_text=True),
        'tracker': client.get('/admin/crm/tracker?who=%d' % cs_user.id).get_data(as_text=True),
        'results': client.get('/admin/crm/insights?days=7').get_data(as_text=True),
    }
    for name, html in pages.items():
        text = words(html)
        assert not re.search(r'\bPLS\b|\bTI #|\bQ\b', text), (name, re.findall(r'.{20}(?:PLS|TI #|\bQ\b).{20}', text))
    assert 'Quote sent' in words(pages['results']) and 'Payment link sent' in words(pages['results'])
    assert 'Travel insurance site · Search quote' in words(pages['lead'])   # renamed by crm_sources.tidy
    tracker = words(pages['tracker'])
    assert 'Send the quote' in tracker and 'Did: Send the quote' in tracker
    sent = ('Sent ' + crm_words.step_titles()['TI #3'].lower() + ' on WhatsApp')      # the step's own title, not its code
    assert sent in tracker, tracker[tracker.find('Hour by hour'):][:400]


def test_the_replies_line_and_the_dot_use_words(client, app, admin_user):
    lead = ti_lead()
    login(client, admin_user.email)
    text = words(client.get('/admin/crm/lead/%d' % lead.id).get_data(as_text=True))
    assert 'Not replied yet' in text
    lead.temperature = 'R'
    _db.session.commit()
    text = words(client.get('/admin/crm/lead/%d' % lead.id).get_data(as_text=True))
    assert 'Replied' in text and 'Zombie' not in text


def test_lost_is_the_one_word_on_screens(app):
    from app.services import crm_kpi, crm_reports
    assert crm.ROLE_LABELS['lost'] == 'Lost'
    assert ('lost', 'Lost') in crm_reports.METRICS
    labels = [row[1] for _, rows in crm_kpi.GROUPS for row in rows]
    assert not [l for l in labels if 'allout' in l]
    # a stage's own name is the admins': the seeded 'Prospect fallout' stage keeps it
    crm.ensure_defaults()
    names = [s.name for p in CrmPipeline.query for s in p.stages]
    assert 'Prospect fallout' in names


# ================================================================================================ the board

def _many_leads(n):
    crm.ensure_defaults()
    for i in range(n):
        crm.capture('ti-quote', name='Lead %d' % i, phone='+9198001%05d' % i, utm={}, notify=False, plan=False,
                    sync=False)


def test_a_long_column_shows_twenty_and_a_button_for_the_rest(client, app, admin_user):
    _many_leads(65)
    login(client, admin_user.email)
    html = client.get('/admin/crm/?p=ti-standard&view=board&owner=all').get_data(as_text=True)
    assert html.count('data-extra') == 40                                  # 60 shown by the server, 20 at first
    assert 'Show 40 more' in words(html)
    assert 'Showing 60 of 65' in words(html) and 'use List for all' in words(html)
    assert 'data-col-value' in html                                        # room for the column's value (phase 1)


def test_a_short_column_has_no_button_and_no_cap_note(client, app, admin_user):
    _many_leads(12)
    login(client, admin_user.email)
    html = client.get('/admin/crm/?p=ti-standard&view=board&owner=all').get_data(as_text=True)
    # no "Show 8 more" (the filter panel's "Show leads" button and "Show all" are not that)
    assert 'data-extra' not in html and 'Show ' not in words(html).replace('Show all', '').replace('Show leads', '')
    assert 'Showing 12 of' not in words(html)


def test_the_card_is_compact_late_is_one_small_badge(client, app, admin_user):
    a = ti_lead(phone='+919800000771', name='Late Lena')
    b = ti_lead(phone='+919800000772', name='On Time')
    for l in (a, b):
        l.owner_id = admin_user.id
        _db.session.query(CrmTask).filter_by(lead_id=l.id).delete()
    _db.session.add(CrmTask(lead_id=a.id, title='Call about the quote', channel='call',
                            due_at=datetime.utcnow() - timedelta(hours=5)))
    _db.session.add(CrmTask(lead_id=b.id, title='Send the brochure', channel='whatsapp',
                            due_at=datetime.utcnow() + timedelta(hours=5)))
    a.entered_stage_at = datetime.utcnow() - timedelta(days=3, hours=2)
    _db.session.commit()
    login(client, admin_user.email)
    html = client.get('/admin/crm/?p=ti-standard&view=board&owner=all').get_data(as_text=True)
    assert html.count('class="late-badge"') == 1
    assert 'title="Was due ' in html
    text = words(html)
    assert 'Call about the quote' in text and 'Send the brochure' in text
    assert 'was due' not in text.lower().replace('title', '')              # no long red line on the card
    assert re.search(r'\b3 d\b', text)                                     # age in the stage


# ================================================================================================ results

def test_results_names_its_two_won_numbers_apart(client, app, admin_user):
    ti_lead()
    login(client, admin_user.email)
    html = client.get('/admin/crm/insights?days=7').get_data(as_text=True)
    text = words(html)
    assert 'Won in these days' in text and 'Customers won' not in text
    assert 'Leads that came in these days' in text and '…and how far each one got' in text
    assert 'Won so far' in text and 'From lead to customer' not in text and 'Won (customer)' not in text
    assert 'Leads marked Won between these dates, whenever they came in.' in html
    assert 'Of the leads that came in these days, how many are won by now.' in html
    assert 'Download for Excel' in text and 'Download per person' in text
    for lost in ('Fell out', 'fallout', 'Fallout'):
        assert lost not in text.replace('Prospect fallout', ''), lost


def test_the_excel_download_is_what_the_screen_shows(client, app, admin_user, cs_user):
    lead = ti_lead()
    lead.owner_id = cs_user.id
    crm.log_touch(lead, 'system', 'none', body='I sent the quote', code='Q', user=cs_user)
    _db.session.commit()
    login(client, admin_user.email)
    r = client.get('/admin/crm/insights.csv?days=7')
    assert r.status_code == 200 and r.headers['Content-Type'].startswith('text/csv')
    body = r.get_data(as_text=True)
    for want in ('Sales results', 'Won in these days', 'New leads', 'Replied', 'Quoted', 'First contact time',
                 'Customers waiting now', 'Change %', 'Leads that came in these days, and how far each one got',
                 'Won so far', 'Where customers come from', 'Travel insurance site · Search quote',
                 'Messages, by who sent them', 'Quotes and payment links', 'Quote sent', 'Payment link sent',
                 'Why we lost leads', 'Day by day'):
        assert want in body, want
    narrowed = client.get('/admin/crm/insights.csv?days=30&who=%d' % cs_user.id).get_data(as_text=True)
    assert 'Whose numbers,' in narrowed and cs_user.full_name in narrowed and 'Days,30' in narrowed
    people = client.get('/admin/crm/insights-people.csv?days=7')
    assert people.status_code == 200 and b'Messages sent' in people.data and b'Person' in people.data


def test_the_download_is_for_the_same_people_as_before(client, app, cs_user):
    login(client, cs_user.email)
    for url in ('/cs/crm/insights.csv', '/cs/crm/insights-people.csv'):
        assert client.get(url).status_code in (302, 403)
