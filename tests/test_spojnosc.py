"""scripts/sprawdz_spojnosc.py — kontrola po wdrozeniu.

Test pilnuje, zeby skrypt nie zgnil razem ze zmianami modelu: na spojnych
danych nie zglasza bledow, a rozjechane rozliczenie i wiszaca paczke widzi.
"""
import importlib.util
import os
from datetime import date, datetime, timedelta

from conftest import make_user

from logistat.extensions import db
from logistat.models import GeneralStat
from logistat.web.wspolne import process_import_rows


DZIEN = date(2026, 10, 15)

_spec = importlib.util.spec_from_file_location(
    'sprawdz_spojnosc',
    os.path.join(os.path.dirname(__file__), '..', 'scripts', 'sprawdz_spojnosc.py'))
skrypt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(skrypt)


def dane(leader_client):
    make_user('operator', barcode_id='A', display_name='Osoba A')
    process_import_rows([
        {'barcode': f'P{i}', 'land': 'PL', 'stueckzahl': 10, 'uebergabe_nr': 'UB-1'}
        for i in range(3)], DZIEN)
    for kod in ('P0', 'P1'):
        leader_client.post('/api/package-time/start', json={'employee_barcode': 'A', 'package_barcode': kod})
        leader_client.post('/api/package-time/end', json={
            'employee_barcode': 'A', 'package_barcode': kod, 'tryb': 'wzor',
            'tabela': {'wersja': 2, 'grupy': {'bizuteria': {'ilosc': 7}}, 'podwojnie': 3}})


def opisy(lista):
    return [opis for opis, _ in lista]


def test_spojne_dane_bez_bledow(leader_client, acting_admin):
    dane(leader_client)

    bledy, uwagi = skrypt.sprawdz()

    assert bledy == []
    assert not any('niezakończone' in o for o in opisy(uwagi))


def test_stara_tabela_v1_dalej_spojna(leader_client, acting_admin):
    """Paczki z tabela z 15–22.10 (wersja 1) licza sie dalej po staremu —
    po wdrozeniu wersji 2 skrypt nie moze zglosic na nich rozjazdu."""
    from logistat.models import ImportedCarton
    from logistat.paczki import zapisz_tabele_kartonu
    dane(leader_client)
    c = ImportedCarton.query.filter_by(barcode='P2').one()
    c.scan_start_at = c.scan_end_at = datetime.utcnow()
    zapisz_tabele_kartonu(c, {
        'tryb': 'wzor', 'dodatki': {'sortowanie_inne': 1, 'worki': 2},
        'grupy': {'bizuteria': {'ilosc': 10, 'brak': 0, 'nadwyzka': 0, 'uszkodzone': 1,
                                'podwojnie': 2, 'potrojnie': 0, 'pojedynczo': 7}}}, None)
    db.session.commit()

    bledy, _ = skrypt.sprawdz()

    assert bledy == []
    assert c.get_scan_categories() == {'labelling_on': 7, 'labelling_tvl': 3, 'sorting': 2,
                                       'labelling_polybag': 2}


def test_rozjechane_rozliczenie_to_blad(leader_client, acting_admin):
    dane(leader_client)
    linia = GeneralStat.query.one()
    linia.amounts = 999
    dane_kat = linia.get_category_data()
    dane_kat['labelling_tvl']['amount'] = 1
    linia.set_category_data(dane_kat)
    db.session.commit()

    bledy, _ = skrypt.sprawdz()

    assert 'Amounts linii ≠ suma Stückzahl jej paczek' in opisy(bledy)
    assert "linia 'scan' ≠ suma ilości z jej paczek" in opisy(bledy)


def test_wiszaca_paczka_to_uwaga(leader_client, acting_admin):
    dane(leader_client)
    leader_client.post('/api/package-time/start', json={'employee_barcode': 'A', 'package_barcode': 'P2'})

    _, uwagi = skrypt.sprawdz(teraz=datetime.utcnow() + timedelta(days=1))

    assert any('niezakończone' in o for o in opisy(uwagi))


def test_import_z_flaga_nie_dotyka_bazy():
    """Skrypt „tylko do odczytu" importuje app z LOGISTAT_BEZ_INIT=1 — wtedy
    import nie moze robic DDL / migracji / seeda. Dowod: baza nieosiagalna,
    a import i tak przechodzi (bez flagi init_db() by na niej padl)."""
    import subprocess
    import sys
    katalog = os.path.join(os.path.dirname(__file__), '..')
    env = {**os.environ, 'LOGISTAT_BEZ_INIT': '1',
           'DATABASE_URL': 'postgresql+psycopg2://nikt:nic@127.0.0.1:1/brak'}
    wynik = subprocess.run([sys.executable, '-c', 'import app'], cwd=katalog, env=env,
                           capture_output=True, text=True, timeout=60)
    assert wynik.returncode == 0, wynik.stderr


def test_main_zwraca_kod_bledu(leader_client, acting_admin, capsys):
    dane(leader_client)
    GeneralStat.query.one().amounts = 1
    db.session.commit()

    assert skrypt.main() == 1
    assert 'BŁĘDY' in capsys.readouterr().out


def test_skrypt_uruchamia_sie_jako_plik():
    """Tak jak po wdrozeniu: `python scripts/sprawdz_spojnosc.py` z katalogu
    aplikacji — import pakietu musi isc po dodaniu katalogu do sys.path."""
    import subprocess
    import sys
    katalog = os.path.join(os.path.dirname(__file__), '..')
    wynik = subprocess.run([sys.executable, 'scripts/sprawdz_spojnosc.py'], cwd=katalog,
                           capture_output=True, text=True, timeout=120)
    assert 'Spójność' in wynik.stdout, wynik.stderr

