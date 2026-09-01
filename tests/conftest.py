"""Wspolna konfiguracja testow.

`app.py` tworzy `app` i odpala `init_db()` na poziomie modulu, wiec DATABASE_URL
musi byc ustawiony PRZED importem. Kazdy test dostaje czysta baze (drop_all +
create_all + seed), zeby kolejnosc testow nie mialy znaczenia.
"""
import os
import sys
import tempfile

import pytest
from flask import g
from flask.testing import FlaskClient

# Sciezka do repo + baza testowa muszą być gotowe przed importem app.py.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_DB_FD, _DB_PATH = tempfile.mkstemp(suffix='.db', prefix='logistat-test-')
os.close(_DB_FD)
os.environ['DATABASE_URL'] = f'sqlite:///{_DB_PATH}'
os.environ.setdefault('SECRET_KEY', 'test-secret-key')

import app as logistat  # noqa: E402  (import po ustawieniu env)


def pytest_unconfigure(config):
    for suffix in ('', '-wal', '-shm'):
        try:
            os.unlink(_DB_PATH + suffix)
        except OSError:
            pass


class IsolatedClient(FlaskClient):
    """Klient, ktory nie dziedziczy zalogowanego uzytkownika po innym kliencie.

    Fixture trzyma jeden app context na caly test, a Flask reuzywa go dla
    kazdego zadania test-clienta — wiec `g` jest wspolne. Flask-Login cache'uje
    uzytkownika w `g._login_user` i nie przeladowuje go, jesli jest ustawiony,
    co przeciekaloby miedzy dwoma klientami w jednym tescie (test uprawnien
    widzialby nie te role, ktora testuje). Czyscimy cache przed kazdym zadaniem.
    """

    def open(self, *args, **kwargs):
        g.pop('_login_user', None)
        # Produkcja dostaje swiezy app context (a wiec i `g`) na kazde zadanie;
        # tu context jest wspolny, wiec czyscimy cache stawek recznie.
        g.pop('_rates_cache', None)
        return super().open(*args, **kwargs)


@pytest.fixture
def flask_app():
    """Czysta baza na kazdy test."""
    logistat.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    logistat.app.test_client_class = IsolatedClient
    with logistat.app.app_context():
        logistat.db.drop_all()
        logistat.db.create_all()
        logistat.seed_data()
        yield logistat.app
        logistat.db.session.remove()


@pytest.fixture
def db(flask_app):
    return logistat.db


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


# ── Fabryki ──────────────────────────────────────────────────────────────────

PASSWORD = 'test-pass-123'


def make_user(role='operator', username=None, barcode_id=None, display_name=None):
    """Utworz uzytkownika i zwroc go (juz w bazie)."""
    username = username or f'{role}-{os.urandom(4).hex()}'
    user = logistat.User(
        username=username,
        display_name=display_name or username.upper(),
        role=role,
        barcode_id=barcode_id,
    )
    if role in ('leader', 'admin'):
        user.set_password(PASSWORD)
    logistat.db.session.add(user)
    logistat.db.session.commit()
    return user


def login(client, username, password=PASSWORD):
    return client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=False)


@pytest.fixture
def admin(flask_app):
    return make_user('admin', username='test-admin')


@pytest.fixture
def leader(flask_app):
    return make_user('leader', username='test-leader')


@pytest.fixture
def admin_client(client, admin):
    login(client, admin.username)
    return client


@pytest.fixture
def leader_client(client, leader):
    login(client, leader.username)
    return client


class QueryCounter:
    """Licznik zapytan SQL — pilnuje, zeby N+1 nie wrocilo."""

    def __init__(self):
        self.statements = []

    @property
    def count(self):
        return len(self.statements)

    @property
    def selects(self):
        """Tylko odczyty — INSERT-ow jest z natury tyle, ile wierszy."""
        return [q for q in self.statements if q.lstrip().upper().startswith('SELECT')]

    def matching(self, fragment):
        return [q for q in self.statements if fragment.lower() in q.lower()]


@pytest.fixture
def queries(flask_app):
    from sqlalchemy import event

    counter = QueryCounter()

    def before(conn, cursor, statement, params, context, executemany):
        counter.statements.append(statement)

    engine = logistat.db.engine
    event.listen(engine, 'before_cursor_execute', before)
    try:
        yield counter
    finally:
        event.remove(engine, 'before_cursor_execute', before)


@pytest.fixture
def acting_admin(flask_app, admin):
    """Kontekst zadania z zalogowanym adminem — dla bezposrednich wywolan
    helperow, ktore czytaja `current_user` (np. process_import_rows)."""
    from flask_login import login_user
    with flask_app.test_request_context():
        login_user(admin)
        yield admin
