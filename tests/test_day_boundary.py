"""Granica doby: „dzis" musi znaczyc to samo na kazdym ekranie.

Wszystko jest zapisywane jako naive UTC (`datetime.utcnow()`), a uzytkownik
pracuje w Europe/Warsaw. Doba lokalna zaczyna sie o 22:00 UTC (lato) albo
23:00 UTC (zima) dnia poprzedniego — i tak samo musi ja liczyc dashboard,
widok per zmiana i statystyki pracownika. Testy przechodza niezaleznie od
strefy czasowej serwera.
"""
from datetime import date, datetime, timedelta

import app as logistat
from conftest import make_user

ZIEL = date(2026, 9, 10)


def utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm)


def carton(barcode, scan_end_at, user, stueckzahl=10):
    c = logistat.ImportedCarton(
        barcode=barcode, land='PL', stueckzahl=stueckzahl,
        ziel_datum=ZIEL, uebergabe_nr='UB-1',
        scan_start_at=scan_end_at - timedelta(minutes=5), scan_start_by=user.id,
        scan_end_at=scan_end_at, scan_end_by=user.id,
    )
    logistat.db.session.add(c)
    logistat.db.session.commit()
    return c


# ── Helpery stref ────────────────────────────────────────────────────────────

def test_granice_doby_latem_to_utc_plus_2(flask_app):
    start, end = logistat.local_day_bounds(date(2026, 9, 2))

    assert start == utc(2026, 9, 1, 22), 'polnoc 2.09 w Warszawie = 1.09 22:00 UTC'
    assert end == utc(2026, 9, 2, 22)


def test_granice_doby_zima_to_utc_plus_1(flask_app):
    start, end = logistat.local_day_bounds(date(2026, 1, 15))

    assert start == utc(2026, 1, 14, 23), 'zima Warszawa to UTC+1'
    assert end == utc(2026, 1, 15, 23)


def test_granice_doby_w_dniu_zmiany_czasu(flask_app):
    """29.03.2026 — przejscie na czas letni, doba lokalna ma 23 godziny."""
    start, end = logistat.local_day_bounds(date(2026, 3, 29))

    assert start == utc(2026, 3, 28, 23)
    assert end == utc(2026, 3, 29, 22)
    assert (end - start) == timedelta(hours=23)


def test_local_today_to_data_warszawska(flask_app):
    from datetime import timezone
    oczekiwana = datetime.now(timezone.utc).astimezone(logistat.LOCAL_TZ).date()

    assert logistat.local_today() == oczekiwana


# ── Dashboard per zmiana ─────────────────────────────────────────────────────

def test_paczka_z_nocy_liczy_sie_do_doby_lokalnej(leader_client):
    """23:30 UTC to 01:30 czasu lokalnego NASTEPNEGO dnia — II zmiana."""
    w = make_user('operator', barcode_id='W1')
    carton('P-noc', utc(2026, 9, 1, 23, 30), w)

    r = leader_client.get('/api/dashboard/shifts?date=2026-09-02')
    d = r.get_json()
    razem = sum(s['packages'] for s in d['shifts']) + d['unattributed']['packages']

    assert razem == 1, 'praca po lokalnej polnocy nalezy do nowej doby'


def test_paczka_z_wieczora_zostaje_w_swojej_dobie(leader_client):
    """21:30 UTC to 23:30 lokalnie — jeszcze ten sam dzien."""
    w = make_user('operator', barcode_id='W1')
    carton('P-wieczor', utc(2026, 9, 1, 21, 30), w)

    d1 = leader_client.get('/api/dashboard/shifts?date=2026-09-01').get_json()
    d2 = leader_client.get('/api/dashboard/shifts?date=2026-09-02').get_json()

    def razem(d):
        return sum(s['packages'] for s in d['shifts']) + d['unattributed']['packages']

    assert razem(d1) == 1
    assert razem(d2) == 0


def test_kazda_paczka_dokladnie_w_jednej_dobie(leader_client):
    w = make_user('operator', barcode_id='W1')
    carton('A', utc(2026, 9, 1, 21, 30), w)   # 1.09 23:30 lokalnie
    carton('B', utc(2026, 9, 1, 23, 30), w)   # 2.09 01:30 lokalnie
    carton('C', utc(2026, 9, 2, 10, 0), w)    # 2.09 12:00 lokalnie
    carton('D', utc(2026, 9, 2, 22, 30), w)   # 3.09 00:30 lokalnie

    def razem(dstr):
        d = leader_client.get(f'/api/dashboard/shifts?date={dstr}').get_json()
        return sum(s['packages'] for s in d['shifts']) + d['unattributed']['packages']

    assert razem('2026-09-01') == 1
    assert razem('2026-09-02') == 2
    assert razem('2026-09-03') == 1
    assert razem('2026-09-01') + razem('2026-09-02') + razem('2026-09-03') == 4


def test_przypisanie_do_zmiany_po_obecnosci(leader_client):
    w = make_user('operator', barcode_id='W1')
    shift = logistat.get_or_create_shift(date(2026, 9, 2), 2)
    logistat.db.session.add(logistat.ShiftAttendance(shift_id=shift.id, user_id=w.id))
    logistat.db.session.commit()
    carton('P-noc', utc(2026, 9, 1, 23, 30), w, stueckzahl=7)

    d = leader_client.get('/api/dashboard/shifts?date=2026-09-02').get_json()
    zmiana2 = next(s for s in d['shifts'] if s['shift_number'] == 2)

    assert zmiana2['packages'] == 1
    assert zmiana2['pieces'] == 7
    assert d['unattributed']['packages'] == 0


# ── Spojnosc miedzy ekranami ─────────────────────────────────────────────────

def test_statystyki_pracownika_licza_te_sama_dobe_co_dashboard(leader_client):
    """Rdzen problemu: dashboard budowal granice z `date.today()`, a
    api_stats_user grupowal po `func.date()` w UTC. Ta sama paczka wypadala
    na roznych dniach na dwoch ekranach."""
    w = make_user('operator', barcode_id='W1', username='pracownik')
    carton('A', utc(2026, 9, 1, 21, 30), w)   # 1.09 lokalnie
    carton('B', utc(2026, 9, 1, 23, 30), w)   # 2.09 lokalnie
    carton('C', utc(2026, 9, 2, 22, 30), w)   # 3.09 lokalnie

    d = leader_client.get('/api/dashboard/shifts?date=2026-09-02').get_json()
    z_dashboardu = sum(s['packages'] for s in d['shifts']) + d['unattributed']['packages']

    s = leader_client.get(
        f'/api/stats/user/{w.id}?date_from=2026-09-02&date_to=2026-09-02').get_json()
    z_statystyk = next(
        (x['quantity'] for x in s['daily'] if x['activity'] == '📦 Paczki'), 0)

    assert z_dashboardu == 1
    assert z_statystyk == z_dashboardu, 'oba ekrany musza pokazac to samo'


def test_statystyki_pracownika_grupuja_po_dobie_lokalnej(leader_client):
    w = make_user('operator', barcode_id='W1', username='pracownik')
    carton('A', utc(2026, 9, 1, 21, 30), w, stueckzahl=3)   # 1.09
    carton('B', utc(2026, 9, 1, 23, 30), w, stueckzahl=5)   # 2.09
    carton('C', utc(2026, 9, 2, 6, 0), w, stueckzahl=7)     # 2.09

    s = leader_client.get(f'/api/stats/user/{w.id}').get_json()
    paczki = {x['date']: x['quantity'] for x in s['daily'] if x['activity'] == '📦 Paczki'}
    sztuki = {x['date']: x['quantity'] for x in s['daily']
              if x['activity'] == '📦 Paczki (szt.)'}

    assert paczki == {'2026-09-01': 1, '2026-09-02': 2}
    assert sztuki == {'2026-09-01': 3, '2026-09-02': 12}


def test_filtr_daty_w_statystykach_obejmuje_cala_dobe_lokalna(leader_client):
    w = make_user('operator', barcode_id='W1', username='pracownik')
    carton('B', utc(2026, 9, 1, 23, 30), w)   # 2.09 01:30 lokalnie
    carton('D', utc(2026, 9, 2, 21, 0), w)    # 2.09 23:00 lokalnie

    s = leader_client.get(
        f'/api/stats/user/{w.id}?date_from=2026-09-02&date_to=2026-09-02').get_json()
    paczki = [x for x in s['daily'] if x['activity'] == '📦 Paczki']

    assert len(paczki) == 1
    assert paczki[0]['date'] == '2026-09-02'
    assert paczki[0]['quantity'] == 2, 'oba konce doby lokalnej wchodza do filtra'


def test_miesieczna_agregacja_paczek_uzywa_doby_lokalnej(leader_client):
    w = make_user('operator', barcode_id='W1', username='pracownik')
    # 30.09 22:30 UTC = 1.10 00:30 lokalnie → to juz pazdziernik
    carton('X', utc(2026, 9, 30, 22, 30), w, stueckzahl=4)

    s = leader_client.get(f'/api/stats/user/{w.id}').get_json()
    miesiace = {m['month'] for m in s['monthly'] if m['activity'] == '📦 Paczki'}

    assert miesiace == {'2026-10'}
