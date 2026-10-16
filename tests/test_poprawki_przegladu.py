"""Poprawki z przegladu architektury (2026-10-16).

- `?next=` po zalogowaniu tylko jako sciezka tej aplikacji (open redirect);
- logowanie domyslnym haslem admina wymusza jego zmiane;
- nazwa kategorii z cudzyslowem / backslashem nie psuje JS na stronach;
- `migrate_columns()` nie polyka bledu — start pada z nazwa kolumny.
"""
import json
import re

import pytest

import app as logistat
from conftest import PASSWORD, login, make_user


# ── open redirect ────────────────────────────────────────────────────────────

@pytest.mark.parametrize('nastepna,oczekiwane', [
    ('/paczki', '/paczki'),
    ('https://zla-strona.example/', '/'),
    ('//zla-strona.example/', '/'),
    ('/\\zla-strona.example', '/'),
    ('javascript:alert(1)', '/'),
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
    u.set_password(logistat.DEFAULT_ADMIN_PASSWORD)
    logistat.db.session.commit()
    return u


def test_domyslne_haslo_wymusza_zmiane(client):
    u = admin_z_domyslnym_haslem()

    r = login(client, u.username, logistat.DEFAULT_ADMIN_PASSWORD)

    assert r.headers['Location'] == '/profile'
    assert client.get('/dashboard').headers['Location'] == '/profile'
    assert client.get('/api/dashboard').status_code == 403
    assert client.get('/profile').status_code == 200


def test_po_zmianie_hasla_dostep_wraca(client):
    u = admin_z_domyslnym_haslem()
    login(client, u.username, logistat.DEFAULT_ADMIN_PASSWORD)

    client.post('/profile', data={'current_password': logistat.DEFAULT_ADMIN_PASSWORD,
                                  'new_password': 'nowe-haslo-1', 'confirm_password': 'nowe-haslo-1'})

    assert client.get('/dashboard').status_code == 200
    assert client.get('/api/dashboard').status_code == 200


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
    monkeypatch.setattr(logistat, 'MIGRACJE_KOLUMN', zla)

    with pytest.raises(RuntimeError, match='nie_ma_takiej_tabeli.kolumna'):
        logistat.migrate_columns()
