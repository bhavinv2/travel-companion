"""Two things a page must not be able to do to a visitor without them acting.

Logging them out, and choosing their language for them. Both used to be possible: logout was a
plain GET link, and the language switcher read its own codes out of text that Google Translate
had already rewritten.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import login  # noqa: E402


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

def test_a_get_cannot_sign_somebody_out(client, db, user):
    """It was a link. Any page anywhere -- an <img> in an e-mail, a link in a forum post -- could
    make this browser fetch it, and a GET should not change the most visible state there is."""
    login(client, 'bob@test.com')
    assert client.get('/dashboard').status_code == 200

    r = client.get('/auth/logout')
    assert r.status_code == 405, 'a GET must not be accepted at all'
    assert client.get('/dashboard').status_code == 200, 'still signed in'


def test_a_post_signs_them_out(client, db, user):
    login(client, 'bob@test.com')
    r = client.post('/auth/logout')
    assert r.status_code == 302
    assert client.get('/dashboard').status_code == 302, 'signed out'


def test_the_menu_offers_a_form_rather_than_a_link(client, db, user):
    login(client, 'bob@test.com')
    html = client.get('/').data.decode()
    assert 'class="menu-logout"' in html
    assert 'action="/auth/logout"' in html
    assert 'href="/auth/logout"' not in html


def test_logout_carries_a_csrf_token(app, db, user):
    """The form has to be usable with CSRF on, which is how it runs in production. The rest of
    the suite turns it off, so this is the one place it is switched back on."""
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        c = app.test_client()
        # with CSRF on, signing in needs its own token first
        page = c.get('/auth/login').data.decode()
        tok = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page).group(1)
        c.post('/auth/login', data={'email': 'bob@test.com', 'password': 'password123',
                                    'csrf_token': tok})
        html = c.get('/').data.decode()
        form = html.split('class="menu-logout"', 1)[1].split('</form>', 1)[0]
        token = re.search(r'name="csrf_token" value="([^"]+)"', form)
        assert token, 'the logout form needs a token or nobody can sign out'
        assert c.post('/auth/logout', data={'csrf_token': token.group(1)}).status_code == 302
    finally:
        app.config['WTF_CSRF_ENABLED'] = False


# ---------------------------------------------------------------------------
# The language switcher
# ---------------------------------------------------------------------------

LANG_PAGES = ('/', '/help')


def test_the_language_menu_is_left_untranslated(client, db):
    """Google Translate rewrites text nodes. This menu's text is language names and language
    codes: translated, the names stop being how a reader recognises their own language, and the
    codes stop being codes.
    """
    for path in LANG_PAGES:
        html = client.get(path).data.decode()
        menu = html.split('id="langMenu"', 1)
        assert len(menu) == 2, path
        opening = html[:html.index('id="langMenu"')].rsplit('<div', 1)[-1] + 'id="langMenu"' \
            + menu[1].split('>', 1)[0]
        assert 'notranslate' in opening, path
        assert 'translate="no"' in opening, path


def test_the_codes_are_in_attributes_not_in_text(client, db):
    """The landing page read the code out of the button's text. After one switch to Hindi that
    text is transliterated -- "ta" becomes "टा" -- and that went into the googtrans cookie, which
    Google could not parse, so the page came back in English."""
    html = client.get('/').data.decode()
    menu = html.split('id="langMenu"', 1)[1].split('</div>', 1)[0]
    assert 'data-lang="ta"' in menu and 'data-lang="hi"' in menu
    assert 'dataset.lang' in html or 'data-lang' in html


def test_only_a_real_code_can_reach_the_cookie(client, db):
    """Belt and braces on the same bug: whatever the button says, the switcher checks the shape
    of what it is about to write."""
    for path in LANG_PAGES:
        html = client.get(path).data.decode()
        assert 'LANG_RE' in html, path
        assert re.search(r'LANG_RE\s*=\s*/\^\[a-z\]\{2\}', html), path


def test_the_server_refuses_a_transliterated_code(client, db):
    """It held before, but by accident -- on a combining mark not counting as a letter."""
    for bad in ('टा', 'ta1', '../en', 'ਪੰ'):
        r = client.post('/api/language', json={'lang': bad})
        assert r.get_json()['lang'] == 'en', bad
    assert client.post('/api/language', json={'lang': 'ta'}).get_json()['lang'] == 'ta'
