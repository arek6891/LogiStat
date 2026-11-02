"""Przydzial osob do stanowisk zwrotow + blokada przyjecia + dashboard (operacja
2026-10-27). Paczka nalezy do stanowiska (konto), osoby do stanowiska przydziela
lider; paczka dzieli sie po rowno na obsade w chwili przyjecia."""
from datetime import date, datetime, timedelta

import pytest

from conftest import login, make_user
from test_przyjecie_zwrotu import obsadz, zwrot

from logistat.czas import local_today, teraz_utc
from logistat.extensions import db
from logistat.models import (
    Activity, ActivityAssignment, PrzydzialZwrotow, ShiftAttendance, WorkerTimeEvent, ZwrotPaczki,
    get_or_create_shift)
from logistat.przydzial_zwrotow import dashboard_zwrotow
from logistat.przyjecie_zwrotu import (
    CZYNNOSC_ZWROTOW, KOMUNIKAT_BRAK_OBSADY, efektywne_okresy, kto_na_stanowisku, obsada_paczki,
    przerwy_osob)

T0 = datetime(2026, 9, 2, 6, 0)


def klient(flask_app, konto):
    k = flask_app.test_client()
    login(k, konto.username)
    return k


def na_zwrotach(zmiana, *osoby):
    zwroty = Activity.query.filter_by(name=CZYNNOSC_ZWROTOW).one()
    for o in osoby:
        db.session.add(ActivityAssignment(shift_id=zmiana.id, user_id=o.id, activity_id=zwroty.id))
    db.session.commit()


# ── czysta logika ────────────────────────────────────────────────────────────

def test_okres_konczy_sie_na_do_koncu_pracy_albo_po_12h():
    h = lambda n: T0 + timedelta(hours=n)  # noqa: E731
    okresy = efektywne_okresy([
        (1, 10, False, h(0), h(2)),      # zamkniety przez lidera
        (2, 10, False, h(0), None),      # Koniec pracy po 3 h
        (3, 10, False, h(0), None),      # nic — limit 12 h
        (4, None, True, h(0), None),     # Support
    ], {2: [h(-1), h(3), h(5)]})
    assert [(u, k) for u, _, _, _, k in okresy] == [(1, h(2)), (2, h(3)), (3, h(12)), (4, h(12))]
    assert kto_na_stanowisku(okresy, 10, h(1)) == [1, 2, 3]
    assert kto_na_stanowisku(okresy, 10, h(2)) == [2, 3], 'koniec okresu wylaczny'
    assert kto_na_stanowisku(okresy, 10, h(12)) == []
    assert kto_na_stanowisku(okresy, None, h(1)) == [], 'Support nie stoi na stanowisku'


def test_paczka_dzieli_sie_na_stol_i_support_calej_zmiany():
    """Operacja 2026-11-02: Support bez stolu, udzial w kazdej paczce w swoim czasie;
    pusty stol = bez obsady (Support go nie obsadza)."""
    h = lambda n: T0 + timedelta(hours=n)  # noqa: E731
    okresy = efektywne_okresy([
        (1, 10, False, h(0), h(8)),
        (2, 20, False, h(0), h(8)),
        (5, None, True, h(1), h(3)),     # Support
        (6, 10, True, h(0), h(8)),       # Support z 29.10–1.11 (jeszcze przy stole)
    ], {})
    assert obsada_paczki(okresy, 10, h(0.5)) == [1, 6]
    assert obsada_paczki(okresy, 20, h(2)) == [2, 5, 6], 'Support kazdego stolu'
    assert obsada_paczki(okresy, 30, h(2)) == [], 'pusty stol — bez obsady mimo Supportu'
    assert kto_na_stanowisku(okresy, 10, h(2)) == [1], 'blokada przyjecia bez Supportu'


def test_przerwy_osob_pary_otwarte_i_koniec_pracy():
    h = lambda n: T0 + timedelta(hours=n)  # noqa: E731
    przerwy = przerwy_osob([
        (1, 7, 'break_start', h(1)), (1, 7, 'break_end', h(1.5)),
        (1, 7, 'other_start', h(2)), (1, 7, 'other_end', h(2.25)),
        (1, 7, 'training_start', h(3)), (1, 7, 'training_end', h(4)),   # praca — nie odejmuje
        (2, 7, 'break_start', h(1)), (2, 7, 'work_end', h(2)),          # zamyka Koniec pracy
        (3, 7, 'other_start', h(1)),                                    # trwa — do „teraz”
        (4, 7, 'break_end', h(1)),                                      # koniec bez startu
    ], teraz=h(5))
    assert przerwy == {1: [(h(1), h(1.5)), (h(2), h(2.25))], 2: [(h(1), h(2))], 3: [(h(1), h(5))]}


def test_przerwy_paruja_sie_w_obrebie_zmiany():
    """Niezamknieta przerwa z poniedzialku nie moze zjesc wtorku: wtorkowa para
    start/koniec zostaje sobie, poniedzialkowa trwa (do „teraz”, jak w Czasie pracy)."""
    h = lambda n: T0 + timedelta(hours=n)  # noqa: E731
    przerwy = przerwy_osob([
        (1, 7, 'break_start', h(2)),                                # pon., bez konca
        (1, 8, 'break_start', h(26)), (1, 8, 'break_end', h(26.5)), # wt.
    ], teraz=h(2.5))
    assert przerwy == {1: [(h(2), h(2.5)), (h(26), h(26.5))]}


# ── blokada przyjecia ────────────────────────────────────────────────────────

def test_bez_obsady_przyjecie_zablokowane(flask_app):
    st = make_user('stanowisko')
    k = klient(flask_app, st)

    html = k.get('/zwroty/przyjecie').get_data(as_text=True)
    assert '"obsada": []' in html or '"obsada":[]' in html
    r = k.post('/api/zwroty/przyjecie', json=zwrot())
    assert r.status_code == 409 and r.get_json()['error'] == KOMUNIKAT_BRAK_OBSADY
    assert ZwrotPaczki.query.count() == 0


def test_konto_lidera_to_nie_stanowisko(leader_client):
    r = leader_client.post('/api/zwroty/przyjecie', json=zwrot())
    assert r.status_code == 409 and r.get_json()['brak_obsady'] is True


def test_z_obsada_zapis_i_imiona_w_odpowiedzi(flask_app):
    st = make_user('stanowisko')
    anna = make_user('operator', display_name='Anna')
    obsadz(st, anna)
    r = klient(flask_app, st).post('/api/zwroty/przyjecie', json=zwrot())
    assert r.status_code == 201 and r.get_json()['obsada'] == ['Anna']


def test_ponowienie_zapisanego_przechodzi_po_zdjeciu_obsady(flask_app):
    """Zwrot juz zapisany (ten sam token) — ponowienie to 200, nie 409."""
    st = make_user('stanowisko')
    obsadz(st, make_user('operator'))
    k = klient(flask_app, st)
    body = zwrot(token='ponowienie-01')
    assert k.post('/api/zwroty/przyjecie', json=body).status_code == 201
    PrzydzialZwrotow.query.update({'do': teraz_utc()})
    db.session.commit()

    r = k.post('/api/zwroty/przyjecie', json=body)
    assert r.status_code == 200 and r.get_json()['powtorzony'] is True
    assert k.post('/api/zwroty/przyjecie', json=zwrot(token='nowy-zwrot-02')).status_code == 409


# ── ekran przydzialu ─────────────────────────────────────────────────────────

def test_lider_przydziela_przenosi_i_zdejmuje(leader_client):
    st1, st2 = make_user('stanowisko', display_name='Z1'), make_user('stanowisko', display_name='Z2')
    ola = make_user('operator', display_name='Ola')
    zmiana = get_or_create_shift(local_today(), 1)
    na_zwrotach(zmiana, ola)
    body = {'date': local_today().isoformat(), 'shift': 1, 'user_id': ola.id}

    r = leader_client.put('/api/zwroty/przydzial', json={**body, 'miejsce': st1.id})
    assert r.status_code == 200
    assert [o['miejsce'] for o in r.get_json()['osoby']] == [st1.id]
    leader_client.put('/api/zwroty/przydzial', json={**body, 'miejsce': st2.id})
    wiersze = PrzydzialZwrotow.query.order_by(PrzydzialZwrotow.id).all()
    assert [w.stanowisko_id for w in wiersze] == [st1.id, st2.id]
    assert wiersze[0].do == wiersze[1].od, 'przeniesienie bez dziury i nakladki'

    # Support calej zmiany (2026-11-02): bez stolu.
    r = leader_client.put('/api/zwroty/przydzial', json={**body, 'miejsce': 'support'})
    assert [o['miejsce'] for o in r.get_json()['osoby']] == ['support']
    leader_client.put('/api/zwroty/przydzial', json={**body, 'miejsce': None})
    assert PrzydzialZwrotow.query.filter_by(do=None).count() == 0
    sup = PrzydzialZwrotow.query.filter_by(support=True).one()
    assert sup.stanowisko_id is None


@pytest.mark.parametrize('zmiana_body,blad', [
    ({'miejsce': 999999}, 'Nieznane stanowisko'),
    ({'miejsce': True}, 'Nieznane stanowisko'),
    ({'date': '2020-01-01'}, 'bieżącej zmiany'),
    ({'miejsce': 'pomoc'}, 'Nieznane stanowisko'),
    ({'support': True}, 'odśwież'),               # ekran z Supportem przy stole (29.10–1.11)
])
def test_walidacja_przydzialu(leader_client, zmiana_body, blad):
    ola = make_user('operator')
    na_zwrotach(get_or_create_shift(local_today(), 1), ola)
    body = {'date': local_today().isoformat(), 'shift': 1, 'user_id': ola.id,
            'miejsce': None, **zmiana_body}
    r = leader_client.put('/api/zwroty/przydzial', json=body)
    assert r.status_code == 400 and blad in r.get_json()['error']


def test_tylko_osoby_z_czynnosci_zwroty(leader_client):
    st = make_user('stanowisko')
    obcy = make_user('operator')
    r = leader_client.put('/api/zwroty/przydzial', json={
        'date': local_today().isoformat(), 'shift': 1, 'user_id': obcy.id, 'miejsce': st.id})
    assert r.status_code == 400 and 'Zwroty' in r.get_json()['error']


def test_zdjecie_z_czynnosci_w_przydzielaniu_zamyka_stanowisko(leader_client):
    st = make_user('stanowisko')
    ola = make_user('operator', przeszkolony=True)
    zmiana = obsadz(st, ola)
    db.session.add(ShiftAttendance(shift_id=zmiana.id, user_id=ola.id))   # jest na tablicy
    db.session.commit()
    r = leader_client.post('/api/assignment/save', json={
        'date': local_today().isoformat(), 'shift_number': 1, 'assignments': []})
    assert r.status_code == 200, r.get_json()
    assert PrzydzialZwrotow.query.filter_by(shift_id=zmiana.id, do=None).count() == 0


def test_otwarte_z_innej_zmiany_widac_do_zakonczenia(leader_client):
    st = make_user('stanowisko')
    ola = make_user('operator', display_name='Ola')
    obsadz(st, ola)   # zmiana 1
    r = leader_client.get(f'/api/zwroty/przydzial?date={local_today().isoformat()}&shift=2')
    inne = r.get_json()['inne_zmiany']
    assert [(w['nazwa'], w['stanowisko_id']) for w in inne] == [('Ola', st.id)]
    leader_client.put('/api/zwroty/przydzial', json={
        'date': local_today().isoformat(), 'shift': 2, 'user_id': ola.id, 'miejsce': None})
    assert PrzydzialZwrotow.query.filter_by(do=None).count() == 0


def test_strony_dla_lidera(leader_client):
    assert leader_client.get('/zwroty/przydzial').status_code == 200
    assert leader_client.get('/zwroty/dashboard').status_code == 200
    assert leader_client.get('/zwroty/dashboard?rok=2026&miesiac=9').status_code == 200


def test_stanowisko_nie_przydziela(flask_app):
    k = klient(flask_app, make_user('stanowisko'))
    assert k.put('/api/zwroty/przydzial', json={}).status_code == 403


# ── dashboard ────────────────────────────────────────────────────────────────

def _zwrot_o(st, kiedy, token):
    db.session.add(ZwrotPaczki(paketnummer='%1', brand='ACC', pos_nummer='NO', kurier='UPS',
                               retoure=1, verpackungsvorschrift='Yes', token=token,
                               przyjal_id=st.id, przyjeto_at=kiedy))


def test_dashboard_po_rowno_i_suma_zgadza_sie_ze_stanowiskiem(flask_app):
    st = make_user('stanowisko', display_name='Z1')
    a, b = make_user('operator', display_name='A'), make_user('operator', display_name='B')
    zmiana = get_or_create_shift(date(2026, 9, 2), 1)
    db.session.add_all([
        PrzydzialZwrotow(shift_id=zmiana.id, user_id=a.id, stanowisko_id=st.id, od=T0),
        PrzydzialZwrotow(shift_id=zmiana.id, user_id=b.id, stanowisko_id=st.id,
                         od=T0 + timedelta(hours=1), do=T0 + timedelta(hours=3)),
    ])
    _zwrot_o(st, T0 + timedelta(minutes=30), 'd-1')   # tylko A → 1
    _zwrot_o(st, T0 + timedelta(hours=2), 'd-2')      # A i B → po 0,5
    _zwrot_o(st, T0 + timedelta(hours=2, minutes=1), 'd-3')
    _zwrot_o(st, T0 - timedelta(hours=1), 'd-4')      # nikt → bez obsady
    db.session.add(WorkerTimeEvent(user_id=a.id, shift_id=zmiana.id, event_type='work_end',
                                   timestamp=T0 + timedelta(hours=4)))
    db.session.commit()

    dzien = date(2026, 9, 2)
    d = dashboard_zwrotow([dzien], teraz=datetime(2026, 9, 3))
    osoby = {o['nazwa']: o for o in d['osoby']}
    assert osoby['A']['paczki'] == pytest.approx(2.0)
    assert osoby['B']['paczki'] == pytest.approx(1.0)
    assert osoby['A']['godziny'] == pytest.approx(4.0), 'do Konca pracy'
    assert osoby['B']['godziny'] == pytest.approx(2.0)
    assert osoby['A']['na_godzine'] == pytest.approx(0.5)
    st_wiersz = next(s for s in d['stanowiska'] if s['nazwa'] == 'Z1')
    assert st_wiersz['dni'][dzien] == 4
    assert d['nieprzypisane'] == {dzien: 1}
    assert sum(o['dni'][dzien]['paczki'] for o in d['osoby']) + d['nieprzypisane'][dzien] \
        == pytest.approx(st_wiersz['dni'][dzien]), 'udzialy osob = paczki stanowiska'
    assert d['obsada'][dzien] == {'osoby': 2, 'support': 0}


def test_dashboard_godziny_netto_bez_przerw_i_innych(flask_app):
    """Operacja 2026-10-29: godziny na stanowisku netto, jak w PP — przerwa
    i „Inne” z Czasu pracy odjete, szkolenie nie; przerwa poza przydzialem nic."""
    st = make_user('stanowisko')
    a = make_user('operator', display_name='A')
    zmiana = get_or_create_shift(date(2026, 9, 2), 1)
    h = lambda n: T0 + timedelta(hours=n)  # noqa: E731
    db.session.add(PrzydzialZwrotow(shift_id=zmiana.id, user_id=a.id, stanowisko_id=st.id,
                                    od=h(0), do=h(6)))
    for typ, kiedy in (('break_start', h(-1)), ('break_end', h(-0.5)),     # przed przydzialem
                       ('break_start', h(2)), ('break_end', h(2.5)),
                       ('other_start', h(3)), ('other_end', h(3.25)),
                       ('training_start', h(4)), ('training_end', h(5))):
        db.session.add(WorkerTimeEvent(user_id=a.id, shift_id=zmiana.id, event_type=typ, timestamp=kiedy))
    _zwrot_o(st, h(1), 'netto-1')
    db.session.commit()
    d = dashboard_zwrotow([date(2026, 9, 2)], teraz=datetime(2026, 9, 3))
    a_ = d['osoby'][0]
    assert a_['godziny'] == pytest.approx(6 - 0.5 - 0.25)
    assert a_['na_godzine'] == pytest.approx(1 / 5.25)


def test_dashboard_dzien_lokalny_i_godziny_dzielone_o_polnocy(flask_app):
    st = make_user('stanowisko')
    a = make_user('operator', display_name='A')
    s = make_user('operator', display_name='S')
    zmiana = get_or_create_shift(date(2026, 9, 2), 2)
    # 02.09 20:00 → 03.09 02:00 czasu polskiego (UTC+2)
    od, do = datetime(2026, 9, 2, 18, 0), datetime(2026, 9, 3, 0, 0)
    db.session.add_all([
        PrzydzialZwrotow(shift_id=zmiana.id, user_id=a.id, stanowisko_id=st.id, od=od, do=do),
        PrzydzialZwrotow(shift_id=zmiana.id, user_id=s.id, support=True, od=od, do=do),
    ])
    _zwrot_o(st, datetime(2026, 9, 2, 22, 30), 'polnoc')   # 03.09 00:30 w Warszawie
    db.session.commit()

    d2, d3 = date(2026, 9, 2), date(2026, 9, 3)
    d = dashboard_zwrotow([d2, d3], teraz=datetime(2026, 9, 4))
    a_ = next(o for o in d['osoby'] if o['nazwa'] == 'A')
    assert a_['dni'][d2]['godziny'] == pytest.approx(4.0)
    assert a_['dni'][d3]['godziny'] == pytest.approx(2.0)
    assert a_['dni'][d3]['paczki'] == pytest.approx(0.5) and a_['dni'][d2]['paczki'] == 0
    # Support calej zmiany (operacja 2026-11-02): udzial w paczce i godziny jak kazdy.
    s_ = next(o for o in d['osoby'] if o['nazwa'] == 'S')
    assert s_['support'] is True and a_['support'] is False
    assert s_['dni'][d3]['paczki'] == pytest.approx(0.5)
    assert s_['godziny'] == pytest.approx(6.0)
    assert d['obsada'][d3] == {'osoby': 1, 'support': 1}


def test_support_dostaje_udzial_suma_sie_zgadza(flask_app):
    """Support (2026-11-02) dzieli paczki dwoch stolow; pusty stol zostaje bez obsady,
    suma udzialow + bez obsady = paczki stanowisk."""
    st1, st2 = make_user('stanowisko', display_name='Z1'), make_user('stanowisko', display_name='Z2')
    a, s = make_user('operator', display_name='A'), make_user('operator', display_name='S')
    zmiana = get_or_create_shift(date(2026, 9, 2), 1)
    db.session.add_all([
        PrzydzialZwrotow(shift_id=zmiana.id, user_id=a.id, stanowisko_id=st1.id, od=T0,
                         do=T0 + timedelta(hours=4)),
        PrzydzialZwrotow(shift_id=zmiana.id, user_id=s.id, support=True, od=T0,
                         do=T0 + timedelta(hours=4)),
    ])
    _zwrot_o(st1, T0 + timedelta(hours=1), 's-1')    # A + S → po 0,5
    _zwrot_o(st1, T0 + timedelta(hours=2), 's-2')
    _zwrot_o(st2, T0 + timedelta(hours=2), 's-3')    # nikt przy Z2 → bez obsady
    db.session.commit()
    dzien = date(2026, 9, 2)
    d = dashboard_zwrotow([dzien], teraz=datetime(2026, 9, 3))
    osoby = {o['nazwa']: o for o in d['osoby']}
    assert osoby['A']['paczki'] == pytest.approx(1.0)
    assert osoby['S']['paczki'] == pytest.approx(1.0)
    assert osoby['S']['na_godzine'] == pytest.approx(0.25)
    assert d['nieprzypisane'] == {dzien: 1}
    assert sum(o['paczki'] for o in d['osoby']) + 1 == d['suma_dni'][dzien] == 3


def test_sam_support_nie_odblokowuje_stanowiska(flask_app):
    st = make_user('stanowisko')
    s = make_user('operator')
    zmiana = get_or_create_shift(local_today(), 1)
    na_zwrotach(zmiana, s)
    db.session.add(PrzydzialZwrotow(shift_id=zmiana.id, user_id=s.id, support=True,
                                    od=teraz_utc() - timedelta(minutes=5)))
    db.session.commit()
    r = klient(flask_app, st).post('/api/zwroty/przyjecie', json=zwrot())
    assert r.status_code == 409 and r.get_json()['brak_obsady'] is True


def test_odpowiedz_zapisu_zostawia_edycje(leader_client):
    """Ekran rysuje sie z odpowiedzi PUT — bez `edycja` przelaczal sie w podglad."""
    ola = make_user('operator')
    st = make_user('stanowisko')
    na_zwrotach(get_or_create_shift(local_today(), 1), ola)
    r = leader_client.put('/api/zwroty/przydzial', json={
        'date': local_today().isoformat(), 'shift': 1, 'user_id': ola.id, 'miejsce': 'support'})
    assert r.get_json()['edycja'] is True
    r = leader_client.get('/api/zwroty/przydzial?date=2020-01-01&shift=1')
    assert r.get_json()['edycja'] is False
