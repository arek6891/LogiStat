"""Dane z bazy w HTML-u.

Nazwy pracownikow, notatki i barcode'y sa wpisywane przez ludzi albo wchodza
z importu CSV — czyli sa TRWALE. Jesli trafiaja do HTML-a bez escapowania,
raz zaimportowany barcode dziala na kazdym, kto otworzy widok.
"""
import glob
import os
import re

import pytest
from conftest import make_user, strona_z_js

from logistat.extensions import db
from logistat.models import CountryMapping, ImportedCarton


ZLOSLIWA_NAZWA = '<img src=x onerror=alert(1)>'
ZLOSLIWY_BARCODE = '"><script>alert(1)</script>'

KATALOG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Szablony I skrypty stron: od 2026-10-16 JS jest w static/js/, a to tam
# skladane sa szablony HTML z danych — bez nich te reguly niczego by nie lapaly.
SZABLONY = sorted(glob.glob(os.path.join(KATALOG, 'templates', '*.html'))
                  + glob.glob(os.path.join(KATALOG, 'static', 'js', '*.js')))
assert any(p.endswith('.js') for p in SZABLONY), 'brak static/js/*.js do sprawdzenia'


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


# Jinja w inline handlerze w apostrofach JS: `onclick="f('{{ x }}')"`. Autoescape
# zamienia ' na &#39;, ale przegladarka odkodowuje encje ZANIM uruchomi JS — apostrof
# w kodzie paczki / nazwie kraju (Côte d'Ivoire) psul przycisk albo wykonywal kod
# (przeglad 2026-10-24). Wolno: onclick='f({{ x|tojson }})' (atrybut w apostrofach).
JINJA_W_HANDLERZE = re.compile(r"""\bon\w+\s*=\s*"[^"]*['"]\{\{""")
TOJSON_W_CUDZYSLOWIE = re.compile(r'\bon\w+\s*=\s*"[^"]*\|\s*tojson')


@pytest.mark.parametrize('sciezka', [p for p in SZABLONY if p.endswith('.html')],
                         ids=lambda p: os.path.basename(p))
def test_jinja_w_handlerze_tylko_przez_tojson(sciezka):
    tresc = open(sciezka, encoding='utf-8').read()

    zle = JINJA_W_HANDLERZE.findall(tresc) + TOJSON_W_CUDZYSLOWIE.findall(tresc)

    assert not zle, (f'{os.path.basename(sciezka)}: tekst z Jinja w inline handlerze — '
                     "uzyj onclick='f({{ x|tojson }})' albo data-*")


# Wolny tekst z bazy, ktory JS wstawia przez innerHTML (notatka z Wpisu ilosci,
# kto wpisal / poprawil, nazwa kategorii edytowana przez admina) — zawsze escapeHtml.
# Uzycie wprost: `${d.note || '-'}` albo po operatorze `${x ? d.modified_by + …}`;
# sam warunek (`${e.note ? … escapeHtml(e.note) …}`) jest w porzadku.
_POLE = r'[\w.]*\.(?:note|entered_by|modified_by)\b(?!\s*\?)'
TEKST_Z_BAZY = re.compile(r'(?:\$\{|[?:+]\s)\s*' + _POLE)


@pytest.mark.parametrize('sciezka', [p for p in SZABLONY if p.endswith('.js')],
                         ids=lambda p: os.path.basename(p))
def test_wolny_tekst_z_bazy_escapowany(sciezka):
    tresc = open(sciezka, encoding='utf-8').read()

    zle = [m.group(0) for m in TEKST_Z_BAZY.finditer(tresc)]
    if sciezka.endswith('admin_cost_mapping.js'):
        zle += re.findall(r'\$\{label\}', tresc)

    assert not zle, f'{os.path.basename(sciezka)}: bez escapeHtml: {zle}'


def test_lista_paczek_barcode_z_apostrofem_nie_psuje_przycisku(leader_client):
    db.session.add(ImportedCarton(barcode="12'3", stueckzahl=1, land='DE'))
    db.session.commit()

    html = strona_z_js(leader_client, '/paczki')

    assert "'12&#39;3'" not in html and '"12\\u00273"' in html


@pytest.mark.parametrize('sciezka', SZABLONY, ids=lambda p: os.path.basename(p))
def test_title_z_danych_jest_escapowany(sciezka):
    tresc = open(sciezka, encoding='utf-8').read()

    goly = re.findall(r'title="\$\{(?!escapeHtml)([^}]+)\}"', tresc)

    assert not goly, f'{os.path.basename(sciezka)}: nieescapowany title: {goly}'


def test_escapehtml_zdefiniowany_raz_w_base():
    # Jedna definicja dla wszystkich stron: static/js/base.js (z base.html).
    definicje = [p for p in SZABLONY
                 if 'function escapeHtml' in open(p, encoding='utf-8').read()]

    assert [os.path.basename(p) for p in definicje] == ['base.js']


# ── Szablony renderowane serwerowo (Jinja autoescape) ───────────────────────

def test_lista_uzytkownikow_escapuje_nazwe(admin_client):
    make_user('operator', username='zlosliwy', display_name=ZLOSLIWA_NAZWA)

    html = strona_z_js(admin_client, '/admin/users')

    assert ZLOSLIWA_NAZWA not in html
    assert '&lt;img src=x onerror=alert(1)&gt;' in html


def test_lista_paczek_escapuje_barcode(leader_client):
    db.session.add(ImportedCarton(
        barcode=ZLOSLIWY_BARCODE, land='PL', stueckzahl=1))
    db.session.commit()

    html = strona_z_js(leader_client, '/paczki')

    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;' in html


def test_sidebar_escapuje_nazwe_zalogowanego(client):
    from conftest import login
    u = make_user('leader', username='zly-lider', display_name=ZLOSLIWA_NAZWA)
    login(client, u.username)

    html = strona_z_js(client, '/dashboard')

    assert ZLOSLIWA_NAZWA not in html


def test_lista_krajow_escapuje_nazwe(admin_client):
    db.session.add(CountryMapping(
        country=ZLOSLIWA_NAZWA, innenauftrag='X1'))
    db.session.commit()

    html = strona_z_js(admin_client, '/admin/country-mapping')

    assert ZLOSLIWA_NAZWA not in html


# ── API oddaje surowe dane; escapowanie robi klient ─────────────────────────

def test_api_oddaje_surowa_nazwe(leader_client):
    """JSON ma zawierac prawdziwa wartosc — to widok ma ja zescapowac przy
    wstawianiu do DOM-u."""
    make_user('operator', username='zlosliwy2', display_name=ZLOSLIWA_NAZWA)

    users = leader_client.get('/api/users').get_json()

    nazwy = [u['display_name'] for u in users]
    assert ZLOSLIWA_NAZWA in nazwy
