"""Post-login portal chooser for multi-role accounts + footer Admin Login removal."""
from app import db
from app.models import User


def make(email, username, roles, password='password123'):
    u = User(email=email, username=username, first_name=username.title())
    u.set_password(password)
    u.set_roles(roles)
    db.session.add(u)
    db.session.commit()
    return u


def login(client, email, password='password123'):
    return client.post('/auth/login', data={'email': email, 'password': password})


def test_multi_role_login_shows_chooser(client, app):
    make('multi@test.com', 'multi', ['user', 'cs', 'admin'])
    r = login(client, 'multi@test.com')
    assert r.status_code == 302 and r.headers['Location'].endswith('/auth/choose-portal')
    html = client.get('/auth/choose-portal').data.decode()
    assert 'Traveller' in html and 'CS Console' in html and 'Admin Panel' in html


def test_two_role_account_sees_only_its_portals(client, app):
    make('duo@test.com', 'duo', ['user', 'cs'])
    login(client, 'duo@test.com')
    html = client.get('/auth/choose-portal').data.decode()
    assert 'Traveller' in html and 'CS Console' in html and 'Admin Panel' not in html


def test_choose_cs_lands_console(client, app):
    make('multi2@test.com', 'multi2', ['user', 'cs', 'admin'])
    login(client, 'multi2@test.com')
    r = client.get('/auth/choose-portal?to=cs')
    assert r.status_code == 302 and r.headers['Location'].endswith('/cs/')


def test_choose_traveller_sets_view(client, app):
    make('multi3@test.com', 'multi3', ['user', 'admin'])
    login(client, 'multi3@test.com')
    r = client.get('/auth/choose-portal?to=traveller')
    assert r.status_code == 302 and r.headers['Location'].endswith('/dashboard')
    assert client.get('/dashboard').status_code == 200     # not bounced back to a console


def test_choose_admin_lands_admin(client, app):
    make('multi4@test.com', 'multi4', ['user', 'admin'])
    login(client, 'multi4@test.com')
    r = client.get('/auth/choose-portal?to=admin')
    assert r.status_code == 302 and '/admin' in r.headers['Location']


def test_single_role_login_skips_chooser(client, user):
    r = login(client, 'bob@test.com')
    assert r.status_code == 302 and not r.headers['Location'].endswith('/auth/choose-portal')


def test_chooser_guards_unheld_roles(client, cs_user):
    login(client, 'cs@test.com')
    r = client.get('/auth/choose-portal?to=admin')          # cs-only: admin denied
    assert r.status_code == 302 and '/admin' not in r.headers['Location']


def test_next_param_wins_over_chooser(client, app):
    make('multi5@test.com', 'multi5', ['user', 'cs'])
    r = client.post('/auth/login?next=/trips', data={'email': 'multi5@test.com', 'password': 'password123'})
    assert r.status_code == 302 and r.headers['Location'].endswith('/trips')


def test_footer_admin_login_link_removed(client):
    assert 'Admin Login' not in client.get('/').data.decode()
