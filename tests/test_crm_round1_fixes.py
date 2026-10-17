"""Final-test round 1 fixes (portal): the lead page's More menu, Remove keeps the contact, the Tags box on the lead
card, the frame saying why a fill was refused, the Chatbot / AI lines, the help lines naming real labels, and
the two squashed lines. (Put it in the chat and the reply-rule links are in test_crm_f1_gaps.py.)"""
import os
import re

from conftest import login
from app import db as _db
from app.models import CrmLead, CrmPerson
from app.services import crm, wacrm_team

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(HERE, *parts), encoding='utf8') as f:
        return f.read()


def lead():
    return crm.capture('ti-quote', name='Ramesh Kumar', phone='+919876543210', utm={})


def test_more_menu_uses_the_new_words_and_erase_is_for_admins(app, client, admin_user):
    ld = lead()
    login(client, admin_user.email)
    page = client.get('/admin/crm/lead/%d' % ld.id).get_data(as_text=True)
    assert 'Remove this lead' in page and 'stays in Contacts' in page
    assert 'Erase this person' in page and 'erase=1' in page
    assert 'Remove from the Sales CRM' not in page and 'Undo the last move' not in page


def test_erase_is_not_offered_to_a_sales_agent(app, client, cs_user):
    ld = lead()
    ld.owner_id = cs_user.id
    _db.session.commit()
    login(client, cs_user.email)
    page = client.get('/cs/crm/lead/%d' % ld.id).get_data(as_text=True)
    assert 'Erase this person' not in page


def test_removing_a_lead_keeps_the_contact(app, client, admin_user):
    ld = lead()
    pid = ld.person_id
    login(client, admin_user.email)
    assert client.post('/admin/crm/lead/%d/remove' % ld.id).get_json()['success']
    _db.session.expire_all()
    assert CrmLead.query.count() == 0 and _db.session.get(CrmPerson, pid) is not None


def test_the_lead_card_carries_the_tags_box(app, client, admin_user):
    ld = lead()
    login(client, admin_user.email)
    page = client.get('/admin/crm/lead/%d' % ld.id).get_data(as_text=True)
    assert 'data-tags' in page and 'automatic' in page and 'crm-people.js' in page


def test_the_frame_says_why_a_fill_was_refused():
    html = read('app', 'templates', 'messaging', 'frame.html')
    assert "wacrm:composed" in html
    for reason, words in (('window_closed', 'Only an approved template can go now.'),
                          ('busy', 'Finish the attachment or voice note first.'),
                          ('read_only', 'You can read this chat but not write in it.'),
                          ('not_open', 'Open the chat on the left first.')):
        assert reason in html and words in html
    assert 'answers nothing' not in read('app', 'static', 'js', 'crm.js')


def test_automations_info_reads_the_chatbot_and_ai_fields_or_says_unknown(app, monkeypatch):
    monkeypatch.setattr(wacrm_team, '_api', lambda *a, **k: {'items': [{'id': 'a'}], 'flows_active': 2, 'ai_auto_reply': False})
    info = wacrm_team.automations_info()
    assert info['flows_active'] == 2 and info['ai_auto_reply'] is False and wacrm_team.automations() == [{'id': 'a'}]
    monkeypatch.setattr(wacrm_team, '_api', lambda *a, **k: {'items': [], 'flows_active': 'x', 'ai_auto_reply': 'yes'})
    info = wacrm_team.automations_info()
    assert info['flows_active'] is None and info['ai_auto_reply'] is None


def test_help_lines_name_labels_that_exist():
    from app.routes import messaging
    assert any('are locked here' in l for l in messaging.SCREENS['tags']['help'])
    # a label quoted in a help line must exist somewhere on that page's templates
    data = read('app', 'templates', 'cs', 'crm', 'data.html')
    conn = read('app', 'templates', 'cs', 'crm', 'connection.html')
    quoted = re.findall(r'"([^"]+)"', ' '.join(re.findall(r'help=\[(.*?)\]', data, re.S)))
    for q in quoted:
        assert q in data or q in conn, q
    today = read('app', 'templates', 'cs', 'crm', 'today.html')
    bits = read('app', 'templates', 'cs', 'crm', '_bits.html')
    for q in re.findall(r'"([^"]+)"', ' '.join(re.findall(r'help=\[(.*?)\]', today, re.S))):
        assert q in today or q in bits, q


def test_the_squashed_lines_are_split():
    src = read('app', 'routes', 'crm.py')
    assert not re.search(r'\S {6,}(else|if) ', src)
