"""Formuly w eksportach do Excela (przeglad bezpieczenstwa 2026-11-09).

openpyxl zapisuje kazdy tekst zaczynajacy sie od „=” jako formule — takze
z formatem „@”. Tekst wpisany na stanowisku (Paketnummer, numer artykulu
dostawy) bylby w pliku lidera zywa formula (`=HYPERLINK(…)` → link do obcej
strony). `odpowiedz_xlsx()` zostawia formuly tylko wpisane przez `formula()`.
Dane syntetyczne.
"""
import io

import openpyxl
import pytest
from conftest import login, make_user
from openpyxl import Workbook

from test_dekoracje import nowa_akcja
from test_dekoracje_dostawy import wiersz
from test_przyjecie_zwrotu import stanowisko, stanowisko_client, zwrot  # noqa: F401  (fixtures)
from test_zwroty_raporty import ustaw_cene

from logistat.web.excel import formula, odpowiedz_xlsx

ZLA = '=HYPERLINK("http://example.invalid/x","Kliknij")'


@pytest.fixture
def stanowisko_dekoracji(flask_app):
    klient = flask_app.test_client()
    login(klient, make_user('stanowisko').username)
    return klient


def wczytaj(odpowiedz):
    assert odpowiedz.status_code == 200
    return openpyxl.load_workbook(io.BytesIO(odpowiedz.data))


def test_tekst_z_danych_nie_jest_formula(flask_app):
    wb = Workbook()
    ws = wb.active
    ws.append(['=1+1', '+1', 'zwykly'])
    formula(ws, 2, 1, '=SUM(A1:A1)')
    with flask_app.test_request_context():
        ws2 = wczytaj(odpowiedz_xlsx(wb, 'x.xlsx')).active

    assert (ws2['A1'].value, ws2['A1'].data_type) == ('=1+1', 's')
    assert (ws2['A2'].value, ws2['A2'].data_type) == ('=SUM(A1:A1)', 'f')


def test_paketnummer_ze_stanowiska_jest_tekstem_w_excelu(stanowisko_client, leader_client):
    r = stanowisko_client.post('/api/zwroty/przyjecie', json=zwrot(paketnummer=ZLA))
    assert r.status_code == 201, r.get_json()

    ws = wczytaj(leader_client.get('/zwroty/paczki/export')).active

    assert (ws['A2'].value, ws['A2'].data_type) == (ZLA, 's')


def test_artykul_dostawy_jest_tekstem_w_excelu(leader_client, stanowisko_dekoracji):
    a = nowa_akcja(leader_client)
    wiersz(stanowisko_dekoracji, a, '=K1', '=HYPERLINK("HTTP://X.INVALID","X")', 1, 1)

    ws = wczytaj(leader_client.get(f'/displays/akcje/{a["id"]}/dostawy/export'))['Wiersze']

    assert [ws.cell(2, k).data_type for k in (1, 2)] == ['s', 's']
    assert ws['B2'].value == '=HYPERLINK("HTTP://X.INVALID","X")'


def test_formuly_serwera_zostaja(admin_client):
    """Invoice specification i Sorting Data liczą w Excelu jak arkusz operacji."""
    ustaw_cene()
    ws = wczytaj(admin_client.get('/zwroty/invoice-specification/export?rok=2026&miesiac=9')).active
    assert (ws['F11'].data_type, ws['F17'].data_type) == ('f', 'f')

    ws = wczytaj(admin_client.get('/zwroty/sorting-data/export?rok=2026')).active
    sumy = [c for wiersz_ in ws.iter_rows() for c in wiersz_
            if isinstance(c.value, str) and c.value.startswith('=SUM(')]
    assert sumy and all(c.data_type == 'f' for c in sumy)
