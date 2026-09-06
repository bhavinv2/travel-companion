"""CS and admin accounts live in their consoles: no traveller screens, no traveller navigation."""
from conftest import login, logout


def test_staff_land_on_their_console_after_login(client, cs_user, admin_user, user):
    assert login(client, 'cs@test.com').headers['Location'].endswith('/cs/')
    logout(client)
    assert login(client, 'admin@test.com').headers['Location'].endswith('/admin/')
    logout(client)
    assert login(client, 'bob@test.com').headers['Location'].endswith('/')


def test_traveller_screens_redirect_staff_to_console(client, cs_user, admin_user):
    login(client, 'cs@test.com')
    for path in ('/', '/trips', '/dashboard', '/connections', '/inbox'):
        r = client.get(path)
        assert r.status_code == 302 and r.headers['Location'].endswith('/cs/'), path
    assert client.get('/cs/').status_code == 200
    assert client.get('/settings/notifications').status_code == 200      # their own prefs still reachable
    logout(client)
    login(client, 'admin@test.com')
    assert client.get('/').headers['Location'].endswith('/admin/')
    assert client.get('/dashboard').headers['Location'].endswith('/admin/')
    assert client.get('/cs/').status_code == 200 and client.get('/admin/').status_code == 200
    # logged-in traveller pages keep working for everybody else
    logout(client)
    assert client.get('/').status_code == 200


def test_staff_navbar_has_no_traveller_links(client, cs_user, admin_user, user):
    login(client, 'cs@test.com')
    html = client.get('/cs/').data.decode()
    assert 'CS Console' in html and 'Match Queue' in html and 'staff-tag' in html
    for traveller_bit in ('All Trips', 'How It Works', 'My Dashboard', 'My Connections', 'id="chatSidebar"',
                          'lang-dd', 'Public view', 'portal-switch'):
        assert traveller_bit not in html, traveller_bit
    logout(client)
    login(client, 'admin@test.com')
    html = client.get('/admin/').data.decode()
    # admins flip between the two portals with one segmented switch, not duplicated menu items
    assert 'portal-switch' in html and 'CS Console' in html
    assert html.count('aria-checked="true"') == 1 and 'fa-gauge"></i> <span>Admin</span></a>' in html
    cs_html = client.get('/cs/').data.decode()
    assert 'portal-switch' in cs_html
    assert 'All Trips' not in html and 'id="chatSidebar"' not in html
    logout(client)
    login(client, 'bob@test.com')
    html = client.get('/dashboard').data.decode()
    assert 'All Trips' in html and 'My Connections' in html and 'id="chatSidebar"' in html
    assert 'staff-tag' not in html and 'CS Console' not in html
