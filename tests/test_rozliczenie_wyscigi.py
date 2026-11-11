"""Przeglad kodu 2026-11-11 — rozliczenie przy rownoczesnych zapisach.

- suma sztuk linii liczona przed jej blokada: koniec paczki rownolegle z importem
  do tej samej linii nadpisywal `amounts` stara suma → linia blokowana przed suma;
- „🔓 Odblokuj” i korekta ilosci lidera czytaly karton bez blokady, ktora
  trzyma koniec na stanowisku;
- Statystyki ogolne zapisywaly ilosci przez parseInt — 4,5 stawalo sie 4.
Dane syntetyczne.
"""
from datetime import date

from conftest import make_user, strona_z_js

from logistat.extensions import db
from logistat.models import GeneralStat, ImportedCarton
from logistat.rozliczenie import recompute_general_stat

ZIEL = date(2026, 9, 10)


def karton(barcode, sztuk=10):
    c = ImportedCarton(barcode=barcode, land='PL', stueckzahl=sztuk,
                       ziel_datum=ZIEL, data_pliku=ZIEL, uebergabe_nr='UB-1')
    db.session.add(c)
    db.session.commit()
    return c


def linia():
    db.session.expire_all()
    return GeneralStat.query.filter_by(list_id='UB-1', country_ledger='PL', loading_date=ZIEL).one()


def test_linia_blokowana_przed_suma_kartonow(flask_app, queries):
    """Suma liczona przed blokada linii nie widzi kartonow, ktore import
    dokladal w tej chwili — koniec paczki nadpisywal `amounts` stara suma
    (blokowal linie dopiero autoflush, juz po SUM)."""
    karton('P1')
    recompute_general_stat('UB-1', 'PL', ZIEL)
    db.session.commit()
    queries.statements.clear()

    recompute_general_stat('UB-1', 'PL', ZIEL, from_scan=True)

    zapytania = [q.lower() for q in queries.statements]
    blokada = next(i for i, q in enumerate(zapytania)
                   if 'from general_stat' in q and 'for update' in q)
    suma = next(i for i, q in enumerate(zapytania) if 'sum(imported_carton.stueckzahl)' in q)
    assert blokada < suma


def test_odblokuj_i_korekta_ilosci_blokuja_karton(leader_client, queries):
    make_user('operator', barcode_id='W1')
    c = karton('P1')
    assert leader_client.post('/api/package-time/start', json={
        'employee_barcode': 'W1', 'package_barcode': 'P1'}).status_code == 200

    for metoda, adres, cialo in (
            ('put', f'/api/packages/{c.id}/categories', {'categories': {'labelling_on': 3}}),
            ('post', f'/api/packages/{c.id}/unlock-scan', None)):
        queries.statements.clear()
        r = getattr(leader_client, metoda)(adres, json=cialo)
        assert r.status_code == 200, (adres, r.get_json())
        assert any('FOR UPDATE' in q.upper() for q in queries.matching('FROM imported_carton')), adres


def test_statystyki_ogolne_zapisuja_polowki(admin_client):
    karton('P1')
    recompute_general_stat('UB-1', 'PL', ZIEL)
    db.session.commit()
    l = linia()

    r = admin_client.put(f'/api/general-stats/{l.id}', json={
        'double_rate_category_data': {'labelling_tvl': {'amount': 4.5, 'cost': 0},
                                      'labelling_on': {'amount': 'abc', 'cost': 0}}})

    assert r.status_code == 200, r.get_json()
    dr = linia().get_double_rate_category_data()
    assert dr['labelling_tvl']['amount'] == 4.5
    assert dr['labelling_on']['amount'] == 0


def test_ekran_statystyk_nie_ucina_polowek(admin_client):
    strona = strona_z_js(admin_client, '/general-stats')
    assert 'parseInt(inp.value)' not in strona
