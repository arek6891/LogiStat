"""Normy jednej osoby: ocena na tle zespolu, wykresy z paczek, wejscie z dashboardu.

Ocena w widoku per pracownik to wiersz wyjety z tego samego `przeglad_zespolu()`,
z ktorego korzysta „Przeglad ogolny" — test pilnuje, zeby nigdy sie nie rozjechaly.
Wykresy ida z paczek, bo stary wykres dzienny rysowal tylko „Wpis ilosci", ktory
na `.31` ma 3 wiersze — byl pusty niemal u kazdego.
"""
from datetime import date, timedelta

import app as logistat
from conftest import make_user

ZIEL = date(2026, 9, 10)


def paczka(barcode, kto, sztuk, dzien, godzina=10, minut=30, ze_startem=True):
    koniec = logistat.local_day_bounds(dzien)[0] + timedelta(hours=godzina)
    logistat.db.session.add(logistat.ImportedCarton(
        barcode=barcode, land='PL', stueckzahl=sztuk, ziel_datum=ZIEL,
        uebergabe_nr='UB-1',
        scan_start_at=koniec - timedelta(minutes=minut) if ze_startem else None,
        scan_start_by=kto.id if ze_startem else None,
        scan_end_at=koniec, scan_end_by=kto.id))
    logistat.db.session.commit()


def osoba(client, kto, **params):
    r = client.get(f'/api/stats/user/{kto.id}', query_string=params)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


ZAKRES = {'date_from': '2026-09-01', 'date_to': '2026-09-30'}


def zespol_trzech():
    """Szybka 120 szt./h, Wolna 40 szt./h — po 4 paczki po 30 min."""
    a = make_user('operator', username='szybka', display_name='Szybka')
    b = make_user('operator', username='wolna', display_name='Wolna')
    for i in range(4):
        paczka(f'A{i}', a, 60, date(2026, 9, 2), godzina=8 + i)
        paczka(f'B{i}', b, 20, date(2026, 9, 2), godzina=8 + i)
    return a, b


# ── ocena = ten sam wiersz co w przegladzie ──────────────────────────────────

def test_ocena_osoby_zgadza_sie_z_przegladem(leader_client):
    a, b = zespol_trzech()

    przeglad = leader_client.get('/api/stats/overview', query_string=ZAKRES).get_json()
    for kto in (a, b):
        n = osoba(leader_client, kto, **ZAKRES)['norma']
        wiersz = next(r for r in przeglad['pracownicy'] if r['user_id'] == kto.id)

        assert n['wiersz'] == wiersz
        assert n['srednia_szt_h'] == przeglad['srednia_szt_h']
        assert n['progi'] == przeglad['progi']


def test_ocena_ma_miejsce_w_rankingu(leader_client):
    a, b = zespol_trzech()

    na = osoba(leader_client, a, **ZAKRES)['norma']
    nb = osoba(leader_client, b, **ZAKRES)['norma']

    assert (na['miejsce'], na['w_rankingu']) == (1, 2)
    assert (nb['miejsce'], nb['w_rankingu']) == (2, 2)
    assert na['wiersz']['ocena'] == 'dobra' and nb['wiersz']['ocena'] == 'slaba'
    assert na['powod_braku_oceny'] is None


def test_ocena_nie_zalezy_od_filtra_czynnosci(leader_client):
    a, _ = zespol_trzech()
    czynnosc = logistat.Activity.query.first()

    bez = osoba(leader_client, a, **ZAKRES)['norma']
    z = osoba(leader_client, a, activity_id=czynnosc.id, **ZAKRES)['norma']

    assert bez == z


def test_za_malo_paczek_nie_dostaje_oceny(leader_client):
    zespol_trzech()
    c = make_user('operator', username='nowa', display_name='Nowa')
    paczka('C1', c, 50, date(2026, 9, 2))

    n = osoba(leader_client, c, **ZAKRES)['norma']

    assert n['powod_braku_oceny'] == 'za_malo_paczek'
    assert n['miejsce'] is None
    assert n['wiersz']['ocena'] is None


def test_paczki_bez_czasu_maja_wlasny_powod(leader_client):
    c = make_user('operator', username='bezstartu', display_name='BezStartu')
    for i in range(4):
        paczka(f'C{i}', c, 50, date(2026, 9, 2), godzina=8 + i, ze_startem=False)

    n = osoba(leader_client, c, **ZAKRES)['norma']

    assert n['powod_braku_oceny'] == 'brak_czasu'


def test_osoba_bez_paczek(leader_client):
    zespol_trzech()
    c = make_user('operator', username='nic', display_name='Nic')

    n = osoba(leader_client, c, **ZAKRES)['norma']

    assert n['powod_braku_oceny'] == 'brak_paczek'
    assert n['wiersz'] is None
    assert n['srednia_szt_h'] is not None      # srednia zespolu i tak widac


# ── wykresy ──────────────────────────────────────────────────────────────────

def test_wykres_dzienny_z_paczek_rosnaco(leader_client):
    a = make_user('operator', username='ala', display_name='Ala')
    paczka('W1', a, 60, date(2026, 9, 5))                 # 30 min
    paczka('W2', a, 30, date(2026, 9, 1))
    paczka('W3', a, 30, date(2026, 9, 1), godzina=11)

    w = osoba(leader_client, a, **ZAKRES)['wykres_dzienny']

    assert [p['okres'] for p in w] == ['2026-09-01', '2026-09-05']
    assert w[0] == {'okres': '2026-09-01', 'paczek': 2, 'sztuk': 60,
                    'godzin': 1.0, 'szt_h': 60.0}
    assert w[1]['szt_h'] == 120.0


def test_wykres_miesieczny(leader_client):
    a = make_user('operator', username='ala', display_name='Ala')
    paczka('W1', a, 60, date(2026, 9, 5))
    paczka('W2', a, 60, date(2026, 9, 20))
    paczka('P1', a, 30, date(2026, 10, 1))

    w = osoba(leader_client, a, date_from='2026-09-01', date_to='2026-10-31')['wykres_miesieczny']

    assert [(p['okres'], p['paczek'], p['sztuk']) for p in w] == [
        ('2026-09', 2, 120), ('2026-10', 1, 30)]
    assert w[0]['szt_h'] == 120.0              # 120 szt / 1 h


def test_dzien_bez_zmierzonego_czasu_to_null_nie_zero(leader_client):
    a = make_user('operator', username='ala', display_name='Ala')
    paczka('W1', a, 60, date(2026, 9, 5), ze_startem=False)

    w = osoba(leader_client, a, **ZAKRES)['wykres_dzienny']

    assert w[0]['sztuk'] == 60
    assert w[0]['szt_h'] is None


def test_nakladajace_sie_paczki_w_wykresie_nie_licza_czasu_dwa_razy(leader_client):
    a = make_user('operator', username='ala', display_name='Ala')
    paczka('W1', a, 30, date(2026, 9, 5), godzina=10, minut=60)    # 9:00–10:00
    paczka('W2', a, 30, date(2026, 9, 5), godzina=10, minut=60)    # ta sama godzina

    w = osoba(leader_client, a, **ZAKRES)['wykres_dzienny']

    assert w[0]['godzin'] == 1.0


def test_szablon_rysuje_wykresy_z_paczek(leader_client):
    html = leader_client.get('/stats').get_data(as_text=True)

    assert 'wykres_dzienny' in html and 'wykres_miesieczny' in html
    assert 'id="monthlyChart"' in html
    assert 'renderNorma' in html


# ── wejscie z dashboardu ─────────────────────────────────────────────────────

def test_dashboard_podaje_id_pracownika(leader_client):
    a = make_user('operator', username='ala', display_name='Ala')
    paczka('W1', a, 60, logistat.local_today(), godzina=1)

    d = leader_client.get('/api/dashboard').get_json()

    assert d['workers_today'][0]['user_id'] == a.id


def test_nieprzypisany_w_zmianach_ma_id(leader_client):
    a = make_user('operator', username='ala', display_name='Ala')
    paczka('W1', a, 60, date(2026, 9, 5))

    d = leader_client.get('/api/dashboard/shifts?date=2026-09-05').get_json()

    assert d['unattributed']['workers'][0]['user_id'] == a.id


def test_dashboard_linkuje_do_norm(leader_client):
    html = leader_client.get('/dashboard').get_data(as_text=True)

    assert '/stats?user=${w.user_id}' in html
    assert '/stats?user=${w.id}' in html


def test_normy_otwieraja_osobe_z_linku(leader_client):
    html = leader_client.get('/stats').get_data(as_text=True)

    assert "q.get('user')" in html
