"""Czasy pracowników: oś czasu, filtr po osobie, korekta wejścia (operacja 2026-10-23).

- `/api/worker-times?user_id=&date_from=&date_to=` — każdy dzień jednej osoby,
- `czynnosci` w wierszu = czynności z Przydzielania tego dnia (bez godzin),
- `PUT /api/worker-times/wejscie/<id>` — korekta godziny skanu na zmianie
  z zapisem pierwotnego skanu, kto i kiedy.
"""
from datetime import date, timedelta

from conftest import make_user

from logistat.czas import local_day_bounds
from logistat.extensions import db
from logistat.models import (
    Activity, ActivityAssignment, ShiftAttendance, WorkerTimeEvent, get_or_create_shift)


D1, D2, D3 = date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22)


def obecnosc(user, dzien, godzina=7, nr=1):
    shift = get_or_create_shift(dzien, nr)
    od, _ = local_day_bounds(dzien)
    att = ShiftAttendance(shift_id=shift.id, user_id=user.id,
                          scanned_at=od + timedelta(hours=godzina))
    db.session.add(att)
    db.session.commit()
    return att


def zdarzenie(att, typ, minut_po_wejsciu):
    e = WorkerTimeEvent(user_id=att.user_id, shift_id=att.shift_id, event_type=typ,
                        timestamp=att.scanned_at + timedelta(minutes=minut_po_wejsciu))
    db.session.add(e)
    db.session.commit()
    return e


def przydziel(att, nazwa):
    akt = Activity.query.filter_by(name=nazwa).first()
    if akt is None:
        akt = Activity(name=nazwa, sort_order=99)
        db.session.add(akt)
        db.session.flush()
    db.session.add(ActivityAssignment(shift_id=att.shift_id, user_id=att.user_id,
                                      activity_id=akt.id))
    db.session.commit()


# ── filtr po osobie ──────────────────────────────────────────────────────────

def test_osoba_w_zakresie_dostaje_kazdy_swoj_dzien(leader_client):
    a = make_user('operator', barcode_id='A', display_name='Osoba A')
    b = make_user('operator', barcode_id='B', display_name='Osoba B')
    for dzien in (D1, D2, D3):
        obecnosc(a, dzien)
    obecnosc(b, D2)
    obecnosc(a, D2 - timedelta(days=5))      # poza zakresem

    r = leader_client.get(f'/api/worker-times?user_id={a.id}&date_from={D1}&date_to={D3}')

    assert r.status_code == 200, r.get_json()
    wiersze = r.get_json()['workers']
    assert [w['date'] for w in wiersze] == [D1.isoformat(), D2.isoformat(), D3.isoformat()]
    assert {w['user_id'] for w in wiersze} == {a.id}


def test_dzien_z_dwiema_zmianami_to_jeden_wiersz_od_wczesniejszej(leader_client):
    a = make_user('operator', barcode_id='A')
    obecnosc(a, D1, godzina=14, nr=2)
    rano = obecnosc(a, D1, godzina=6, nr=1)

    wiersze = leader_client.get(
        f'/api/worker-times?user_id={a.id}&date_from={D1}&date_to={D1}').get_json()['workers']

    assert len(wiersze) == 1
    assert wiersze[0]['attendance_id'] == rano.id


def test_zly_zakres_to_400(leader_client):
    a = make_user('operator', barcode_id='A')
    url = f'/api/worker-times?user_id={a.id}'

    assert leader_client.get(url).status_code == 400
    assert leader_client.get(f'{url}&date_from={D3}&date_to={D1}').status_code == 400
    r = leader_client.get(f'{url}&date_from=2026-01-01&date_to=2026-12-31')
    assert r.status_code == 400 and 'dni' in r.get_json()['error']


def test_widok_dnia_bez_zmian(leader_client):
    a = make_user('operator', barcode_id='A', display_name='Osoba A')
    att = obecnosc(a, D2)
    zdarzenie(att, 'work_end', 480)

    r = leader_client.get(f'/api/worker-times?date={D2}')

    w = r.get_json()['workers'][0]
    assert w['user_name'] == 'Osoba A' and w['work_ended'] is True
    assert w['attendance_id'] == att.id and w['date'] == D2.isoformat()
    assert w['wejscie_poprawione'] is None


# ── czynnosci ────────────────────────────────────────────────────────────────

def test_czynnosci_z_przydzielania_bez_godzin(leader_client):
    a = make_user('operator', barcode_id='A')
    att = obecnosc(a, D2)
    przydziel(att, 'Post Processing')
    przydziel(att, 'Tekstylia')
    obecnosc(a, D3)

    wiersze = leader_client.get(
        f'/api/worker-times?user_id={a.id}&date_from={D2}&date_to={D3}').get_json()['workers']

    assert sorted(wiersze[0]['czynnosci']) == ['Post Processing', 'Tekstylia']
    assert wiersze[1]['czynnosci'] == []


# ── korekta wejscia ──────────────────────────────────────────────────────────

def put_wejscie(client, att, ts):
    return client.put(f'/api/worker-times/wejscie/{att.id}',
                      json={'timestamp': ts.isoformat(timespec='seconds')})


def test_korekta_wejscia_zapisuje_pierwotny_skan_i_kto(leader_client, leader):
    a = make_user('operator', barcode_id='A')
    att = obecnosc(a, D2, godzina=7)
    skan = att.scanned_at
    zdarzenie(att, 'work_end', 480)

    r1 = put_wejscie(leader_client, att, skan - timedelta(minutes=15))
    r2 = put_wejscie(leader_client, att, skan - timedelta(minutes=20))

    assert r1.status_code == 200 and r2.status_code == 200, (r1.get_json(), r2.get_json())
    db.session.expire_all()
    att = db.session.get(ShiftAttendance, att.id)
    assert att.scanned_at == skan - timedelta(minutes=20)
    assert att.pierwotny_skan == skan, 'pierwotny skan z PRZED pierwszej korekty'
    assert att.poprawione_przez == leader.id and att.poprawione_at is not None
    w = leader_client.get(f'/api/worker-times?date={D2}').get_json()['workers'][0]
    assert w['work_minutes'] == 500
    assert w['wejscie_poprawione']['kto'] == leader.display_name


def test_wejscie_po_pierwszym_zdarzeniu_to_400(leader_client):
    a = make_user('operator', barcode_id='A')
    att = obecnosc(a, D2, godzina=7)
    przerwa = zdarzenie(att, 'break_start', 60)

    r = put_wejscie(leader_client, att, przerwa.timestamp + timedelta(minutes=1))

    assert r.status_code == 400 and 'przed pierwszym' in r.get_json()['error']
    db.session.expire_all()
    assert db.session.get(ShiftAttendance, att.id).pierwotny_skan is None


def test_wejscie_w_innym_dniu_to_400(leader_client):
    a = make_user('operator', barcode_id='A')
    att = obecnosc(a, D2, godzina=7)

    r = put_wejscie(leader_client, att, att.scanned_at - timedelta(days=1))

    assert r.status_code == 400 and 'dniu zmiany' in r.get_json()['error']


def test_korekta_wejscia_wymaga_logowania(client):
    a = make_user('operator', barcode_id='A')
    att = obecnosc(a, D2)

    r = put_wejscie(client, att, att.scanned_at)

    assert r.status_code == 401


# ── ekran ────────────────────────────────────────────────────────────────────

def test_ekran_ma_filtr_osoby_z_zakresem_i_os(leader_client):
    make_user('operator', barcode_id='A', display_name='Osoba Zakresowa')

    html = leader_client.get('/worker-times').get_data(as_text=True)
    js = leader_client.get('/static/js/worker_times.js').get_data(as_text=True)

    assert 'Osoba Zakresowa' in html
    assert 'id="dateFrom"' in html and 'id="dateTo"' in html
    assert 'os-czasu' in js and '/api/worker-times/wejscie/' in js



def test_filtr_osoby_bez_n_plus_1(leader_client, queries):
    """Zdarzenia wszystkich dni jednym zapytaniem — liczba zapytan nie rosnie z dniami."""
    a = make_user('operator', barcode_id='A')
    for i in range(10):
        att = obecnosc(a, D1 + timedelta(days=i))
        zdarzenie(att, 'break_start', 60)
        zdarzenie(att, 'break_end', 75)
        zdarzenie(att, 'work_end', 480)
    queries.statements.clear()

    r = leader_client.get(
        f'/api/worker-times?user_id={a.id}&date_from={D1}&date_to={D1 + timedelta(days=9)}')

    assert r.status_code == 200 and len(r.get_json()['workers']) == 10
    assert len(queries.matching('FROM worker_time_event')) == 1
