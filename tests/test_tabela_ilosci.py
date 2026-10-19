"""Tabela ilosci na koniec paczki (Post Processing, operacja 2026-10-15).

Operator wpisuje tabele grup artykulowych (Brak / Nadwyzka / Uszkodzone /
Podwojnie / Potrojnie), „Pojedynczo" liczy serwer. Z tabeli powstaja kolumny
rozliczenia: Labelling one/twice/triple tylko z biżuterii (twice ×1,5, triple
×2 — LOGIKA_KLEJENIA.xlsx), pozostale grupy do swoich kolumn, uszkodzone do
Sorting. Paczka kilku osob: kazdy wpisuje swoje sztuki wprost, Normy licza
to, co osoba wpisala. Roznica → ❗ do potwierdzenia przez lidera.
"""
from datetime import date, datetime

from conftest import make_user

from logistat.extensions import db
from logistat.kategorie import STAT_CATEGORIES, total_amount_wiersza
from logistat.models import GeneralStat, ImportedCarton
from logistat.normy_dane import prace_osob
from logistat.paczki import bledy_paczki
from logistat.tabela_ilosci import (
    ZRODLO_KATEGORII, kategorie_z_tabeli, normalizuj_tabele, sztuki_tabeli)


DZIEN = date(2026, 10, 15)

# Przyklad z dokumentu dla operacji: 41 szt. w pliku = 20 biżuterii + 12 akcesoriow
# + 5 okularow + 4 tekstylia (biżuteria = 41 − pozostale grupy).
PRZYKLAD = {
    'grupy': {
        'bizuteria': {'brak': 1, 'podwojnie': 2, 'potrojnie': 3},
        'akcesoria': {'ilosc': 12, 'nadwyzka': 1, 'uszkodzone': 1, 'podwojnie': 1},
        'okulary': {'ilosc': 5},
        'tekstylia': {'ilosc': 4},
    },
    'dodatki': {},
}


def karton(barcode='P1', sztuk=41):
    c = ImportedCarton(barcode=barcode, land='PL', stueckzahl=sztuk,
                                data_pliku=DZIEN, uebergabe_nr='UB-1')
    db.session.add(c)
    db.session.commit()
    return c


def k(barcode='P1'):
    db.session.expire_all()
    return ImportedCarton.query.filter_by(barcode=barcode).one()


def post(client, url, emp, pkg='P1', **extra):
    return client.post(url, json={'employee_barcode': emp, 'package_barcode': pkg, **extra})


def start(c, emp, pkg='P1'):
    return post(c, '/api/package-time/start', emp, pkg)


def koniec(c, emp, tabela, tryb='wzor', pkg='P1', **extra):
    return post(c, '/api/package-time/end', emp, pkg, tabela=tabela, tryb=tryb, **extra)


def zespol(**grupy):
    """Tabela jednej osoby w paczce kilku osob: {grupa: (poj, podw, potr, uszk)}."""
    return {'grupy': {g: dict(zip(('pojedynczo', 'podwojnie', 'potrojnie', 'uszkodzone'), v))
                      for g, v in grupy.items()}, 'dodatki': {}}


def linia():
    db.session.expire_all()
    return GeneralStat.query.filter_by(list_id='UB-1').one()


def osoba(kod):
    return make_user('operator', barcode_id=kod, display_name=f'Osoba {kod}')


# ── liczenie (czyste funkcje) ────────────────────────────────────────────────

def test_przyklad_z_dokumentu():
    tabela, blad = normalizuj_tabele(PRZYKLAD, 'wzor', 41)

    assert blad is None
    assert tabela['grupy']['bizuteria']['ilosc'] == 20
    assert tabela['grupy']['bizuteria']['pojedynczo'] == 14
    assert tabela['grupy']['akcesoria']['pojedynczo'] == 11
    assert kategorie_z_tabeli(tabela) == {
        'labelling_on': 14, 'labelling_tvl': 3, 'labelling_try': 6,
        'accessoire': 12, 'sunglasses': 5, 'textile': 4, 'sorting': 1,
    }
    kategorie = {kat: {'amount': v} for kat, v in kategorie_z_tabeli(tabela).items()}
    assert total_amount_wiersza(kategorie) == 36


def test_logika_klejenia_z_excela():
    # LOGIKA_KLEJENIA.xlsx: 15 szt. = 10 pojedynczo + 2 podwojnie + 3 potrojnie.
    tabela, blad = normalizuj_tabele(
        {'grupy': {'bizuteria': {'podwojnie': 2, 'potrojnie': 3}}}, 'wzor', 15)

    assert blad is None
    assert kategorie_z_tabeli(tabela) == {
        'labelling_on': 10, 'labelling_tvl': 3, 'labelling_try': 6}


def test_nieparzyste_podwojnie_daje_polowke():
    tabela, _ = normalizuj_tabele(
        {'grupy': {'bizuteria': {'podwojnie': 3}}}, 'wzor', 10)

    assert kategorie_z_tabeli(tabela)['labelling_tvl'] == 4.5


def test_brak_nie_trafia_do_rozliczenia_a_nadwyzka_tak():
    tabela, _ = normalizuj_tabele(
        {'grupy': {'bizuteria': {'brak': 2, 'nadwyzka': 5}}}, 'wzor', 10)

    assert kategorie_z_tabeli(tabela) == {'labelling_on': 13}


def test_dodatki_ida_do_swoich_kolumn():
    tabela, _ = normalizuj_tabele({
        'grupy': {'okulary': {'ilosc': 2, 'uszkodzone': 1}},
        'dodatki': {'sortowanie_inne': 4, 'karta_uszkodzona': 1, 'karta_algorytm': 2, 'worki': 3},
    }, 'wzor', 10)

    assert kategorie_z_tabeli(tabela) == {
        'labelling_on': 8, 'sunglasses': 1, 'sorting': 5, 'card_facture': 3,
        'labelling_polybag': 3}


def test_ujemne_pojedynczo_to_blad_z_nazwa_wiersza():
    _, blad = normalizuj_tabele(
        {'grupy': {'okulary': {'ilosc': 2, 'podwojnie': 3}}}, 'wzor', 10)

    assert blad and blad.startswith('Okulary:')


def test_pozostale_grupy_ponad_plik_to_blad():
    _, blad = normalizuj_tabele(
        {'grupy': {'tekstylia': {'ilosc': 11}}}, 'wzor', 10)

    assert blad and 'więcej niż w paczce' in blad


def test_liczba_jak_kod_kreskowy_to_blad():
    _, blad = normalizuj_tabele(
        {'grupy': {'bizuteria': {'brak': 5901234123457}}}, 'wzor', 10)

    assert blad and 'kod' in blad


def test_tryb_zespol_bierze_sztuki_wprost():
    tabela, blad = normalizuj_tabele(zespol(bizuteria=(7, 1, 0, 2)), 'zespol', 41)

    assert blad is None
    assert sztuki_tabeli(tabela) == 10
    assert kategorie_z_tabeli(tabela) == {
        'labelling_on': 7, 'labelling_tvl': 1.5, 'sorting': 2}


# ── stanowisko: paczka jednej osoby ─────────────────────────────────────────

def test_koniec_zapisuje_tabele_i_rozliczenie(leader_client):
    osoba('A')
    karton()
    start(leader_client, 'A')

    r = koniec(leader_client, 'A', PRZYKLAD)

    assert r.status_code == 200, r.get_json()
    c = k()
    assert c.get_tabela()['grupy']['bizuteria']['pojedynczo'] == 14
    assert c.get_scan_categories()['labelling_tvl'] == 3
    l = linia()
    assert l.category_source == 'scan'
    assert l.get_category_data()['labelling_on']['amount'] == 14
    assert l.get_category_data()['sorting']['amount'] == 1


def test_polowka_dochodzi_do_statystyk_ogolnych(leader_client):
    osoba('A')
    karton(sztuk=10)
    start(leader_client, 'A')

    koniec(leader_client, 'A', {'grupy': {'bizuteria': {'podwojnie': 3}}})

    assert linia().get_category_data()['labelling_tvl']['amount'] == 4.5


def test_blad_tabeli_nie_konczy_paczki(leader_client):
    osoba('A')
    karton(sztuk=5)
    start(leader_client, 'A')

    r = koniec(leader_client, 'A', {'grupy': {'bizuteria': {'podwojnie': 6}}})

    assert r.status_code == 400
    assert 'Biżuteria' in r.get_json()['error']
    assert k().scan_end_at is None


def test_zly_tryb_to_409_bez_zapisu(leader_client):
    osoba('A')
    karton()
    start(leader_client, 'A')

    r = koniec(leader_client, 'A', PRZYKLAD, tryb='zespol')

    assert r.status_code == 409
    assert r.get_json()['zmiana_trybu'] is True
    assert k().scan_end_at is None


def test_stary_formularz_kategorii_dalej_dziala(leader_client):
    """Karta stanowiska otwarta przed wdrozeniem wysyla jeszcze `categories`."""
    osoba('A')
    karton()
    start(leader_client, 'A')

    r = post(leader_client, '/api/package-time/end', 'A', categories={'labelling_on': 41})

    assert r.status_code == 200
    c = k()
    assert c.get_scan_categories() == {'labelling_on': 41}
    assert c.tabela_ilosci is None and c.roznica is False


# ── ❗ roznica i potwierdzenie lidera ─────────────────────────────────────────

def test_roznica_zapala_wykrzyknik(leader_client):
    osoba('A')
    karton()
    start(leader_client, 'A')
    koniec(leader_client, 'A', PRZYKLAD)

    c = k()
    assert c.roznica is True and c.roznica_do_potwierdzenia()
    assert c.powody_roznicy() == ['Biżuteria: brak 1', 'Akcesoria: nadwyżka 1, uszkodzone 1']
    assert any(b.startswith('❗') for b in bledy_paczki(c))
    assert leader_client.get('/api/dashboard').get_json()['do_potwierdzenia'] == 1


def test_paczka_bez_roznicy_nie_ma_wykrzyknika(leader_client):
    osoba('A')
    karton(sztuk=10)
    start(leader_client, 'A')
    koniec(leader_client, 'A', {'grupy': {'bizuteria': {'podwojnie': 2}}})

    c = k()
    assert c.roznica is False
    assert bledy_paczki(c) == []


def test_lider_potwierdza_roznice(leader_client):
    osoba('A')
    karton()
    start(leader_client, 'A')
    koniec(leader_client, 'A', PRZYKLAD)

    r = leader_client.post(f'/api/packages/{k().id}/potwierdz-roznice')

    assert r.status_code == 200
    c = k()
    assert c.roznica_potwierdzona_at is not None and c.potwierdzajacy.role == 'leader'
    assert bledy_paczki(c) == []
    assert leader_client.get('/api/dashboard').get_json()['do_potwierdzenia'] == 0
    html = leader_client.get('/paczki?bledy=1').get_data(as_text=True)
    assert 'P1' not in html.split('<tbody>')[1]


def test_kafelek_dashboardu_i_jego_lista_to_ten_sam_zbior(leader_client):
    """Kafelek „❗ Do potwierdzenia" linkuje do /paczki?do_potwierdzenia=1 —
    tam ma byc dokladnie tyle paczek, ile pokazuje licznik. `bledy=1` dokladalby
    stare bledy (+10 %) i paczki bez konca z calej historii."""
    osoba('A')
    for kod in ('NIEPOTW', 'POTW'):
        karton(kod)
        start(leader_client, 'A', kod)
        koniec(leader_client, 'A', PRZYKLAD, pkg=kod)
    leader_client.post(f'/api/packages/{k("POTW").id}/potwierdz-roznice')
    stara = karton('STARA', sztuk=10)
    stara.scan_end_at = datetime.utcnow()
    stara.set_scan_categories({'labelling_on': 12})   # stara regula +10 %
    karton('BEZ-KONCA')
    start(leader_client, 'A', 'BEZ-KONCA')
    db.session.commit()

    licznik = leader_client.get('/api/dashboard').get_json()['do_potwierdzenia']
    html = leader_client.get('/paczki?do_potwierdzenia=1').get_data(as_text=True)
    wiersze = html.split('<tbody>')[1]

    assert licznik == 1
    assert 'NIEPOTW' in wiersze
    assert all(kod not in wiersze for kod in ('>POTW<', 'STARA', 'BEZ-KONCA'))
    assert wiersze.count('class="paczka-ilosci"') == licznik
    assert 'href="/paczki?do_potwierdzenia=1"' in leader_client.get('/dashboard').get_data(as_text=True)


def test_niepotwierdzona_roznica_jest_w_filtrze_bledow(leader_client):
    osoba('A')
    karton()
    start(leader_client, 'A')
    koniec(leader_client, 'A', PRZYKLAD)

    html = leader_client.get('/paczki?bledy=1').get_data(as_text=True)

    assert '✔ Potwierdź' in html
    assert 'Biżuteria: brak 1' in html


def test_poprawka_lidera_przelicza_i_potwierdza(leader_client):
    osoba('A')
    karton()
    start(leader_client, 'A')
    koniec(leader_client, 'A', PRZYKLAD)
    poprawiona = {'grupy': {**PRZYKLAD['grupy'], 'bizuteria': {'podwojnie': 2, 'potrojnie': 3}},
                  'dodatki': {}}

    r = leader_client.put(f'/api/packages/{k().id}/tabela', json={'tabela': poprawiona})

    assert r.status_code == 200, r.get_json()
    c = k()
    assert c.get_tabela()['grupy']['bizuteria']['pojedynczo'] == 15
    assert linia().get_category_data()['labelling_on']['amount'] == 15
    assert c.roznica is True and c.roznica_potwierdzona_at is not None, 'akcesoria dalej z roznica'
    assert c.modified_by is not None


def test_paczka_sprzed_tabeli_ma_stare_okno_i_stare_reguly(leader_client):
    c = karton(sztuk=10)
    c.scan_end_at = datetime.utcnow()
    c.set_scan_categories({'labelling_on': 12})   # +20 % — stara regula +10 %
    db.session.commit()

    c = k()
    assert c.edytor_ilosci() == 'stary'
    assert any('Labelling one' in b for b in bledy_paczki(c))
    r = leader_client.put(f'/api/packages/{c.id}/tabela', json={'tabela': PRZYKLAD})
    assert r.status_code == 400


# ── paczka kilku osob ───────────────────────────────────────────────────────

def test_zespol_kazdy_wpisuje_swoje_sztuki(leader_client):
    a, b = osoba('A'), osoba('B')
    karton(sztuk=20)
    start(leader_client, 'A')
    post(leader_client, '/api/package-time/dolacz', 'B')

    assert k().tryb_tabeli() == 'zespol'
    r1 = koniec(leader_client, 'A', zespol(bizuteria=(8, 2, 0, 0)), tryb='zespol')
    r2 = koniec(leader_client, 'B', zespol(bizuteria=(9, 0, 0, 1)), tryb='zespol')

    assert r1.status_code == 200 and r2.status_code == 200, (r1.get_json(), r2.get_json())
    c = k()
    assert c.scan_end_at is not None
    assert c.get_tabela()['tryb'] == 'zespol'
    assert c.get_tabela()['grupy']['bizuteria']['pojedynczo'] == 17
    assert c.get_scan_categories() == {'labelling_on': 17, 'labelling_tvl': 3, 'sorting': 1}
    # Normy: kazda osoba to, co sama wpisala (podwojne jako zwykle sztuki).
    prace = prace_osob()
    assert [p[2] for p in prace[a.id]] == [10]
    assert [p[2] for p in prace[b.id]] == [10]
    # 20 sztuk przy 20 w pliku, ale 1 uszkodzona → ❗
    assert c.powody_roznicy() == ['Biżuteria: uszkodzone 1']


def test_zespol_suma_inna_niz_plik_to_wykrzyknik(leader_client):
    osoba('A')
    osoba('B')
    karton(sztuk=20)
    start(leader_client, 'A')
    post(leader_client, '/api/package-time/dolacz', 'B')
    koniec(leader_client, 'A', zespol(bizuteria=(8, 0, 0, 0)), tryb='zespol')
    koniec(leader_client, 'B', zespol(bizuteria=(9, 0, 0, 0)), tryb='zespol')

    c = k()
    assert c.roznica is True
    assert c.powody_roznicy() == ['2 os. wpisało razem 17 szt. przy 20 w paczce']


def test_przekazanie_z_tabela(leader_client):
    osoba('A')
    osoba('B')
    karton(sztuk=20)
    start(leader_client, 'A')

    r = post(leader_client, '/api/package-time/przekaz', 'A',
             tabela=zespol(bizuteria=(12, 0, 0, 0)), tryb='zespol')
    assert r.status_code == 200, r.get_json()
    assert 'wpisano 12 szt.' in r.get_json()['message']

    start(leader_client, 'B')
    r = koniec(leader_client, 'B', zespol(bizuteria=(8, 0, 0, 0)), tryb='zespol')

    assert r.status_code == 200, r.get_json()
    c = k()
    assert c.scan_end_at is not None and c.roznica is False
    assert c.get_scan_categories() == {'labelling_on': 20}


def test_lider_poprawia_jedna_osobe_w_zespole(leader_client):
    osoba('A')
    osoba('B')
    karton(sztuk=20)
    start(leader_client, 'A')
    post(leader_client, '/api/package-time/dolacz', 'B')
    koniec(leader_client, 'A', zespol(bizuteria=(8, 0, 0, 0)), tryb='zespol')
    koniec(leader_client, 'B', zespol(bizuteria=(9, 0, 0, 0)), tryb='zespol')
    c = k()
    udzial_b = next(u for u in c.udzialy if u.user.barcode_id == 'B')

    r = leader_client.put(f'/api/packages/{c.id}/tabela', json={
        'udzial_id': udzial_b.id, 'tabela': zespol(bizuteria=(12, 0, 0, 0))})

    assert r.status_code == 200, r.get_json()
    c = k()
    assert c.get_scan_categories() == {'labelling_on': 20}
    assert c.roznica is False


# ── ekrany ───────────────────────────────────────────────────────────────────

def test_statystyki_ogolne_maja_dymki_zrodla_kolumn(admin_client):
    l = GeneralStat(loading_date=DZIEN, week_number=42, list_id='UB-1',
                             country_ledger='PL', amounts=10)
    db.session.add(l)
    db.session.commit()

    html = admin_client.get(f'/general-stats?date_from={DZIEN}&date_to={DZIEN}').get_data(as_text=True)

    for opis in ZRODLO_KATEGORII.values():
        assert opis in html
    assert 'Mapowania kosztów' in html


def test_lider_nie_dostaje_opisu_stawek_w_dymku(leader_client):
    html = leader_client.get('/general-stats').get_data(as_text=True)

    assert 'Biżuteria → „Pojedynczo”' in html
    assert 'Amount × stawka' not in html


def test_kazda_kategoria_ma_opis_zrodla():
    assert set(ZRODLO_KATEGORII) == set(STAT_CATEGORIES)


def test_normy_maja_dymek_ktore_pola_sie_licza(leader_client):
    html = leader_client.get('/stats').get_data(as_text=True)

    assert 'Pojedynczo + Podwójnie + Potrójnie + Uszkodzone' in html


def test_dashboard_ma_licznik_do_potwierdzenia(leader_client):
    html = leader_client.get('/dashboard').get_data(as_text=True)

    assert 'doPotwierdzeniaVal' in html
