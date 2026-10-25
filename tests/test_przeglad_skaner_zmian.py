"""Skaner zmian — poprawki z przegladu 2026-10-24.

- data obecnosci = dzis serwera (Warszawa), nie data z karty otwartej od wczoraj
  (konto stanowiska ma sesje 30 dni — rano zapisywalo obecnosc na wczoraj),
- podwojny skan z dwoch stanowisk naraz → „juz zarejestrowany”, nie 500,
- usuniecie obecnosci ze zdarzeniami czasu pracy → 409 (zdarzenia zostalyby
  osierocone i znikaly z /worker-times); konto stanowiska usuwa tylko dzisiejsze.
"""
from datetime import timedelta

from conftest import login, make_user

from logistat.czas import local_today
from logistat.extensions import db
from logistat.models import Shift, ShiftAttendance, WorkerTimeEvent


def test_skan_zapisuje_dzis_mimo_starej_daty_z_karty(leader_client):
    make_user('operator', barcode_id='EMP1')
    wczoraj = (local_today() - timedelta(days=1)).isoformat()

    r = leader_client.post('/api/scan', json={'barcode': 'EMP1', 'shift_number': 1, 'date': wczoraj})

    assert r.status_code == 201
    a = db.session.get(ShiftAttendance, r.get_json()['attendance']['id'])
    assert db.session.get(Shift, a.shift_id).date == local_today()


def test_podwojny_skan_naraz_to_juz_zarejestrowany(leader_client, monkeypatch):
    """Dwie stacje: obie sprawdzaja „czy jest” przed zapisem drugiej — unikalny
    klucz (shift, user) odrzuca drugi INSERT. Ma byc komunikat, nie 500."""
    u = make_user('operator', barcode_id='EMP2')
    assert leader_client.post('/api/scan', json={'barcode': 'EMP2'}).status_code == 201
    import logistat.web.stanowisko as st
    prawdziwe = st.ShiftAttendance.query

    class BezIstniejacej:
        def filter_by(self, **kw):
            class Pusto:
                def first(self):
                    return None
            return Pusto()
    monkeypatch.setattr(st.ShiftAttendance, 'query', BezIstniejacej())

    r = leader_client.post('/api/scan', json={'barcode': 'EMP2'})

    monkeypatch.setattr(st.ShiftAttendance, 'query', prawdziwe)
    assert r.status_code == 200 and r.get_json()['already_scanned'] is True
    assert ShiftAttendance.query.filter_by(user_id=u.id).count() == 1


def _obecnosc(client, kod):
    return client.post('/api/scan', json={'barcode': kod}).get_json()['attendance']['id']


def test_nie_usunie_obecnosci_ze_zdarzeniami_czasu(leader_client):
    make_user('operator', barcode_id='EMP3')
    aid = _obecnosc(leader_client, 'EMP3')
    assert leader_client.post('/api/time/scan', json={'barcode': 'EMP3', 'mode': 'break'}).status_code == 200

    r = leader_client.delete(f'/api/scan/{aid}')

    assert r.status_code == 409 and 'Czasy pracowników' in r.get_json()['error']
    assert db.session.get(ShiftAttendance, aid) is not None


def test_obecnosc_bez_zdarzen_usuwa_sie(leader_client):
    make_user('operator', barcode_id='EMP4')
    aid = _obecnosc(leader_client, 'EMP4')

    assert leader_client.delete(f'/api/scan/{aid}').status_code == 200
    assert db.session.get(ShiftAttendance, aid) is None


def test_stanowisko_nie_usuwa_obecnosci(client):
    """Operacje 2026-10-25: konto stanowiska nie usuwa obecnosci wcale, nawet dzisiejszej."""
    u = make_user('operator', barcode_id='EMP5')
    stara = Shift(date=local_today() - timedelta(days=2), shift_number=1)
    db.session.add(stara)
    db.session.flush()
    a = ShiftAttendance(shift_id=stara.id, user_id=u.id)
    db.session.add(a)
    db.session.commit()
    st = make_user('stanowisko')
    login(client, st.username)

    assert client.delete(f'/api/scan/{a.id}').status_code == 403
    assert db.session.get(ShiftAttendance, a.id) is not None
    dzis = _obecnosc(client, 'EMP5')
    assert client.delete(f'/api/scan/{dzis}').status_code == 403
    assert db.session.get(ShiftAttendance, dzis) is not None
    strona = client.get('/scanner/1').get_data(as_text=True)
    assert 'removeAttendance(' not in strona.split('<script')[0]
    assert 'const MOZE_USUWAC = false' in strona


def test_lider_widzi_przycisk_usuwania(leader_client):
    make_user('operator', barcode_id='EMP7')
    _obecnosc(leader_client, 'EMP7')
    strona = leader_client.get('/scanner/1').get_data(as_text=True)
    assert 'removeAttendance(' in strona
    assert 'const MOZE_USUWAC = true' in strona


def test_zdarzenie_sprawdzane_dla_tej_zmiany(leader_client):
    """Zdarzenia z innej zmiany tej osoby nie blokuja usuniecia."""
    u = make_user('operator', barcode_id='EMP6')
    inna = Shift(date=local_today() - timedelta(days=1), shift_number=1)
    db.session.add(inna)
    db.session.flush()
    db.session.add(WorkerTimeEvent(user_id=u.id, shift_id=inna.id, event_type='break_start'))
    db.session.commit()
    aid = _obecnosc(leader_client, 'EMP6')

    assert leader_client.delete(f'/api/scan/{aid}').status_code == 200


def test_js_nie_bierze_dnia_utc():
    """`valueAsDate = new Date()` = dzien UTC: po polnocy Przydzielanie i Wpis
    ilosci pokazywaly wczoraj i autozapis pisal pod wczoraj. Jest dzisLokalnie()."""
    import glob
    for plik in glob.glob('static/js/*.js'):
        assert 'valueAsDate = new Date()' not in open(plik, encoding='utf-8').read(), plik
    skaner = open('static/js/scanner.js', encoding='utf-8').read()
    assert 'date: TODAY' not in skaner and 'nowyDzien' in skaner
    # Zegar tabletu vs serwer: porownanie z TODAY = petla przeladowan przy zlej strefie.
    assert '=== TODAY' not in skaner and 'TODAY ===' not in skaner
    assert 'if (nowyDzien()) return' not in skaner, 'skan ma isc, przeladowanie potem'


def test_udzial_pokazuje_sztuki_nie_jednostki_rozliczenia():
    """`suma()` udzialu = kategorie rozliczenia (Podwojne ×1,5, Flagi) — 10 podwojnych
    pokazywalo sie jako „15 szt.”. Sztuki = `sztuki` (sztuki_tabeli)."""
    for plik in ('static/js/scan_package.js', 'static/js/paczki.js'):
        assert "u.suma + ' szt.'" not in open(plik, encoding='utf-8').read(), plik
