"""Walidacja API — przeglad 2026-10-24. Ekrany tego nie wysylaja, ale API nie
moze konczyc sie 500-ka ani zapisywac bzdur (ujemne ilosci, pusta nazwa)."""
import pytest
from conftest import make_user

from logistat.czas import local_today
from logistat.extensions import db
from logistat.models import (
    Activity, ActivityAssignment, DailyStat, User, WorkerTimeEvent, get_or_create_shift)


def _wpis(user):
    s = get_or_create_shift(local_today(), 1)
    st = DailyStat(user_id=user.id, activity_id=Activity.query.first().id, shift_id=s.id,
                   quantity=5)
    db.session.add(st)
    db.session.commit()
    return st


@pytest.mark.parametrize('ilosc', ['abc', -5, None])
def test_poprawka_wpisu_ilosci_waliduje(leader_client, ilosc):
    st = _wpis(make_user('operator'))

    r = leader_client.put(f'/api/daily-stats/{st.id}', json={'quantity': ilosc})

    assert r.status_code == 400
    db.session.refresh(st)
    assert st.quantity == 5


def test_wpis_ilosci_bez_ujemnych(leader_client):
    u = make_user('operator')
    r = leader_client.post('/api/daily-stats', json={'date': local_today().isoformat(), 'shift_number': 1,
                           'entries': [{'user_id': u.id, 'activity_id': Activity.query.first().id,
                                        'quantity': -3}]})
    assert r.status_code == 400 and DailyStat.query.count() == 0


def test_forecast_bez_ujemnych(leader_client):
    r = leader_client.post('/api/forecast/save', json={'date': '2026-10-01', 'quantity': -1})
    assert r.status_code == 400


@pytest.mark.parametrize('adres', ['/api/forecast/chart-data', '/api/forecast/export'])
def test_forecast_limit_zakresu(leader_client, adres):
    r = leader_client.get(f'{adres}?date_from=2020-01-01&date_to=2026-12-31')
    assert r.status_code == 400


def _zdarzenie(user):
    s = get_or_create_shift(local_today(), 1)
    e = WorkerTimeEvent(user_id=user.id, shift_id=s.id, event_type='break_start')
    db.session.add(e)
    db.session.commit()
    return e


@pytest.mark.parametrize('ts', [None, 12, ''])
def test_korekta_zdarzenia_zly_czas_400(leader_client, ts):
    e = _zdarzenie(make_user('operator'))
    r = leader_client.put(f'/api/worker-times/event/{e.id}', json={'timestamp': ts})
    assert r.status_code == 400


def test_korekta_zdarzenia_czas_ze_strefa_zapisany_jako_utc(leader_client):
    e = _zdarzenie(make_user('operator'))
    r = leader_client.put(f'/api/worker-times/event/{e.id}',
                          json={'timestamp': '2026-10-24T10:00:00+02:00'})
    assert r.status_code == 200
    db.session.refresh(e)
    assert e.timestamp.tzinfo is None and e.timestamp.hour == 8


def test_progi_norm_slaby_ponizej_dobrego(admin_client):
    r = admin_client.put('/api/settings', json={'norm_good_pct': 90, 'norm_weak_pct': 95})
    assert r.status_code == 400


def test_czynnosc_bez_pustej_nazwy(admin_client):
    a = Activity.query.first()
    nazwa = a.name
    assert admin_client.put(f'/api/activities/{a.id}', json={'name': '  '}).status_code == 400
    db.session.refresh(a)
    assert a.name == nazwa


def test_usuniecie_czynnosci_w_uzyciu_409(admin_client):
    a = Activity.query.first()
    u = make_user('operator')
    db.session.add(ActivityAssignment(shift_id=get_or_create_shift(local_today(), 1).id,
                                      user_id=u.id, activity_id=a.id))
    db.session.commit()
    assert admin_client.delete(f'/api/activities/{a.id}').status_code == 409


@pytest.mark.parametrize('rola', ['stanowisko', 'leader', 'admin'])
def test_konto_z_logowaniem_wymaga_hasla(admin_client, rola):
    r = admin_client.post('/api/users', json={'username': f'x-{rola}', 'display_name': 'X', 'role': rola})
    assert r.status_code == 400
    assert User.query.filter_by(username=f'x-{rola}').first() is None
