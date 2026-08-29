import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db as _db  # noqa: E402
from app.models import User  # noqa: E402


@pytest.fixture()
def app(tmp_path):
    app = create_app({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SQLALCHEMY_DATABASE_URI': 'sqlite://',
        'UPLOAD_FOLDER': str(tmp_path / 'uploads'),
        'PRIVATE_UPLOAD_FOLDER': str(tmp_path / 'private'),
        'SERVER_NAME': 'localhost',
        'MAIL_PASSWORD': None,
    })
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def db(app):
    return _db


@pytest.fixture()
def client(app):
    return app.test_client()


def make_user(email, username, role='user', password='password123'):
    u = User(email=email, username=username, first_name=username.title(), role=role, is_admin=(role == 'admin'))
    u.set_password(password)
    _db.session.add(u)
    _db.session.commit()
    return u


@pytest.fixture()
def user(app):
    return make_user('bob@test.com', 'bob')


@pytest.fixture()
def other_user(app):
    return make_user('alice@test.com', 'alice')


@pytest.fixture()
def cs_user(app):
    return make_user('cs@test.com', 'csagent', role='cs')


@pytest.fixture()
def admin_user(app):
    return make_user('admin@test.com', 'admin', role='admin')


def login(client, email, password='password123'):
    return client.post('/auth/login', data={'email': email, 'password': password})


def logout(client):
    return client.get('/auth/logout')


TRIP_JSON = {
    'trip_type': 'one_way', 'role': 'seeking_help',
    'flying_from': 'Hyderabad (HYD)', 'destination': 'Dallas (DFW)', 'from_date': '2099-12-01',
    'airline': 'Qatar Airways', 'flight_number': 'QR573', 'preferred_languages': ['Telugu'],
    'contact_points': [{'type': 'auto', 'value': '+1 214 555 0100', 'label': ''}],
    'contact_consent': True,
}
