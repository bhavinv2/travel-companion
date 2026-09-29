"""Can this deployment be asked whether its database matches its code?

Written after a 500 that took an afternoon to place from the outside: the container was running
new code against a database whose migrations had not run, so every page worked except the one
that touched the new table, and the response said nothing about why.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import login  # noqa: E402


def test_it_answers_without_signing_in(client, db):
    """A health check that needs a session is no use to a platform's health probe."""
    r = client.get('/healthz')
    assert r.status_code in (200, 503)
    assert 'status' in r.get_json()


def test_the_public_answer_says_nothing_about_the_schema(client, db):
    """Naming your revisions to the world is free reconnaissance, and only somebody who can fix
    it has any use for them."""
    body = client.get('/healthz').get_json()
    assert set(body) == {'status'}


def test_an_admin_is_told_what_is_wrong(client, db, admin_user):
    """The detail is the point: "degraded" alone would have saved nobody any time."""
    login(client, 'admin@test.com')
    body = client.get('/healthz').get_json()
    assert body['database'] == 'ok'
    assert 'migration' in body
    assert set(body['migration']) >= {'current', 'head'}


def test_a_database_behind_the_code_is_not_healthy(client, db, admin_user, monkeypatch):
    """The failure this exists for: the process is up, the database answers, and the schema is
    from the previous deploy. Simulated rather than left to the suite's own state, because a
    test that only checks the failure when it happens to occur checks nothing."""
    from app.routes import files as files_routes
    monkeypatch.setattr(files_routes, '_migration_state', lambda app, db_: ('k1rev001', 'l1rep001'))

    login(client, 'admin@test.com')
    r = client.get('/healthz')
    body = r.get_json()
    assert r.status_code == 503
    assert body['status'] == 'degraded'
    assert body['migration'] == {'current': 'k1rev001', 'head': 'l1rep001',
                                 'problem': 'the database is behind the code; '
                                            'run "flask db upgrade" on this deployment'}


def test_an_unstamped_database_is_reported_but_not_failed(client, db, admin_user):
    """create_all() leaves no alembic stamp. That is the development and test shape, where the
    schema does match the code, so it is information rather than an alarm."""
    login(client, 'admin@test.com')
    r = client.get('/healthz')
    assert r.status_code == 200
    assert r.get_json()['migration']['current'] is None


def test_a_degraded_deployment_still_answers_the_public(client, db, monkeypatch):
    """A probe needs a status code it can act on, not a stack trace."""
    from app.routes import files as files_routes
    monkeypatch.setattr(files_routes, '_migration_state', lambda app, db_: ('k1rev001', 'l1rep001'))
    r = client.get('/healthz')
    assert r.status_code == 503
    assert r.get_json() == {'status': 'degraded'}
