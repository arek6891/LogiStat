"""Czas pracy i szkolenia — poprawki z przegladu 2026-10-24.

- osoba szkolona kolejno u dwoch szkolacych: koniec szkolenia A zamykal ja
  takze u B (B zostawal bez szkolonych, a Normy liczyly mu 100 % celu),
- dwie obecnosci jednego dnia: zdarzenia szly na pozniejsza zmiane, a Czasy
  pracownikow pokazuja wiersz od najwczesniejszej — przerwy znikaly,
- lista trwajacych szkolen wywracala sie (400) przez jednego szkolacego bez
  dzisiejszej obecnosci.
"""
from datetime import datetime, timedelta

from conftest import make_user
from test_szkolenie import dopisz, obecny, skan, szkolacy, wybierz_trenera, zakoncz

from logistat.czas import local_today
from logistat.extensions import db
from logistat.models import ShiftAttendance, WorkerTimeEvent, get_or_create_shift


def _otwarte_szkolenie(user):
    typy = [e.event_type for e in WorkerTimeEvent.query.filter_by(user_id=user.id)]
    return typy.count('trainee_start') > typy.count('trainee_end')


def test_koniec_szkolenia_a_nie_zamyka_szkolonego_u_b(leader_client):
    a, b = szkolacy('A', barcode='TA'), szkolacy('B', barcode='TB')
    x = make_user('operator', display_name='X', barcode_id='SX')
    y = make_user('operator', display_name='Y', barcode_id='SY')
    for u in (a, b, x, y):
        obecny(u)

    wybierz_trenera(leader_client, 'TA')
    assert dopisz(leader_client, a, 'SX').status_code == 200
    assert zakoncz(leader_client, a).status_code == 200
    wybierz_trenera(leader_client, 'TB')
    assert dopisz(leader_client, b, 'SX').status_code == 200
    wybierz_trenera(leader_client, 'TA')
    assert dopisz(leader_client, a, 'SY').status_code == 200

    r = zakoncz(leader_client, a)

    assert r.status_code == 200
    assert _otwarte_szkolenie(x), 'X dalej szkoli sie u B'
    assert not _otwarte_szkolenie(y)
    aktywne = leader_client.get('/api/time/training/aktywne').get_json()['szkolenia']
    assert [s['szkoleni'] for s in aktywne] == [[{'id': x.id, 'display_name': 'X'}]]


def test_dwie_obecnosci_dnia_zdarzenia_na_pierwszej(leader_client):
    u = make_user('operator', barcode_id='E1')
    z1 = obecny(u, minut_temu=300)
    z2 = get_or_create_shift(local_today(), 2)
    db.session.add(ShiftAttendance(shift_id=z2.id, user_id=u.id,
                                   scanned_at=datetime.utcnow() - timedelta(minutes=10)))
    db.session.commit()

    assert skan(leader_client, 'break', 'E1').status_code == 200

    assert WorkerTimeEvent.query.filter_by(user_id=u.id).one().shift_id == z1.id
    wiersze = leader_client.get(f'/api/worker-times?date={local_today().isoformat()}').get_json()
    wiersz = next(w for w in (wiersze if isinstance(wiersze, list) else wiersze['workers'])
                  if w['user_id'] == u.id)
    assert wiersz['on_break'] is True


def test_lista_szkolen_przezywa_szkolacego_bez_obecnosci(leader_client):
    a = szkolacy('A', barcode='TA')
    x = make_user('operator', display_name='X', barcode_id='SX')
    obecny(a)
    obecny(x)
    wybierz_trenera(leader_client, 'TA')
    assert dopisz(leader_client, a, 'SX').status_code == 200
    ShiftAttendance.query.filter_by(user_id=a.id).delete()
    db.session.commit()

    r = leader_client.get('/api/time/training/aktywne')

    assert r.status_code == 200 and r.get_json()['szkolenia'] == []
