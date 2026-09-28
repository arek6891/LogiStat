"""Statystyki jednej osoby (`/api/stats/user/<id>`) — srednie paczek i sztuk.

Mianownik to dni / miesiace, w ktorych osoba zakonczyla choc jedna paczke,
nie dni kalendarzowe zakresu — dzien wolny nie zaniza sredniej.
"""
from datetime import date, timedelta

import app as logistat
from conftest import make_user

ZIEL = date(2026, 9, 10)


def paczka(barcode, kto, sztuk, dzien, godzina=10):
    """Paczka zakonczona o `godzina` czasu lokalnego danego dnia."""
    koniec = logistat.local_day_bounds(dzien)[0] + timedelta(hours=godzina)
    logistat.db.session.add(logistat.ImportedCarton(
        barcode=barcode, land='PL', stueckzahl=sztuk, ziel_datum=ZIEL,
        uebergabe_nr='UB-1', scan_start_at=koniec - timedelta(minutes=10),
        scan_start_by=kto.id, scan_end_at=koniec, scan_end_by=kto.id))
    logistat.db.session.commit()


def statystyki(client, kto, **params):
    r = client.get(f'/api/stats/user/{kto.id}', query_string=params)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()['paczki_podsumowanie']


def test_srednia_dzienna_i_miesieczna(leader_client):
    a = make_user('operator', username='ala', display_name='Ala')
    # wrzesien: 2 dni pracy (3 + 1 paczka), pazdziernik: 1 dzien (2 paczki)
    paczka('W1', a, 10, date(2026, 9, 1))
    paczka('W2', a, 20, date(2026, 9, 1), godzina=11)
    paczka('W3', a, 30, date(2026, 9, 1), godzina=12)
    paczka('W4', a, 40, date(2026, 9, 15))
    paczka('P1', a, 50, date(2026, 10, 2))
    paczka('P2', a, 60, date(2026, 10, 2), godzina=11)

    p = statystyki(leader_client, a, date_from='2026-09-01', date_to='2026-10-31')

    assert (p['paczek'], p['sztuk']) == (6, 210)
    assert (p['dni_pracy'], p['miesiecy_pracy']) == (3, 2)
    assert p['srednio_dziennie'] == {'paczek': 2.0, 'sztuk': 70.0}
    assert p['srednio_miesiecznie'] == {'paczek': 3.0, 'sztuk': 105.0}


def test_dni_bez_pracy_nie_zanizaja_sredniej(leader_client):
    a = make_user('operator', username='ala', display_name='Ala')
    paczka('W1', a, 100, date(2026, 9, 1))
    paczka('W2', a, 100, date(2026, 9, 20))

    p = statystyki(leader_client, a, date_from='2026-09-01', date_to='2026-09-30')

    assert p['dni_pracy'] == 2
    assert p['srednio_dziennie'] == {'paczek': 1.0, 'sztuk': 100.0}


def test_paczki_innej_osoby_i_spoza_zakresu_nie_licza_sie(leader_client):
    a = make_user('operator', username='ala', display_name='Ala')
    b = make_user('operator', username='ola', display_name='Ola')
    paczka('A1', a, 10, date(2026, 9, 5))
    paczka('A2', a, 99, date(2026, 8, 31))       # przed zakresem
    paczka('B1', b, 77, date(2026, 9, 5))        # cudza

    p = statystyki(leader_client, a, date_from='2026-09-01', date_to='2026-09-30')

    assert (p['paczek'], p['sztuk']) == (1, 10)


def test_podsumowanie_jest_takze_przy_filtrze_czynnosci(leader_client):
    """Tabela chowa wiersze paczek przy wybranej czynnosci, ale srednie paczek
    maja sie liczyc niezaleznie od tego filtra."""
    a = make_user('operator', username='ala', display_name='Ala')
    paczka('A1', a, 10, date(2026, 9, 5))
    czynnosc = logistat.Activity.query.first()

    p = statystyki(leader_client, a, activity_id=czynnosc.id,
                   date_from='2026-09-01', date_to='2026-09-30')

    assert p['paczek'] == 1


def test_brak_paczek_daje_none_a_nie_zero(leader_client):
    a = make_user('operator', username='ala', display_name='Ala')

    p = statystyki(leader_client, a)

    assert p['paczek'] == 0 and p['dni_pracy'] == 0
    assert p['srednio_dziennie'] == {'paczek': None, 'sztuk': None}
    assert p['srednio_miesiecznie'] == {'paczek': None, 'sztuk': None}


def test_ekran_ma_karte_srednich(leader_client):
    html = leader_client.get('/stats').get_data(as_text=True)

    assert 'id="paczkiPodsumowanie"' in html
