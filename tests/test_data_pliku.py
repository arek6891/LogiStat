"""Data pliku — dzien pracy podawany przy imporcie (2026-10).

Glowna data paczki: klucz linii rozliczenia (Loading date w Statystykach
ogolnych), Dashboard, Forecast, filtry. Ziel-Datum zostaje tylko jako
informacja z pliku. Tu: wymagana data przy imporcie, jednorazowa migracja
starych danych, lista importow i grupowa poprawa daty, Dashboard.
"""
import io
from datetime import date, datetime

import openpyxl

import app as logistat
from conftest import login, make_user
from test_import_aggregation import gstat

CSV = ('Barcode;Land;Stückzahl;Kategorie;Ziel-Datum;Übergabe Nr.\n'
       'C1;PL;10;textile;11.09.2026;UB-1\n'
       'C2;PL;5;textile;12.09.2026;UB-1\n')


def wyslij_csv(client, data_pliku=None, tresc=CSV):
    dane = {'file': (io.BytesIO(tresc.encode('utf-8')), 'plik.csv')}
    if data_pliku is not None:
        dane['data_pliku'] = data_pliku
    return client.post('/api/import-csv', data=dane, content_type='multipart/form-data')


def karton(barcode):
    return logistat.ImportedCarton.query.filter_by(barcode=barcode).one()


# ── import ───────────────────────────────────────────────────────────────────

def test_import_bez_daty_pliku_daje_400_i_nic_nie_zapisuje(leader_client):
    for brak in (None, '', '   '):
        r = wyslij_csv(leader_client, brak)
        assert r.status_code == 400, repr(brak)
        assert 'datę pliku' in r.get_json()['error']
    assert logistat.ImportedCarton.query.count() == 0


def test_zla_data_pliku_daje_400(leader_client):
    assert wyslij_csv(leader_client, '13.10.2026').status_code == 400
    assert logistat.ImportedCarton.query.count() == 0


def test_import_csv_zapisuje_date_pliku_i_linie_pod_nia(leader_client):
    r = wyslij_csv(leader_client, '2026-09-10')

    assert r.status_code == 200
    assert {c.data_pliku for c in logistat.ImportedCarton.query} == {date(2026, 9, 10)}
    # Dwie rozne Ziel-Datum, jeden plik -> jedna linia pod data pliku.
    assert logistat.GeneralStat.query.count() == 1
    assert gstat(loading_date=date(2026, 9, 10)).amounts == 15


def test_import_excel_tez_wymaga_daty_pliku(leader_client):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['Barcode', 'Land', 'Stückzahl', 'Kategorie', 'Ziel-Datum', 'Übergabe Nr.'])
    ws.append(['X1', 'PL', 7, 'textile', '11.09.2026', 'UB-1'])
    bufor = io.BytesIO()
    wb.save(bufor)

    def wyslij(**pola):
        bufor.seek(0)
        return leader_client.post('/api/import/excel', content_type='multipart/form-data',
                                  data={'file': (io.BytesIO(bufor.getvalue()), 'p.xlsx'), **pola})

    assert wyslij().status_code == 400
    assert wyslij(data_pliku='2026-09-10').status_code == 200
    assert karton('X1').data_pliku == date(2026, 9, 10)


def test_strona_importu_podpowiada_dzisiejsza_date(leader_client):
    html = leader_client.get('/import-csv').get_data(as_text=True)

    assert f"const DZIS = '{logistat.local_today().isoformat()}'" in html
    assert 'id="dataPlikuModal"' in html


# ── migracja ─────────────────────────────────────────────────────────────────

def _stara_linia(ub, land, d, amounts=0, reczne=None, zrodlo='manual'):
    s = logistat.GeneralStat(loading_date=d, week_number=d.isocalendar()[1], list_id=ub,
                             country_ledger=land, amounts=amounts, category_source=zrodlo)
    s.set_category_data({k: {'amount': v, 'cost': 0.0} for k, v in (reczne or {}).items()})
    logistat.db.session.add(s)
    return s


def _stary_karton(barcode, ub, ziel, imported_at, szt=10, **kw):
    c = logistat.ImportedCarton(barcode=barcode, land='PL', stueckzahl=szt, uebergabe_nr=ub,
                                ziel_datum=ziel, imported_at=imported_at, **kw)
    logistat.db.session.add(c)
    return c


def _migruj():
    logistat.db.session.commit()
    logistat.migruj_date_pliku()


def test_migracja_bierze_lokalny_dzien_importu(flask_app):
    # 22:30 UTC 9.09 = 00:30 10.09 w Warszawie (lato) — data UTC dalaby 9.09.
    _stary_karton('N1', 'UB-1', date(2026, 9, 11), datetime(2026, 9, 9, 22, 30))
    _migruj()

    assert karton('N1').data_pliku == date(2026, 9, 10)


def test_migracja_bez_czasu_importu_bierze_ziel_datum(flask_app):
    _stary_karton('N2', 'UB-1', date(2026, 9, 11), datetime(2026, 9, 9, 6, 0))
    logistat.db.session.commit()
    logistat.db.session.execute(logistat.db.text(
        "UPDATE imported_carton SET imported_at = NULL WHERE barcode = 'N2'"))
    _migruj()

    assert karton('N2').data_pliku == date(2026, 9, 11)


def test_migracja_przenosi_linie_na_date_pliku_i_laczy_kolizje(flask_app):
    import_dzien = datetime(2026, 9, 10, 6, 0)          # 08:00 lokalnie, 10.09
    _stary_karton('A1', 'UB-1', date(2026, 9, 11), import_dzien, szt=10)
    _stary_karton('A2', 'UB-1', date(2026, 9, 12), import_dzien, szt=5)
    _stara_linia('UB-1', 'PL', date(2026, 9, 11), 10, reczne={'textile': 3})
    _stara_linia('UB-1', 'PL', date(2026, 9, 12), 5, reczne={'textile': 4})
    _migruj()

    linie = logistat.GeneralStat.query.all()
    assert len(linie) == 1, 'ten sam UB + kraj + data pliku = jedna linia'
    assert linie[0].loading_date == date(2026, 9, 10)
    assert linie[0].amounts == 15
    assert linie[0].get_category_data()['textile']['amount'] == 7, \
        'reczne ilosci obu starych linii sa sumowane, nie gubione'


def test_migracja_przelicza_linie_ze_skanow(flask_app):
    c = _stary_karton('S1', 'UB-1', date(2026, 9, 11), datetime(2026, 9, 10, 6, 0))
    c.set_scan_categories({'sorting': 9})
    _stara_linia('UB-1', 'PL', date(2026, 9, 11), 10, zrodlo='scan')
    _migruj()

    linia = gstat(loading_date=date(2026, 9, 10))
    assert linia.category_source == 'scan'
    assert linia.get_category_data()['sorting']['amount'] == 9


def test_migracja_zaklada_linie_dla_kartonow_bez_ziel_datum(flask_app):
    _stary_karton('BZ1', 'UB-9', None, datetime(2026, 9, 10, 6, 0), szt=12)
    _migruj()

    assert gstat(list_id='UB-9', loading_date=date(2026, 9, 10)).amounts == 12


def test_migracja_nie_rusza_linii_przesunietych_na_zajety_dzien_w_zlej_kolejnosci(flask_app):
    """Linia A wchodzi na dzien, ktory zajmuje linia B, a B sama sie przesuwa —
    bez odsuniecia na tymczasowe daty unikalny indeks wybucha."""
    _stary_karton('A', 'UB-1', date(2026, 9, 11), datetime(2026, 9, 10, 6, 0))   # 11 -> 10
    _stary_karton('B', 'UB-1', date(2026, 9, 10), datetime(2026, 9, 9, 6, 0))    # 10 -> 9
    _stara_linia('UB-1', 'PL', date(2026, 9, 11), 10, reczne={'textile': 1})
    _stara_linia('UB-1', 'PL', date(2026, 9, 10), 10, reczne={'textile': 2})
    _migruj()

    assert gstat(loading_date=date(2026, 9, 10)).get_category_data()['textile']['amount'] == 1
    assert gstat(loading_date=date(2026, 9, 9)).get_category_data()['textile']['amount'] == 2


def test_migracja_biegnie_tylko_raz(flask_app):
    _stary_karton('A1', 'UB-1', date(2026, 9, 11), datetime(2026, 9, 10, 6, 0))
    _stara_linia('UB-1', 'PL', date(2026, 9, 11), 10)
    _migruj()
    karton('A1').data_pliku = date(2026, 1, 1)       # ktos potem poprawil date
    logistat.db.session.commit()

    logistat.migruj_date_pliku()

    assert karton('A1').data_pliku == date(2026, 1, 1)


# ── lista importow i grupowa zmiana daty ─────────────────────────────────────

def _import(client, dzien, tresc=CSV):
    assert wyslij_csv(client, dzien, tresc).status_code == 200
    return client.get('/api/imports').get_json()['importy']


def _zmien(client, klucze, nowa, podglad=False):
    return client.post('/api/imports/zmien-date',
                       json={'importy': klucze, 'nowa_data': nowa, 'podglad': podglad})


def test_lista_importow_grupuje_plik_w_jeden_wpis(leader_client, leader):
    importy = _import(leader_client, '2026-09-10')

    assert len(importy) == 1
    assert importy[0]['paczek'] == 2 and importy[0]['sztuk'] == 15
    assert importy[0]['data_pliku'] == '2026-09-10'
    assert importy[0]['osoba_id'] == leader.id


def test_filtry_listy_importow(leader_client, leader):
    _import(leader_client, '2026-09-10')
    dzis = logistat.local_today().isoformat()

    def ile(**f):
        return len(leader_client.get('/api/imports', query_string=f).get_json()['importy'])

    assert ile(data_pliku='2026-09-10') == 1
    assert ile(data_pliku='2026-09-11') == 0
    assert ile(dzien_importu=dzis) == 1
    assert ile(osoba=leader.id) == 1
    assert ile(osoba=leader.id + 999) == 0
    assert ile(godz_od='00:00', godz_do='23:59') == 1
    assert leader_client.get('/api/imports?godz_od=25:99').status_code == 400


def test_podglad_nic_nie_zapisuje(leader_client):
    klucz = _import(leader_client, '2026-09-10')[0]['klucz']

    r = _zmien(leader_client, [klucz], '2026-09-09', podglad=True)

    assert r.status_code == 200
    assert r.get_json()['paczek'] == 2 and r.get_json()['linii_przenoszonych'] == 1
    assert {c.data_pliku for c in logistat.ImportedCarton.query} == {date(2026, 9, 10)}


def test_zmiana_przenosi_paczki_i_linie_z_recznymi_ilosciami(leader_client, leader):
    klucz = _import(leader_client, '2026-09-10')[0]['klucz']
    linia = gstat(loading_date=date(2026, 9, 10))
    linia.set_category_data({'textile': {'amount': 6, 'cost': 0.0}})
    logistat.db.session.commit()

    r = _zmien(leader_client, [klucz], '2026-09-09')

    assert r.status_code == 200
    assert {c.data_pliku for c in logistat.ImportedCarton.query} == {date(2026, 9, 9)}
    assert {c.modified_by for c in logistat.ImportedCarton.query} == {leader.id}
    assert logistat.GeneralStat.query.count() == 1
    przeniesiona = gstat(loading_date=date(2026, 9, 9))
    assert przeniesiona.amounts == 15
    assert przeniesiona.get_category_data()['textile']['amount'] == 6, \
        'reczne ilosci ida razem z linia'


def test_zmiana_laczy_sie_z_istniejaca_linia_nowej_daty(leader_client):
    _import(leader_client, '2026-09-09',
            'Barcode;Land;Stückzahl;Kategorie;Ziel-Datum;Übergabe Nr.\nE1;PL;100;textile;;UB-1\n')
    zly = [i for i in _import(leader_client, '2026-09-10') if i['data_pliku'] == '2026-09-10'][0]

    assert _zmien(leader_client, [zly['klucz']], '2026-09-09').status_code == 200

    assert logistat.GeneralStat.query.count() == 1
    assert gstat(loading_date=date(2026, 9, 9)).amounts == 115


def test_czesciowe_przeniesienie_linii_z_recznymi_ilosciami_daje_409(leader_client):
    """Dwa importy w jednej linii, poprawiany tylko jeden — recznie wpisanych
    liczb nie da sie podzielic miedzy dwie linie."""
    _import(leader_client, '2026-09-10')
    druga = 'Barcode;Land;Stückzahl;Kategorie;Ziel-Datum;Übergabe Nr.\nD1;PL;7;textile;;UB-1\n'
    login(leader_client, make_user('leader').username)    # inna osoba = inny import
    importy = _import(leader_client, '2026-09-10', druga)
    linia = gstat(loading_date=date(2026, 9, 10))
    linia.set_category_data({'textile': {'amount': 6, 'cost': 0.0}})
    logistat.db.session.commit()
    jeden = [i for i in importy if i['paczek'] == 1][0]['klucz']

    r = _zmien(leader_client, [jeden], '2026-09-09')

    assert r.status_code == 409
    assert r.get_json()['konflikty']
    assert karton('D1').data_pliku == date(2026, 9, 10), 'nic nie moze sie zmienic'


def test_czesciowe_przeniesienie_bez_recznych_dzieli_linie(leader_client):
    _import(leader_client, '2026-09-10')
    druga = 'Barcode;Land;Stückzahl;Kategorie;Ziel-Datum;Übergabe Nr.\nD1;PL;7;textile;;UB-1\n'
    login(leader_client, make_user('leader').username)
    importy = _import(leader_client, '2026-09-10', druga)
    jeden = [i for i in importy if i['paczek'] == 1][0]['klucz']

    assert _zmien(leader_client, [jeden], '2026-09-09').status_code == 200

    assert gstat(loading_date=date(2026, 9, 10)).amounts == 15
    assert gstat(loading_date=date(2026, 9, 9)).amounts == 7


def test_przeniesione_ilosci_ze_skanu_ida_za_paczka(leader_client):
    klucz = _import(leader_client, '2026-09-10')[0]['klucz']
    c = karton('C1')
    c.set_scan_categories({'sorting': 4})
    logistat.recompute_general_stat(*logistat.klucz_linii(c), from_scan=True)
    logistat.db.session.commit()

    assert _zmien(leader_client, [klucz], '2026-09-09').status_code == 200

    linia = gstat(loading_date=date(2026, 9, 9))
    assert linia.category_source == 'scan'
    assert linia.get_category_data()['sorting']['amount'] == 4


def test_zle_zadanie_zmiany_daty(leader_client):
    klucz = _import(leader_client, '2026-09-10')[0]['klucz']

    assert _zmien(leader_client, [], '2026-09-09').status_code == 400
    assert _zmien(leader_client, [klucz], '').status_code == 400
    assert _zmien(leader_client, ['bzdura'], '2026-09-09').status_code == 400
    assert _zmien(leader_client, ['1|2020-01-01T00:00|2020-01-01'], '2026-09-09').status_code == 404


def test_operator_bez_logowania_nie_zmieni_daty(client):
    assert client.post('/api/imports/zmien-date', json={}).status_code == 302


# ── Dashboard i Forecast ─────────────────────────────────────────────────────

def test_plan_dnia_pliku(leader_client):
    _import(leader_client, '2026-09-10')
    c = karton('C1')
    c.scan_start_at = c.scan_end_at = datetime(2026, 9, 11, 8, 0)    # skonczona nastepnego dnia
    karton('C2').scan_start_at = datetime(2026, 9, 11, 9, 0)
    logistat.db.session.commit()

    p = leader_client.get('/api/dashboard/plik?date=2026-09-10').get_json()

    assert (p['paczek'], p['sztuk']) == (2, 15)
    assert (p['zrobione'], p['zrobione_sztuk']) == (1, 10), \
        'zrobione = ma koniec, niezaleznie od dnia, w ktorym go zrobiono'
    assert (p['pozostalo'], p['pozostalo_sztuk'], p['w_toku']) == (1, 5, 1)
    assert p['procent'] == 50.0


def test_podsumowanie_to_tylko_niezrobione_wg_daty_pliku(leader_client):
    _import(leader_client, '2026-09-10')
    karton('C1').scan_end_at = datetime(2026, 9, 10, 8, 0)
    logistat.db.session.commit()

    z = leader_client.get('/api/dashboard').get_json()['zalegle']

    assert (z['paczek'], z['sztuk']) == (1, 5)
    assert z['dni'] == [{'data_pliku': '2026-09-10', 'paczek': 1, 'sztuk': 5, 'w_toku': 0}]


def test_forecast_actual_liczy_po_dacie_pliku(leader_client):
    _import(leader_client, '2026-09-10')     # Ziel-Datum 11 i 12.09

    dane = leader_client.get('/api/forecast/chart-data?date_from=2026-09-09&date_to=2026-09-12').get_json()
    actual = {d['date']: d['actual'] for d in dane}

    assert actual['2026-09-10'] == 15, 'Actual to suma sztuk z plikow tego dnia'
    assert actual['2026-09-11'] == 0 and actual['2026-09-12'] == 0


def test_filtr_paczek_po_dacie_pliku(leader_client):
    _import(leader_client, '2026-09-10')

    html = leader_client.get('/paczki?date_from=2026-09-10&date_to=2026-09-10').get_data(as_text=True)
    pusto = leader_client.get('/paczki?date_from=2026-09-11&date_to=2026-09-11').get_data(as_text=True)

    assert 'C1' in html and 'C2' in html
    assert 'C1' not in pusto
