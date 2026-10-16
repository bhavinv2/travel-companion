"""CS and admin accounts live in their consoles: no traveller screens, no traveller navigation."""
from conftest import login, logout


def test_staff_land_on_their_console_after_login(client, cs_user, admin_user, user):
    assert login(client, 'cs@test.com').headers['Location'].endswith('/cs/crm/today')   # U2: staff start on My day
    logout(client)
    assert login(client, 'admin@test.com').headers['Location'].endswith('/admin/crm/insights')   # U2: site owners start on Results
    logout(client)
    assert login(client, 'bob@test.com').headers['Location'].endswith('/')


def test_traveller_screens_redirect_staff_to_console(client, cs_user, admin_user):
    login(client, 'cs@test.com')
    for path in ('/', '/trips', '/dashboard', '/connections', '/inbox'):
        r = client.get(path)
        assert r.status_code == 302 and r.headers['Location'].endswith('/cs/crm/today'), path
    assert client.get('/cs/').status_code == 200
    assert client.get('/settings/notifications').status_code == 200      # their own prefs still reachable
    logout(client)
    login(client, 'admin@test.com')
    assert client.get('/').headers['Location'].endswith('/admin/crm/insights')
    assert client.get('/dashboard').headers['Location'].endswith('/admin/crm/insights')
    assert client.get('/cs/').status_code == 200 and client.get('/admin/').status_code == 200
    # logged-in traveller pages keep working for everybody else
    logout(client)
    assert client.get('/').status_code == 200


def test_staff_navbar_has_no_traveller_links(client, cs_user, admin_user, user):
    login(client, 'cs@test.com')
    html = client.get('/cs/crm/today').data.decode()
    # the console's screens are in the menu on the left (Match queue among them), not repeated up top
    assert 'CS Console' in html and 'Match queue' in html and 'staff-tag' in html
    assert 'Match Queue' not in html.split('nav-links', 1)[1].split('</ul>', 1)[0]
    for traveller_bit in ('Desis on Move', 'How It Works', 'My Dashboard', 'My Connections', 'id="chatSidebar"',
                          'lang-dd', 'Public view', 'portal-switch'):
        assert traveller_bit not in html, traveller_bit
    logout(client)
    login(client, 'admin@test.com')
    html = client.get('/admin/').data.decode()
    # U2: one staff menu for everybody; the Website / Staff switch is only for an account that is both
    assert 'Desis on Move' not in html and 'id="chatSidebar"' not in html and 'admin-nav-items' in html
    assert 'portal-switch' not in html
    assert client.get('/cs/').status_code == 200
    logout(client)
    login(client, 'bob@test.com')
    html = client.get('/dashboard').data.decode()
    assert 'Desis on Move' in html and 'My Connections' in html and 'id="chatSidebar"' in html
    assert 'staff-tag' not in html and 'CS Console' not in html
