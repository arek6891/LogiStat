"""Grupy P1/P2/P3 w Przydzielaniu i sugestie AI po grupach (operacja 2026-10-23).

Grupa = ocena z Norm (`przeglad_zespolu()`) za ostatnie 20 dni pracy magazynu
przed dniem zmiany: 🔴 slaba → P1, w normie → P2, 🟢 dobra → P3, za malo danych
→ bez grupy. AI: najpierw P3 (potem P2, bez grupy, P1) do Post Processing, az
estymacja obu zmian pokryje ilosc do zrobienia (Actual, bez niego Forecast).
"""
from datetime import date, timedelta
from types import SimpleNamespace

from conftest import make_user

from logistat.czas import local_day_bounds
from logistat.extensions import db
from logistat.models import (
    Activity, ActivityAssignment, Forecast, ImportedCarton, ShiftAttendance,
    get_or_create_shift)
from logistat.normy_dane import przeglad_zespolu
from logistat.przydzial import (
    CZYNNOSC_SKANOW_PACZEK, DNI_GRUP, dni_pracy_magazynu, do_zrobienia_dnia, grupy_wydajnosci,
    sugestie_przydzialu)


DZIEN = date(2026, 10, 23)
_nr = [0]


def paczka(kto, dzien, sztuk, minut=30, data_pliku=None):
    _nr[0] += 1
    koniec = local_day_bounds(dzien)[0] + timedelta(hours=8 + _nr[0] % 8, minutes=_nr[0] % 50)
    db.session.add(ImportedCarton(
        barcode=f'G{_nr[0]}', land='PL', stueckzahl=sztuk, data_pliku=data_pliku or dzien,
        uebergabe_nr='UB-1', scan_start_at=koniec - timedelta(minutes=minut),
        scan_start_by=kto.id, scan_end_at=koniec, scan_end_by=kto.id))
    db.session.commit()


def trzy_osoby():
    """Wolna 200 szt./h, srednia 300, szybka 400 — srednia zespolu 300."""
    wolna = make_user('operator', display_name='Wolna', przeszkolony=True)
    srednia = make_user('operator', display_name='Srednia', przeszkolony=True)
    szybka = make_user('operator', display_name='Szybka', przeszkolony=True)
    dzien = DZIEN - timedelta(days=1)
    for _ in range(3):
        paczka(wolna, dzien, 100)
        paczka(srednia, dzien, 150)
        paczka(szybka, dzien, 200)
    return wolna, srednia, szybka


def obecny(user, dzien=DZIEN, nr=1):
    zmiana = get_or_create_shift(dzien, nr)
    db.session.add(ShiftAttendance(shift_id=zmiana.id, user_id=user.id))
    db.session.commit()
    return zmiana


# ── dni pracy magazynu ───────────────────────────────────────────────────────

def test_dni_pracy_magazynu_to_ostatnie_20_dni_z_paczkami_bez_dzisiaj(flask_app):
    kto = make_user('operator')
    dni = [DZIEN - timedelta(days=2 * i) for i in range(30)]   # co drugi dzien = przerwy
    for d in dni:
        paczka(kto, d, 10)

    wynik = dni_pracy_magazynu(DZIEN)

    assert len(wynik) == DNI_GRUP == 20
    assert DZIEN not in wynik, 'dzien zmiany jest w toku'
    assert wynik == sorted(dni[1:21])


# ── grupy ────────────────────────────────────────────────────────────────────

def test_grupy_to_oceny_z_norm(flask_app):
    wolna, srednia, szybka = trzy_osoby()
    nowa = make_user('operator')
    paczka(nowa, DZIEN - timedelta(days=1), 50)          # 1 paczka = za malo danych

    g = grupy_wydajnosci(DZIEN)

    assert {u: v['grupa'] for u, v in g['grupy'].items()} == {
        wolna.id: 'P1', srednia.id: 'P2', szybka.id: 'P3'}
    assert nowa.id not in g['grupy']
    okno = g['okno']
    normy = {r['user_id']: r['ocena'] for r in przeglad_zespolu(
        date.fromisoformat(okno['od']), date.fromisoformat(okno['do']))['pracownicy']}
    assert normy == {wolna.id: 'slaba', srednia.id: 'ok', szybka.id: 'dobra'}


def test_dane_przydzialu_maja_grupy_i_do_zrobienia(leader_client):
    wolna, _, szybka = trzy_osoby()
    obecny(wolna)
    obecny(szybka)
    db.session.add(Forecast(date=DZIEN, quantity=5000))
    db.session.commit()

    d = leader_client.get(f'/api/assignment/data?date={DZIEN}&shift_number=1').get_json()

    assert d['grupy'][str(szybka.id)]['grupa'] == 'P3'
    assert d['grupy'][str(wolna.id)]['grupa'] == 'P1'
    assert d['okno_grup']['dni'] == 1
    assert d['do_zrobienia'] == {'sztuk': 5000, 'zrodlo': 'forecast'}
    assert d['pp_activity_id'] == Activity.query.filter_by(name=CZYNNOSC_SKANOW_PACZEK).one().id


def test_do_zrobienia_actual_ma_pierwszenstwo_przed_forecastem(flask_app):
    kto = make_user('operator')
    db.session.add(Forecast(date=DZIEN, quantity=5000))
    db.session.commit()
    paczka(kto, DZIEN - timedelta(days=3), 300, data_pliku=DZIEN)
    paczka(kto, DZIEN - timedelta(days=3), 200, data_pliku=DZIEN)

    assert do_zrobienia_dnia(DZIEN) == {'sztuk': 500, 'zrodlo': 'actual'}
    assert do_zrobienia_dnia(DZIEN + timedelta(days=1)) is None


# ── sugestie (czysta logika) ─────────────────────────────────────────────────

PP = SimpleNamespace(id=1, name=CZYNNOSC_SKANOW_PACZEK)
ZWROTY = SimpleNamespace(id=2, name='Zwroty')
WSZYSCY = {1, 2}


def sugestie(grupy, do_zrobienia, druga=0, obecni=(10, 11, 12, 13, 14)):
    return sugestie_przydzialu(
        obecni=list(obecni), czynnosci=[PP, ZWROTY],
        szkolenia={u: WSZYSCY for u in obecni}, grupy=grupy, srednie={},
        wydajnosc={PP.id: {'szt_zmiana_os': 1000}}, do_zrobienia=do_zrobienia,
        osob_pp_druga=druga)


GRUPY = {10: {'grupa': 'P1', 'proc_sredniej': 80}, 11: {'grupa': 'P3', 'proc_sredniej': 120},
         12: {'grupa': 'P2', 'proc_sredniej': 100}, 13: {'grupa': 'P3', 'proc_sredniej': 130}}


def test_pp_od_najlepszych_az_do_pokrycia_forecastu():
    s = sugestie(GRUPY, {'sztuk': 2500, 'zrodlo': 'forecast'})
    pp = [x['user_id'] for x in s if x['activity_id'] == PP.id]

    assert pp == [13, 11, 12], 'P3 (wyzszy % pierwszy), potem P2 — 3 × 1000 ≥ 2500'
    assert {x['user_id'] for x in s if x['activity_id'] == ZWROTY.id} == {14, 10}


def test_druga_zmiana_zmniejsza_potrzebe():
    s = sugestie(GRUPY, {'sztuk': 2500, 'zrodlo': 'actual'}, druga=2)

    assert [x['user_id'] for x in s if x['activity_id'] == PP.id] == [13]


def test_bez_forecastu_do_pp_ida_p3_i_p2():
    s = sugestie(GRUPY, None)

    assert sorted(x['user_id'] for x in s if x['activity_id'] == PP.id) == [11, 12, 13]


def test_p1_trafia_do_pp_ostatni():
    s = sugestie(GRUPY, {'sztuk': 5000, 'zrodlo': 'forecast'})
    pp = [x['user_id'] for x in s if x['activity_id'] == PP.id]

    assert pp[:3] == [13, 11, 12] and pp.index(10) > pp.index(14), 'bez grupy przed P1'


def test_sugestie_api_stawiaja_p3_na_post_processing(leader_client):
    wolna, srednia, szybka = trzy_osoby()
    for u in (wolna, srednia, szybka):
        obecny(u)

    s = leader_client.get(f'/api/assignment/suggestions?date={DZIEN}&shift_number=1') \
        .get_json()['suggestions']
    pp_id = Activity.query.filter_by(name=CZYNNOSC_SKANOW_PACZEK).one().id
    na_pp = [x['user_id'] for x in s if x['activity_id'] == pp_id]

    assert na_pp == [szybka.id, srednia.id], 'bez forecastu: P3 i P2'
    assert next(x for x in s if x['user_id'] == wolna.id)['activity_id'] != pp_id
    assert next(x for x in s if x['user_id'] == szybka.id)['grupa'] == 'P3'


def test_ekran_ma_znaczek_grupy_i_do_zrobienia(leader_client):
    html = leader_client.get('/assignment').get_data(as_text=True)
    js = leader_client.get('/static/js/assignment.js').get_data(as_text=True)

    assert 'id="doZrobieniaPP"' in html
    assert 'grupa-p' in js and 'Do zrobienia' in js


def test_przydzial_drugiej_zmiany_liczy_osoby_pp(leader_client):
    u = make_user('operator', przeszkolony=True)
    zmiana2 = obecny(u, nr=2)
    pp = Activity.query.filter_by(name=CZYNNOSC_SKANOW_PACZEK).one()
    db.session.add(ActivityAssignment(shift_id=zmiana2.id, user_id=u.id, activity_id=pp.id))
    db.session.commit()

    d = leader_client.get(f'/api/assignment/data?date={DZIEN}&shift_number=1').get_json()

    assert d['osob_pp_druga_zmiana'] == 1
