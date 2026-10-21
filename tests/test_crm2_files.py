"""Sales CRM 2.0, run 4a -- files on a person or an enquiry (4.4).

    storage     random names under PRIVATE_UPLOAD_FOLDER/crm, never under static
    rules       only the listed extensions, at most 10 MB, not empty
    download    permission-checked (login, visibility, recycle bin), attachment, nosniff
    delete      the uploader or an admin, with an in-page confirm step (no confirm())
    life        a purged enquiry leaves its files on the person; Erase deletes them from disk; merge moves them
"""
import io
import os
import re
from datetime import datetime

import pytest

from conftest import login, make_user
from app import db as _db
from app.models import CrmFile, CrmLead, CrmPerson
from app.services import crm, crm_bin, crm_files, crm_merge, crm_people

from test_crm2_visibility import lead_for, staff, words
from test_crm_wa_sync_engine import ti_lead


def upload(client, name='passport.pdf', data=b'%PDF-1.4 hello', **form):
    form = dict(form)
    form['file'] = (io.BytesIO(data), name)
    return client.post('/cs/crm/file/upload', data=form, content_type='multipart/form-data')


def folder(app):
    return os.path.join(os.path.abspath(app.config['PRIVATE_UPLOAD_FOLDER']), 'crm')


@pytest.fixture
def agent(app):
    return staff('agent@test.com', 'agent')


@pytest.fixture
def lead(app, agent):
    l = lead_for('Filey Person', '+919876500901', agent)
    return l


def test_an_upload_is_stored_privately_under_a_random_name(app, client, agent, lead):
    login(client, agent.email)
    r = upload(client, person_id=lead.person_id, lead_id=lead.id)
    assert r.status_code == 302 and '/lead/%d' % lead.id in r.headers['Location']
    f = CrmFile.query.one()
    assert (f.person_id, f.lead_id, f.filename, f.size, f.content_type, f.uploaded_by_id) == (
        lead.person_id, lead.id, 'passport.pdf', len(b'%PDF-1.4 hello'), 'application/pdf', agent.id)
    assert re.fullmatch(r'[0-9a-f]{32}\.pdf', f.stored_name)
    path = os.path.join(folder(app), f.stored_name)
    assert os.path.isfile(path) and open(path, 'rb').read() == b'%PDF-1.4 hello'
    assert 'static' not in os.path.relpath(path, os.path.abspath(app.config['PRIVATE_UPLOAD_FOLDER'])).split(os.sep)
    assert not os.path.abspath(path).startswith(os.path.abspath(app.static_folder))
    # two uploads of the same name never share a stored name
    upload(client, person_id=lead.person_id)
    assert len({x.stored_name for x in CrmFile.query.all()}) == 2
    assert CrmFile.query.filter_by(lead_id=None).count() == 1                        # one on the person only


def test_only_the_listed_kinds_up_to_ten_mb(app, client, agent, lead):
    login(client, agent.email)
    for bad in ('virus.exe', 'page.html', 'x.svg', 'noextension', 'archive.zip', 'x.php.txt.exe'):
        r = upload(client, name=bad, person_id=lead.person_id, follow_redirects=False)
        assert r.status_code == 302
    assert CrmFile.query.count() == 0
    r = client.post('/cs/crm/file/upload', data={'person_id': lead.person_id, 'file': (io.BytesIO(b'x'), 'a.exe')},
                    content_type='multipart/form-data', follow_redirects=True)
    assert 'That kind of file is not allowed' in words(r.get_data(as_text=True))
    big = b'0' * (10 * 1024 * 1024 + 1)
    r = client.post('/cs/crm/file/upload', data={'person_id': lead.person_id, 'file': (io.BytesIO(big), 'big.pdf')},
                    content_type='multipart/form-data', follow_redirects=True)
    assert 'bigger than 10 MB' in words(r.get_data(as_text=True))
    ok = b'0' * (10 * 1024 * 1024)
    upload(client, name='edge.pdf', data=ok, person_id=lead.person_id)
    r = upload(client, name='empty.txt', data=b'', person_id=lead.person_id, follow_redirects=True)
    names = [f.filename for f in CrmFile.query.all()]
    assert names == ['edge.pdf']
    assert len(os.listdir(folder(app))) == 1                                      # a refused file leaves nothing behind
    for name in ('a.PDF', 'b.JpG', 'c.docx', 'd.xlsx', 'e.csv', 'f.txt', 'g.webp', 'h.png', 'i.jpeg', 'j.doc', 'k.xls'):
        upload(client, name=name, data=b'data', person_id=lead.person_id)
    assert CrmFile.query.count() == 12


def test_a_path_in_the_file_name_is_cut_off(app, client, agent, lead):
    login(client, agent.email)
    upload(client, name='..\\..\\evil/../scan.pdf', person_id=lead.person_id)
    f = CrmFile.query.one()
    assert f.filename == 'scan.pdf' and '/' not in f.stored_name and '\\' not in f.stored_name


def test_download_is_an_attachment_and_asks_for_a_login(app, client, agent, lead):
    login(client, agent.email)
    upload(client, name='Policy copy.pdf', data=b'PDFDATA', person_id=lead.person_id, lead_id=lead.id)
    f = CrmFile.query.one()
    r = client.get('/cs/crm/file/%d/download' % f.id)
    assert r.status_code == 200 and r.data == b'PDFDATA'
    assert r.headers['Content-Disposition'].startswith('attachment') and 'Policy copy.pdf' in r.headers['Content-Disposition']
    assert r.headers['X-Content-Type-Options'] == 'nosniff'
    _db.session.expire_all()
    from flask import g
    g.pop('_login_user', None)                         # a real request has its own user; the test shares them
    anon = app.test_client()
    r = anon.get('/cs/crm/file/%d/download' % f.id)
    assert r.status_code in (302, 401, 403) and b'PDFDATA' not in r.data
    _db.session.expire_all()
    g.pop('_login_user', None)
    # a file that vanished from disk is a plain 404
    os.remove(os.path.join(folder(app), f.stored_name))
    assert client.get('/cs/crm/file/%d/download' % f.id).status_code == 404
    # no static route serves it
    assert app.test_client().get('/static/crm/%s' % f.stored_name).status_code == 404


def test_the_cards_show_on_the_lead_page_and_the_contact_page(app, client, agent, lead):
    login(client, agent.email)
    upload(client, name='visa.pdf', person_id=lead.person_id, lead_id=lead.id)
    upload(client, name='aadhaar.pdf', person_id=lead.person_id)
    t = words(client.get('/cs/crm/lead/%d' % lead.id).get_data(as_text=True))
    assert 'Files' in t and 'visa.pdf' in t and 'aadhaar.pdf' not in t               # the enquiry's own files
    page = client.get('/cs/crm/contact/%d' % lead.person_id).get_data(as_text=True)
    t = words(page)
    assert 'visa.pdf' in t and 'aadhaar.pdf' in t and 'on an enquiry' in t
    assert 'confirm(' not in page.split('id="files"', 1)[1].split('</section>', 1)[0]


def test_delete_is_for_the_uploader_or_an_admin_with_a_confirm_step(app, client, agent, lead, admin_user):
    other = staff('other@test.com', 'other')
    login(client, agent.email)
    upload(client, name='mine.pdf', person_id=lead.person_id)
    f = CrmFile.query.one()
    path = os.path.join(folder(app), f.stored_name)
    page = client.get('/cs/crm/contact/%d' % lead.person_id).get_data(as_text=True)
    assert 'Yes, delete' in page and 'Delete mine.pdf for good?' in page         # the in-page confirm step
    # somebody else cannot
    _db.session.expire_all()
    from flask import g
    g.pop('_login_user', None)
    c2 = app.test_client()
    login(c2, other.email)
    assert 'Yes, delete' not in c2.get('/cs/crm/contact/%d' % lead.person_id).get_data(as_text=True)
    assert c2.post('/cs/crm/file/%d/delete' % f.id).status_code == 403
    assert os.path.isfile(path)
    # an admin can
    _db.session.expire_all()
    g.pop('_login_user', None)
    c3 = app.test_client()
    login(c3, admin_user.email)
    r = c3.post('/cs/crm/file/%d/delete' % f.id)
    assert r.status_code == 302
    assert CrmFile.query.count() == 0 and not os.path.exists(path)


def test_the_uploader_can_delete_their_own(app, client, agent, lead):
    login(client, agent.email)
    upload(client, name='mine.pdf', person_id=lead.person_id, lead_id=lead.id)
    f = CrmFile.query.one()
    path = os.path.join(folder(app), f.stored_name)
    r = client.post('/cs/crm/file/%d/delete' % f.id, data={'next': '/cs/crm/lead/%d' % lead.id})
    assert r.status_code == 302 and '/lead/%d' % lead.id in r.headers['Location']
    assert CrmFile.query.count() == 0 and not os.path.exists(path)


# ====================================================================================== visibility and the bin

def test_files_follow_record_visibility(app, client):
    asha = staff('asha@test.com', 'asha', scope='own')
    bela = staff('bela@test.com', 'bela')
    mine = lead_for('Ownerone Mine', '+919876501001', asha)
    hidden = lead_for('Otherwoman Hidden', '+919876501002', bela)
    # one person with an enquiry of each, and a file on each
    other_lead = ti_lead(phone='+919876501003', name='Mixed Person')
    other_lead.owner_id = asha.id
    second = crm.capture('sh-booking', name='Mixed Person', phone='+919876501003', product='SH', utm={})
    assert second.person_id == other_lead.person_id and second.id != other_lead.id
    second.owner_id = bela.id
    _db.session.commit()
    mixed = other_lead.person_id
    for name, lead_id, pid in (('mine.pdf', mine.id, mine.person_id), ('hidden.pdf', hidden.id, hidden.person_id),
                               ('mixed-mine.pdf', other_lead.id, mixed), ('mixed-bela.pdf', second.id, mixed)):
        _db.session.add(CrmFile(person_id=pid, lead_id=lead_id, filename=name, stored_name=name + '.x', size=1,
                                content_type='application/pdf'))
    _db.session.commit()
    by = {f.filename: f.id for f in CrmFile.query.all()}
    for fname in by:
        open(os.path.join(crm_files.folder(), fname + '.x'), 'wb').write(b'x')
    login(client, asha.email)
    assert client.get('/cs/crm/file/%d/download' % by['mine.pdf']).status_code == 200
    assert client.get('/cs/crm/file/%d/download' % by['hidden.pdf']).status_code == 404            # hidden person
    assert client.get('/cs/crm/file/%d/download' % by['mixed-mine.pdf']).status_code == 200
    assert client.get('/cs/crm/file/%d/download' % by['mixed-bela.pdf']).status_code == 404        # hidden enquiry
    assert client.post('/cs/crm/file/%d/delete' % by['hidden.pdf']).status_code == 404
    assert upload(client, person_id=hidden.person_id).status_code == 404
    assert upload(client, person_id=mixed, lead_id=second.id).status_code == 404
    assert upload(client, person_id=0).status_code == 404
    # the contact page of a person with one visible enquiry lists only the files of the visible one
    t = words(client.get('/cs/crm/contact/%d' % mixed).get_data(as_text=True))
    assert 'mixed-mine.pdf' in t and 'mixed-bela.pdf' not in t
    t = words(client.get('/cs/crm/lead/%d' % mine.id).get_data(as_text=True))
    assert 'mine.pdf' in t and 'hidden.pdf' not in t
    assert CrmFile.query.count() == 4


def test_a_removed_enquirys_files_are_hidden_and_a_purge_keeps_them_on_the_person(app, client, agent, lead, admin_user):
    login(client, agent.email)
    upload(client, name='keep-me.pdf', person_id=lead.person_id, lead_id=lead.id)
    f = CrmFile.query.one()
    path = os.path.join(folder(app), f.stored_name)
    pid, lid = lead.person_id, lead.id
    crm_bin.remove(lead, admin_user)
    assert client.get('/cs/crm/file/%d/download' % f.id).status_code == 404
    assert 'keep-me.pdf' not in words(client.get('/cs/crm/contact/%d' % pid).get_data(as_text=True))
    crm_bin.purge(crm_bin.get_removed(lid), admin_user)
    _db.session.expire_all()
    f = _db.session.get(CrmFile, f.id)
    assert f is not None and f.lead_id is None and f.person_id == pid and os.path.isfile(path)
    assert client.get('/cs/crm/file/%d/download' % f.id).status_code == 200
    assert 'keep-me.pdf' in words(client.get('/cs/crm/contact/%d' % pid).get_data(as_text=True))


def test_erasing_a_person_deletes_their_files_from_disk(app, client, agent, lead, admin_user):
    login(client, agent.email)
    upload(client, name='a.pdf', person_id=lead.person_id, lead_id=lead.id)
    upload(client, name='b.pdf', person_id=lead.person_id)
    paths = [os.path.join(folder(app), f.stored_name) for f in CrmFile.query.all()]
    assert all(os.path.isfile(p) for p in paths)
    survivor = ti_lead(phone='+919876501101', name='Survivor Person')
    upload(client, name='s.pdf', person_id=survivor.person_id)
    keep_path = os.path.join(folder(app), CrmFile.query.filter_by(filename='s.pdf').one().stored_name)
    plan = crm_people.erase_plan(lead.person)
    assert plan['files'] == 2
    crm_people.erase(lead.person, admin_user)
    assert CrmFile.query.filter_by(filename='a.pdf').count() == 0 and CrmFile.query.filter_by(filename='b.pdf').count() == 0
    assert not any(os.path.exists(p) for p in paths)
    assert os.path.isfile(keep_path) and CrmFile.query.count() == 1


def test_the_erase_dialog_lists_the_files(app, client, admin_user, agent, lead):
    login(client, agent.email)
    upload(client, name='a.pdf', person_id=lead.person_id)
    _db.session.expire_all()
    from flask import g
    g.pop('_login_user', None)
    c = app.test_client()
    login(c, admin_user.email)
    t = words(c.get('/cs/crm/contact/%d?erase=1' % lead.person_id).get_data(as_text=True))
    assert '1 file, deleted from the server' in t


def test_a_merge_moves_the_files_and_leaves_them_on_disk(app, client, agent, lead, admin_user):
    login(client, agent.email)
    upload(client, name='a.pdf', person_id=lead.person_id, lead_id=lead.id)
    f = CrmFile.query.one()
    path = os.path.join(folder(app), f.stored_name)
    keep = CrmPerson(name='Keep Person', phone='+919876501201')
    _db.session.add(keep)
    _db.session.commit()
    crm_merge.merge(keep, lead.person, admin_user)
    _db.session.expire_all()
    f = _db.session.get(CrmFile, f.id)
    assert f.person_id == keep.id and os.path.isfile(path)


def test_nothing_in_the_new_templates_uses_a_browser_confirm_box():
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app')
    for rel in ('templates/cs/crm/_files.html', 'templates/cs/crm/_family.html', 'templates/cs/crm/merge.html',
                'templates/cs/crm/duplicates.html', 'static/js/crm-files.js'):
        text = open(os.path.join(root, rel), encoding='utf-8').read()
        assert 'confirm(' not in text and 'data-confirm' not in text, rel
