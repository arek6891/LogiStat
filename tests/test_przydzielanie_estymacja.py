"""Estymacja na tablicy Przydzielania: ile zrobia przydzieleni do czynnosci.

`/api/assignment/data` podaje srednia JEDNEJ osoby per czynnosc (`wydajnosc`),
a ekran mnozy ja przez liczbe przydzielonych. Srednia jest ze wszystkich
pracownikow, nie tylko obecnych na zmianie. `Post Processing` = skany paczek
(srednia zespolu z Norm), reszta = Wpis ilosci. Zmiana = 7,5 h.
"""
from datetime import date, timedelta

import app as logistat
from conftest import make_user

DZIEN = date(2026, 9, 20)


def wczytaj(client, dzien=DZIEN):
    r = client.get(f'/api/assignment/data?date={dzien.isoformat()}&shift_number=1')
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()['wydajnosc']


def zmiana(dzien, numer=1):
    s = logistat.Shift.query.filter_by(date=dzien, shift_number=numer).first()
    if not s:
        s = logistat.Shift(date=dzien, shift_number=numer)
        logistat.db.session.add(s)
        logistat.db.session.flush()
    return s


def wpis(kto, akt, ilosc, dzien):
    logistat.db.session.add(logistat.DailyStat(
        shift_id=zmiana(dzien).id, user_id=kto.id, activity_id=akt.id, quantity=ilosc))
    logistat.db.session.commit()


def paczka(barcode, kto, sztuk, dzien, minut=30):
    koniec = logistat.local_day_bounds(dzien)[0] + timedelta(hours=10)
    logistat.db.session.add(logistat.ImportedCarton(
        barcode=barcode, land='PL', stueckzahl=sztuk, data_pliku=dzien,
        uebergabe_nr='UB-1',
        scan_start_at=koniec - timedelta(minutes=minut), scan_start_by=kto.id,
        scan_end_at=koniec, scan_end_by=kto.id))
    logistat.db.session.commit()


def czynnosc(nazwa):
    return logistat.Activity.query.filter_by(name=nazwa).one()


def test_wpis_ilosci_srednia_wszystkich_na_osobe(leader_client):
    akt = czynnosc('Zwroty')
    a, b = make_user('operator'), make_user('operator')
    wpis(a, akt, 300, DZIEN - timedelta(days=1))
    wpis(b, akt, 150, DZIEN - timedelta(days=2))

    w = wczytaj(leader_client)[str(akt.id)]

    assert w['zrodlo'] == 'wpis'
    assert w['szt_zmiana_os'] == 225
    assert w['szt_h_os'] == 30          # 225 / 7,5 h
    assert w['probek'] == 2


def test_srednia_nie_zalezy_od_obecnosci_na_zmianie(leader_client):
    """Nikt nie jest wbity na zmiane — srednia i tak jest (ogolna, nie przydzielonych)."""
    akt = czynnosc('Zwroty')
    wpis(make_user('operator'), akt, 75, DZIEN - timedelta(days=3))

    assert wczytaj(leader_client)[str(akt.id)]['szt_zmiana_os'] == 75


def test_tylko_ostatnie_30_dni(leader_client):
    akt = czynnosc('Zwroty')
    kto = make_user('operator')
    wpis(kto, akt, 999, DZIEN - timedelta(days=31))
    wpis(kto, akt, 90, DZIEN - timedelta(days=30))

    assert wczytaj(leader_client)[str(akt.id)]['szt_zmiana_os'] == 90


def test_czynnosc_bez_danych_nie_ma_klucza(leader_client):
    """Brak danych to nie zero — ekran pokazuje „brak danych do estymacji"."""
    assert str(czynnosc('Orders').id) not in wczytaj(leader_client)


def test_post_processing_ze_skanow_paczek(leader_client):
    akt = czynnosc(logistat.CZYNNOSC_SKANOW_PACZEK)
    a, b = make_user('operator'), make_user('operator')
    paczka('PP-1', a, 100, DZIEN - timedelta(days=1), minut=30)    # 200 szt./h
    paczka('PP-2', b, 50, DZIEN - timedelta(days=2), minut=30)     # 100 szt./h

    w = wczytaj(leader_client)[str(akt.id)]

    assert w['zrodlo'] == 'skany'
    assert w['szt_h_os'] == 150         # 150 szt. / 1 h — wazone godzinami
    assert w['szt_zmiana_os'] == 1125   # × 7,5 h


def test_post_processing_ta_sama_srednia_co_w_normach(leader_client):
    paczka('PP-1', make_user('operator'), 70, DZIEN - timedelta(days=1), minut=20)
    od = DZIEN - timedelta(days=logistat.DNI_SREDNIEJ_PRZYDZIALU)

    w = wczytaj(leader_client)[str(czynnosc(logistat.CZYNNOSC_SKANOW_PACZEK).id)]

    assert w['szt_h_os'] == logistat.przeglad_zespolu(od, DZIEN)['srednia_szt_h']


def test_estymacja_takze_bez_utworzonej_zmiany(leader_client):
    """Planowanie na jutro: zmiany jeszcze nie ma, a estymacja juz jest."""
    akt = czynnosc('Zwroty')
    wpis(make_user('operator'), akt, 60, DZIEN - timedelta(days=1))
    jutro = DZIEN + timedelta(days=1)

    assert logistat.Shift.query.filter_by(date=jutro).first() is None
    assert wczytaj(leader_client, jutro)[str(akt.id)]['szt_zmiana_os'] == 60


def test_tablica_rysuje_estymacje(leader_client):
    html = leader_client.get('/assignment').get_data(as_text=True)
    assert 'data-est-for=' in html
    assert 'pokazEstymacje' in html
