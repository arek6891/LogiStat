"""Dane z bazy w HTML-u.

Nazwy pracownikow, notatki i barcode'y sa wpisywane przez ludzi albo wchodza
z importu CSV — czyli sa TRWALE. Jesli trafiaja do HTML-a bez escapowania,
raz zaimportowany barcode dziala na kazdym, kto otworzy widok.
"""
import glob
import os
import re

import pytest

import app as logistat
from conftest import make_user

ZLOSLIWA_NAZWA = '<img src=x onerror=alert(1)>'
ZLOSLIWY_BARCODE = '"><script>alert(1)</script>'

SZABLONY = sorted(glob.glob(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates', '*.html')))


# ── Regula statyczna: zaden inline handler nie sklada danych z bazy ──────────

# `onclick="foo(${x})"` jest bezpieczne TYLKO dla wartosci liczbowych. Dla
# tekstu escapeHtml nie pomaga: przegladarka dekoduje encje w atrybucie zanim
# JS zobaczy string, wiec &quot; wraca jako " i zamyka literal.
INLINE_HANDLER = re.compile(r'on\w+\s*=\s*([\'"])(?:(?!\1).)*\$\{(?P<wyr>[^}]*)\}')
# Wyrazenie konczace sie na `id` (e.id, d.stat_id, w.user_id) — z bazy zawsze
# liczba, wiec nie da sie nim wyjsc z atrybutu.
DOZWOLONE_LICZBOWE = re.compile(r'^[A-Za-z_][\w.]*[Ii][Dd]$')


@pytest.mark.parametrize('sciezka', SZABLONY, ids=lambda p: os.path.basename(p))
def test_inline_handler_tylko_z_id(sciezka):
    tresc = open(sciezka, encoding='utf-8').read()

    podejrzane = [m.group('wyr').strip() for m in INLINE_HANDLER.finditer(tresc)
                  if not DOZWOLONE_LICZBOWE.match(m.group('wyr').strip())]

    assert not podejrzane, (
        f'{os.path.basename(sciezka)}: inline handler sklada dane inne niż id: '
        f'{podejrzane}. Uzyj data-* + delegacji (patrz podepnijAkcje() w '
        'worker_times.html).')


@pytest.mark.parametrize('sciezka', SZABLONY, ids=lambda p: os.path.basename(p))
def test_title_z_danych_jest_escapowany(sciezka):
    tresc = open(sciezka, encoding='utf-8').read()

    goly = re.findall(r'title="\$\{(?!escapeHtml)([^}]+)\}"', tresc)

    assert not goly, f'{os.path.basename(sciezka)}: nieescapowany title: {goly}'


def test_escapehtml_zdefiniowany_raz_w_base():
    base = open(os.path.join(os.path.dirname(SZABLONY[0]), 'base.html'),
                encoding='utf-8').read()

    assert base.count('function escapeHtml') == 1


# ── Szablony renderowane serwerowo (Jinja autoescape) ───────────────────────

def test_lista_uzytkownikow_escapuje_nazwe(admin_client):
    make_user('operator', username='zlosliwy', display_name=ZLOSLIWA_NAZWA)

    html = admin_client.get('/admin/users').get_data(as_text=True)

    assert ZLOSLIWA_NAZWA not in html
    assert '&lt;img src=x onerror=alert(1)&gt;' in html


def test_lista_paczek_escapuje_barcode(leader_client):
    logistat.db.session.add(logistat.ImportedCarton(
        barcode=ZLOSLIWY_BARCODE, land='PL', stueckzahl=1))
    logistat.db.session.commit()

    html = leader_client.get('/paczki').get_data(as_text=True)

    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;' in html


def test_sidebar_escapuje_nazwe_zalogowanego(client):
    from conftest import login
    u = make_user('leader', username='zly-lider', display_name=ZLOSLIWA_NAZWA)
    login(client, u.username)

    html = client.get('/dashboard').get_data(as_text=True)

    assert ZLOSLIWA_NAZWA not in html


def test_lista_krajow_escapuje_nazwe(admin_client):
    logistat.db.session.add(logistat.CountryMapping(
        country=ZLOSLIWA_NAZWA, innenauftrag='X1'))
    logistat.db.session.commit()

    html = admin_client.get('/admin/country-mapping').get_data(as_text=True)

    assert ZLOSLIWA_NAZWA not in html


# ── API oddaje surowe dane; escapowanie robi klient ─────────────────────────

def test_api_oddaje_surowa_nazwe(leader_client):
    """JSON ma zawierac prawdziwa wartosc — to widok ma ja zescapowac przy
    wstawianiu do DOM-u."""
    make_user('operator', username='zlosliwy2', display_name=ZLOSLIWA_NAZWA)

    users = leader_client.get('/api/users').get_json()

    nazwy = [u['display_name'] for u in users]
    assert ZLOSLIWA_NAZWA in nazwy
