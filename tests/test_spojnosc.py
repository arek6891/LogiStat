"""scripts/sprawdz_spojnosc.py — kontrola po wdrozeniu.

Test pilnuje, zeby skrypt nie zgnil razem ze zmianami modelu: na spojnych
danych nie zglasza bledow, a rozjechane rozliczenie i wiszaca paczke widzi.
"""
import importlib.util
import os
from datetime import date, datetime, timedelta

import app as logistat
from conftest import make_user

DZIEN = date(2026, 10, 15)

_spec = importlib.util.spec_from_file_location(
    'sprawdz_spojnosc',
    os.path.join(os.path.dirname(__file__), '..', 'scripts', 'sprawdz_spojnosc.py'))
skrypt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(skrypt)


def dane(leader_client):
    make_user('operator', barcode_id='A', display_name='Osoba A')
    logistat.process_import_rows([
        {'barcode': f'P{i}', 'land': 'PL', 'stueckzahl': 10, 'uebergabe_nr': 'UB-1'}
        for i in range(3)], DZIEN)
    for kod in ('P0', 'P1'):
        leader_client.post('/api/package-time/start', json={'employee_barcode': 'A', 'package_barcode': kod})
        leader_client.post('/api/package-time/end', json={
            'employee_barcode': 'A', 'package_barcode': kod, 'tryb': 'wzor',
            'tabela': {'grupy': {'bizuteria': {'podwojnie': 3}}}})


def opisy(lista):
    return [opis for opis, _ in lista]


def test_spojne_dane_bez_bledow(leader_client, acting_admin):
    dane(leader_client)

    bledy, uwagi = skrypt.sprawdz(logistat)

    assert bledy == []
    assert not any('niezakończone' in o for o in opisy(uwagi))


def test_rozjechane_rozliczenie_to_blad(leader_client, acting_admin):
    dane(leader_client)
    linia = logistat.GeneralStat.query.one()
    linia.amounts = 999
    dane_kat = linia.get_category_data()
    dane_kat['labelling_tvl']['amount'] = 1
    linia.set_category_data(dane_kat)
    logistat.db.session.commit()

    bledy, _ = skrypt.sprawdz(logistat)

    assert 'Amounts linii ≠ suma Stückzahl jej paczek' in opisy(bledy)
    assert "linia 'scan' ≠ suma ilości z jej paczek" in opisy(bledy)


def test_wiszaca_paczka_to_uwaga(leader_client, acting_admin):
    dane(leader_client)
    leader_client.post('/api/package-time/start', json={'employee_barcode': 'A', 'package_barcode': 'P2'})

    _, uwagi = skrypt.sprawdz(logistat, teraz=datetime.utcnow() + timedelta(days=1))

    assert any('niezakończone' in o for o in opisy(uwagi))


def test_main_zwraca_kod_bledu(leader_client, acting_admin, capsys):
    dane(leader_client)
    logistat.GeneralStat.query.one().amounts = 1
    logistat.db.session.commit()

    assert skrypt.main() == 1
    assert 'BŁĘDY' in capsys.readouterr().out
