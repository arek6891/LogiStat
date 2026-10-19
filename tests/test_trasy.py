"""Trasy przy przenoszeniu do blueprintow (krok 5, 2026-10-19).

Kontraktem sa ADRESY i metody — wola je JS w static/js/, stanowiska skanera,
linki z Dashboardu i zakladki uzytkownikow. Nazwy endpointow sa wewnetrzne,
ale kazde `url_for('nazwa')` musi trafic; szablony renderuja sie w testach
tylko w domyslnych galeziach, wiec zla nazwa w rzadko pokazywanym bloku
dalaby 500 na produkcji przy zielonym CI.
"""
import glob
import os
import re

import app as logistat

KATALOG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGAWKA = os.path.join(os.path.dirname(__file__), 'mapa_adresow.txt')


def obecna_mapa():
    return sorted(
        f'{" ".join(sorted((r.methods or set()) - {"HEAD", "OPTIONS"}))} {r.rule}'
        for r in logistat.app.url_map.iter_rules() if r.endpoint != 'static')


def test_adresy_i_metody_bez_zmian():
    """Przenosiny tras nie moga zmienic zadnego adresu ani metody. Zmiana
    zamierzona (nowa trasa) = aktualizacja tests/mapa_adresow.txt w tym samym PR."""
    zapisane = open(MIGAWKA, encoding='utf-8').read().split('\n')
    assert obecna_mapa() == [w for w in zapisane if w]


def nazwy_url_for():
    pliki = (glob.glob(os.path.join(KATALOG, 'templates', '*.html'))
             + [os.path.join(KATALOG, 'app.py')]
             + glob.glob(os.path.join(KATALOG, 'logistat', '**', '*.py'), recursive=True))
    nazwy = set()
    for p in pliki:
        tresc = open(p, encoding='utf-8').read()
        nazwy |= {(os.path.relpath(p, KATALOG), n)
                  for n in re.findall(r"url_for\(\s*['\"]([\w.]+)['\"]", tresc)}
        # Podswietlenie menu w base.html: request.endpoint == 'nazwa' / in ('a', 'b').
        # Po zmianie nazwy na 'obszar.nazwa' zla nazwa nie daje bledu — pozycja
        # menu po cichu przestaje sie podswietlac.
        for linia in re.findall(r'request\.endpoint[^%\n]*', tresc):
            nazwy |= {(os.path.relpath(p, KATALOG), n)
                      for n in re.findall(r"['\"]([\w.]+)['\"]", linia)}
    return nazwy


def test_kazde_url_for_wskazuje_istniejaca_trase():
    endpointy = set(logistat.app.view_functions)
    zle = sorted(f'{plik}: {nazwa}' for plik, nazwa in nazwy_url_for()
                 if nazwa not in endpointy)
    assert not zle, f'url_for do nieistniejacych tras: {zle}'


def test_nazwy_tras_w_konfiguracji_istnieja():
    """Nazwy endpointow poza url_for: strona logowania Flask-Login i lista
    tras dostepnych przy wymuszonej zmianie hasla (porownuje request.endpoint)."""
    endpointy = set(logistat.app.view_functions)
    assert logistat.login_manager.login_view in endpointy
    assert set(logistat.BEZ_WYMOGU_ZMIANY_HASLA) <= endpointy
