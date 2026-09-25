"""The database URL a host hands us must not decide which library has to be installed.

SQLAlchemy 2.1 changed what a bare `postgresql://` means: psycopg2 on 2.0, psycopg 3 on 2.1. The
dependency was unpinned, so a rebuild of an unchanged commit swapped the driver, every gunicorn
worker died at import with "No module named 'psycopg'", and the site went down behind a 502 that
pointed at nothing. The URL now names the driver we actually ship, whatever the default is.
"""
import pytest

from app import create_app


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    # monkeypatch so DATABASE_URL is restored afterwards: create_app reads it at call time, and
    # leaking it would point every later test at a database that does not exist
    monkeypatch.setenv('SECRET_KEY', 'x' * 40)
    return {'MAIL_PASSWORD': None, 'UPLOAD_FOLDER': str(tmp_path / 'u'),
            'PRIVATE_UPLOAD_FOLDER': str(tmp_path / 'p')}


@pytest.mark.parametrize('given, expected_uri', [
    # the production failure: a driver we do not ship
    ('postgresql+psycopg://u:p@h:5432/db', 'postgresql+psycopg2://u:p@h:5432/db'),
    # Heroku-style legacy scheme, already handled
    ('postgres://u:p@h:5432/db', 'postgresql+psycopg2://u:p@h:5432/db'),
    ('postgresql://u:p@h:5432/db', 'postgresql+psycopg2://u:p@h:5432/db'),
    # a driver we DO ship is left exactly as asked for
    ('postgresql+psycopg2://u:p@h:5432/db', 'postgresql+psycopg2://u:p@h:5432/db'),
])
def test_the_url_resolves_to_a_driver_that_is_installed(monkeypatch, cfg, given, expected_uri):
    monkeypatch.setenv('DATABASE_URL', given)
    app = create_app(cfg)
    assert app.config['SQLALCHEMY_DATABASE_URI'] == expected_uri
    with app.app_context():
        # the real proof: the engine builds at all, which is what failed in production
        assert app.extensions['sqlalchemy'].engine.dialect.driver == 'psycopg2'


def test_sqlite_is_untouched(monkeypatch, cfg, tmp_path):
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + str(tmp_path / 'x.db').replace('\\', '/'))
    app = create_app(cfg)
    assert app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite:///')
