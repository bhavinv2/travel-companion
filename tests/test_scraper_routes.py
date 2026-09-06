"""Scraper console routes (admin-only), end-to-end with fakes for fetchall."""
import json
import re

from conftest import login, logout
from app import db
from app.models import ScrapeRecipe, ScrapeRun, ScrapeRow, CompanionRequest
from app.services import scraper_worker
from app.vendor.fetchall.models import Table, Candidate, Inspection
from test_scraper import RECIPE, FakeRunner, fake_rows, COLUMNS  # noqa: F401  (fixtures re-exported below)
from test_scraper import scraper_ready, recipe  # noqa: F401


def test_scraper_pages_require_admin(client, user, cs_user):
    assert client.get('/cs/scraper/').status_code == 302
    login(client, 'cs@test.com')
    assert client.get('/cs/scraper/').status_code == 302          # cs role is not enough
    logout(client)
    login(client, 'bob@test.com')
    assert client.get('/cs/scraper/new').status_code == 302


def test_disabled_scraper_is_404(client, app, admin_user):
    app.config['SCRAPER_ENABLED'] = False
    login(client, 'admin@test.com')
    assert client.get('/cs/scraper/').status_code == 404


def test_unavailable_banner_and_503(client, app, admin_user, recipe):
    app.config.update(SCRAPER_FORCE_AVAILABLE=False, SCRAPER_INLINE=True)
    login(client, 'admin@test.com')
    r = client.get('/cs/scraper/')
    assert r.status_code == 200 and b'cannot run on this server' in r.data
    assert client.post(f'/cs/scraper/recipes/{recipe.id}/run', json={}).status_code == 503
    r = client.post(f'/cs/scraper/recipes/{recipe.id}/run', data={})
    assert r.status_code == 302                                  # flash + redirect for form posts


def test_detect_flow_creates_source_recipe_with_mapping(client, app, admin_user, monkeypatch):
    app.config.update(SCRAPER_INLINE=True, SCRAPER_FORCE_AVAILABLE=True)
    table = Table(columns=['title', 'origin', 'destination', 'start', 'contact', 'message'],
                  rows=[{'title': f'T{i}', 'origin': 'HYD', 'destination': 'DFW', 'start': '2099-01-0%d' % (i + 1),
                         'contact': f'a{i}@x.com', 'message': 'hi'} for i in range(3)])
    insp = Inspection(url='https://example.test/', final_url='https://example.test/', title='Example',
                      candidates=[Candidate(kind='csv', source='https://example.test/data.csv', table=table)],
                      responses_seen=3, visible_text='T0 HYD DFW')
    monkeypatch.setattr(scraper_worker, '_inspect', lambda url, **kw: insp)
    monkeypatch.setattr(scraper_worker, '_fetch_direct', lambda url: Candidate(kind='csv', source=url, table=table))
    login(client, 'admin@test.com')
    assert client.get('/cs/scraper/new').status_code == 200
    r = client.post('/cs/scraper/new', data={'url': 'https://example.test/', 'name': 'example-csv', 'default_source': 'website', 'wait': '2'})
    assert r.status_code == 302
    run_id = int(r.headers['Location'].rstrip('/').split('/')[-1])
    r = client.get(f'/cs/scraper/new/{run_id}')
    assert r.status_code == 200 and b'Use this source' in r.data and b'data.csv' in r.data
    r = client.post(f'/cs/scraper/new/{run_id}/use-source', data={'candidate': '0'})
    assert r.status_code == 302 and '/mapping' in r.headers['Location']
    rec = ScrapeRecipe.query.filter_by(name='example-csv').first()
    assert rec.mode == 'source' and rec.field_mapping['origin'] == 'origin' and rec.field_mapping['contact'] == 'contact'
    assert rec.field_mapping['_key'] == 'import_key'
    assert client.get(f'/cs/scraper/recipes/{rec.id}/mapping').status_code == 200
    # run it (source mode -> fetch_direct) and review rows
    r = client.post(f'/cs/scraper/recipes/{rec.id}/run', data={})
    run_id = int(r.headers['Location'].rstrip('/').split('/')[-1])
    r = client.get(f'/cs/scraper/runs/{run_id}')
    assert r.status_code == 200 and b'Create posts' in r.data and ScrapeRow.query.filter_by(run_id=run_id).count() == 3
    st = client.get(f'/cs/scraper/api/runs/{run_id}/status').get_json()
    assert st['done'] and st['status'] == 'done' and st['progress']['rows_new'] == 3


def test_recipe_editor_validation_preview_and_save(client, app, admin_user, scraper_ready):
    login(client, 'admin@test.com')
    assert client.get('/cs/scraper/recipes/new').status_code == 200
    r = client.post('/cs/scraper/recipes/new', data={'name': 'x', 'recipe_json': '{not json'})
    assert r.status_code == 200 and b'not valid' in r.data
    r = client.post('/cs/scraper/recipes/new', data={'name': 'x', 'recipe_json': json.dumps({'start_url': 'nope'})})
    assert r.status_code == 200 and b'list.row' in r.data
    r = client.post('/cs/scraper/api/recipes/preview', json={'recipe': {'start_url': 'x'}})
    assert r.status_code == 400
    r = client.post('/cs/scraper/api/recipes/preview', json={'recipe': RECIPE})
    assert r.status_code == 200
    st = client.get(f"/cs/scraper/api/runs/{r.get_json()['run_id']}/status").get_json()
    assert st['done'] and len(st['result']['rows']) == 3 and st['result']['report']['status'] == 'ok'
    r = client.post('/cs/scraper/recipes/new', data={'name': 'taught', 'recipe_json': json.dumps(RECIPE), 'default_source': 'facebook'})
    assert r.status_code == 302 and '/mapping' in r.headers['Location']
    rec = ScrapeRecipe.query.filter_by(name='taught').first()
    assert rec.mode == 'recipe' and rec.default_source == 'facebook' and rec.field_mapping['contact'] == 'contact'
    # mapping page save
    r = client.post(f'/cs/scraper/recipes/{rec.id}/mapping', data={'map__title': 'message', 'map__origin': 'origin',
                                                                     'map__destination': 'destination', 'map__start': 'start',
                                                                     'map__contact': 'contact', 'map__bogus': 'title',
                                                                     'default_source': 'website'})
    assert r.status_code == 302
    rec = db.session.get(ScrapeRecipe, rec.id)
    assert rec.field_mapping['title'] == 'message' and rec.field_mapping['flight'] == 'ignore' and 'bogus' not in rec.field_mapping


def test_run_review_create_posts_skip_export(client, app, admin_user, scraper_ready, recipe):
    login(client, 'admin@test.com')
    assert client.get(f'/cs/scraper/recipes/{recipe.id}/runs').status_code == 200
    r = client.post(f'/cs/scraper/recipes/{recipe.id}/run', data={'incremental': 'on', 'max_rows': ''})
    run_id = int(r.headers['Location'].rstrip('/').split('/')[-1])
    r = client.get(f'/cs/scraper/runs/{run_id}?status=new')
    html = r.data.decode()
    assert 'Hyderabad (HYD)' in html and 'Qatar Airways' in html and html.count('class="inc"') == 3
    rows = ScrapeRow.query.filter_by(run_id=run_id).order_by(ScrapeRow.id).all()

    # single row -> post
    r = client.post(f'/cs/scraper/runs/{run_id}/create-posts', data={'include': [str(rows[0].id)]})
    assert r.status_code == 302 and 'status=imported' in r.headers['Location']
    assert CompanionRequest.query.count() == 1 and db.session.get(ScrapeRow, rows[0].id).status == 'imported'
    # bulk: all remaining new rows, published immediately
    r = client.post(f'/cs/scraper/runs/{run_id}/create-posts', data={'select': 'all_new', 'publish_now': 'on'})
    assert r.status_code == 302
    posts = CompanionRequest.query.order_by(CompanionRequest.id).all()
    assert len(posts) == 3 and posts[0].status == 'unconfirmed' and posts[1].status == 'open' and posts[2].status == 'open'
    assert all(p.source_url == 'https://example.test/list' for p in posts)
    r = client.get(f'/cs/scraper/runs/{run_id}?status=imported')
    assert r.data.decode().count('chip-open">imported') == 3
    # nothing left to create
    r = client.post(f'/cs/scraper/runs/{run_id}/create-posts', data={'select': 'all_new'})
    assert r.status_code == 302 and 'status=new' in r.headers['Location']

    # row detail JSON + export
    d = client.get(f'/cs/scraper/api/rows/{rows[0].id}').get_json()
    assert d['row']['key'] == 'key000' and d['mapped']['flying_from'].endswith('(HYD)')
    r = client.get(f'/cs/scraper/runs/{run_id}/export.xlsx?mapped=1')
    assert r.status_code == 200 and r.headers['Content-Disposition'].endswith('.xlsx') and r.data[:2] == b'PK'
    r = client.get(f'/cs/scraper/runs/{run_id}/export.xlsx?ids={rows[0].id},{rows[1].id}')
    assert r.status_code == 200 and r.data[:2] == b'PK'
    r = client.get(f'/cs/scraper/recipes/{recipe.id}/export.xlsx')
    assert r.status_code == 200


def test_skip_cancel_toggle_delete(client, app, admin_user, scraper_ready, recipe):
    login(client, 'admin@test.com')
    r = client.post(f'/cs/scraper/recipes/{recipe.id}/run', data={})
    run_id = int(r.headers['Location'].rstrip('/').split('/')[-1])
    rows = ScrapeRow.query.filter_by(run_id=run_id).all()
    r = client.post(f'/cs/scraper/runs/{run_id}/skip', data={'include': [str(rows[0].id)]})
    assert r.status_code == 302 and db.session.get(ScrapeRow, rows[0].id).status == 'skipped'
    # cancel on a finished run is a no-op; on a queued run it cancels
    r = client.post(f'/cs/scraper/runs/{run_id}/cancel', json={})
    assert r.get_json()['success']
    queued = ScrapeRun(recipe_id=None, kind='detect', status='queued', options={'url': 'https://x'})
    db.session.add(queued)
    db.session.commit()
    client.post(f'/cs/scraper/runs/{queued.id}/cancel', json={})
    assert db.session.get(ScrapeRun, queued.id).status == 'cancelled'
    r = client.post(f'/cs/scraper/recipes/{recipe.id}/toggle', data={'what': 'schedule', 'every_hours': '6'})
    rec = db.session.get(ScrapeRecipe, recipe.id)
    assert rec.schedule_enabled and rec.schedule_every_hours == 6
    r = client.post(f'/cs/scraper/recipes/{recipe.id}/delete', data={})
    assert r.status_code == 302 and db.session.get(ScrapeRecipe, recipe.id) is None
    assert ScrapeRow.query.count() == 0


def test_open_scraped_row_in_post_form_marks_it_imported(client, app, admin_user, scraper_ready, recipe):
    login(client, 'admin@test.com')
    r = client.post(f'/cs/scraper/recipes/{recipe.id}/run', data={})
    run_id = int(r.headers['Location'].rstrip('/').split('/')[-1])
    row = ScrapeRow.query.filter_by(run_id=run_id).first()
    r = client.get(f'/cs/posts/new?scrape_row={row.id}')
    html = r.data.decode()
    assert r.status_code == 200 and 'Hyderabad (HYD)' in html and f'name="scrape_row_id" value="{row.id}"' in html
    r = client.post('/cs/posts/new', data={
        'source': 'website', 'poster_name': 'Someone', 'role': 'seeking_help', 'trip_type': 'one_way',
        'flying_from': 'Hyderabad (HYD)', 'destination': 'Dallas (DFW)', 'from_date': '2099-12-01',
        'contact_type': ['auto'], 'contact_value': ['+1 214 555 0100'], 'contact_label': [''],
        'scrape_row_id': str(row.id),
    })
    assert r.status_code == 302
    row = db.session.get(ScrapeRow, row.id)
    assert row.status == 'imported' and row.imported_post_id
    assert db.session.get(CompanionRequest, row.imported_post_id).import_key == row.key


def test_jobs_endpoint_reports_scraper_counters(client, app, admin_user, scraper_ready, recipe):
    app.config['JOBS_SECRET'] = 's'
    r = client.post('/internal/jobs/run', headers={'X-Jobs-Secret': 's'})
    d = r.get_json()
    assert 'scrape_stale_recovered' in d and 'scrape_runs_started' in d and 'scrape_rows_purged' in d
