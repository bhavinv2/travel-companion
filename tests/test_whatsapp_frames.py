"""Every WhatsApp CRM screen shown inside the portal fills the page.

The frame sits in a flex column under the heading bar; the box around it has to stretch too, or the
iframe falls back to the browser's 150px default and the screen shows as a thin strip with its own
scrollbar (seen on Broadcasts, Tags, Reply rules, Chatbot... on 2026-10-17).
"""
import re

import pytest

from conftest import login
from app.routes.messaging import SCREENS
from app.services import access


@pytest.fixture
def connected(monkeypatch):
    """The WhatsApp CRM looks connected; the address is unreachable, so nothing leaves."""
    monkeypatch.setenv('WACRM_URL', 'http://127.0.0.1:9/crm')
    monkeypatch.setenv('WACRM_API_KEY', 'dummy')
    monkeypatch.setenv('WACRM_PORTAL_SECRET', 'x' * 40)


@pytest.mark.parametrize('name', sorted(SCREENS))
def test_the_frame_sits_in_a_box_that_stretches(app, client, admin_user, connected, name):
    access.ensure_defaults()
    login(client, admin_user.email)
    html = client.get('/admin/messaging/' + name.replace('_', '-')).get_data(as_text=True)
    assert 'data-wa-frame' in html, name
    # beside the numbers rail (WhatsApp chats) the frame sits in the row's middle cell, which stretches the same way
    box = re.search(r'<div class="([^"]*)"[^>]*>\s*<iframe class="wa-frame"', html)
    assert box and box.group(1) in ('wa-split', 'wa-solo', 'wa-mid'), (name, box and box.group(1))


def test_both_boxes_stretch_in_the_stylesheet(app):
    css = open(app.static_folder + '/css/workspace.css', encoding='utf-8').read()
    for rule in ('.wa-solo {', '.wa-split {'):
        body = css.split(rule, 1)[1].split('}', 1)[0]
        assert 'flex: 1' in body and 'min-height: 0' in body, rule
    mid = css.split('.wa-mid {', 1)[1].split('}', 1)[0]
    frame = css.split('.wa-mid .wa-frame {', 1)[1].split('}', 1)[0]
    assert 'min-height: 0' in mid and 'flex-direction: column' in mid and 'flex: 1' in frame
