"""The staff menu as a rail of work areas (2026-10-26): every area an icon, only the area being worked in shows its
lines beside it; an area of one line is a link; Help and the Set-up gear sit apart, and Set-up opens one group at a
time; the "+" button offers only what the person's role allows. Who sees which page is tests/test_crm_menu.py."""
import re

from conftest import login, make_user


def _qc_end(html):
    """Where the + menu ends: the star ("This page") comes next in the header."""
    start = html.index('id="qcDD"')
    return html.index('id="favDD"', start) if 'id="favDD"' in html[start:] else html.index('<!-- Notifications -->', start)


def test_the_rail_has_every_section_and_lights_the_one_worked_in(app, client, admin_user):
    login(client, admin_user.email)
    html = client.get('/admin/health').get_data(as_text=True)
    tabs = re.findall(r'data-area-(?:tab|link)="([a-z_0-9]+)"', html)
    groups = re.findall(r'class="sn-group[^"]*" data-group="([a-z_0-9]+)"', html)
    # ★ Favourites first (2026-10-27, routes/favourites.py), then the work areas
    assert tabs == groups == ['fav', 'home', 'inbox', 'leads', 'contacts', 'tasks', 'services', 'reports', 'content',
                              'automate', 'help', 'setup']
    assert re.search(r'class="sn-tab on" data-area-tab="home"', html)
    assert re.search(r'class="sn-group[^"]*current[^"]*" data-group="home"', html)
    assert len(re.findall(r'class="sn-group[^"]*current', html)) == 1
    # one line: a link straight to it; Help and the gear apart at the bottom
    assert re.search(r'<a class="sn-tab" href="/admin/crm/contacts" data-area-link="contacts"', html)
    assert re.findall(r'data-area-(?:tab|link)="([a-z]+)"[^>]*data-low', html) == ['help', 'setup']
    # a set-up page lights the gear, with only its own group open
    html = client.get('/admin/crm/integrations').get_data(as_text=True)
    assert re.search(r'class="sn-tab on" data-area-tab="setup"', html)
    setup = html.split('data-group="setup"', 1)[1].split('sn-none', 1)[0]
    assert 'data-one-open' in html.split('data-group="setup"', 1)[1][:40]
    assert re.findall(r'class="sn-sub open" data-sub="([a-z.]+)"', setup) == ['setup.channels']


def test_the_plus_button_offers_what_the_role_allows(app, client, admin_user):
    login(client, admin_user.email)
    html = client.get('/admin/health').get_data(as_text=True)
    menu = html[html.index('id="qcDD"'):_qc_end(html)]
    for word in ('Lead', 'Companion post', 'Blog post', 'Import a list'):
        assert word in menu, word
    agent = make_user('agent@test.com', 'agent', role='cs')
    c = app.test_client()
    login(c, agent.email)
    html = c.get('/cs/').get_data(as_text=True)
    if 'id="qcDD"' in html:
        menu = html[html.index('id="qcDD"'):_qc_end(html)]
        assert 'Blog post' not in menu and 'Import a list' not in menu
