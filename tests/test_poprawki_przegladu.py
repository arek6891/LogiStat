"""Poprawki z przegladu architektury (2026-10-16).

- `?next=` po zalogowaniu tylko jako sciezka tej aplikacji (open redirect);
- logowanie domyslnym haslem admina wymusza jego zmiane;
- nazwa kategorii z cudzyslowem / backslashem nie psuje JS na stronach;
- `migrate_columns()` nie polyka bledu — start pada z nazwa kolumny.
"""
import json
import re
from datetime import datetime

import pytest
from conftest import PASSWORD, login, make_user

from logistat import baza
from logistat.baza import migrate_columns
from logistat.config import DEFAULT_ADMIN_PASSWORD
from logistat.extensions import db
from logistat.models import ProbaLogowania
from logistat.web import auth

# ── open redirect ────────────────────────────────────────────────────────────

@pytest.mark.parametrize('nastepna,oczekiwane', [
    ('/paczki', '/paczki'),
    ('https://zla-strona.example/', '/start'),
    ('//zla-strona.example/', '/start'),
    ('/\\zla-strona.example', '/start'),
    ('javascript:alert(1)', '/start'),
])
def test_next_po_zalogowaniu_tylko_lokalny(client, nastepna, oczekiwane):
    lider = make_user('leader')
    r = client.post('/login?next=' + nastepna,
                    data={'username': lider.username, 'password': PASSWORD})

    assert r.status_code == 302
    assert r.headers['Location'] == oczekiwane


# ── domyslne haslo ───────────────────────────────────────────────────────────

def admin_z_domyslnym_haslem():
    u = make_user('admin', username='admin-domyslne')
    u.set_password(DEFAULT_ADMIN_PASSWORD)
    db.session.commit()
    return u


def test_domyslne_haslo_wymusza_zmiane(client):
    u = admin_z_domyslnym_haslem()

    r = login(client, u.username, DEFAULT_ADMIN_PASSWORD)

    assert r.headers['Location'] == '/profile'
    assert client.get('/dashboard').headers['Location'] == '/profile'
    assert client.get('/api/dashboard').status_code == 403
    assert client.get('/profile').status_code == 200


def test_po_zmianie_hasla_dostep_wraca(client):
    u = admin_z_domyslnym_haslem()
    login(client, u.username, DEFAULT_ADMIN_PASSWORD)

    client.post('/profile', data={'current_password': DEFAULT_ADMIN_PASSWORD,
                                  'new_password': 'nowe-haslo-1', 'confirm_password': 'nowe-haslo-1'})

    assert client.get('/dashboard').status_code == 200
    assert client.get('/api/dashboard').status_code == 200


def test_wylogowanie_dziala_przy_wymuszonej_zmianie(client):
    """Bez tego po zmianie nazw endpointow (blueprinty) /logout trafialby do
    przekierowania na /profile — petla, z ktorej nie da sie wylogowac."""
    u = admin_z_domyslnym_haslem()
    login(client, u.username, DEFAULT_ADMIN_PASSWORD)

    r = client.post('/logout')

    assert r.status_code == 302 and r.headers['Location'].startswith('/login')
    assert client.get('/dashboard').headers['Location'].startswith('/login')


def test_zwykle_haslo_bez_wymogu(client):
    lider = make_user('leader')

    login(client, lider.username)

    assert client.get('/dashboard').status_code == 200


# ── nazwy kategorii w JS ─────────────────────────────────────────────────────

ZLA_NAZWA = 'Sort "A" \\ \'B\''


def literal_js(html, nazwa):
    """Wartosc `const <nazwa> = …;` z <script> — musi byc poprawnym JSON-em."""
    m = re.search(r'const ' + nazwa + r' = (.*?);\n', html)
    assert m, f'brak const {nazwa}'
    return json.loads(m.group(1))


def test_cudzyslow_w_nazwie_kategorii_nie_psuje_mapowania_kosztow(admin_client):
    admin_client.put('/api/category-labels', json={'nazwy': {'sorting': ZLA_NAZWA}})

    html = admin_client.get('/admin/cost-mapping').get_data(as_text=True)

    assert "JSON.parse('" not in html
    assert ZLA_NAZWA in literal_js(html, 'categoryLabels')['sorting']


def test_statystyki_ogolne_bez_json_parse_w_apostrofach(admin_client):
    html = admin_client.get('/general-stats').get_data(as_text=True)

    assert "JSON.parse('" not in html
    assert literal_js(html, 'ratesByYm') == {}


# ── migrate_columns ──────────────────────────────────────────────────────────

def test_blad_migracji_kolumny_przerywa_start(flask_app, monkeypatch):
    zla = [('nie_ma_takiej_tabeli', 'kolumna', 'TEXT')]
    # migrate_columns() czyta liste ze swojego modulu (logistat/baza.py, krok 6).
    monkeypatch.setattr(baza, 'MIGRACJE_KOLUMN', zla)

    with pytest.raises(RuntimeError, match='nie_ma_takiej_tabeli.kolumna'):
        migrate_columns()


# ── Bezpieczenstwo logowania (2026-10-19) ────────────────────────────────────

def test_limit_nieudanych_logowan(client):
    """Po MAKS_PROB nieudanych probach w oknie login jest zablokowany — takze
    dla poprawnego hasla; komunikat mowi, za ile minut."""
    lider = make_user('leader')
    for _ in range(auth.MAKS_PROB_LOGOWANIA):
        assert login(client, lider.username, 'zle-haslo').status_code == 200

    r = login(client, lider.username)

    assert r.status_code == 429
    assert 'Spróbuj ponownie za' in r.get_data(as_text=True)
    assert client.get('/dashboard').status_code == 302, 'nie zalogowal sie'


def test_udane_logowanie_czysci_licznik(client):
    lider = make_user('leader')
    for _ in range(auth.MAKS_PROB_LOGOWANIA - 1):
        login(client, lider.username, 'zle-haslo')

    assert login(client, lider.username).status_code == 302
    assert ProbaLogowania.query.count() == 0


def test_blokada_mija_po_oknie(client):
    lider = make_user('leader')
    dawno = datetime.utcnow() - auth.OKNO_PROB_LOGOWANIA - auth.timedelta(minutes=1)
    for _ in range(auth.MAKS_PROB_LOGOWANIA):
        db.session.add(ProbaLogowania(login=lider.username.lower(), kiedy=dawno))
    db.session.commit()

    assert login(client, lider.username).status_code == 302


def test_api_bez_sesji_zwraca_401_json(client):
    r = client.get('/api/dashboard')

    assert r.status_code == 401
    assert r.get_json()['error'].startswith('Sesja wygasła')


def test_strona_bez_sesji_przekierowuje_do_logowania(client):
    r = client.get('/paczki?status=wszystkie')

    assert r.status_code == 302 and r.headers['Location'].startswith('/login?next=')


def test_api_bez_uprawnien_zwraca_403_json(leader_client):
    r = leader_client.get('/api/general-stats')

    assert r.status_code == 403 and r.get_json()['error']


def test_wylogowanie_tylko_post(leader_client):
    assert leader_client.get('/logout').status_code == 405
    assert leader_client.post('/logout').status_code == 302
