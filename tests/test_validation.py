"""Bledne wejscie ma dawac 400 z komunikatem, nie 500 w logach.

Endpointy sa tylko dla zalogowanych liderow, wiec to nie jest dziura — ale
literowka w URL-u albo pusty POST z fronta nie powinny konczyc sie 500-ka.
"""
from datetime import date

import app as logistat
from conftest import make_user


# ── Helpery ──────────────────────────────────────────────────────────────────

def test_parse_shift_number(flask_app):
    assert logistat.parse_shift_number(1) == 1
    assert logistat.parse_shift_number('2') == 2
    assert logistat.parse_shift_number(7) == 1, 'poza zakresem -> default'
    assert logistat.parse_shift_number('abc') == 1
    assert logistat.parse_shift_number(None) == 1
    assert logistat.parse_shift_number(None, default=2) == 2


def test_parse_date(flask_app):
    assert logistat.parse_date('2026-09-01') == date(2026, 9, 1)
    assert logistat.parse_date('') == logistat.local_today()
    assert logistat.parse_date(None) == logistat.local_today()


# ── Query string ─────────────────────────────────────────────────────────────

def test_zla_data_w_query_daje_400(leader_client):
    for url in ('/api/shift/attendances?date=wczoraj',
                '/api/assignment/data?date=32-13-2026',
                '/api/assignment/suggestions?date=bzdura',
                '/api/daily-stats?date=2026-13-45'):
        r = leader_client.get(url)
        assert r.status_code == 400, url
        assert 'error' in r.get_json(), url


def test_zly_numer_zmiany_wraca_do_domyslnego(leader_client):
    r = leader_client.get('/api/shift/attendances?date=2026-09-01&shift_number=abc')

    assert r.status_code == 200, 'numer zmiany degraduje do 1, nie wywala'


def test_bledy_na_api_sa_jsonem_a_nie_htmlem(leader_client):
    r = leader_client.get('/api/shift/attendances?date=nie-data')

    assert r.status_code == 400
    assert r.content_type.startswith('application/json'), \
        'front czyta data.error — HTML wywalal parsowanie JSON-a'


def test_404_na_api_tez_jest_jsonem(leader_client):
    r = leader_client.put('/api/daily-stats/999999', json={'quantity': 1})

    assert r.status_code == 404
    assert 'error' in r.get_json()


def test_zla_data_w_statystykach_pracownika(leader_client):
    u = make_user('operator')

    r = leader_client.get(f'/api/stats/user/{u.id}?date_from=kiedys')

    assert r.status_code == 400


# ── Cialo JSON ───────────────────────────────────────────────────────────────

def test_pusty_post_daje_400_nie_500(leader_client):
    r = leader_client.post('/api/scan', json={})

    assert r.status_code == 400
    assert 'kodu kreskowego' in r.get_json()['error']


def test_brak_ciala_daje_400_nie_415(leader_client):
    r = leader_client.post('/api/scan', data='', content_type='text/plain')

    assert r.status_code == 400


def test_wpis_ilosci_bez_user_id_daje_400(leader_client):
    r = leader_client.post('/api/daily-stats', json={
        'date': '2026-09-01', 'shift_number': 1,
        'entries': [{'activity_id': 1, 'quantity': 5}],
    })

    assert r.status_code == 400
    assert 'user_id' in r.get_json()['error']


def test_wpis_ilosci_z_bzdurna_ilościa_daje_400(leader_client):
    u = make_user('operator')
    akt = logistat.Activity.query.first()

    r = leader_client.post('/api/daily-stats', json={
        'date': '2026-09-01', 'shift_number': 1,
        'entries': [{'user_id': u.id, 'activity_id': akt.id, 'quantity': 'duzo'}],
    })

    assert r.status_code == 400
    assert logistat.DailyStat.query.count() == 0


def test_entries_musi_byc_lista(leader_client):
    r = leader_client.post('/api/daily-stats',
                           json={'date': '2026-09-01', 'entries': 'nie lista'})

    assert r.status_code == 400


# ── Przydzielanie: bledne cialo nie moze wyczyscic zmiany ───────────────────

def test_przydzielenie_nieznanego_pracownika_daje_400(leader_client):
    r = leader_client.post('/api/assignment/save', json={
        'date': '2026-09-01', 'shift_number': 1,
        'assignments': [{'user_id': 999999, 'activity_id': 1}],
    })

    assert r.status_code == 400
    assert 'Nieznany pracownik' in r.get_json()['error']


def test_bledne_przydzielenie_nie_kasuje_istniejacych(leader_client):
    """Endpoint najpierw czyscil zmiane, potem wstawial — bledny wiersz w
    srodku zostawialby zmiane bez przydzialu."""
    u = make_user('operator')
    akt = logistat.Activity.query.first()
    ok = leader_client.post('/api/assignment/save', json={
        'date': '2026-09-01', 'shift_number': 1,
        'assignments': [{'user_id': u.id, 'activity_id': akt.id}],
    })
    assert ok.status_code == 200
    assert logistat.ActivityAssignment.query.count() == 1

    r = leader_client.post('/api/assignment/save', json={
        'date': '2026-09-01', 'shift_number': 1,
        'assignments': [{'user_id': u.id, 'activity_id': akt.id},
                        {'user_id': 999999, 'activity_id': akt.id}],
    })

    assert r.status_code == 400
    assert logistat.ActivityAssignment.query.count() == 1, \
        'odrzucony zapis nie moze zostawic zmiany bez przydzialu'


# ── Zdarzenia czasu pracy: klucze obce ───────────────────────────────────────

def test_zdarzenie_dla_nieznanego_pracownika_daje_400(leader_client):
    shift = logistat.get_or_create_shift(date(2026, 9, 1), 1)

    r = leader_client.post('/api/worker-times/event', json={
        'user_id': 999999, 'shift_id': shift.id,
        'event_type': 'break_start', 'timestamp': '2026-09-01T10:00:00',
    })

    assert r.status_code == 400
    assert logistat.WorkerTimeEvent.query.count() == 0


def test_zdarzenie_dla_nieznanej_zmiany_daje_400(leader_client):
    u = make_user('operator')

    r = leader_client.post('/api/worker-times/event', json={
        'user_id': u.id, 'shift_id': 999999,
        'event_type': 'break_start', 'timestamp': '2026-09-01T10:00:00',
    })

    assert r.status_code == 400
    assert logistat.WorkerTimeEvent.query.count() == 0


def test_zly_typ_zdarzenia_daje_400(leader_client):
    u = make_user('operator')
    shift = logistat.get_or_create_shift(date(2026, 9, 1), 1)

    r = leader_client.post('/api/worker-times/event', json={
        'user_id': u.id, 'shift_id': shift.id,
        'event_type': 'kawa', 'timestamp': '2026-09-01T10:00:00',
    })

    assert r.status_code == 400


def test_poprawne_zdarzenie_przechodzi(leader_client):
    u = make_user('operator')
    shift = logistat.get_or_create_shift(date(2026, 9, 1), 1)

    r = leader_client.post('/api/worker-times/event', json={
        'user_id': u.id, 'shift_id': shift.id,
        'event_type': 'break_start', 'timestamp': '2026-09-01T10:00:00',
        'note': 'wpis reczny',
    })

    assert r.status_code == 201
    assert logistat.WorkerTimeEvent.query.count() == 1


# ── Pozostale ────────────────────────────────────────────────────────────────

def test_forecast_ze_zla_ilościa_daje_400(leader_client):
    r = leader_client.post('/api/forecast/save',
                           json=[{'date': '2026-09-01', 'quantity': 'duzo'}])

    assert r.status_code == 400
    assert logistat.Forecast.query.count() == 0


def test_czynnosc_z_nietekstowa_nazwa_nie_wywala(admin_client):
    akt = logistat.Activity.query.first()

    r = admin_client.put(f'/api/activities/{akt.id}', json={'name': 12345})

    assert r.status_code in (200, 400), 'byleby nie 500'


def test_mapowanie_kraju_z_nullem_nie_wywala(admin_client):
    m = logistat.CountryMapping.query.first()

    r = admin_client.put(f'/api/country-mappings/{m.id}', json={'country': None})

    assert r.status_code in (200, 400)
