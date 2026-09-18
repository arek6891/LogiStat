"""Czas „Inne" (np. wyjscie do HR) — rejestracja i wplyw na czas pracy.

„Inne" dziala jak przerwa: pomniejsza czas pracy, ale jest raportowane osobno,
bo operacja rozlicza przerwe i wyjscie sluzbowe inaczej. Przerwa i „Inne" nie
moga trwac jednoczesnie — inaczej ten sam czas zostalby odjety dwa razy.
"""
from datetime import datetime, timedelta

import app as logistat
from conftest import make_user


def zmiana_z_obecnoscia(barcode='W1', minut_temu=120):
    """Pracownik zeskanowany na dzisiejsza zmiane `minut_temu` minut temu."""
    user = make_user('operator', barcode_id=barcode)
    shift = logistat.get_or_create_shift(logistat.local_today(), 1)
    obecnosc = logistat.ShiftAttendance(
        shift_id=shift.id, user_id=user.id,
        scanned_at=datetime.utcnow() - timedelta(minutes=minut_temu))
    logistat.db.session.add(obecnosc)
    logistat.db.session.commit()
    return user, shift, obecnosc


def skan(client, barcode='W1', mode='other'):
    return client.post('/api/time/scan', json={'barcode': barcode, 'mode': mode})


def typy(user, shift):
    return [e.event_type for e in logistat.WorkerTimeEvent.query.filter_by(
        user_id=user.id, shift_id=shift.id).order_by(logistat.WorkerTimeEvent.timestamp)]


# ── rejestracja ──────────────────────────────────────────────────────────────

def test_skan_w_trybie_inne_przelacza_wyjscie_i_powrot(leader_client):
    user, shift, _ = zmiana_z_obecnoscia()

    r1 = skan(leader_client)
    r2 = skan(leader_client)

    assert r1.status_code == 200 and r1.get_json()['event_type'] == 'other_start'
    assert r2.status_code == 200 and r2.get_json()['event_type'] == 'other_end'
    assert typy(user, shift) == ['other_start', 'other_end']


def test_inne_nie_miesza_sie_z_przerwa(leader_client):
    """Dwa niezalezne liczniki — przerwa nie zamyka „Innego" i odwrotnie."""
    user, shift, _ = zmiana_z_obecnoscia()

    skan(leader_client, mode='break')      # break_start
    skan(leader_client, mode='break')      # break_end
    skan(leader_client, mode='other')      # other_start

    assert typy(user, shift) == ['break_start', 'break_end', 'other_start']


def test_przerwa_w_trakcie_innego_jest_odrzucona(leader_client):
    zmiana_z_obecnoscia()
    skan(leader_client, mode='other')

    r = skan(leader_client, mode='break')

    assert r.status_code == 409
    assert 'Inne' in r.get_json()['error']


def test_inne_w_trakcie_przerwy_jest_odrzucone(leader_client):
    zmiana_z_obecnoscia()
    skan(leader_client, mode='break')

    r = skan(leader_client, mode='other')

    assert r.status_code == 409
    assert 'przerwie' in r.get_json()['error']


def test_nieznany_tryb_konczy_sie_400(leader_client):
    zmiana_z_obecnoscia()

    r = skan(leader_client, mode='cokolwiek')

    assert r.status_code == 400


# ── wplyw na podsumowanie ────────────────────────────────────────────────────

def zdarzenie(user, shift, typ, minut_temu):
    logistat.db.session.add(logistat.WorkerTimeEvent(
        user_id=user.id, shift_id=shift.id, event_type=typ,
        timestamp=datetime.utcnow() - timedelta(minutes=minut_temu)))
    logistat.db.session.commit()


def test_inne_odejmuje_sie_od_czasu_pracy_i_jest_raportowane_osobno(flask_app):
    user, shift, obecnosc = zmiana_z_obecnoscia(minut_temu=120)
    zdarzenie(user, shift, 'other_start', 90)
    zdarzenie(user, shift, 'other_end', 60)      # 30 min „Inne"
    zdarzenie(user, shift, 'break_start', 50)
    zdarzenie(user, shift, 'break_end', 40)      # 10 min przerwy
    zdarzenie(user, shift, 'work_end', 0)

    p = logistat._compute_worker_times(user.id, shift, obecnosc.scanned_at)

    assert p['other_minutes'] == 30
    assert p['break_minutes'] == 10
    assert p['work_minutes'] == 80, '120 min obecnosci - 30 „Inne" - 10 przerwy'
    assert len(p['others']) == 1


def test_otwarte_inne_widac_jako_trwajace(flask_app):
    user, shift, obecnosc = zmiana_z_obecnoscia(minut_temu=60)
    zdarzenie(user, shift, 'other_start', 20)

    p = logistat._compute_worker_times(user.id, shift, obecnosc.scanned_at)

    assert p['on_other'] is True
    assert p['others'][0]['end'] is None


def test_koniec_pracy_zamyka_otwarte_inne(leader_client):
    """Bez auto-zamkniecia otwarte „Inne" zjadaloby czas pracy w nieskonczonosc."""
    user, shift, _ = zmiana_z_obecnoscia()
    skan(leader_client, mode='other')

    r = skan(leader_client, mode='work_end')

    assert r.status_code == 200
    assert typy(user, shift) == ['other_start', 'other_end', 'work_end']
    domkniete = logistat.WorkerTimeEvent.query.filter_by(
        user_id=user.id, event_type='other_end').first()
    assert 'Auto-zamknięcie' in (domkniete.note or '')


def test_koniec_pracy_zamyka_i_przerwe_i_inne(leader_client):
    user, shift, _ = zmiana_z_obecnoscia()
    skan(leader_client, mode='break')          # otwarta przerwa
    # „Inne" otwarte recznie — omija blokade wzajemna, symuluje korekte lidera
    zdarzenie(user, shift, 'other_start', 5)

    skan(leader_client, mode='work_end')

    assert typy(user, shift).count('break_end') == 1
    assert typy(user, shift).count('other_end') == 1


# ── korekta reczna ───────────────────────────────────────────────────────────

def test_lider_moze_dodac_zdarzenie_inne_recznie(leader_client):
    user, shift, _ = zmiana_z_obecnoscia()

    r = leader_client.post('/api/worker-times/event', json={
        'user_id': user.id, 'shift_id': shift.id,
        'event_type': 'other_start',
        'timestamp': datetime.utcnow().replace(microsecond=0).isoformat(),
    })

    assert r.status_code == 201
    assert r.get_json()['event_type'] == 'other_start'


# ── nakladajace sie okresy (reczne korekty) ──────────────────────────────────

def test_nachodzaca_przerwa_i_inne_nie_odejmuja_czasu_dwa_razy(flask_app):
    """Skan pilnuje rozlacznosci, ale korekta na /worker-times juz nie —
    a sumowanie dlugosci zanizyloby czas pracy."""
    user, shift, obecnosc = zmiana_z_obecnoscia(minut_temu=120)
    zdarzenie(user, shift, 'break_start', 90)
    zdarzenie(user, shift, 'break_end', 60)      # 30 min przerwy
    zdarzenie(user, shift, 'other_start', 80)
    zdarzenie(user, shift, 'other_end', 50)      # 30 min „Inne", 20 min wspolne

    p = logistat._compute_worker_times(user.id, shift, obecnosc.scanned_at)

    assert p['break_minutes'] == 30, 'raportowanie zostaje bez zmian'
    assert p['other_minutes'] == 30
    assert p['work_minutes'] == 80, '120 - 40 min zlaczonych okresow (nie 120 - 60)'


def test_okres_zawarty_w_drugim_liczy_sie_raz(flask_app):
    user, shift, obecnosc = zmiana_z_obecnoscia(minut_temu=100)
    zdarzenie(user, shift, 'break_start', 90)
    zdarzenie(user, shift, 'break_end', 30)      # 60 min
    zdarzenie(user, shift, 'other_start', 70)
    zdarzenie(user, shift, 'other_end', 50)      # 20 min w srodku przerwy

    p = logistat._compute_worker_times(user.id, shift, obecnosc.scanned_at)

    assert p['work_minutes'] == 40, '100 - 60, „Inne" siedzi w calosci w przerwie'


def test_rozlaczne_okresy_sumuja_sie_normalnie(flask_app):
    user, shift, obecnosc = zmiana_z_obecnoscia(minut_temu=120)
    zdarzenie(user, shift, 'break_start', 110)
    zdarzenie(user, shift, 'break_end', 100)     # 10 min
    zdarzenie(user, shift, 'other_start', 50)
    zdarzenie(user, shift, 'other_end', 30)      # 20 min

    p = logistat._compute_worker_times(user.id, shift, obecnosc.scanned_at)

    assert p['work_minutes'] == 90, '120 - 30'


def test_odwrocony_zakres_po_recznej_korekcie_jest_pomijany(flask_app):
    """Koniec przed poczatkiem to blad danych — nie moze dodac czasu pracy."""
    user, shift, obecnosc = zmiana_z_obecnoscia(minut_temu=60)
    zdarzenie(user, shift, 'break_start', 20)
    zdarzenie(user, shift, 'break_end', 30)      # koniec 10 min PRZED startem

    p = logistat._compute_worker_times(user.id, shift, obecnosc.scanned_at)

    assert p['work_minutes'] <= 60


def test_suma_zlaczonych_okresow_bez_danych():
    assert logistat.suma_zlaczonych_okresow([]) == 0
