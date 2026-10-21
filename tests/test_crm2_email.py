"""Sales CRM 2.0, run 3a -- e-mail from the lead page, and e-mail that comes in.

    composer   To is read-only, ready answers can be inserted, the sender is the CRM sender (reply-to the agent)
    send       goes only when a person presses Send; logged as a touchpoint by the agent
    no mail    when the server cannot send (Gmail is kept for account mail) it says so, offers the mail app, and
               logs "E-mail written in own mail app" only if asked
    inbound    SendGrid Inbound Parse: matched to a person, logged as theirs ("waiting on us"), unknown senders
               become a lead from source 'email'; quoted history is cut; 20k cap; token-guarded
"""
import os
from pathlib import Path

import pytest

from conftest import login, make_user
from app import db as _db
from app.models import CrmAnswer, CrmLead, CrmPerson, CrmSource, CrmTouchpoint
from app.services import crm, crm_email, crm_metrics, mailer, settings

from test_crm_wa_sync_engine import ti_lead

TOKEN = 'inbound-secret-123'
URL = '/api/crm/email-inbound?token=' + TOKEN


@pytest.fixture
def agent(app):
    return make_user('agent@test.com', 'agent', role='cs')


@pytest.fixture
def lead(app, agent):
    l = ti_lead(phone='+919876502222', name='Meera Rao', email='meera@example.com')
    l.owner_id = agent.id
    _db.session.commit()
    return l


@pytest.fixture
def me(client, agent):
    login(client, 'agent@test.com')
    mailer.OUTBOX.clear()
    return agent


@pytest.fixture
def inbound(monkeypatch):
    monkeypatch.setenv('CRM_INBOUND_EMAIL_TOKEN', TOKEN)


def compose(client, lead):
    return client.get('/cs/crm/email/compose?lead_id=%d' % lead.id).get_json()


def send(client, lead, **kw):
    body = {'lead_id': lead.id, 'subject': 'Your cover', 'body': 'Hello Meera, here is your cover.'}
    body.update(kw)
    return client.post('/cs/crm/email/send', json=body)


def mails(lead):
    return (CrmTouchpoint.query.filter_by(person_id=lead.person_id, channel='email')
            .order_by(CrmTouchpoint.id).all())


# ====================================================================================== the composer

def test_the_composer_has_the_persons_address_and_the_ready_answers(client, me, lead):
    _db.session.add(CrmAnswer(title='How to claim', body='Hi {name}, send us the bill.', product='GEN'))
    _db.session.commit()
    d = compose(client, lead)
    assert d['to'] == 'meera@example.com' and d['can_send'] is True
    assert d['reply_to'] == 'agent@test.com' and d['from_name'] == crm_email.DEFAULT_NAME
    claim = next(a for a in d['answers'] if a['title'] == 'How to claim')
    assert 'Meera' in claim['text'] and '{name}' not in claim['text']              # filled in for this person


def test_the_lead_page_and_the_contact_page_open_the_composer(client, me, lead):
    html = client.get('/cs/crm/lead/%d' % lead.id).get_data(as_text=True)
    assert 'data-email-open' in html and 'id="email-dialog"' in html
    assert 'readonly' in html and 'Insert a ready answer' in html and 'Open in my mail app' in html
    contact = client.get('/cs/crm/contact/%d' % lead.person_id).get_data(as_text=True)
    assert 'data-email-open' in contact and 'id="email-dialog"' in contact


def test_the_sender_setting_changes_the_name_and_reply_to(client, me, lead):
    settings.set_setting(crm_email.SETTING_KEY, {'name': 'Preventia Care', 'reply_to': 'care@preventia.example'})
    assert compose(client, lead)['reply_to'] == 'care@preventia.example'
    assert send(client, lead).status_code == 200
    out = mailer.OUTBOX[-1]
    assert out['from_name'] == 'Preventia Care' and out['reply_to'] == 'care@preventia.example'


# ====================================================================================== sending

def test_send_goes_from_the_crm_sender_and_is_logged_by_the_agent(client, me, lead):
    r = send(client, lead)
    assert r.status_code == 200 and r.get_json()['success']
    out = mailer.OUTBOX[-1]
    assert out['category'] == 'crm' and out['recipients'] == ['meera@example.com']
    assert out['subject'] == 'Your cover' and out['body'] == 'Hello Meera, here is your cover.'
    assert out['reply_to'] == 'agent@test.com' and out['account'] is False and out['transport'] == 'smtp'
    tp = mails(lead)[-1]
    assert (tp.direction, tp.channel, tp.agent_id, tp.lead_id, tp.via) == ('out', 'email', me.id, lead.id, 'person')
    assert 'Your cover' in tp.body and 'here is your cover' in tp.body


def test_a_ready_answer_that_was_used_is_counted(client, me, lead):
    a = CrmAnswer(title='Claims', body='x', product='GEN')
    _db.session.add(a)
    _db.session.commit()
    send(client, lead, answer_id=a.id)
    assert _db.session.get(CrmAnswer, a.id).use_count == 1


def test_a_crm_mail_is_not_a_notification_so_the_switches_do_not_hold_it_back(client, me, lead):
    settings.set_setting(settings.NOTIFY_KEY, {**settings.NOTIFY_DEFAULTS, 'enabled': False})
    assert send(client, lead).status_code == 200
    assert mailer.OUTBOX[-1]['category'] == 'crm'


def test_nothing_is_sent_without_a_subject_and_message_or_an_address(client, me, lead):
    assert send(client, lead, subject='  ').get_json()['error'] == crm_email.NEED_WORDS
    assert send(client, lead, body='').get_json()['error'] == crm_email.NEED_WORDS
    lead.person.email = None
    _db.session.commit()
    assert send(client, lead).get_json()['error'] == crm_email.NO_ADDRESS
    assert mailer.OUTBOX == [] and mails(lead) == []


def test_a_mail_that_the_provider_refuses_is_reported_and_not_logged(client, me, lead, monkeypatch):
    monkeypatch.setattr(mailer, 'send', lambda *a, **k: False)
    r = send(client, lead)
    assert r.status_code == 400 and r.get_json()['error'] == crm_email.NOT_SENT
    assert mails(lead) == []


def test_the_subject_and_body_are_capped(client, me, lead):
    send(client, lead, subject='s' * 500, body='b' * 30000)
    assert len(mailer.OUTBOX[-1]['subject']) == crm_email.SUBJECT_CAP and len(mailer.OUTBOX[-1]['body']) == crm_email.BODY_CAP


def test_from_the_contact_page_with_no_lead_the_mail_is_logged_on_the_person(client, me):
    person = CrmPerson(name='Lone', email='lone@example.com')
    _db.session.add(person)
    _db.session.commit()
    r = client.post('/cs/crm/email/send', json={'person_id': person.id, 'subject': 'Hi', 'body': 'Hello'})
    assert r.status_code == 200
    tp = CrmTouchpoint.query.filter_by(person_id=person.id, channel='email').one()
    assert tp.lead_id is None and tp.direction == 'out'


def test_only_a_press_of_send_sends_anything(client, me, lead):
    """No page, job or webhook sends category 'crm' mail: the only place that does is crm_email.send."""
    root = Path(__file__).resolve().parents[1] / 'app'
    users = [str(p.relative_to(root)) for p in root.rglob('*.py')
             if p.name != 'mailer.py' and "category='crm'" in p.read_text(encoding='utf-8')]
    assert users == [os.path.join('services', 'crm_email.py')]
    client.get('/cs/crm/lead/%d' % lead.id)
    client.get('/cs/crm/email/compose?lead_id=%d' % lead.id)
    client.get('/cs/crm/today')
    assert mailer.OUTBOX == []


# ====================================================================================== when the server cannot send

@pytest.fixture
def gmail(app):
    app.config['MAIL_SERVER'] = 'smtp.gmail.com'


def test_when_mail_cannot_go_the_composer_says_so_and_nothing_is_sent_or_logged(client, me, lead, gmail):
    assert mailer.transport_for(False) is None
    d = compose(client, lead)
    assert d['can_send'] is False
    r = send(client, lead)
    assert r.status_code == 400 and r.get_json()['error'] == crm_email.CANNOT_SEND and r.get_json()['can_send'] is False
    assert mailer.OUTBOX == [] and mails(lead) == []
    assert 'Open in my mail app' in client.get('/cs/crm/lead/%d' % lead.id).get_data(as_text=True)
    js = (Path(__file__).resolve().parents[1] / 'app/static/js/crm-activities.js').read_text(encoding='utf-8')
    assert 'not set up to send e-mail' in js and "mailto:" in js


def test_written_in_the_own_mail_app_is_logged_only_when_asked(client, me, lead, gmail):
    r = client.post('/cs/crm/email/send', json={'lead_id': lead.id, 'own_app': True, 'log': True, 'subject': 'Your cover'})
    assert r.status_code == 200
    tp = mails(lead)[-1]
    assert tp.direction == 'out' and tp.agent_id == me.id and tp.body.startswith(crm_email.OWN_APP_LINE)
    assert 'Your cover' in tp.body
    n = len(mails(lead))
    client.post('/cs/crm/email/send', json={'lead_id': lead.id, 'own_app': True, 'log': False, 'subject': 'x'})
    assert len(mails(lead)) == n and mailer.OUTBOX == []


# ====================================================================================== the mailer

def test_the_mailer_knows_a_crm_sender_name_and_keeps_account_mail_as_it_was(app):
    with app.test_request_context():
        mailer.OUTBOX.clear()
        assert mailer.send('Hi', 'a@b.com', 'x', reply_to='r@b.com', category='crm', force=True, from_name='Team')
        assert mailer.OUTBOX[-1]['from_name'] == 'Team' and mailer.OUTBOX[-1]['category'] == 'crm'
        assert mailer.send('Hi', 'a@b.com', 'x', category='account', account=True)
        assert mailer.OUTBOX[-1]['from_name'] is None


# ====================================================================================== coming in

def post_mail(client, url=URL, **form):
    data = {'from': 'Meera Rao <meera@example.com>', 'to': 'sales@in.example.com', 'subject': 'Re: your cover',
            'text': 'I would like to change my dates.'}
    data.update(form)
    return client.post(url, data=data, content_type='multipart/form-data')


def test_the_door_is_shut_while_there_is_no_token(client, lead, monkeypatch):
    monkeypatch.delenv('CRM_INBOUND_EMAIL_TOKEN', raising=False)
    assert post_mail(client).status_code == 404
    assert post_mail(client, url='/api/crm/email-inbound').status_code == 404
    assert mails(lead) == []


def test_a_wrong_or_missing_token_is_refused(client, lead, inbound):
    assert post_mail(client, url='/api/crm/email-inbound?token=nope').status_code == 403
    assert post_mail(client, url='/api/crm/email-inbound').status_code == 403
    assert mails(lead) == []


def test_a_known_sender_is_logged_on_their_newest_open_lead_and_is_waiting_on_us(client, lead, inbound, agent):
    older = ti_lead(phone='+919876503333', name='Other', email='other@example.com')
    r = post_mail(client)
    assert r.status_code == 200 and r.get_json()['result'] == 'logged'
    tp = mails(lead)[-1]
    assert (tp.direction, tp.lead_id, tp.agent_id) == ('in', lead.id, None)
    assert 'change my dates' in tp.body and 'Re: your cover' in tp.body
    entry = crm_metrics.last_touches([lead.person_id])[lead.person_id]
    assert crm_metrics.waiting_on_us(entry) and entry['reply_last'][0] == 'email'
    assert mails(older) == []


def test_our_answer_ends_the_wait(client, lead, inbound, agent):
    post_mail(client)
    crm.log_touch(lead, 'email', 'out', body='Sure.', user=agent)
    _db.session.commit()
    entry = crm_metrics.last_touches([lead.person_id])[lead.person_id]
    assert not crm_metrics.waiting_on_us(entry)


def test_the_newest_open_lead_is_the_one_that_gets_it(client, lead, inbound):
    lead.person.email = 'meera@example.com'
    second = ti_lead(phone='+919876502222', name='Meera Rao', product='SH', email='meera@example.com') \
        if False else None
    from datetime import datetime, timedelta
    other = CrmLead(person_id=lead.person_id, product=lead.product, pipeline_id=lead.pipeline_id, stage_id=lead.stage_id,
                    status='open', created_at=datetime.utcnow(), last_activity_at=datetime.utcnow() + timedelta(hours=1),
                    entered_stage_at=datetime.utcnow())
    _db.session.add(other)
    _db.session.commit()
    assert post_mail(client).get_json()['lead_id'] == other.id
    lead.status = other.status = 'lost'
    _db.session.commit()
    res = post_mail(client, **{'subject': 'again'}).get_json()
    assert res['result'] == 'logged' and res['lead_id'] is None                     # no open lead: on the person
    assert CrmTouchpoint.query.filter_by(person_id=lead.person_id, channel='email', lead_id=None).count() == 1


def test_an_unknown_sender_becomes_a_lead_from_the_email_source_waiting_for_an_admin(client, inbound):
    r = post_mail(client, **{'from': '"Priya Nair" <priya@new.example>', 'subject': 'Insurance for my parents',
                             'text': 'Please call me.'})
    assert r.get_json()['result'] == 'new_lead'
    person = CrmPerson.query.filter_by(email='priya@new.example').one()
    assert person.name == 'Priya Nair'
    lead = CrmLead.query.filter_by(person_id=person.id).one()
    src = CrmSource.query.filter_by(key='email').one()
    assert lead.source_id == src.id and src.status == 'unrouted' and lead.pipeline_id is None
    tp = CrmTouchpoint.query.filter_by(person_id=person.id).one()
    assert (tp.channel, tp.direction) == ('email', 'in') and 'Please call me' in tp.body
    entry = crm_metrics.last_touches([person.id])[person.id]
    assert crm_metrics.waiting_on_us(entry)


def test_the_same_message_twice_is_logged_once(client, lead, inbound):
    hdr = 'Received: x\nMessage-ID: <abc123@mail.example>\nSubject: hi\n'
    assert post_mail(client, headers=hdr).get_json()['result'] == 'logged'
    assert post_mail(client, headers=hdr).get_json()['result'] == 'duplicate'
    assert len(mails(lead)) == 1


def test_a_message_with_only_html_is_read_as_text(client, lead, inbound):
    post_mail(client, text='', html='<div>Hello<br>I need <b>help</b></div><p>Thanks</p>')
    body = mails(lead)[-1].body
    assert 'I need help' in body and '<' not in body


def test_a_bad_sender_address_is_ignored(client, lead, inbound):
    assert post_mail(client, **{'from': 'not an address'}).get_json()['result'] == 'ignored'
    assert CrmTouchpoint.query.filter_by(channel='email').count() == 0


def test_somebody_erased_at_their_request_does_not_come_back_by_e_mail(client, lead, inbound, admin_user):
    from app.services import crm_people
    crm_people.erase(lead.person, admin_user)
    assert post_mail(client).get_json()['result'] == 'ignored'
    assert CrmPerson.query.filter_by(email='meera@example.com').count() == 0


def test_a_broken_message_is_answered_and_nothing_half_saved(client, lead, inbound, monkeypatch):
    monkeypatch.setattr(crm_email, 'strip_quoted', lambda t: (_ for _ in ()).throw(RuntimeError('boom')))
    r = post_mail(client)
    assert r.status_code == 200 and r.get_json()['ok'] is False
    assert mails(lead) == []


def test_receiving_mail_never_sends_anything(client, lead, inbound):
    mailer.OUTBOX.clear()
    post_mail(client)
    post_mail(client, **{'from': 'new@new.example'})
    assert mailer.OUTBOX == []
    assert CrmTouchpoint.query.filter_by(channel='email', direction='out').count() == 0


def test_the_body_is_capped_at_20000_characters(client, lead, inbound):
    post_mail(client, text='x' * 50000)
    assert len(mails(lead)[-1].body) <= crm_email.BODY_CAP


# ====================================================================================== quoted history

GMAIL = """Yes please, 12 November.

On Tue, 3 Nov 2026 at 10:15, NRI Parent Service <care@preventia.example> wrote:
> When do you travel?
> Regards"""

GMAIL_WRAPPED = """Thanks!

On Tuesday, 3 November 2026 at 10:15:00 AM GMT+5:30, NRI Parent Service
<care@preventia.example> wrote:

> older"""

OUTLOOK = """Please send the forms.

From: NRI Parent Service <care@preventia.example>
Sent: 03 November 2026 10:15
To: Meera
Subject: Your cover

Earlier text."""

ORIGINAL = """OK.

-----Original Message-----
From: someone
Earlier text."""

QUOTED_ONLY = """> only a quote
> nothing else"""


@pytest.mark.parametrize('text, keep, gone', [
    (GMAIL, 'Yes please, 12 November.', 'When do you travel'),
    (GMAIL_WRAPPED, 'Thanks!', 'older'),
    (OUTLOOK, 'Please send the forms.', 'Earlier text'),
    (ORIGINAL, 'OK.', 'Earlier text'),
])
def test_quoted_history_is_cut(text, keep, gone):
    out = crm_email.strip_quoted(text)
    assert keep in out and gone not in out


def test_a_message_that_is_only_a_quote_is_kept_whole():
    assert 'only a quote' in crm_email.strip_quoted(QUOTED_ONLY)


def test_a_line_that_starts_with_from_in_the_middle_of_the_text_is_not_a_header():
    text = 'Hello\nFrom: Chennai to Dallas on 12 Nov\nplease book it'
    assert crm_email.strip_quoted(text) == text
