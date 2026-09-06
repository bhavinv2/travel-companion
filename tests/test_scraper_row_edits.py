"""Per-row corrections on the scraper run page: edit spellings/source before creating the post."""
from conftest import login
from app.models import ScrapeRecipe, ScrapeRun, ScrapeRow, CompanionRequest


def _mk(db, **data_over):
    rec = ScrapeRecipe(name='edits-test', start_url='http://example.test', mode='source',
                       field_mapping={'origin': 'origin', 'destination': 'destination', 'name': 'poster_name',
                                      'start': 'start', 'contact': 'contact'},
                       default_source='website')
    db.session.add(rec)
    db.session.flush()
    run = ScrapeRun(recipe_id=rec.id, kind='run', status='done')
    db.session.add(run)
    db.session.flush()
    data = {'origin': 'Hyderbad', 'destination': 'Dallas (DFW)', 'name': 'Priya Sharna',
            'start': '2099-12-01', 'contact': 'priya@example.com', '_key': 'k1', '_url': 'http://example.test/1'}
    data.update(data_over)
    row = ScrapeRow(recipe_id=rec.id, run_id=run.id, row_index=0, key='k1', status='new', data=data)
    db.session.add(row)
    db.session.commit()
    return rec, run, row


def test_row_edit_fixes_values_and_flows_into_the_post(client, db, admin_user):
    rec, run, row = _mk(db)
    login(client, 'admin@test.com')
    d = client.get(f'/cs/scraper/api/rows/{row.id}').get_json()
    assert d['editable'] and d['canon']['origin'] == 'Hyderbad' and d['base']['origin'] == 'Hyderbad'
    assert any(f['key'] == 'origin' for f in d['fields']) and any(f['key'] == 'source' for f in d['fields'])
    # save corrections: spelling fixes + source override; unknown keys are ignored
    r = client.post(f'/cs/scraper/api/rows/{row.id}/edit',
                    json={'edits': {'origin': 'Hyderabad', 'poster_name': 'Priya Sharma',
                                    'source': 'facebook', 'bogus': 'x', 'destination': 'Dallas (DFW)'}})
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert set(d['edits']) == {'origin', 'poster_name', 'source'}          # unchanged + unknown dropped
    assert d['mapped']['flying_from'] == 'Hyderabad (HYD)'                  # corrected value normalises now
    assert d['mapped']['poster_name'] == 'Priya Sharma' and d['mapped']['source'] == 'facebook'
    detail = client.get(f'/cs/scraper/api/rows/{row.id}').get_json()
    assert detail['canon']['origin'] == 'Hyderabad' and detail['base']['origin'] == 'Hyderbad'
    # run page marks the row as edited
    page = client.get(f'/cs/scraper/runs/{run.id}?status=all').data.decode()
    assert 'edited' in page and 'Priya Sharma' in page
    # creating the post uses the corrections
    from app.services import scraper as scraper_svc
    res = scraper_svc.create_posts(rec, [row.id], admin_user)
    assert res['created'] == 1, res
    trip = db.session.get(CompanionRequest, res['post_ids'][0])
    assert trip.flying_from == 'Hyderabad (HYD)' and trip.poster_name == 'Priya Sharma'
    assert trip.source == 'facebook' and trip.status == 'unconfirmed'
    # once it is a post, the row can no longer be edited
    assert client.post(f'/cs/scraper/api/rows/{row.id}/edit', json={'edits': {}}).status_code == 400
    assert client.get(f'/cs/scraper/api/rows/{row.id}').get_json()['editable'] is False


def test_row_edit_clear_and_reset(client, db, admin_user):
    rec, run, row = _mk(db)
    login(client, 'admin@test.com')
    # clearing a field drops the mapped value
    d = client.post(f'/cs/scraper/api/rows/{row.id}/edit', json={'edits': {'poster_name': ''}}).get_json()
    assert d['edits'] == {'poster_name': ''} and not d['mapped'].get('poster_name')
    # re-typing the original value un-edits the field
    d = client.post(f'/cs/scraper/api/rows/{row.id}/edit', json={'edits': {'poster_name': 'Priya Sharna'}}).get_json()
    assert d['edits'] == {} and d['mapped']['poster_name'] == 'Priya Sharna'
    # reset removes everything
    client.post(f'/cs/scraper/api/rows/{row.id}/edit', json={'edits': {'origin': 'Delhi'}})
    d = client.post(f'/cs/scraper/api/rows/{row.id}/edit', json={'edits': {}}).get_json()
    assert d['edits'] == {} and d['mapped']['flying_from'] == 'Hyderbad'


def test_row_edit_admin_only(client, db, admin_user, user):
    rec, run, row = _mk(db)
    login(client, 'bob@test.com')
    assert client.post(f'/cs/scraper/api/rows/{row.id}/edit', json={'edits': {}}).status_code in (302, 403, 404)
