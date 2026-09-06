"""Spoken 'Languages' list and 'Site languages' stay in sync (additive, both directions)."""
from conftest import login


def test_spoken_add_syncs_site_languages(client, admin_user):
    login(client, 'admin@test.com')
    d = client.post('/admin/options/languages',
                    json={'items': [{'value': 'English'}, {'value': 'Hindi'}, {'value': 'French'}]}).get_json()
    assert d['success'] and d['sync'] and d['sync']['name'] == 'site_languages'
    codes = [r['code'] for r in d['sync']['rows']]
    assert 'fr' in codes and 'en' in codes
    fr = next(r for r in d['sync']['rows'] if r['code'] == 'fr')
    assert fr['mode'] == 'google'                       # new UI languages arrive as Google-only


def test_site_add_syncs_spoken_languages(client, admin_user):
    login(client, 'admin@test.com')
    d = client.post('/admin/options/site_languages',
                    json={'items': [{'code': 'hi', 'label': 'हिंदी', 'mode': 'babel'},
                                    {'code': 'fr', 'label': 'Français', 'mode': 'google'}]}).get_json()
    assert d['success'] and d['sync'] and d['sync']['name'] == 'languages'
    values = [r['value'] for r in d['sync']['rows']]
    assert 'French' in values and 'Hindi' in values     # Hindi was already there, French added


def test_unmapped_spoken_language_is_ignored(client, admin_user):
    login(client, 'admin@test.com')
    d = client.post('/admin/options/languages',
                    json={'items': [{'value': 'English'}, {'value': 'Sign language'}]}).get_json()
    assert d['success'] and not d['sync']               # nothing mappable to add


def test_default_spoken_list_backfills_site(client, admin_user):
    login(client, 'admin@test.com')
    from app import options
    d = client.post('/admin/options/languages',
                    json={'items': [{'value': v} for v in options.DEFAULT_LANGUAGES]}).get_json()
    assert d['sync'] and d['sync']['name'] == 'site_languages'
    codes = {r['code'] for r in d['sync']['rows']}
    assert {'sd', 'ne', 'si'} <= codes                  # Sindhi/Nepali/Sinhala join the site list
    assert not client.post('/admin/options/languages',
                           json={'items': [{'value': v} for v in options.DEFAULT_LANGUAGES]}).get_json()['sync']
