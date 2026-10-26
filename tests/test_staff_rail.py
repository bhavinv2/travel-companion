"""The staff menu as a rail of sections (2026-10-26): every section an icon, only the section being worked in shows
its lines beside it; the "+" button offers only what the person's role allows. The pages and who sees them are
unchanged (tests/test_crm_menu.py)."""
import re

from conftest import login, make_user


def test_the_rail_has_every_section_and_lights_the_one_worked_in(app, client, admin_user):
    login(client, admin_user.email)
    html = client.get('/admin/health').get_data(as_text=True)
    tabs = re.findall(r'data-area-tab="([a-z_0-9]+)"', html)
    groups = re.findall(r'class="sn-group[^"]*" data-group="([a-z_0-9]+)"', html)
    assert tabs == groups and 'overview' in tabs and 'sales' in tabs and 'team' in tabs
    assert re.search(r'class="sn-tab on" data-area-tab="overview"', html)
    assert re.search(r'class="sn-group[^"]*current[^"]*" data-group="overview"', html)
    assert len(re.findall(r'class="sn-group[^"]*current', html)) == 1
    # a Sales CRM page lights Sales CRM, and the long names are short on the rail
    html = client.get('/admin/crm/integrations').get_data(as_text=True)
    assert re.search(r'class="sn-tab on" data-area-tab="sales"', html)
    assert '<span>Companion</span>' in html and '<span>Travel Companion</span>' in html


def test_the_plus_button_offers_what_the_role_allows(app, client, admin_user):
    login(client, admin_user.email)
    html = client.get('/admin/health').get_data(as_text=True)
    menu = html[html.index('id="qcDD"'):html.index('<!-- Notifications -->', html.index('id="qcDD"'))]
    for word in ('Lead', 'Companion post', 'Blog post', 'Import a list'):
        assert word in menu, word
    agent = make_user('agent@test.com', 'agent', role='cs')
    c = app.test_client()
    login(c, agent.email)
    html = c.get('/cs/').get_data(as_text=True)
    if 'id="qcDD"' in html:
        menu = html[html.index('id="qcDD"'):html.index('<!-- Notifications -->', html.index('id="qcDD"'))]
        assert 'Blog post' not in menu and 'Import a list' not in menu
