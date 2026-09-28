"""Stanowisko /scan-paczki — pomylki, ktore logi z .31 pokazaly na hali.

- zly kod pracownika wychodzil dopiero przy zapisie konca, po wpisaniu ilosci
  (14.09: piec razy, dwie paczki wisza do dzis) → `GET /api/employee-lookup`
  sprawdza go w kroku 1;
- identyfikator zeskanowany w pole paczki dawal goly „nieznany kod paczki"
  → 400 z nazwiskiem i `kod_pracownika`;
- dwa rownolegle „koniec" tej samej paczki oba dostawaly 200 (15.09)
  → `SELECT … FOR UPDATE` na kartonie.
"""
import threading
import time
from datetime import date

import app as logistat
from conftest import login, make_user

ZIEL = date(2026, 9, 10)


def make_carton(barcode='P1', stueckzahl=10):
    c = logistat.ImportedCarton(barcode=barcode, land='PL', stueckzahl=stueckzahl,
                                ziel_datum=ZIEL, uebergabe_nr='UB-1')
    logistat.db.session.add(c)
    logistat.db.session.commit()
    return c


def carton(barcode='P1'):
    logistat.db.session.expire_all()
    return logistat.ImportedCarton.query.filter_by(barcode=barcode).first()


def start(client, emp, pkg='P1'):
    return client.post('/api/package-time/start',
                       json={'employee_barcode': emp, 'package_barcode': pkg})


def end(client, emp, pkg='P1', categories=None):
    body = {'employee_barcode': emp, 'package_barcode': pkg}
    if categories is not None:
        body['categories'] = categories
    return client.post('/api/package-time/end', json=body)


def employee(client, kod):
    return client.get('/api/employee-lookup', query_string={'barcode': kod})


# ── Krok 1: kod pracownika sprawdzany od razu ────────────────────────────────

def test_znany_pracownik_zwraca_nazwisko(leader_client):
    w = make_user('operator', barcode_id='W1', display_name='Kowalska Anna')

    r = employee(leader_client, 'W1')

    assert r.status_code == 200
    assert r.get_json()['user'] == {'id': w.id, 'display_name': 'Kowalska Anna'}


def test_nieznany_pracownik_daje_404(leader_client):
    assert employee(leader_client, 'NIEMA').status_code == 404


def test_nieaktywny_pracownik_nie_przechodzi_kroku_1(leader_client):
    w = make_user('operator', barcode_id='W1')
    w.is_active_user = False
    logistat.db.session.commit()

    assert employee(leader_client, 'W1').status_code == 404


def test_kod_paczki_w_polu_pracownika_nazwany_po_imieniu(leader_client):
    make_carton('3998302113')

    r = employee(leader_client, '3998302113')

    assert r.status_code == 400
    assert 'kod paczki' in r.get_json()['error']


def test_pusty_kod_pracownika_daje_400(leader_client):
    assert employee(leader_client, '').status_code == 400


def test_sprawdzenie_pracownika_wymaga_lidera(client):
    make_user('operator', barcode_id='W1')

    r = client.get('/api/employee-lookup', query_string={'barcode': 'W1'})

    assert r.status_code in (302, 401, 403)


# ── Identyfikator zeskanowany w pole paczki ──────────────────────────────────

def test_podglad_paczki_rozpoznaje_kod_pracownika(leader_client):
    make_user('operator', barcode_id='LSMOLIACHENKO', display_name='Smoliachenko Lina')

    r = leader_client.get('/api/package-lookup', query_string={'barcode': 'LSMOLIACHENKO'})

    assert r.status_code == 400
    data = r.get_json()
    assert data['kod_pracownika'] is True
    assert 'Smoliachenko Lina' in data['error']


def test_start_z_kodem_pracownika_w_polu_paczki(leader_client):
    make_user('operator', barcode_id='W1')
    make_user('operator', barcode_id='W2')

    r = start(leader_client, 'W1', pkg='W2')

    assert r.status_code == 400
    assert r.get_json()['kod_pracownika'] is True


def test_koniec_z_kodem_pracownika_w_polu_paczki(leader_client):
    make_user('operator', barcode_id='W1')

    r = end(leader_client, 'W1', pkg='W1')

    assert r.status_code == 400
    assert r.get_json()['kod_pracownika'] is True


def test_naprawde_nieznana_paczka_dalej_404(leader_client):
    make_user('operator', barcode_id='W1')

    assert start(leader_client, 'W1', pkg='BRAK').status_code == 404
    assert leader_client.get('/api/package-lookup',
                             query_string={'barcode': 'BRAK'}).status_code == 404


def test_podglad_paczki_podaje_kto_ja_rozpoczal(leader_client):
    """Ekran porownuje to z pracownikiem z kroku 1, zanim otworzy panel ilosci
    — inaczej 403 „tylko on moze zakonczyc" kasowaloby wpisane ilosci."""
    w = make_user('operator', barcode_id='W1')
    make_carton()
    start(leader_client, 'W1')

    r = leader_client.get('/api/package-lookup', query_string={'barcode': 'P1'})

    assert r.get_json()['carton']['scan_start_by'] == w.id


# ── Rownolegle zadania ───────────────────────────────────────────────────────

def test_start_i_koniec_blokuja_wiersz_kartonu(leader_client, queries):
    make_user('operator', barcode_id='W1')
    make_carton()

    start(leader_client, 'W1')
    end(leader_client, 'W1')

    zablokowane = [q for q in queries.matching('FROM imported_carton')
                   if 'FOR UPDATE' in q.upper()]
    assert len(zablokowane) == 2, 'start i koniec musza czytac karton z blokada'


def test_dwa_rownolegle_konce_przechodzi_tylko_jeden(flask_app, leader, monkeypatch):
    """Podwojny Enter z 15.09: bez blokady oba zadania mijaly kontrole
    `scan_end_at` i oba konczyly sie 200."""
    make_user('operator', barcode_id='W1')
    make_carton()
    nazwa_lidera = leader.username
    klient = flask_app.test_client()
    login(klient, nazwa_lidera)
    assert start(klient, 'W1').status_code == 200
    logistat.db.session.commit()

    # Okno miedzy kontrola stanu a zapisem — bez blokady oba watki w nie wchodza.
    oryginal = logistat.parse_scan_categories

    def wolno(surowe):
        time.sleep(0.5)
        return oryginal(surowe)

    monkeypatch.setattr(logistat, 'parse_scan_categories', wolno)

    wyniki = []

    def zadanie():
        with flask_app.app_context():
            k = flask_app.test_client()
            login(k, nazwa_lidera)
            wyniki.append(end(k, 'W1', categories={'labelling_on': 5}).status_code)
            logistat.db.session.remove()

    watki = [threading.Thread(target=zadanie) for _ in range(2)]
    for w in watki:
        w.start()
    for w in watki:
        w.join(timeout=10)

    assert sorted(wyniki) == [200, 409]
    assert carton().get_scan_categories() == {'labelling_on': 5}


# ── Ekran ────────────────────────────────────────────────────────────────────

def test_panel_ilosci_mowi_ze_paczka_nie_jest_zakonczona(leader_client):
    html = leader_client.get('/scan-paczki').get_data(as_text=True)

    assert 'Paczka NIE jest jeszcze zakończona' in html
    assert '/api/employee-lookup' in html
