"""Google Ads conversion tracking on the travel-insurance page.

Four conversion actions, one tag, and a set of rules about when none of it loads. The rules are
what these tests are for: a conversion report is a number somebody makes a spending decision on,
and the ways it goes wrong are all quiet ones -- a pixel firing from a developer's laptop, a
label that was never filled in, a tag left running on a fork.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import ads  # noqa: E402


LIVE = {'HTTP_HOST': 'nriparentservice.com'}


@pytest.fixture()
def live(app):
    """A request that looks like production.

    Two things have to change together: tracking is off in TESTING, which is right for every other
    test in the suite and useless for this one, and the suite pins SERVER_NAME to localhost --
    both the host these rules reject and the only host Flask will route.
    """
    app.config['TESTING'] = False
    app.config['SERVER_NAME'] = 'nriparentservice.com'
    yield
    app.config['TESTING'] = True
    app.config['SERVER_NAME'] = 'localhost'


# ---------------------------------------------------------------------------
# When it does not load
# ---------------------------------------------------------------------------

def test_nothing_loads_on_localhost(app, live):
    """A developer filling in the form all afternoon would report an afternoon of conversions."""
    with app.test_request_context('/travel-insurance', environ_overrides={'HTTP_HOST': '127.0.0.1:8080'}):
        assert ads.enabled() is False
        assert ads.conversions() == {}
    with app.test_request_context('/travel-insurance', environ_overrides={'HTTP_HOST': 'localhost:5000'}):
        assert ads.enabled() is False


def test_nothing_loads_in_tests(app):
    """Otherwise the suite reports conversions every time it renders the page."""
    with app.test_request_context('/travel-insurance', environ_overrides=LIVE):
        assert app.config['TESTING'] is True
        assert ads.enabled() is False


def test_unsetting_the_account_switches_everything_off(app, live, monkeypatch):
    """The documented off switch, and what makes a fork or a staging copy silent."""
    monkeypatch.setenv('GOOGLE_ADS_ID', '')
    with app.test_request_context('/travel-insurance', environ_overrides=LIVE):
        assert ads.enabled() is False
        assert ads.conversions() == {}


def test_a_page_without_tracking_carries_no_tag_at_all(client, db):
    html = client.get('/travel-insurance').data.decode()
    assert 'googletagmanager.com' not in html
    assert 'AW-' not in html
    assert '"conversions": {}' in html or "'conversions': {}" in html or '"conversions":{}' in html


# ---------------------------------------------------------------------------
# When it does
# ---------------------------------------------------------------------------

def test_the_four_actions_are_sent_ready_to_use(app, live):
    """Joined here rather than in the browser: a half-built id is exactly the kind of thing that
    fails silently in an ad account for a month."""
    with app.test_request_context('/travel-insurance', environ_overrides=LIVE):
        conv = ads.conversions()
        assert set(conv) == {'quote', 'popup_lead', 'expert_form', 'whatsapp'}
        assert conv['quote'] == 'AW-18430711486/l4geCNSpvokdEL6tudRE'
        assert conv['popup_lead'] == 'AW-18430711486/XhR4COzM0YkdEL6tudRE'
        assert conv['whatsapp'] == 'AW-18430711486/rPgKCLOM04kdEL6tudRE'
        assert conv['expert_form'] == 'AW-18430711486/11uuCLyj0YkdEL6tudRE'
        for value in conv.values():
            assert value.count('/') == 1 and not value.endswith('/')


def test_an_account_can_be_changed_without_a_deploy(app, live, monkeypatch):
    monkeypatch.setenv('GOOGLE_ADS_ID', 'AW-999')
    monkeypatch.setenv('GOOGLE_ADS_LABEL_QUOTE', 'newlabel')
    with app.test_request_context('/travel-insurance', environ_overrides=LIVE):
        assert ads.conversions()['quote'] == 'AW-999/newlabel'
        # the ones not overridden keep working
        assert ads.conversions()['whatsapp'].startswith('AW-999/')


def test_an_action_with_no_label_is_left_out(app, live, monkeypatch):
    """Rather than sent as 'AW-x/', which Google accepts and silently never counts."""
    monkeypatch.setenv('GOOGLE_ADS_LABEL_WHATSAPP', '')
    with app.test_request_context('/travel-insurance', environ_overrides=LIVE):
        conv = ads.conversions()
        assert 'whatsapp' not in conv
        assert 'quote' in conv


def test_the_live_page_loads_the_tag_and_hands_over_the_labels(app, db, live):
    """The one that proves the wiring: the template reads what the service decided."""
    # over https, the way the page is actually served: http now redirects before it renders
    html = app.test_client().get('/travel-insurance', environ_overrides=LIVE,
                                 base_url='https://nriparentservice.com').data.decode()
    assert 'googletagmanager.com/gtag/js?id=AW-18430711486' in html
    assert "gtag('config', " in html and 'AW-18430711486' in html
    for label in ('l4geCNSpvokdEL6tudRE', 'XhR4COzM0YkdEL6tudRE',
                  'rPgKCLOM04kdEL6tudRE', '11uuCLyj0YkdEL6tudRE'):
        assert label in html, label


# ---------------------------------------------------------------------------
# The bundle
# ---------------------------------------------------------------------------

def test_the_bundle_fires_only_what_the_server_sent():
    """No labels compiled into the build: switching Ads off has to be a config change, not a
    rebuild, and `npm run dev` must not report anything at all."""
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'frontend', 'insurance', 'src')
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith(('.ts', '.tsx')):
                continue
            body = open(os.path.join(folder, name), encoding='utf-8').read()
            # an id, not the letters: the type carrying these documents the shape
            # as AW-account slash label, which is not an account
            assert not re.search(r'AW-[0-9]', body), '%s has an Ads id in it' % name


def test_every_conversion_the_server_offers_is_fired_somewhere():
    """A label configured and never fired is a conversion action reporting zero for ever, which
    reads as "the ads are not working" rather than "nobody wired it up"."""
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'frontend', 'insurance', 'src')
    fired = set()
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(('.ts', '.tsx')) and name != 'track.ts':
                body = open(os.path.join(folder, name), encoding='utf-8').read()
                for action in ads.DEFAULT_LABELS:
                    if "track('%s')" % action in body:
                        fired.add(action)
    assert fired == set(ads.DEFAULT_LABELS), 'never fired: %s' % (set(ads.DEFAULT_LABELS) - fired)
