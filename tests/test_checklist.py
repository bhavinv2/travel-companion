"""Home › Health's first-week checklist (Staff Console 2.0, 2026-10-26): lines that tick themselves, only for pages
the person opens, gone when everything is done or when they hide it."""
from conftest import login
from app.services import access, checklist, signin


def test_the_checklist_ticks_itself_and_can_be_hidden(app, client, admin_user):
    access.ensure_defaults()
    login(client, admin_user.email)
    html = client.get('/admin/health').get_data(as_text=True)
    assert 'Getting started' in html and 'Turn on two-step sign-in for yourself' in html
    with app.test_request_context():
        keys = {s['key']: s['done'] for s in checklist.steps(admin_user)}
    assert keys['two_step_me'] is False and keys['two_step_rule'] is False and keys['sources'] is True
    signin.save_rules(admin_user, two_step='admins')
    with app.test_request_context():
        assert {s['key']: s['done'] for s in checklist.steps(admin_user)}['two_step_rule'] is True
    client.post('/admin/health/checklist/hide')
    assert 'Getting started' not in client.get('/admin/health').get_data(as_text=True)
