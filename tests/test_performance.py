"""Liczba zapytan SQL — zeby N+1 nie wrocilo niezauwazone.

Limity sa z zapasem: chodzi o rzad wielkosci (stale, nie „jedno na wiersz"),
nie o dokladna liczbe.
"""
from datetime import date

import app as logistat
from conftest import make_user
from test_import_aggregation import ZIEL, row


def test_import_nie_robi_zapytania_na_wiersz(acting_admin, queries):
    """Dotad kazdy wiersz odpalal 2 SELECT-y: dedup barcode + mapowanie kraju.
    Przy 10k wierszy to 20k round-tripow do bazy."""
    wiersze = [row(f'B{i}', 1) for i in range(200)]

    logistat.process_import_rows(wiersze)

    assert logistat.ImportedCarton.query.count() == 200
    odczyty = len(queries.selects)
    assert odczyty < 20, (
        f'200 wierszy = {odczyty} SELECT-ow — powinno byc kilka partii, nie '
        'jedno zapytanie na wiersz (INSERT-ow jest z natury 200)')


def test_mapowania_krajow_czytane_raz(acting_admin, queries):
    logistat.process_import_rows([row(f'B{i}', 1, land='PL') for i in range(50)])

    selecty = queries.matching('FROM country_mapping')

    assert len(selecty) <= 2, 'mapowania krajow to jeden odczyt na import'


def test_dedup_idzie_partiami(acting_admin, queries):
    logistat.process_import_rows([row(f'B{i}', 1) for i in range(50)])

    dedup = [q for q in queries.matching('FROM imported_carton') if ' IN ' in q]

    assert len(dedup) >= 1, 'dedup ma isc jednym IN (...) na partie'
    assert len(dedup) <= 2


def test_stawki_z_cache_na_zadanie(admin_client, queries):
    # 30 linii w trzech miesiacach
    for i in range(30):
        d = date(2026, 1 + (i % 3), 10)
        logistat.db.session.add(logistat.GeneralStat(
            loading_date=d, week_number=d.isocalendar()[1],
            list_id=f'UB-{i}', country_ledger='PL', amounts=10,
            category_data='{}'))
    for m in (1, 2, 3):
        cm = logistat.CostMapping(year=2026, month=m)
        cm.set_rates_data({'textile': 1.0})
        logistat.db.session.add(cm)
    logistat.db.session.commit()
    queries.statements.clear()

    r = admin_client.get('/api/general-stats')

    assert r.status_code == 200
    assert len(r.get_json()) == 30
    stawki = queries.matching('FROM cost_mapping')
    assert len(stawki) <= 3, (
        f'{len(stawki)} zapytan o stawki na 30 wierszy — powinno byc po jednym '
        'na miesiac, z cache na zadanie')


def test_filtry_daty_na_liscie_statystyk(admin_client):
    for d in (date(2026, 1, 5), date(2026, 6, 5), date(2026, 12, 5)):
        logistat.db.session.add(logistat.GeneralStat(
            loading_date=d, week_number=d.isocalendar()[1],
            list_id=f'UB-{d.month}', country_ledger='PL', amounts=10,
            category_data='{}'))
    logistat.db.session.commit()

    wszystkie = admin_client.get('/api/general-stats').get_json()
    zakres = admin_client.get(
        '/api/general-stats?date_from=2026-05-01&date_to=2026-07-01').get_json()

    assert len(wszystkie) == 3, 'bez parametrow zwraca wszystko, jak dotad'
    assert len(zakres) == 1


def test_zla_data_w_filtrze_daje_400(admin_client):
    assert admin_client.get('/api/general-stats?date_from=bzdura').status_code == 400


def test_lista_obecnosci_bez_zapytania_na_pracownika(leader_client, queries):
    shift = logistat.get_or_create_shift(date(2026, 9, 1), 1)
    for i in range(20):
        u = make_user('operator', barcode_id=f'W{i}')
        logistat.db.session.add(logistat.ShiftAttendance(shift_id=shift.id, user_id=u.id))
    logistat.db.session.commit()
    queries.statements.clear()

    r = leader_client.get('/api/shift/attendances?date=2026-09-01&shift_number=1')

    assert len(r.get_json()['attendances']) == 20
    odczyty = len(queries.selects)
    assert odczyty < 8, (
        f'{odczyty} SELECT-ow na 20 obecnosci — user ma isc joinedloadem')


def test_dane_przydzielania_bez_n_plus_1(leader_client, queries):
    shift = logistat.get_or_create_shift(date(2026, 9, 1), 1)
    akt = logistat.Activity.query.first()
    for i in range(20):
        u = make_user('operator', barcode_id=f'W{i}')
        logistat.db.session.add(logistat.ShiftAttendance(shift_id=shift.id, user_id=u.id))
        logistat.db.session.add(logistat.ActivityAssignment(
            shift_id=shift.id, user_id=u.id, activity_id=akt.id))
    logistat.db.session.commit()
    queries.statements.clear()

    r = leader_client.get('/api/assignment/data?date=2026-09-01&shift_number=1')
    d = r.get_json()

    assert len(d['assignments']) == 20
    odczyty = len(queries.selects)
    assert odczyty < 10, (
        f'{odczyty} SELECT-ow na 20 przydzielen — user i activity '
        'maja isc joinedloadem')
