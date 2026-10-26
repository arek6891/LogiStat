"""Dashboard, zakladka Podsumowanie — kafle w paczkach i w sztukach.

„Zrobione dzis" i „Pozostalo" sa pokazywane w obu jednostkach, bo paczki maja
od 1 do kilkuset sztuk i sama liczba paczek nie mowi, ile towaru zostalo.
"""
from datetime import date, timedelta

from conftest import strona_z_js

from logistat.czas import local_day_bounds, local_today
from logistat.extensions import db
from logistat.models import ImportedCarton


ZIEL = date(2026, 9, 10)


def carton(barcode, stueckzahl, scan_end_at=None):
    c = ImportedCarton(barcode=barcode, land='PL', stueckzahl=stueckzahl,
                                ziel_datum=ZIEL, data_pliku=ZIEL, uebergabe_nr='UB-1',
                                scan_end_at=scan_end_at)
    db.session.add(c)
    return c


def test_pozostalo_i_zrobione_dzis_w_sztukach(leader_client):
    start_dzis, _ = local_day_bounds(local_today())
    carton('D1', 30, scan_end_at=start_dzis + timedelta(hours=1))   # dzis
    carton('D2', 12, scan_end_at=start_dzis + timedelta(hours=2))   # dzis
    carton('W1', 500, scan_end_at=start_dzis - timedelta(minutes=1))  # wczoraj
    carton('O1', 40)                                                  # otwarta
    carton('O2', 7)                                                   # otwarta
    db.session.commit()

    d = leader_client.get('/api/dashboard').get_json()

    assert d['done_today'] == 2
    assert d['pieces_today'] == 42, 'wczorajsza i otwarte paczki sie nie licza'


def test_kafel_pozostalo_w_sztukach_na_ekranie(leader_client):
    html = leader_client.get('/dashboard').get_data(as_text=True)

    assert 'id="remainingPiecesVal"' in html


def test_dashboard_bez_starych_pol(leader_client):
    """Pola sprzed planu dnia (remaining_*, total_cartons, progress_pct) usuniete
    2026-10-24 — ekran ich nie czytal, a kazde liczylo wszystkie paczki od nowa."""
    d = leader_client.get('/api/dashboard').get_json()

    assert not {'total_cartons', 'done_cartons', 'remaining_cartons', 'remaining_pieces',
                'progress_pct'} & set(d)


def test_sztuki_duze_paczki_male(leader_client):
    """Operacja pracuje na sztukach (2026-10-26): duza liczba = sztuki,
    paczki w malym podpisie — kafle Dzis / Podsumowanie i plan pliku."""
    html = strona_z_js(leader_client, '/dashboard')

    assert 'id="piecesTodayVal" class="dash-val"' in html
    assert 'id="remainingPiecesVal" class="dash-val"' in html
    assert '<strong id="doneTodayVal">' in html
    assert '<strong id="remainingVal">' in html
    assert 'class="dash-val" style="color:${kolor};">${num(sztuk)}' in html
