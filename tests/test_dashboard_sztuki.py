"""Dashboard, zakladka Podsumowanie — kafle w paczkach i w sztukach.

„Zrobione dzis" i „Pozostalo" sa pokazywane w obu jednostkach, bo paczki maja
od 1 do kilkuset sztuk i sama liczba paczek nie mowi, ile towaru zostalo.
"""
from datetime import date, timedelta

import app as logistat

ZIEL = date(2026, 9, 10)


def carton(barcode, stueckzahl, scan_end_at=None):
    c = logistat.ImportedCarton(barcode=barcode, land='PL', stueckzahl=stueckzahl,
                                ziel_datum=ZIEL, data_pliku=ZIEL, uebergabe_nr='UB-1',
                                scan_end_at=scan_end_at)
    logistat.db.session.add(c)
    return c


def test_pozostalo_i_zrobione_dzis_w_sztukach(leader_client):
    start_dzis, _ = logistat.local_day_bounds(logistat.local_today())
    carton('D1', 30, scan_end_at=start_dzis + timedelta(hours=1))   # dzis
    carton('D2', 12, scan_end_at=start_dzis + timedelta(hours=2))   # dzis
    carton('W1', 500, scan_end_at=start_dzis - timedelta(minutes=1))  # wczoraj
    carton('O1', 40)                                                  # otwarta
    carton('O2', 7)                                                   # otwarta
    logistat.db.session.commit()

    d = leader_client.get('/api/dashboard').get_json()

    assert d['done_today'] == 2
    assert d['pieces_today'] == 42
    assert d['remaining_cartons'] == 2
    assert d['remaining_pieces'] == 47


def test_pusta_baza_daje_zera(leader_client):
    d = leader_client.get('/api/dashboard').get_json()

    assert d['remaining_pieces'] == 0
    assert d['pieces_today'] == 0


def test_kafel_pozostalo_w_sztukach_na_ekranie(leader_client):
    html = leader_client.get('/dashboard').get_data(as_text=True)

    assert 'id="remainingPiecesVal"' in html
