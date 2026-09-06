"""Admin-editable messages: CS claim DM, custom snippets (CRUD), e-mail templates."""
from datetime import date, timedelta

from conftest import login, logout
from app.models import CompanionRequest
from app.services import mailer


def _trip(db, **kw):
    t = CompanionRequest(travel_type='air', trip_type='one_way', poster_name='Priya Patel',
                         flying_from='Hyderabad (HYD)', destination='Dallas (DFW)',
                         from_date=date.today() + timedelta(days=20), role='seeking_help', source='cs')
    for k, v in kw.items():
        setattr(t, k, v)
    t.set_status('unconfirmed')
    db.session.add(t)
    db.session.commit()
    return t


def test_requires_admin(client, cs_user):
    login(client, 'cs@test.com')
    assert client.get('/admin/messages').status_code in (302, 403)


def test_page_lists_all_templates(client, admin_user):
    login(client, 'admin@test.com')
    html = client.get('/admin/messages').data.decode()
    for key in ('cs_claim_dm', 'email_verify', 'email_password_reset', 'email_match_found', 'email_new_match_alert'):
        assert key in html


def test_edit_claim_dm_changes_cs_copy(client, app, db, admin_user):
    login(client, 'admin@test.com')
    r = client.post('/admin/messages/cs_claim_dm',
                    json={'body': 'Namaste {{ name }}! Claim here: {{ url }}'}).get_json()
    assert r['success'] and r['edited']
    t = _trip(db)
    from app.routes.cs import dm_text_for
    with app.test_request_context():
        text = dm_text_for(t, 'https://x/claim/T')
    assert text == 'Namaste Priya! Claim here: https://x/claim/T'
    # reset returns the built-in wording
    client.post('/admin/messages/cs_claim_dm/reset', json={})
    with app.test_request_context():
        assert 'this is the Connecting Desis team' in dm_text_for(t, 'https://x/claim/T')


def test_invalid_jinja_rejected(client, admin_user):
    login(client, 'admin@test.com')
    r = client.post('/admin/messages/cs_claim_dm', json={'body': 'Broken {% if %}'})
    assert r.status_code == 400 and 'Template error' in r.get_json()['error']


def test_email_subject_and_body_override(client, db, admin_user, user):
    login(client, 'admin@test.com')
    client.post('/admin/messages/email_verify',
                json={'subject': 'HELLO {{ user.username }}', 'body': 'CLICK {{ link }} NOW'})
    logout(client)
    mailer.OUTBOX.clear()
    user.is_verified = False
    db.session.commit()
    from app.routes.auth import send_verification_email
    assert send_verification_email(user)
    sent = mailer.OUTBOX[-1]
    assert sent['subject'] == 'HELLO bob'
    assert sent['body'].startswith('CLICK http') and 'NOW' in sent['body']


def test_custom_snippets_crud_and_post_page(client, db, admin_user, cs_user):
    login(client, 'admin@test.com')
    r = client.post('/admin/messages/custom',
                    json={'items': [{'title': 'WhatsApp intro', 'body': 'Hello {{ name }}, about your {{ route }} trip.'}]}).get_json()
    assert r['success'] and r['items'][0]['key'] == 'whatsapp_intro'
    t = _trip(db)
    logout(client)
    login(client, 'cs@test.com')
    html = client.get(f'/cs/posts/{t.id}').data.decode()
    assert 'WhatsApp intro' in html
    assert 'Hello Priya, about your Hyderabad (HYD) → Dallas (DFW) trip.' in html
    # delete = save an empty list
    logout(client)
    login(client, 'admin@test.com')
    assert client.post('/admin/messages/custom', json={'items': []}).get_json()['items'] == []


def test_preview_renders_sample_data(client, admin_user):
    login(client, 'admin@test.com')
    d = client.post('/admin/messages/preview',
                    json={'subject': 'For {{ trip.route_display }}', 'body': 'Score {{ match.score }}%'}).get_json()
    assert 'Hyderabad' in d['subject'] and 'Score 95%' in d['body']
