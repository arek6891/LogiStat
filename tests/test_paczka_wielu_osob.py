"""Paczka wielu osob (2026-10-13): „Paczka do dokonczenia" i „Pakowanie zespolowe".

Przekazanie: koniec zmiany — pracownik wpisuje, co przerobil, paczka zostaje
otwarta (bez startu), nastepna osoba wbija zwykly Start i konczy standardowo.
Zespol: do rozpoczetej paczki dolaczaja kolejne osoby; koniec wbija kazda
sama, paczka zamyka sie po ostatniej (albo „zamknij dla wszystkich" / lider).
Normy licza kazda osobe z jej udzialu: jej czas i jej WPISANE ilosci.
Nadwyzka przy 2+ osobach → blad „do wyjasnienia przez lidera".
"""
import threading
import time
from datetime import date

import app as logistat
from conftest import login, make_user

DZIEN = date(2026, 10, 13)


def karton(barcode='P1', sztuk=100):
    c = logistat.ImportedCarton(barcode=barcode, land='PL', stueckzahl=sztuk,
                                data_pliku=DZIEN, uebergabe_nr='UB-1')
    logistat.db.session.add(c)
    logistat.db.session.commit()
    return c


def k(barcode='P1'):
    logistat.db.session.expire_all()
    return logistat.ImportedCarton.query.filter_by(barcode=barcode).one()


def post(client, url, emp, pkg='P1', **extra):
    return client.post(url, json={'employee_barcode': emp, 'package_barcode': pkg, **extra})


def start(c, emp, pkg='P1'):
    return post(c, '/api/package-time/start', emp, pkg)


def koniec(c, emp, pkg='P1', kat=None, **extra):
    return post(c, '/api/package-time/end', emp, pkg, categories=kat or {}, **extra)


def przekaz(c, emp, pkg='P1', kat=None):
    return post(c, '/api/package-time/przekaz', emp, pkg, categories=kat or {})


def dolacz(c, emp, pkg='P1'):
    return post(c, '/api/package-time/dolacz', emp, pkg)


def osoby(*kody):
    return [make_user('operator', barcode_id=kod, display_name=f'Osoba {kod}') for kod in kody]


# ── Paczka do dokonczenia ────────────────────────────────────────────────────

def test_przekazanie_zapisuje_ilosci_i_zostawia_paczke_otwarta(leader_client):
    osoby('A')
    karton()
    assert start(leader_client, 'A').status_code == 200

    r = przekaz(leader_client, 'A', kat={'labelling_on': 30})

    assert r.status_code == 200, r.get_json()
    c = k()
    assert c.scan_end_at is None and c.scan_start_at is None
    assert c.do_dokonczenia()
    assert c.get_scan_categories() == {'labelling_on': 30}
    assert [(u.rodzaj, u.suma(), u.end_at is not None) for u in c.udzialy] == [('przekazana', 30, True)]
    assert r.get_json()['carton']['do_dokonczenia'] is True


def test_nastepna_osoba_konczy_standardowo(leader_client):
    a, b = osoby('A', 'B')
    karton()
    start(leader_client, 'A')
    przekaz(leader_client, 'A', kat={'labelling_on': 30})

    r = start(leader_client, 'B')
    assert r.status_code == 200 and 'Dokończenie po: Osoba A' in r.get_json()['message']
    r = koniec(leader_client, 'B', kat={'labelling_on': 70})

    assert r.status_code == 200, r.get_json()
    c = k()
    assert c.scan_end_at and c.scan_end_by == b.id
    assert c.scan_start_by == a.id                       # paczke zaczela A
    assert c.get_scan_categories() == {'labelling_on': 100}
    assert [u.user_id for u in c.udzialy] == [a.id, b.id]
    # Czas proc. = suma udzialow, nie rozpietosc od startu A do konca B.
    assert c.processing_seconds() == sum(
        int((u.end_at - u.start_at).total_seconds()) for u in c.udzialy)


def test_normy_licza_kazdego_z_jego_ilosci_i_czasu(leader_client):
    a, b = osoby('A', 'B')
    karton(sztuk=500)
    start(leader_client, 'A')
    przekaz(leader_client, 'A', kat={'labelling_on': 30})
    start(leader_client, 'B')
    koniec(leader_client, 'B', kat={'sorting': 70})

    praca = logistat.prace_osob(logistat.local_today(), logistat.local_today())

    assert [x[2] for x in praca[a.id]] == [30]           # nie Stückzahl 500
    assert [x[2] for x in praca[b.id]] == [70]


def test_przekazanie_strazniki(leader_client):
    osoby('A', 'B')
    karton()
    assert przekaz(leader_client, 'A').status_code == 400           # nierozpoczeta
    start(leader_client, 'A')
    assert przekaz(leader_client, 'B').status_code == 403           # nie jego
    koniec(leader_client, 'A')
    assert przekaz(leader_client, 'A').status_code == 409           # zakonczona


def test_bez_startu_nie_mozna_zakonczyc_przekazanej(leader_client):
    osoby('A', 'B')
    karton()
    start(leader_client, 'A')
    przekaz(leader_client, 'A')

    assert koniec(leader_client, 'B').status_code == 400


def test_status_do_dokonczenia_i_w_toku(leader_client):
    osoby('A')
    karton('P1')
    karton('P2')
    start(leader_client, 'A')
    przekaz(leader_client, 'A', kat={'labelling_on': 3})

    html = leader_client.get('/paczki?status=do_dokonczenia').get_data(as_text=True)
    assert '>P1<' in html and '>P2<' not in html
    plan = logistat.plan_dnia_pliku(DZIEN)
    assert plan['w_toku'] == 1
    # Nie jest bledem „Rozpoczeta, ale nie zakonczona".
    assert logistat.bledy_paczki(k()) == []


def test_przekazana_czesc_nie_liczy_sie_jako_zeskanowana(leader_client):
    osoby('A')
    karton()
    start(leader_client, 'A')
    przekaz(leader_client, 'A', kat={'labelling_on': 30})

    assert logistat.scan_coverage_map()[('UB-1', 'PL', DZIEN)] == (0, 1)


# ── Pakowanie zespolowe ──────────────────────────────────────────────────────

def test_zespol_konczy_kazdy_sam_paczka_zamyka_sie_po_ostatnim(leader_client):
    _, _, c_ = osoby('A', 'B', 'C')
    karton()
    start(leader_client, 'A')
    assert dolacz(leader_client, 'B').status_code == 200
    assert dolacz(leader_client, 'C').status_code == 200
    assert len(logistat.otwarte_udzialy(k())) == 3        # A dostala udzial od swojego startu

    r = koniec(leader_client, 'A', kat={'labelling_on': 10})
    assert r.status_code == 200 and r.get_json()['zamknieta'] is False
    assert k().scan_end_at is None
    r = koniec(leader_client, 'B', kat={'labelling_on': 20})
    assert r.get_json()['zamknieta'] is False
    r = koniec(leader_client, 'C', kat={'labelling_on': 30})

    assert r.get_json()['zamknieta'] is True
    c = k()
    assert c.scan_end_by == c_.id
    assert c.get_scan_categories() == {'labelling_on': 60}


def test_zamknij_dla_wszystkich(leader_client):
    a, b, c_ = osoby('A', 'B', 'C')
    karton()
    start(leader_client, 'A')
    dolacz(leader_client, 'B')
    dolacz(leader_client, 'C')

    r = koniec(leader_client, 'B', kat={'labelling_on': 20}, zamknij_wszystkich=True)

    assert r.get_json()['zamknieta'] is True
    c = k()
    zamkniete = {u.user_id: u.zamkniete_przez for u in c.udzialy}
    assert zamkniete == {a.id: b.id, b.id: None, c_.id: b.id}
    # Zamknieci przez kogos innego (bez ilosci) nie wchodza do norm.
    praca = logistat.prace_osob()
    assert a.id not in praca and c_.id not in praca and praca[b.id][0][2] == 20


def test_zespol_strazniki(leader_client):
    osoby('A', 'B', 'D')
    karton()
    assert dolacz(leader_client, 'B').status_code == 400          # nierozpoczeta
    start(leader_client, 'A')
    assert dolacz(leader_client, 'A').status_code == 200          # juz pracuje — bez zmian
    dolacz(leader_client, 'B')
    assert dolacz(leader_client, 'B').status_code == 200
    assert len(k().udzialy) == 2

    r = start(leader_client, 'D')
    assert r.status_code == 409 and 'Pakowanie zespołowe' in r.get_json()['error']
    assert koniec(leader_client, 'D').status_code == 403
    assert przekaz(leader_client, 'A').status_code == 409          # B dalej pracuje


def test_lider_zamyka_zespol(leader_client, leader):
    a, b = osoby('A', 'B')
    karton()
    start(leader_client, 'A')
    dolacz(leader_client, 'B')
    koniec(leader_client, 'A', kat={'labelling_on': 10})
    cid = k().id

    r = leader_client.post(f'/api/packages/{cid}/zamknij-zespol')

    assert r.status_code == 200, r.get_json()
    c = k()
    assert c.scan_end_at and c.scan_end_by == a.id
    assert {u.user_id: u.zamkniete_przez for u in c.udzialy} == {a.id: None, b.id: leader.id}
    assert c.modified_by == leader.id
    assert leader_client.post(f'/api/packages/{cid}/zamknij-zespol').status_code == 409


def test_lider_zamyka_tylko_zespol(leader_client):
    osoby('A')
    karton()
    start(leader_client, 'A')
    assert leader_client.post(f'/api/packages/{k().id}/zamknij-zespol').status_code == 400


def test_odblokuj_zespol_kasuje_otwarte_udzialy(leader_client):
    osoby('A', 'B')
    karton()
    start(leader_client, 'A')
    dolacz(leader_client, 'B')

    assert leader_client.post(f'/api/packages/{k().id}/unlock-scan').status_code == 200
    c = k()
    assert c.scan_start_at is None and c.udzialy == []


def test_odblokuj_po_przekazaniu_wraca_do_dokonczenia(leader_client):
    osoby('A', 'B')
    karton()
    start(leader_client, 'A')
    przekaz(leader_client, 'A', kat={'labelling_on': 30})
    start(leader_client, 'B')

    leader_client.post(f'/api/packages/{k().id}/unlock-scan')

    c = k()
    assert c.do_dokonczenia() and len(c.udzialy) == 1


def test_filtr_osoby_znajduje_uczestnika(leader_client):
    _, b = osoby('A', 'B')
    karton()
    start(leader_client, 'A')
    dolacz(leader_client, 'B')
    koniec(leader_client, 'A', zamknij_wszystkich=True)          # B nie zaczal ani nie skonczyl

    html = leader_client.get(f'/paczki?osoba={b.id}&status=wszystkie'
                             f'&date_from={DZIEN}&date_to={DZIEN}').get_data(as_text=True)
    assert '>P1<' in html


def test_per_zmiana_liczy_kazdego_uczestnika(leader_client):
    a, b = osoby('A', 'B')
    karton()
    dzis = logistat.local_today()
    for u, nr in ((a, 1), (b, 2)):
        s = logistat.get_or_create_shift(dzis, nr)
        logistat.db.session.add(logistat.ShiftAttendance(shift_id=s.id, user_id=u.id))
    logistat.db.session.commit()
    start(leader_client, 'A')
    przekaz(leader_client, 'A', kat={'labelling_on': 30})
    start(leader_client, 'B')
    koniec(leader_client, 'B', kat={'labelling_on': 70})

    d = leader_client.get(f'/api/dashboard/shifts?date={dzis}').get_json()

    assert [(s['packages'], s['pieces']) for s in d['shifts']] == [(1, 30), (1, 70)]


# ── Nadwyzka przy 2+ osobach → do wyjasnienia ────────────────────────────────

def test_nadwyzka_dwoch_osob_jest_bledem_do_wyjasnienia(leader_client):
    osoby('A', 'B')
    karton(sztuk=100)
    start(leader_client, 'A')
    przekaz(leader_client, 'A', kat={'labelling_on': 60})
    start(leader_client, 'B')
    koniec(leader_client, 'B', kat={'labelling_tvl': 60})        # suma 120 > 100

    bledy = logistat.bledy_paczki(k())

    assert any('Procesowało 2 os.' in b and 'Osoba A' in b and 'Osoba B' in b
               and 'Do wyjaśnienia przez lidera' in b for b in bledy), bledy
    html = leader_client.get('/paczki?bledy=1').get_data(as_text=True)
    assert 'Do wyjaśnienia przez lidera' in html


def test_bez_nadwyzki_nie_ma_bledu(leader_client):
    osoby('A', 'B')
    karton(sztuk=100)
    start(leader_client, 'A')
    przekaz(leader_client, 'A', kat={'labelling_on': 40})
    start(leader_client, 'B')
    koniec(leader_client, 'B', kat={'labelling_on': 60})

    assert logistat.bledy_paczki(k()) == []


def test_jedna_osoba_z_nadwyzka_bez_komunikatu_o_osobach(leader_client):
    osoby('A')
    karton(sztuk=100)
    start(leader_client, 'A')
    koniec(leader_client, 'A', kat={'labelling_on': 120})

    bledy = logistat.bledy_paczki(k())
    assert bledy and not any('Procesowało' in b for b in bledy)


def test_filtr_bledow_bez_n_plus_1(leader_client, queries):
    """bledy_paczki() czyta udzialy per paczka — musza przyjsc jednym zapytaniem."""
    osoby('A', 'B')

    def paczki(od, do):
        for i in range(od, do):
            karton(f'X{i}')
            start(leader_client, 'A', f'X{i}')
            dolacz(leader_client, 'B', f'X{i}')
            koniec(leader_client, 'A', f'X{i}', kat={'labelling_on': 80}, zamknij_wszystkich=True)

    def odczyty():
        queries.statements.clear()
        leader_client.get('/paczki?bledy=1')
        return len(queries.selects)

    paczki(0, 2)
    przy_dwoch = odczyty()
    paczki(2, 12)
    assert odczyty() == przy_dwoch


# ── Wspolbieznosc ────────────────────────────────────────────────────────────

def test_dwa_rownolegle_konce_zespolu_zamykaja_paczke_raz(flask_app, leader, monkeypatch):
    """Dwie osoby z zespolu wbijaja koniec w tej samej chwili na dwoch
    stanowiskach: obie maja 200, paczka zamknieta, suma obu ilosci."""
    osoby('A', 'B')
    karton()
    nazwa_lidera = leader.username      # przed watkami — wspolna sesja ORM
    klient = flask_app.test_client()
    login(klient, nazwa_lidera)
    start(klient, 'A')
    dolacz(klient, 'B')
    logistat.db.session.commit()

    oryginal = logistat.parse_scan_categories

    def wolno(surowe):
        time.sleep(0.4)
        return oryginal(surowe)

    monkeypatch.setattr(logistat, 'parse_scan_categories', wolno)
    wyniki = []

    def zadanie(kod, ile):
        with flask_app.app_context():
            kl = flask_app.test_client()
            login(kl, nazwa_lidera)
            r = koniec(kl, kod, kat={'labelling_on': ile})
            wyniki.append((r.status_code, r.get_json().get('zamknieta')))
            logistat.db.session.remove()

    watki = [threading.Thread(target=zadanie, args=a) for a in (('A', 10), ('B', 20))]
    for w in watki:
        w.start()
    for w in watki:
        w.join(timeout=10)

    assert sorted(wyniki) == [(200, False), (200, True)]
    c = k()
    assert c.scan_end_at and c.get_scan_categories() == {'labelling_on': 30}
