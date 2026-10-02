"""Per-agent CS console access.

The console covers three products plus its own tools and not every agent works on all of them.
What is protected here is mostly that hiding a link is NOT access control: the URL is still there,
and a bookmark or a colleague's pasted link reaches it, so every check below opens the address
directly rather than looking for a menu entry.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import login, logout  # noqa: E402
from app import db as _db  # noqa: E402
from app.models import User  # noqa: E402
from app.services import cs_access  # noqa: E402


@pytest.fixture()
def agent(app, db, cs_user):
    return User.query.filter_by(email='cs@test.com').one()


def restrict(agent, *keys):
    agent.cs_access = list(keys)
    _db.session.commit()


# ---------------------------------------------------------------------------
# The default: nothing changes for anybody
# ---------------------------------------------------------------------------

def test_an_agent_is_unrestricted_until_somebody_says_otherwise(client, db, agent):
    """Null means all of it. Every existing agent has null, so shipping this changes nobody's
    access on the day it runs, and a new hire can start before an admin gets to them."""
    assert agent.cs_access is None
    assert cs_access.allowed_keys(agent) is None

    login(client, 'cs@test.com')
    for path in ('/cs/', '/cs/posts', '/cs/insurance-quotes', '/cs/sahayak'):
        assert client.get(path).status_code == 200, path


def test_the_scraper_stays_admin_only_by_default(client, db, agent):
    """It was admin-only before this feature. Folding it into "everything" would hand every agent
    a tool they have never had."""
    assert cs_access.can_open(agent, 'scraper') is False
    assert 'scraper' not in [s['key'] for s in cs_access.screens_for(agent)]

    restrict(agent, 'home', 'scraper')          # ...unless an admin grants it
    assert cs_access.can_open(agent, 'scraper') is True


# ---------------------------------------------------------------------------
# Restricting
# ---------------------------------------------------------------------------

def test_a_screen_not_granted_is_refused_at_the_url(client, db, agent):
    restrict(agent, 'home', 'insurance')
    login(client, 'cs@test.com')

    assert client.get('/cs/insurance-quotes').status_code == 200
    r = client.get('/cs/posts')
    assert r.status_code == 302, 'the menu hid it; the door has to refuse it too'
    assert '/cs' in r.headers['Location']


def test_sub_routes_are_refused_too(client, db, agent):
    """"All posts" is not one endpoint -- it is the list, the detail page, the editor and the
    rest. Granting by menu entry alone would leave the useful half of a screen wide open."""
    restrict(agent, 'home')
    login(client, 'cs@test.com')
    for path in ('/cs/posts', '/cs/posts/new', '/cs/matches', '/cs/import'):
        r = client.get(path)
        assert r.status_code in (302, 404), path
        if r.status_code == 302:
            assert '/cs' in r.headers['Location'] or '/auth' not in r.headers['Location']


def test_the_menu_shows_only_what_was_granted(client, db, agent):
    restrict(agent, 'home', 'insurance')
    login(client, 'cs@test.com')
    html = client.get('/cs/').data.decode()
    sidebar = html.split('admin-sidebar', 1)[1].split('</aside>', 1)[0]

    assert 'Insurance leads' in sidebar
    for gone in ('All posts', 'Match queue', 'Sahayak queue', 'Import'):
        assert gone not in sidebar, gone


def test_the_navbar_does_not_offer_screens_they_cannot_open(client, db, agent):
    """A link that answers "not for you" is worse than no link."""
    restrict(agent, 'home', 'insurance')
    login(client, 'cs@test.com')
    nav = client.get('/cs/').data.decode().split('nav-links', 1)[1].split('</ul>', 1)[0]
    for gone in ('Match Queue', 'New Post', 'Import'):
        assert gone not in nav, gone


def test_an_unclaimed_endpoint_is_allowed(app, agent):
    """A route added tomorrow should not vanish for restricted agents before anyone has decided
    where it belongs."""
    restrict(agent, 'home')
    assert cs_access.can_open_endpoint(agent, 'main.index') is True
    assert cs_access.can_open_endpoint(agent, 'cs.posts') is False


# ---------------------------------------------------------------------------
# Who it applies to
# ---------------------------------------------------------------------------

def test_admins_are_never_restricted(client, db, admin_user):
    admin = User.query.filter_by(email='admin@test.com').one()
    admin.cs_access = ['home']              # even if something wrote one
    _db.session.commit()

    assert cs_access.applies_to(admin) is False
    assert cs_access.allowed_keys(admin) is None
    login(client, 'admin@test.com')
    assert client.get('/cs/posts').status_code == 200


# ---------------------------------------------------------------------------
# The admin screen
# ---------------------------------------------------------------------------

def test_an_admin_can_narrow_and_restore_an_agent(client, db, admin_user, agent):
    login(client, 'admin@test.com')

    client.post('/admin/users/%d/cs-access' % agent.id,
                data={'mode': 'some', 'screen': ['home', 'insurance']})
    assert User.query.get(agent.id).cs_access == ['home', 'insurance']

    client.post('/admin/users/%d/cs-access' % agent.id, data={'mode': 'all'})
    assert User.query.get(agent.id).cs_access is None


def test_unknown_screen_keys_are_not_stored(client, db, admin_user, agent):
    """The stored list is replayed into a permission check, so a typo must not become a rule."""
    login(client, 'admin@test.com')
    client.post('/admin/users/%d/cs-access' % agent.id,
                data={'mode': 'some', 'screen': ['home', 'made-up', 'insurance']})
    assert User.query.get(agent.id).cs_access == ['home', 'insurance']


def test_only_an_admin_can_change_access(client, db, agent):
    login(client, 'cs@test.com')
    r = client.post('/admin/users/%d/cs-access' % agent.id, data={'mode': 'some', 'screen': ['home']})
    assert r.status_code in (302, 403)
    assert User.query.get(agent.id).cs_access is None


def test_the_screen_is_offered_for_agents_only(client, db, admin_user, agent, other_user):
    login(client, 'admin@test.com')
    html = client.get('/admin/users').data.decode()
    assert '/admin/users/%d/cs-access' % agent.id in html

    traveller = User.query.filter_by(email='alice@test.com').one()
    assert '/admin/users/%d/cs-access' % traveller.id not in html


# ---------------------------------------------------------------------------
# And the notifications about those screens
# ---------------------------------------------------------------------------

def test_an_agent_is_only_told_about_screens_they_have(client, db, admin_user):
    """A notification is an instruction to go and look. Every agent used to get every one of
    them, including the ones whose link 403s for them."""
    from app.models import User, Notification
    from app import db as _db

    narrow = User(username='sahayak_only', email='sk@test.com', role='cs', is_active=True)
    narrow.set_password('x')
    narrow.cs_access = ['home', 'sahayak']
    wide = User(username='voices_agent', email='va@test.com', role='cs', is_active=True)
    wide.set_password('x')
    wide.cs_access = ['home', 'voices']
    _db.session.add_all([narrow, wide])
    _db.session.commit()

    client.post('/contact-us', data={
        'name': 'Asha', 'email': 'asha@example.com', 'phone': '917 900 5094',
        'phone_cc': 'US', 'message': 'Please call me back about this.'}, follow_redirects=True)

    told = {n.user_id for n in Notification.query.filter_by(type='cs_escalation').all()}
    assert wide.id in told, 'the agent who answers these should hear about it'
    assert narrow.id not in told, 'the Sahayak desk should not'
    assert admin_user.id in told, 'admins are never restricted'


def test_an_agent_with_no_limits_set_hears_everything(client, db, cs_user):
    """Null means unrestricted, which is still the default and still everybody today."""
    from app.models import Notification
    assert cs_user.cs_access is None
    client.post('/contact-us', data={
        'name': 'Asha', 'email': 'asha@example.com', 'phone': '917 900 5094',
        'phone_cc': 'US', 'message': 'Please call me back about this.'}, follow_redirects=True)
    assert Notification.query.filter_by(user_id=cs_user.id, type='cs_escalation').count() == 1


def test_recipients_is_the_one_place_that_decides(app, db, cs_user):
    from app.services import cs_access
    assert cs_user in cs_access.recipients('voices')
    cs_user.cs_access = ['home']
    assert cs_user not in cs_access.recipients('voices')
    assert cs_user in cs_access.recipients('home', 'voices'), 'any one of them is enough'
