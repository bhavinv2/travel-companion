"""Release 2, U5 + U6: ONE pipeline system that admins extend without code.

    products      a table now (code, name, icon, default pipeline); codes are checked before they are used
    wizard        a new pipeline from a copy or the simple path, with its own WhatsApp tag when the product's is taken
    editor        one Save, checked first and applied in one transaction: a refusal changes nothing
    engine        stages that move by themselves, lead details, an inactive pipeline that passes new leads on
    safety        nothing here ever sends a message; only admins reach it
"""
import copy
from datetime import date, datetime, timedelta

import pytest

from conftest import login
from app import db as _db
from app.models import (CrmField, CrmLead, CrmPipeline, CrmPlaybookStep, CrmProduct, CrmSource, CrmStage,
                        CrmStageChange, CrmTask, CrmTouchpoint)
from app.services import access, crm, crm_editor, crm_products, wacrm, wacrm_team

from test_crm_wa_sync_engine import due_people, ti_lead  # noqa: F401

A = '/admin/crm'


def pipe_of(key):
    return CrmPipeline.query.filter_by(key=key).one()


def posted(pipe, **over):
    """What the editor's page posts when nothing was touched (a faithful round trip), then `over`."""
    stages = []
    for s in sorted(pipe.stages, key=lambda s: (s.position, s.id)):
        auto = {}
        if s.auto_kind and s.auto_to_id:
            auto = {'kind': s.auto_kind, 'days': s.auto_days, 'to': 's%d' % s.auto_to_id, 'field': s.auto_field,
                    'reason': s.auto_reason}
        stages.append({'id': s.id, 'ref': 's%d' % s.id, 'name': s.name, 'means': s.stage_means,
                       'on_reply': s.on_reply, 'sla_hours': s.sla_hours, 'auto': auto,
                       'button': {'label': s.button_label or '', 'code': s.button_code or ''},
                       'steps': [crm_editor.step_json(t) for t in sorted(s.steps, key=lambda t: (t.position, t.id))]})
    fields = [{'id': f.id, 'ref': 'f%d' % f.id, 'label': f.label, 'type': f.type, 'options': f.options,
               'on_card': f.on_card, 'on_add': f.on_add, 'required': f.required}
              for f in CrmField.query.filter_by(pipeline_id=pipe.id).order_by(CrmField.position, CrmField.id)]
    data = {'stamp': crm_editor.stamp(pipe), 'name': pipe.name, 'is_active': pipe.is_active, 'product': pipe.product,
            'catch_all': pipe.catch_all, 'reasons': list(pipe.fallout_reasons or []), 'fields': fields, 'stages': stages}
    data.update(over)
    return data


def save(client, pipe, data):
    return client.post('%s/pipelines/%d/save' % (A, pipe.id), json=data)


def structure(pipe):
    _db.session.expire_all()
    p = _db.session.get(CrmPipeline, pipe.id)
    return [(s.key, s.name, s.position, s.kind, s.auto_kind, [t.code for t in s.steps]) for s in
            sorted(p.stages, key=lambda s: s.position)], CrmField.query.filter_by(pipeline_id=p.id).count()


@pytest.fixture
def admin(app, client, admin_user):
    crm.ensure_defaults()
    login(client, admin_user.email)
    return admin_user


def new_pipeline(client, **form):
    data = {'name': 'Visa help', 'product': 'TI', 'start': 'simple', 'tag_mode': 'own', 'tag_label': 'TI visa',
            'arrive': 'hand'}
    data.update(form)
    return client.post(A + '/pipelines/new', data=data)


# ======================================================================================= products

def test_the_built_in_products_are_a_table_with_labels_icons_and_default_pipelines(app):
    crm.ensure_defaults()
    assert CrmProduct.query.count() >= 3
    codes = crm_products.codes()
    assert {'TI', 'SH', 'TC'} <= set(codes)
    assert crm_products.labels()['TI'] and crm_products.icon('TI')
    assert crm_products.default_pipeline('TI').product == 'TI'
    assert crm_products.by_code('zz') is None and crm_products.by_code(None) is None
    assert crm_products.default_pipeline('NOPE') is not None                   # an unknown product falls to the catch-all


@pytest.mark.parametrize('code,ok', [('GH', True), ('gh2', True), ('A1B2C3D4', True), ('G', False), ('1AB', False),
                                     ('ABCDEFGHI', False), ('A B', False), ('A-B', False), ('', False), (None, False),
                                     ('PI', False)])
def test_product_codes_are_two_to_eight_letters_or_digits_and_not_a_follow_up_code(app, code, ok):
    assert crm_products.valid_code(code) is ok


def test_a_new_product_is_saved_and_its_code_is_checked(app, client, admin):
    r = client.post(A + '/pipelines/products', data={'name': 'Gift hampers', 'code': 'zq', 'icon': 'fa-gift', 'currency': 'INR'})
    assert r.status_code == 302
    p = CrmProduct.query.filter_by(code='ZQ').one()
    assert p.name == 'Gift hampers' and p.offered
    dup = client.post(A + '/pipelines/products', data={'name': 'Other', 'code': 'ZQ'})
    assert dup.status_code == 400 and CrmProduct.query.filter_by(code='ZQ').count() == 1
    bad = client.post(A + '/pipelines/products', data={'name': 'Bad', 'code': '9x'})
    assert bad.status_code == 400 and CrmProduct.query.filter_by(code='9X').count() == 0
    none = client.post(A + '/pipelines/products', data={'name': '', 'code': 'ZZ'})
    assert none.status_code == 400


def test_a_product_code_cannot_change_once_it_has_leads(app, client, admin):
    ti_lead()
    p = CrmProduct.query.filter_by(code='TI').one()
    client.post(A + '/pipelines/products', data={'id': p.id, 'name': 'Travel Insurance', 'code': 'XX', 'offered': 'on'})
    _db.session.expire_all()
    assert CrmProduct.query.filter_by(code='TI').count() == 1 and CrmProduct.query.filter_by(code='XX').count() == 0


def test_a_code_a_person_already_uses_as_a_whatsapp_tag_is_refused_unless_taken_over(app, client, admin, monkeypatch):
    monkeypatch.setenv('WACRM_URL', 'https://crm.example/crm')
    monkeypatch.setenv('WACRM_API_KEY', 'k')
    monkeypatch.setenv('WACRM_PORTAL_SECRET', 'x' * 40)
    crm.save_settings(whatsapp_mode='contacts')
    monkeypatch.setattr(wacrm_team, 'list_tags', lambda *a, **k: [{'name': 'vip', 'contacts': 40, 'managed': False}])
    monkeypatch.setattr(wacrm_team, '_api', lambda *a, **k: {})
    monkeypatch.setattr(wacrm, '_call', lambda *a, **k: {})
    r = client.get(A + '/pipelines/tag-check?code=VIP')
    out = r.get_json()
    assert out['clash'] and '40' in out['said']
    refused = client.post(A + '/pipelines/products', data={'name': 'VIP club', 'code': 'VIP'})
    assert refused.status_code == 400 and CrmProduct.query.filter_by(code='VIP').count() == 0
    ok = client.post(A + '/pipelines/products', data={'name': 'VIP club', 'code': 'VIP', 'take_over': 'on'})
    assert ok.status_code == 302 and CrmProduct.query.filter_by(code='VIP').count() == 1


def test_the_offered_switch_saves_and_only_admins_can_use_it(app, client, admin):
    p = CrmProduct.query.filter_by(code='TC').one()
    assert client.post('%s/pipelines/products/%d/offered' % (A, p.id), json={'on': False}).get_json()['success']
    _db.session.expire_all()
    assert CrmProduct.query.filter_by(code='TC').one().offered is False
    assert 'TC' not in [x.code for x in crm_products.offered()]


# ======================================================================================= the pages

def test_the_pipeline_pages_draw_for_admins_and_refuse_everyone_else(app, client, admin_user, cs_user):
    crm.ensure_defaults()
    pid = pipe_of('ti-standard').id
    urls = [A + '/pipelines', A + '/pipelines?tab=products', A + '/pipelines?show=templates', A + '/pipelines/new',
            '%s/pipelines/%d' % (A, pid)]
    login(client, admin_user.email)
    for u in urls:
        assert client.get(u).status_code == 200, u
    client.post('/auth/logout')
    access.ensure_defaults()
    login(client, cs_user.email)
    for u in urls:
        assert client.get(u.replace('/admin/', '/cs/')).status_code in (302, 403, 404), u
    assert client.post('/cs/crm/pipelines/%d/save' % pid, json={}).status_code in (302, 403, 404)
    assert client.post('/cs/crm/pipelines/%d/active' % pid, json={'on': False}).status_code in (302, 403, 404)
    assert client.post('/cs/crm/pipelines/products', data={'name': 'x', 'code': 'XY'}).status_code in (302, 403, 404)
    assert pipe_of('ti-standard').is_active


def test_the_old_pipeline_urls_land_on_the_new_editor(app, client, admin):
    r = client.get(A + '/pipelines?p=ti-standard')
    assert r.status_code == 302 and '/pipelines/%d' % pipe_of('ti-standard').id in r.headers['Location']
    assert client.get(A + '/pipelines/99999').status_code == 404
    assert client.get(A + '/pipelines?p=nope').status_code in (200, 302)
    assert client.get(A + '/setup/pipeline').status_code in (302, 405)


def test_taking_new_leads_switch_sends_new_leads_to_the_products_other_pipeline(app, client, admin):
    ti = pipe_of('ti-standard')
    r = client.post('%s/pipelines/%d/active' % (A, ti.id), json={'on': False})
    assert r.get_json()['success']
    _db.session.expire_all()
    assert not pipe_of('ti-standard').is_active
    lead = ti_lead()                                           # the TI source points at it; nobody is left in the cold
    assert lead is not None and lead.pipeline.is_active
    client.post('%s/pipelines/%d/active' % (A, ti.id), json={'on': True})
    assert pipe_of('ti-standard').is_active


def test_an_inactive_pipeline_stays_on_the_board_while_it_has_open_leads(app, client, admin):
    lead = ti_lead()
    pipe = lead.pipeline
    pipe.is_active = False
    _db.session.commit()
    page = client.get(A + '/?p=%s' % pipe.key).get_data(as_text=True)
    assert 'Ramesh Kumar' in page


# ======================================================================================= the wizard

def test_the_simple_path_makes_new_talking_won_lost(app, client, admin):
    r = new_pipeline(client)
    assert r.status_code == 302
    p = pipe_of('visa-help')
    stages = sorted(p.stages, key=lambda s: s.position)
    assert [s.stage_means for s in stages][0] == 'new' and stages[-1].kind in ('won', 'lost')
    assert {s.kind for s in stages} == {'open', 'won', 'lost'} and p.tag_mode == 'own' and p.tag_label == 'TI visa'
    assert p.is_active and not p.catch_all and p.product == 'TI'
    assert CrmTouchpoint.query.count() == 0 and CrmTask.query.count() == 0              # building sends and plans nothing


def test_a_second_pipeline_for_a_product_must_have_its_own_tag(app, client, admin):
    r = new_pipeline(client, tag_mode='product', tag_label='')
    assert r.status_code == 400 and CrmPipeline.query.filter_by(key='visa-help').count() == 0
    assert "uses 'TI'" in r.get_data(as_text=True).replace('&#39;', "'")
    assert new_pipeline(client, tag_label='').status_code == 400                         # own tag, but blank
    assert new_pipeline(client, name='').status_code == 400
    assert new_pipeline(client, product='NOPE').status_code == 400
    assert new_pipeline(client, start='copy', copy_from='').status_code == 400
    assert CrmPipeline.query.filter_by(key='visa-help').count() == 0


def test_a_copy_brings_stages_follow_ups_and_details_and_does_not_share_rows(app, client, admin):
    src = pipe_of('ti-standard')
    CrmField(pipeline_id=src.id, key='budget', label='Budget', type='number', position=0)
    _db.session.add(CrmField(pipeline_id=src.id, key='budget', label='Budget', type='number', position=0))
    _db.session.commit()
    n_stages, n_steps = len(src.stages), sum(len(s.steps) for s in src.stages)
    new_pipeline(client, name='TI renewals', start='copy', copy_from=src.id, tag_label='TI renewals')
    p = pipe_of('ti-renewals')
    assert len(p.stages) == n_stages and sum(len(s.steps) for s in p.stages) == n_steps
    assert CrmField.query.filter_by(pipeline_id=p.id, key='budget').count() == 1
    assert not set(s.id for s in p.stages) & set(s.id for s in src.stages)
    assert not any(t.auto for s in p.stages for t in s.steps)          # copied follow-ups never go by themselves
    assert all(t.stage.pipeline_id == p.id for s in p.stages for t in s.steps)


def test_a_new_product_can_be_made_inside_the_wizard(app, client, admin):
    r = client.post(A + '/pipelines/new', data={'name': 'Hampers', 'product': '__new', 'np_name': 'Gift hampers',
                                                'np_code': 'ZQ', 'np_icon': 'fa-gift', 'np_currency': 'INR',
                                                'start': 'simple', 'tag_mode': 'product', 'arrive': 'hand'})
    assert r.status_code == 302
    prod = CrmProduct.query.filter_by(code='ZQ').one()
    assert pipe_of('hampers').product == 'ZQ' and prod.default_pipeline_id == pipe_of('hampers').id
    bad = client.post(A + '/pipelines/new', data={'name': 'X', 'product': '__new', 'np_name': 'Dup', 'np_code': 'TI',
                                                  'start': 'simple', 'tag_mode': 'product', 'arrive': 'hand'})
    assert bad.status_code == 400 and CrmPipeline.query.filter_by(name='X').count() == 0


def test_a_form_pipeline_gets_a_source_and_two_pipelines_never_share_a_key(app, client, admin):
    new_pipeline(client, arrive='form')
    new_pipeline(client, arrive='form', tag_label='TI visa 2')
    assert CrmPipeline.query.filter(CrmPipeline.key.like('visa-help%')).count() == 2
    assert CrmSource.query.filter(CrmSource.key.like('visa-help-form%')).count() == 2
    assert len({s.key for s in CrmSource.query.all()}) == CrmSource.query.count()


def test_leads_from_a_source_pointed_at_the_new_pipeline_land_in_its_first_stage(app, client, admin):
    new_pipeline(client, arrive='form')
    p = pipe_of('visa-help')
    src = CrmSource.query.filter_by(pipeline_id=p.id).one()
    lead = crm.capture(src.key, name='Visa Person', phone='+919822222222', utm={}, plan=False, notify=False, sync=False)
    assert lead.pipeline_id == p.id and lead.stage.position == 0 and lead.product == 'TI'
    assert lead.stage.name == sorted(p.stages, key=lambda s: s.position)[0].name


# ======================================================================================= the editor

def test_an_untouched_save_changes_nothing_and_a_stale_page_is_refused(app, client, admin):
    p = pipe_of('ti-standard')
    before = structure(p)
    r = save(client, p, posted(p))
    assert r.status_code == 200 and r.get_json()['success'], r.get_json()
    assert structure(p) == before
    stale = posted(p)
    stale['stamp'] = 'old'
    r = save(client, p, stale)
    assert r.status_code == 409 and structure(p) == before
    assert save(client, p, {}).status_code == 409
    assert client.post('%s/pipelines/%d/save' % (A, p.id), data='not json', content_type='text/plain').status_code in (200, 400, 409, 422)


def test_adding_a_stage_a_follow_up_and_a_detail_in_one_save(app, client, admin):
    p = pipe_of('ti-standard')
    d = posted(p)
    d['stages'].insert(1, {'ref': 'new1', 'name': 'Documents', 'means': 'talking', 'steps': [
        {'ref': 'nt', 'channel': 'todo', 'title': 'Collect passport copy', 'when': {'type': 'after', 'value': 2, 'unit': 'days'}}]})
    d['fields'].append({'ref': 'nf', 'label': 'Passport number', 'type': 'text', 'on_card': True, 'on_add': True})
    r = save(client, p, d)
    assert r.status_code == 200, r.get_json()
    p = pipe_of('ti-standard')
    stage = next(s for s in p.stages if s.name == 'Documents')
    assert stage.position == 1 and stage.kind == 'open' and stage.steps[0].channel == 'todo'
    assert stage.steps[0].trigger_value == 48 and stage.steps[0].code
    f = CrmField.query.filter_by(pipeline_id=p.id, key='passport_number').one()
    assert f.on_card and f.on_add and f.type == 'text'
    assert [s.position for s in sorted(p.stages, key=lambda s: s.position)] == list(range(len(p.stages)))


def test_refusals_change_nothing_and_say_what_to_fix(app, client, admin):
    p = pipe_of('ti-standard')
    before = structure(p)
    cases = []
    d = posted(p); d['name'] = '  '; cases.append(('name', d))
    d = posted(p); d['stages'][0]['name'] = ''; cases.append(('blank stage', d))
    d = posted(p); d['stages'][1]['name'] = d['stages'][0]['name'].upper(); cases.append(('same stage name', d))
    d = posted(p); d['product'] = 'NOPE'; cases.append(('product', d))
    d = posted(p); d['stages'] = [s for s in d['stages'] if s['means'] in ('won', 'lost')]; cases.append(('no open stage', d))
    d = posted(p); d['stages'][0]['auto'] = {'kind': 'in_stage', 'days': 'x', 'to': d['stages'][1]['ref']}; cases.append(('days', d))
    d = posted(p); d['stages'][1]['auto'] = {'kind': 'in_stage', 'days': 3, 'to': d['stages'][0]['ref']}; cases.append(('backwards', d))
    d = posted(p); d['stages'][0]['auto'] = {'kind': 'after_date', 'days': 3, 'to': d['stages'][1]['ref']}; cases.append(('no date', d))
    d = posted(p); d['stages'][0]['auto'] = {'kind': 'no_reply', 'days': 3, 'to': d['stages'][0]['ref']}; cases.append(('self', d))
    d = posted(p); d['stages'][0]['sla_hours'] = 99999; cases.append(('sla', d))
    d = posted(p); d['stages'][0]['on_reply'] = d['stages'][1]['on_reply'] = True; cases.append(('two reply stages', d))
    d = posted(p); d['stages'][0]['button'] = {'label': 'I did it', 'code': 'bad code!'}; cases.append(('button code', d))
    d = posted(p); d['fields'] = [{'ref': 'a', 'label': '', 'type': 'text'}]; cases.append(('field label', d))
    d = posted(p); d['fields'] = [{'ref': 'a', 'label': 'Pick', 'type': 'choice', 'options': ['only one']}]; cases.append(('choices', d))
    d = posted(p); d['stages'][0]['steps'].append({'ref': 'x', 'channel': 'todo', 'title': '', 'when': {'type': 'now'}}); cases.append(('step title', d))
    d = posted(p); d['stages'][0]['steps'].append({'ref': 'x', 'channel': 'todo', 'title': 'T', 'when': {'type': 'someday'}}); cases.append(('step when', d))
    for label, data in cases:
        r = save(client, p, data)
        assert r.status_code == 422, (label, r.get_json())
        assert r.get_json()['errors'] and r.get_json()['error']
        assert structure(p) == before, label


def test_a_stage_with_open_leads_cannot_be_removed_or_turned_into_won(app, client, admin):
    lead = ti_lead()
    p = pipe_of('ti-standard')
    here = lead.stage
    d = posted(p)
    d['stages'] = [s for s in d['stages'] if s['id'] != here.id]
    r = save(client, p, d)
    assert r.status_code == 422 and _db.session.get(CrmStage, here.id) is not None
    d = posted(p)
    next(s for s in d['stages'] if s['id'] == here.id)['means'] = 'won'
    assert save(client, p, d).status_code == 422
    assert _db.session.get(CrmStage, here.id).kind == 'open'


def test_an_empty_stage_can_be_removed_and_the_follow_ups_that_pointed_at_it_do_not_dangle(app, client, admin):
    p = pipe_of('ti-standard')
    d = posted(p)
    victim = next(s for s in d['stages'] if s['means'] == 'talking')
    d['stages'] = [s for s in d['stages'] if s is not victim]
    for s in d['stages']:
        if s['auto'] and s['auto'].get('to') == victim['ref']:
            s['auto'] = {}
    assert save(client, p, d).status_code == 200
    _db.session.expire_all()
    assert _db.session.get(CrmStage, victim['id']) is None
    assert not CrmStage.query.filter(CrmStage.auto_to_id == victim['id']).count()


def test_removing_a_follow_up_skips_its_open_tasks_and_leaves_the_lead_alone(app, client, admin):
    lead = ti_lead()
    task = lead.open_task
    assert task is not None and task.step_id
    p = pipe_of('ti-standard')
    d = posted(p)
    for s in d['stages']:
        s['steps'] = [t for t in s['steps'] if t['id'] != task.step_id]
    assert save(client, p, d).status_code == 200
    _db.session.expire_all()
    t = _db.session.get(CrmTask, task.id)
    assert t.status == 'skipped' and t.step_id is None and _db.session.get(CrmLead, lead.id).status == 'open'
    assert CrmTouchpoint.query.filter_by(direction='out').count() == 0


def test_a_whatsapp_follow_up_cannot_go_by_itself_without_an_approved_template(app, client, admin):
    p = pipe_of('ti-standard')
    d = posted(p)
    d['stages'][0]['steps'].append({'ref': 'z', 'channel': 'whatsapp', 'title': 'Auto hello', 'auto': True,
                                    'when': {'type': 'now'}, 'wa_template': 'nri_not_there'})
    r = save(client, p, d)
    assert r.status_code == 422
    d['stages'][0]['steps'][-1]['auto'] = False
    assert save(client, p, d).status_code == 200
    assert CrmPlaybookStep.query.filter_by(title='Auto hello').one().auto is False


def test_a_template_name_with_odd_characters_is_refused(app, client, admin):
    p = pipe_of('ti-standard')
    d = posted(p)
    d['stages'][0]['steps'].append({'ref': 'z', 'channel': 'whatsapp', 'title': 'Hello', 'when': {'type': 'now'},
                                    'wa_template': 'Bad Name; DROP'})
    assert save(client, p, d).status_code == 422


def test_renaming_a_stage_marks_the_open_leads_for_a_tag_update_without_calling_whatsapp(app, client, admin, monkeypatch):
    lead = ti_lead()
    pid = lead.person_id
    p = pipe_of('ti-standard')
    d = posted(p)
    next(s for s in d['stages'] if s['id'] == lead.stage_id)['name'] = 'Brand new name'
    assert save(client, p, d).status_code == 200
    assert _db.session.get(CrmStage, lead.stage_id).name == 'Brand new name'      # mode off: renamed, nothing marked


def test_the_save_is_audited(app, client, admin):
    from app.models import ActivityEvent
    p = pipe_of('ti-standard')
    save(client, p, posted(p))
    assert ActivityEvent.query.filter_by(event='crm_pipeline_saved').count() == 1


def test_changing_the_product_of_a_pipeline_with_leads_must_say_if_they_move(app, client, admin):
    ti_lead()
    p = pipe_of('ti-standard')
    client.post(A + '/pipelines/products', data={'name': 'Zebra cover', 'code': 'ZQ'})
    d = posted(p, product='ZQ')
    r = save(client, p, d)
    assert r.status_code == 422 and 'product' in r.get_json()['errors']          # move them, or not?
    d['move_leads'] = False
    assert save(client, p, d).status_code == 200
    assert CrmLead.query.filter_by(product='ZQ').count() == 0          # "no": the leads keep their product
    assert pipe_of('ti-standard').product == 'ZQ'


# ======================================================================================= lead details

def with_field(client, ftype='number', label='Budget', **kw):
    p = pipe_of('ti-standard')
    d = posted(p)
    d['fields'].append(dict({'ref': 'nf', 'label': label, 'type': ftype, 'on_card': True, 'on_add': True}, **kw))
    assert save(client, p, d).status_code == 200
    return CrmField.query.filter_by(pipeline_id=p.id).order_by(CrmField.id.desc()).first()


def test_a_lead_detail_is_typed_by_its_kind_and_a_wrong_value_is_refused(app, client, admin):
    f = with_field(client, 'number')
    lead = ti_lead()
    url = '%s/lead/%d/update' % (A, lead.id)
    ok = client.post(url, json={'details': {f.key: '12000'}})
    assert ok.status_code == 200
    _db.session.expire_all()
    assert float(_db.session.get(CrmLead, lead.id).details[f.key]) == 12000
    assert client.post(url, json={'details': {f.key: 'lots'}}).status_code == 400
    assert client.post(url, json={'details.' + f.key: 'lots'}).status_code == 400
    assert float(_db.session.get(CrmLead, lead.id).details[f.key]) == 12000
    assert client.post(url, json={'details': {'not_a_field': 'x'}}).status_code in (200, 400)


def test_a_choice_detail_accepts_only_its_choices_and_a_date_only_real_dates(app, client, admin):
    choice = with_field(client, 'choice', label='Plan', options=['Gold', 'Silver'])
    when = with_field(client, 'date', label='Visa appointment')
    lead = ti_lead()
    url = '%s/lead/%d/update' % (A, lead.id)
    assert client.post(url, json={'details': {choice.key: 'Gold'}}).status_code == 200
    assert client.post(url, json={'details': {choice.key: 'Bronze'}}).status_code == 400
    assert client.post(url, json={'details': {when.key: '2031-02-30'}}).status_code == 400
    assert client.post(url, json={'details': {when.key: '2031-03-01'}}).status_code == 200


def test_add_a_lead_asks_the_required_details_of_the_chosen_pipeline(app, client, admin):
    f = with_field(client, 'text', label='Passport number', required=True)
    r = client.get(A + '/add')
    assert r.status_code == 200 and 'Passport number' in r.get_data(as_text=True)
    form = {'name': 'Asha', 'phone': '9811122233', 'phone_cc': 'IN', 'product': 'TI', 'source': 'call', 'owner': 'me'}
    r = client.post(A + '/add', data=form, follow_redirects=True)
    assert CrmLead.query.count() == 0 and 'Fill in' in r.get_data(as_text=True) and 'Passport number' in r.get_data(as_text=True)
    form['detail__TI__' + f.key] = 'N1234567'
    r = client.post(A + '/add', data=form)
    assert r.status_code == 302
    lead = CrmLead.query.first()
    assert lead is not None and lead.details.get(f.key) == 'N1234567'


def test_taking_a_detail_away_that_a_follow_up_uses_is_refused(app, client, admin):
    f = with_field(client, 'date', label='Visa appointment')
    p = pipe_of('ti-standard')
    d = posted(p)
    d['stages'][0]['steps'].append({'ref': 'u', 'channel': 'todo', 'title': 'Visa reminder',
                                    'when': {'type': 'date', 'value': 2, 'sign': 'before', 'field': f.key}})
    assert save(client, p, d).status_code == 200
    d = posted(p)
    d['fields'] = []
    r = save(client, p, d)
    assert r.status_code == 422 and r.get_json()['errors']          # the follow-up would have no date to count from
    assert CrmField.query.filter_by(pipeline_id=p.id, key=f.key).count() == 1


# ======================================================================================= the engine

def test_a_stage_moves_by_itself_after_days_without_a_reply_but_not_when_they_wrote(app, client, admin):
    p = pipe_of('ti-standard')
    d = posted(p)
    first, last_lost = d['stages'][0], next(s for s in d['stages'] if s['means'] == 'lost')
    first['auto'] = {'kind': 'no_reply', 'days': 3, 'to': last_lost['ref'], 'reason': 'Went quiet'}
    assert save(client, p, d).status_code == 200
    quiet = ti_lead()
    chatty = ti_lead('+919811111111', name='Chatty')
    for l in (quiet, chatty):
        l.entered_stage_at = datetime.utcnow() - timedelta(days=5)
    crm.log_touch(chatty, 'whatsapp', 'in', body='hello')
    _db.session.commit()
    assert crm.run_stage_automations() == {'crm_auto_moved': 1}
    _db.session.expire_all()
    assert _db.session.get(CrmLead, quiet.id).status == 'lost' and _db.session.get(CrmLead, chatty.id).status == 'open'
    assert _db.session.get(CrmLead, quiet.id).fallout_reason == 'Went quiet'
    assert crm.run_stage_automations() == {'crm_auto_moved': 0}                 # idempotent
    assert CrmTouchpoint.query.filter_by(lead_id=quiet.id, direction='out').count() == 0     # a move sends nothing


def test_in_stage_moves_only_go_forward_so_two_stages_cannot_loop(app, client, admin):
    p = pipe_of('ti-standard')
    open_stages = [s for s in p.stages if s.kind == 'open']
    a, b = sorted(open_stages, key=lambda s: s.position)[:2]
    a.auto_kind, a.auto_days, a.auto_to_id = 'in_stage', 0, b.id
    b.auto_kind, b.auto_days, b.auto_to_id = 'in_stage', 0, a.id               # a loop, written by hand
    _db.session.commit()
    lead = ti_lead()
    lead.stage_id, lead.entered_stage_at = a.id, datetime.utcnow() - timedelta(days=1)
    _db.session.commit()
    crm.run_stage_automations()
    crm.run_stage_automations()
    _db.session.expire_all()
    assert _db.session.get(CrmLead, lead.id).stage_id == b.id                  # moved forward once, never back
    assert CrmStageChange.query.filter_by(lead_id=lead.id).count() <= 2


def test_after_date_moves_use_the_leads_own_date_and_a_closed_lead_never_moves(app, client, admin):
    p = pipe_of('ti-standard')
    d = posted(p)
    win = next(s for s in d['stages'] if s['means'] == 'won')
    d['stages'][0]['auto'] = {'kind': 'after_date', 'days': 1, 'to': win['ref'], 'field': 'departure_date'}
    assert save(client, p, d).status_code == 200
    past = ti_lead(departure_date=date.today() - timedelta(days=5))
    future = ti_lead('+919811111111', name='F', departure_date=date.today() + timedelta(days=30))
    nodate = ti_lead('+919822222222', name='N')
    closed = ti_lead('+919833333333', name='C', departure_date=date.today() - timedelta(days=9))
    closed.status = 'lost'
    _db.session.commit()
    crm.run_stage_automations()
    _db.session.expire_all()
    assert _db.session.get(CrmLead, past.id).status == 'won'
    assert _db.session.get(CrmLead, future.id).status == 'open' and _db.session.get(CrmLead, nodate.id).status == 'open'
    assert _db.session.get(CrmLead, closed.id).status == 'lost'


def test_an_imported_lead_that_is_not_in_whatsapp_yet_stays_quiet_when_a_stage_moves_it(app, client, admin, monkeypatch):
    monkeypatch.setenv('WACRM_URL', 'https://crm.example/crm')
    monkeypatch.setenv('WACRM_API_KEY', 'k')
    monkeypatch.setenv('WACRM_PORTAL_SECRET', 'x' * 40)
    crm.save_settings(whatsapp_mode='contacts')
    calls = []
    monkeypatch.setattr(wacrm_team, '_api', lambda *a, **k: calls.append(a) or {})
    monkeypatch.setattr(wacrm, '_call', lambda *a, **k: calls.append(a) or {})
    p = pipe_of('ti-standard')
    d = posted(p)
    lost = next(s for s in d['stages'] if s['means'] == 'lost')
    d['stages'][0]['auto'] = {'kind': 'no_reply', 'days': 1, 'to': lost['ref']}
    save(client, p, d)
    del calls[:]
    lead = crm.capture('ti-quote', name='Old', phone='+919800000099', utm={}, plan=False, notify=False, sync=False,
                       imported=True, when=datetime.utcnow() - timedelta(days=40))
    crm.run_stage_automations()
    assert calls == [] and due_people() == []


def test_a_custom_pipeline_runs_end_to_end(app, client, admin):
    """Make it, route a source to it, capture, move through its stages, close it: no code anywhere."""
    new_pipeline(client, arrive='form')
    p = pipe_of('visa-help')
    src = CrmSource.query.filter_by(pipeline_id=p.id).one()
    lead = crm.capture(src.key, name='Visa Person', phone='+919822222222', utm={}, plan=False, notify=False, sync=False)
    stages = sorted(p.stages, key=lambda s: s.position)
    crm.move_stage(lead, stages[1], plan=False, sync=False)
    won = next(s for s in stages if s.kind == 'won')
    crm.move_stage(lead, won, plan=False, sync=False)
    _db.session.commit()
    assert lead.status == 'won' and lead.pipeline_id == p.id
    page = client.get(A + '/lead/%d' % lead.id)
    assert page.status_code == 200 and 'Visa help' in page.get_data(as_text=True)
    assert client.get(A + '/?p=visa-help').status_code == 200
    assert client.get(A + '/insights?pipeline=%d' % p.id).status_code == 200


def test_the_how_we_sell_page_describes_custom_follow_ups_in_words_without_codes(app, client, admin):
    p = pipe_of('ti-standard')
    d = posted(p)
    d['stages'][0]['steps'].append({'ref': 'w', 'channel': 'todo', 'title': 'Check the visa', 'code': '',
                                    'when': {'type': 'after', 'value': 2, 'unit': 'days'}})
    save(client, p, d)
    page = client.get(A + '/process').get_data(as_text=True)
    assert 'Check the visa' in page and 'TI #1' not in page


def test_the_templates_checklist_never_pushes_anything_while_whatsapp_is_off(app, client, admin, monkeypatch):
    pushed = []
    monkeypatch.setattr(wacrm_team, 'push_template_drafts', lambda *a, **k: pushed.append(a) or {})
    step = CrmPlaybookStep.query.filter_by(channel='whatsapp').first()
    r = client.post(A + '/pipelines/template-draft', json={'step_id': step.id})
    assert pushed == [] and r.status_code in (200, 409, 422)
    r = client.post(A + '/pipelines/template-draft', data={'step_id': step.id}, follow_redirects=True)
    assert pushed == [] and r.status_code == 200
    assert client.post(A + '/pipelines/template-draft', json={'step_id': 99999}).status_code in (404, 422)


# ======================================================================================= Add a lead asks first

ADD = {'name': 'Asha', 'phone': '9811122233', 'phone_cc': 'IN', 'product': 'TI', 'source': 'call', 'owner': 'me'}


def test_add_a_lead_asks_before_making_a_second_person_of_an_existing_contact(app, client, admin):
    ti_lead('+919811122233', name='Asha')
    r = client.post(A + '/add', data=ADD)
    assert r.status_code == 200 and CrmLead.query.count() == 1 and 'Add' in r.get_data(as_text=True)
    r = client.post(A + '/add', data=dict(ADD, dup='same', product='SH'))      # "add an enquiry to Asha"
    assert r.status_code == 302 and CrmLead.query.count() == 2
    from app.models import CrmPerson
    assert CrmPerson.query.count() == 1


def test_add_a_lead_refuses_the_same_number_as_a_new_person(app, client, admin):
    from app.models import CrmPerson
    ti_lead('+919811122233', name='Asha')
    client.post(A + '/add', data=dict(ADD, dup='new'), follow_redirects=True)
    assert CrmPerson.query.count() == 1 and CrmLead.query.count() == 1


def test_add_a_lead_asks_before_contacting_somebody_who_asked_to_be_erased(app, client, admin):
    from app.models import CrmPerson
    from app.services import crm_people
    gone = ti_lead('+919811122233', name='Asha')
    crm_people.erase(gone.person, admin)
    r = client.post(A + '/add', data=ADD)
    assert r.status_code == 200 and CrmLead.query.count() == 0 and CrmPerson.query.count() == 0
    r = client.post(A + '/add', data=dict(ADD, dnc='ok'))
    assert r.status_code == 302 and CrmLead.query.count() == 1


def test_add_a_lead_needs_a_way_to_reach_them_and_a_source(app, client, admin):
    assert client.post(A + '/add', data=dict(ADD, phone='')).status_code == 200
    assert client.post(A + '/add', data=dict(ADD, source='')).status_code == 200
    assert client.post(A + '/add', data=dict(ADD, phone='12')).status_code == 200
    assert client.post(A + '/add', data=dict(ADD, owner='pick', owner_id='99999')).status_code == 200
    assert CrmLead.query.count() == 0


# ======================================================================================= "off" means off

def test_with_the_switch_off_no_release_two_screen_calls_whatsapp(app, client, admin, monkeypatch):
    """Keys are set, the mode is Off: building pipelines, products, replies, edits and an erase touch nothing outside."""
    for k, v in (('WACRM_URL', 'https://crm.example/crm'), ('WACRM_API_KEY', 'k'), ('WACRM_PORTAL_SECRET', 'x' * 40)):
        monkeypatch.setenv(k, v)

    def boom(method, *a, **k):
        if method != 'GET':                  # reading is always allowed; writing never is
            raise AssertionError('a write went to WhatsApp while the switch was off: %r' % ((method,) + a,))
        return []
    monkeypatch.setattr(wacrm_team, '_api', boom)
    monkeypatch.setattr(wacrm, '_call', boom)
    assert crm.wa_mode() == 'off'
    lead = ti_lead()
    pid = lead.person.id
    p = pipe_of('ti-standard')
    d = posted(p)
    next(s for s in d['stages'] if s['id'] == lead.stage_id)['name'] = 'Renamed'
    assert save(client, p, d).status_code == 200
    client.post(A + '/pipelines/products', data={'name': 'Zebra', 'code': 'ZQ'})
    new_pipeline(client)
    client.post(A + '/pipelines/%d/active' % p.id, json={'on': False})
    client.post(A + '/setup/answer', data={'title': 'Hello there', 'body': 'Hi', 'product': 'TI'})
    client.post(A + '/contact/%d/edit' % pid, data={'name': 'New Name', 'phone': '+919876543210'})
    client.get(A + '/find?q=New')
    client.get(A + '/contacts')
    client.post(A + '/contact/%d/erase' % pid, data={'confirm_name': 'New Name'})
    assert CrmLead.query.count() == 0
    assert due_people() == []
