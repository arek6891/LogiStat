"""Wspolna konfiguracja testow.

`app.py` tworzy `app` i odpala `init_db()` na poziomie modulu, wiec DATABASE_URL
musi byc ustawiony PRZED importem. Kazdy test dostaje czysta baze (drop_all +
create_all + seed), zeby kolejnosc testow nie miala znaczenia.

Od 2026-09 testy chodza na PostgreSQL — tym samym silniku co produkcja, bo
aplikacja nie wspiera juz SQLite. Baze podnosi:

    docker compose -f docker-compose.test.yml up -d

Inna baza: LOGISTAT_TEST_DATABASE_URL=postgresql+psycopg2://... pytest
"""
import os
import sys

import pytest
from flask import g
from flask.testing import FlaskClient

# Sciezka do repo + baza testowa musza byc gotowe przed importem app.py.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Zgodne z docker-compose.test.yml (port 55432, zeby nie kolidowac z lokalnym
# Postgresem na 5432).
DOMYSLNA_BAZA_TESTOWA = (
    'postgresql+psycopg2://logistat:logistat@127.0.0.1:55432/logistat_test')

os.environ['DATABASE_URL'] = (
    os.environ.get('LOGISTAT_TEST_DATABASE_URL', '').strip() or DOMYSLNA_BAZA_TESTOWA)
os.environ.setdefault('SECRET_KEY', 'test-secret-key')

try:
    from app import app as aplikacja  # noqa: E402  (import po ustawieniu env — init_db)
except Exception as blad:  # pragma: no cover — tylko gdy baza nie odpowiada
    raise RuntimeError(
        f"Nie udalo sie polaczyc z baza testowa ({os.environ['DATABASE_URL']}).\n"
        'LogiStat dziala wylacznie na PostgreSQL — podnies baze testowa:\n'
        '    docker compose -f docker-compose.test.yml up -d\n'
        f'Blad zrodlowy: {blad}'
    ) from blad

# Po imporcie app (env ustawiony, init_db zrobiony). `db` jako nazwa zajeta przez
# fixture ponizej — stad alias.
from logistat.baza import seed_data  # noqa: E402
from logistat.extensions import db as baza_danych  # noqa: E402
from logistat.models import Activity, SzkolenieCzynnosci, User  # noqa: E402


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
    aplikacja.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    aplikacja.test_client_class = IsolatedClient
    with aplikacja.app_context():
        baza_danych.drop_all()
        baza_danych.create_all()
        seed_data()
        yield aplikacja
        baza_danych.session.remove()


@pytest.fixture
def db(flask_app):
    return baza_danych


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


# ── Fabryki ──────────────────────────────────────────────────────────────────

PASSWORD = 'test-pass-123'


def make_user(role='operator', username=None, barcode_id=None, display_name=None,
              przeszkolony=False):
    """Utworz uzytkownika i zwroc go (juz w bazie).

    `przeszkolony=True` — szkolenie ze wszystkich czynnosci (bez niego
    `POST /api/assignment/save` odrzuca nowy przydzial).
    """
    username = username or f'{role}-{os.urandom(4).hex()}'
    user = User(
        username=username,
        display_name=display_name or username.upper(),
        role=role,
        barcode_id=barcode_id,
    )
    if role in ('stanowisko', 'leader', 'admin'):
        user.set_password(PASSWORD)
    baza_danych.session.add(user)
    baza_danych.session.commit()
    if przeszkolony:
        for a in Activity.query.all():
            baza_danych.session.add(SzkolenieCzynnosci(user_id=user.id, activity_id=a.id))
        baza_danych.session.commit()
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

    engine = baza_danych.engine
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


def strona_z_js(client, url):
    """HTML strony + tresc jej skryptow z `static/js/` (od 2026-10-16 JS nie
    siedzi w szablonach). Do testow, ktore sprawdzaja, co robi skrypt strony."""
    import re
    r = client.get(url)
    assert r.status_code == 200, (url, r.status_code)
    html = r.get_data(as_text=True)
    katalog = os.path.join(os.path.dirname(__file__), '..', 'static')
    skrypty = []
    for sciezka in re.findall(r'<script src="/static/(js/[^"?]+)', html):
        with open(os.path.join(katalog, sciezka), encoding='utf-8') as f:
            skrypty.append(f.read())
    return html + '\n' + '\n'.join(skrypty)
