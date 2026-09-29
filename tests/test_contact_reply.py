"""Answering an enquiry from the console.

Reply used to be a mailto: link. On a machine with no mail client configured it did nothing at
all, and when it did work the answer left from somebody's personal mailbox -- so this screen
showed an enquiry with nothing beside it, and the next agent could not tell whether it had been
answered, by whom, or what was said.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import login  # noqa: E402
from app import db as _db  # noqa: E402
from app.models import ContactMessage, ContactReply  # noqa: E402
from app.services import mailer  # noqa: E402


@pytest.fixture()
def enquiry(app, db):
    m = ContactMessage(name='Asha', email='asha@example.com', message='Is my mother covered?')
    _db.session.add(m)
    _db.session.commit()
    return m


def reply(client, mid, body, next_url='/cs/voices?tab=contact'):
    return client.post('/cs/contact/%d/reply' % mid,
                       data={'body': body, 'next': next_url}, follow_redirects=True)


# ---------------------------------------------------------------------------
# Sending one
# ---------------------------------------------------------------------------

def test_a_reply_is_emailed_and_kept(client, db, cs_user, enquiry):
    login(client, 'cs@test.com')
    mailer.OUTBOX.clear()

    r = reply(client, enquiry.id, 'Yes — visitor plans cover her for the dates you gave.')
    assert r.status_code == 200

    sent = ContactReply.query.one()
    assert sent.message_id == enquiry.id
    assert sent.body.startswith('Yes')
    assert sent.delivered is True
    assert sent.author.email == 'cs@test.com'

    assert mailer.OUTBOX[-1]['recipients'] == ['asha@example.com']
    assert 'visitor plans' in mailer.OUTBOX[-1]['body']


def test_answering_moves_a_new_enquiry_along(client, db, cs_user, enquiry):
    """Answering it is what "in progress" means. Closing it stays somebody's decision."""
    assert enquiry.status == 'new'
    login(client, 'cs@test.com')
    reply(client, enquiry.id, 'Looking into this for you now, back shortly.')
    assert ContactMessage.query.get(enquiry.id).status == 'in_progress'


def test_the_reply_shows_on_the_screen_afterwards(client, db, cs_user, enquiry):
    """The whole point: the next agent to open this can see it was answered, and with what."""
    login(client, 'cs@test.com')
    reply(client, enquiry.id, 'Yes — visitor plans cover her for those dates.')
    html = client.get('/cs/voices?tab=contact').data.decode()
    assert 'visitor plans cover her' in html
    assert 'cm-reply' in html


def test_an_empty_reply_is_refused(client, db, cs_user, enquiry):
    login(client, 'cs@test.com')
    reply(client, enquiry.id, 'ok')
    assert ContactReply.query.count() == 0


def test_a_reply_that_could_not_be_sent_is_still_kept(client, db, cs_user, enquiry, monkeypatch):
    """An agent needs to see what was written even when it failed to go, and needs to be told it
    failed rather than left to assume it went."""
    monkeypatch.setattr(mailer, 'send', lambda *a, **k: False)
    login(client, 'cs@test.com')
    r = reply(client, enquiry.id, 'This one never reaches the mail provider.')

    saved = ContactReply.query.one()
    assert saved.delivered is False
    assert 'nothing was sent' in r.data.decode()


def test_the_composer_replaces_the_mailto_link(client, db, cs_user, enquiry):
    login(client, 'cs@test.com')
    html = client.get('/cs/voices?tab=contact').data.decode()
    assert 'vc-reply-open' in html and 'id="vcReplyForm"' in html
    assert 'mailto:asha@example.com?subject=' not in html


# ---------------------------------------------------------------------------
# Who may
# ---------------------------------------------------------------------------

def test_replying_is_for_staff(client, db, user, enquiry):
    login(client, 'bob@test.com')
    r = client.post('/cs/contact/%d/reply' % enquiry.id, data={'body': 'I am not on the team.'})
    assert r.status_code in (302, 403)
    assert ContactReply.query.count() == 0


def test_a_reply_cannot_redirect_off_the_site(client, db, cs_user, enquiry):
    login(client, 'cs@test.com')
    r = client.post('/cs/contact/%d/reply' % enquiry.id,
                    data={'body': 'A perfectly ordinary reply.', 'next': 'https://evil.example.com'})
    assert r.status_code == 302
    assert 'evil.example.com' not in r.headers['Location']
