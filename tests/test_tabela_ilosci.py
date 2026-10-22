"""Tabela ilosci na koniec paczki (Post Processing).

Wersja 2 (operacja, 2026-10-23): operator wpisuje wszystko wprost — per grupa
Ilosc (pojedyncze) / Uszkodzone / Niesprocesowane, na paczke Flagi – Card Change,
Podwojne, Potrojne. Nadwyzka i Brak liczy system (wpisane sztuki − Stückzahl).
Rozliczenie: Ilosc grupy → jej kolumna (biżuteria → Labelling one), Podwojne
×1,5 / Potrojne ×2 → twice / triple (wszystkie grupy), Sorting = Uszkodzone +
Niesprocesowane, Card facture = Flagi. Paczka kilku osob: kazdy wpisuje swoja
czesc, Normy licza to, co osoba wpisala. Roznica → ❗ do potwierdzenia.

Wersja 1 (15–22.10.2026) zostaje tylko do odczytu: zapisane paczki licza sie
po staremu (sekcja „stare tabele" na dole).
"""
from datetime import date, datetime

from conftest import make_user

from logistat.extensions import db
from logistat.kategorie import STAT_CATEGORIES, total_amount_wiersza
from logistat.models import GeneralStat, ImportedCarton
from logistat.normy_dane import prace_osob
from logistat.paczki import bledy_paczki, przelicz_ilosci_udzialow
from logistat.tabela_ilosci import (
    BLAD_STARY_EKRAN, ZRODLO_KATEGORII, kategorie_z_tabeli, na_wersje_2, nadwyzka_brak,
    normalizuj_tabele, roznice_tabeli, suma_tabel, sztuki_tabeli)


DZIEN = date(2026, 10, 15)


def tab(podwojnie=0, potrojnie=0, karty=0, **grupy):
    """Tabela z ekranu: grupa=(ilosc, uszkodzone, niesprocesowane)."""
    return {'wersja': 2, 'podwojnie': podwojnie, 'potrojnie': potrojnie, 'karty': karty,
            'grupy': {g: dict(zip(('ilosc', 'uszkodzone', 'niesprocesowane'), v))
                      for g, v in grupy.items()}}


# 41 szt. w pliku: 14 biżuterii, 11 akcesoriow + 1 uszkodzone, 5 okularow,
# 4 tekstylia, 2 podwojne, 3 potrojne = 40 → Brak 1.
PRZYKLAD = tab(podwojnie=2, potrojnie=3, bizuteria=(14, 0, 0), akcesoria=(11, 1, 0),
               okulary=(5, 0, 0), tekstylia=(4, 0, 0))


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


def linia():
    db.session.expire_all()
    return GeneralStat.query.filter_by(list_id='UB-1').one()


def osoba(kod):
    return make_user('operator', barcode_id=kod, display_name=f'Osoba {kod}')


# ── liczenie (czyste funkcje) ────────────────────────────────────────────────

def test_przyklad():
    tabela, blad = normalizuj_tabele(PRZYKLAD, 'wzor', 41)

    assert blad is None
    assert sztuki_tabeli(tabela) == 40
    assert nadwyzka_brak(tabela, 41) == (0, 1)
    assert kategorie_z_tabeli(tabela) == {
        'labelling_on': 14, 'labelling_tvl': 3, 'labelling_try': 6,
        'accessoire': 11, 'sunglasses': 5, 'textile': 4, 'sorting': 1,
    }
    kategorie = {kat: {'amount': v} for kat, v in kategorie_z_tabeli(tabela).items()}
    assert total_amount_wiersza(kategorie) == 35


def test_logika_klejenia_z_excela():
    # LOGIKA_KLEJENIA.xlsx: 15 szt. = 10 pojedynczo + 2 podwojnie + 3 potrojnie.
    tabela, blad = normalizuj_tabele(tab(podwojnie=2, potrojnie=3, bizuteria=(10, 0, 0)), 'wzor', 15)

    assert blad is None
    assert kategorie_z_tabeli(tabela) == {
        'labelling_on': 10, 'labelling_tvl': 3, 'labelling_try': 6}
    assert nadwyzka_brak(tabela, 15) == (0, 0)


def test_podwojne_innych_grup_ida_do_labelling_twice():
    """Operacja 2026-10-23: ×1,5 / ×2 dla wszystkich grup, nie tylko biżuterii."""
    tabela, _ = normalizuj_tabele(tab(podwojnie=4, tekstylia=(6, 0, 0)), 'wzor', 10)

    assert kategorie_z_tabeli(tabela) == {'textile': 6, 'labelling_tvl': 6}


def test_nieparzyste_podwojnie_daje_polowke():
    tabela, _ = normalizuj_tabele(tab(podwojnie=3, bizuteria=(7, 0, 0)), 'wzor', 10)

    assert kategorie_z_tabeli(tabela)['labelling_tvl'] == 4.5


def test_uszkodzone_i_niesprocesowane_do_sorting_flagi_do_card_facture():
    tabela, _ = normalizuj_tabele(
        tab(karty=3, bizuteria=(5, 1, 2), okulary=(0, 1, 1)), 'wzor', 10)

    assert kategorie_z_tabeli(tabela) == {'labelling_on': 5, 'sorting': 5, 'card_facture': 3}
    assert sztuki_tabeli(tabela) == 10, 'Flagi to karty, nie sztuki'


def test_nadwyzka_i_brak_liczy_system():
    nadwyzka, _ = normalizuj_tabele(tab(bizuteria=(12, 0, 0)), 'wzor', 10)
    brak, _ = normalizuj_tabele(tab(bizuteria=(7, 0, 1)), 'wzor', 10)

    assert nadwyzka_brak(nadwyzka, 10) == (2, 0)
    assert nadwyzka_brak(brak, 10) == (0, 2)
    assert roznice_tabeli(nadwyzka, 10) == ['Nadwyżka 2 szt. (wpisano 12 przy 10 w paczce)']
    assert roznice_tabeli(brak, 10) == ['Brak 2 szt. (wpisano 8 przy 10 w paczce)']


def test_liczba_jak_kod_kreskowy_to_blad():
    _, blad = normalizuj_tabele(tab(bizuteria=(5901234123457, 0, 0)), 'wzor', 10)

    assert blad and 'kod' in blad and 'Biżuteria' in blad


def test_pusta_tabela_jednej_osoby_to_blad_w_zespole_nie():
    _, blad = normalizuj_tabele(tab(), 'wzor', 10)
    tabela, blad_zespolu = normalizuj_tabele(tab(), 'zespol', 10)

    assert blad and 'pusta' in blad
    assert blad_zespolu is None and sztuki_tabeli(tabela) == 0


def test_stary_ksztalt_z_ekranu_odrzucony():
    """Karta stanowiska otwarta przed wdrozeniem wysyla tabele bez `wersja`."""
    _, blad = normalizuj_tabele({'grupy': {'bizuteria': {'podwojnie': 2}}, 'dodatki': {}}, 'wzor', 10)

    assert blad == BLAD_STARY_EKRAN


def test_tryb_zespol_bierze_sztuki_wprost():
    tabela, blad = normalizuj_tabele(tab(podwojnie=1, bizuteria=(7, 2, 1)), 'zespol', 41)

    assert blad is None
    assert sztuki_tabeli(tabela) == 11
    assert kategorie_z_tabeli(tabela) == {
        'labelling_on': 7, 'labelling_tvl': 1.5, 'sorting': 3}


# ── stanowisko: paczka jednej osoby ─────────────────────────────────────────

def test_koniec_zapisuje_tabele_i_rozliczenie(leader_client):
    osoba('A')
    karton()
    start(leader_client, 'A')

    r = koniec(leader_client, 'A', PRZYKLAD)

    assert r.status_code == 200, r.get_json()
    c = k()
    assert c.get_tabela()['wersja'] == 2
    assert c.get_tabela()['grupy']['bizuteria']['ilosc'] == 14
    assert c.get_scan_categories()['labelling_tvl'] == 3
    l = linia()
    assert l.category_source == 'scan'
    assert l.get_category_data()['labelling_on']['amount'] == 14
    assert l.get_category_data()['sorting']['amount'] == 1


def test_polowka_dochodzi_do_statystyk_ogolnych(leader_client):
    osoba('A')
    karton(sztuk=10)
    start(leader_client, 'A')

    koniec(leader_client, 'A', tab(podwojnie=3, bizuteria=(7, 0, 0)))

    assert linia().get_category_data()['labelling_tvl']['amount'] == 4.5


def test_blad_tabeli_nie_konczy_paczki(leader_client):
    osoba('A')
    karton(sztuk=5)
    start(leader_client, 'A')

    r = koniec(leader_client, 'A', tab(bizuteria=(5901234123457, 0, 0)))

    assert r.status_code == 400
    assert 'Biżuteria' in r.get_json()['error']
    assert k().scan_end_at is None


def test_stary_ekran_stanowiska_nic_nie_zapisuje(leader_client):
    osoba('A')
    karton(sztuk=10)
    start(leader_client, 'A')

    r = koniec(leader_client, 'A', {'grupy': {'bizuteria': {'podwojnie': 3}}, 'dodatki': {}})

    assert r.status_code == 400
    assert 'Odśwież' in r.get_json()['error']
    c = k()
    assert c.scan_end_at is None and c.tabela_ilosci is None


def test_zly_tryb_to_409_bez_zapisu(leader_client):
    osoba('A')
    karton()
    start(leader_client, 'A')

    r = koniec(leader_client, 'A', PRZYKLAD, tryb='zespol')

    assert r.status_code == 409
    assert r.get_json()['zmiana_trybu'] is True
    assert k().scan_end_at is None


def test_stary_formularz_kategorii_dalej_dziala(leader_client):
    """Karta stanowiska sprzed 2026-10-15 wysyla jeszcze `categories`."""
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
    assert c.powody_roznicy() == ['Brak 1 szt. (wpisano 40 przy 41 w paczce)', 'Akcesoria: uszkodzone 1']
    assert any(b.startswith('❗') for b in bledy_paczki(c))
    assert leader_client.get('/api/dashboard').get_json()['do_potwierdzenia'] == 1


def test_paczka_bez_roznicy_nie_ma_wykrzyknika(leader_client):
    osoba('A')
    karton(sztuk=10)
    start(leader_client, 'A')
    koniec(leader_client, 'A', tab(podwojnie=2, bizuteria=(8, 0, 0)))

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
    assert 'Brak 1 szt.' in html


def test_poprawka_lidera_przelicza_i_potwierdza(leader_client):
    osoba('A')
    karton()
    start(leader_client, 'A')
    koniec(leader_client, 'A', PRZYKLAD)
    poprawiona = tab(podwojnie=2, potrojnie=3, bizuteria=(15, 0, 0), akcesoria=(11, 1, 0),
                     okulary=(5, 0, 0), tekstylia=(4, 0, 0))

    r = leader_client.put(f'/api/packages/{k().id}/tabela', json={'tabela': poprawiona})

    assert r.status_code == 200, r.get_json()
    c = k()
    assert c.get_tabela()['grupy']['bizuteria']['ilosc'] == 15
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
    r1 = koniec(leader_client, 'A', tab(podwojnie=2, bizuteria=(8, 0, 0)), tryb='zespol')
    r2 = koniec(leader_client, 'B', tab(bizuteria=(9, 1, 0)), tryb='zespol')

    assert r1.status_code == 200 and r2.status_code == 200, (r1.get_json(), r2.get_json())
    c = k()
    assert c.scan_end_at is not None
    assert c.get_tabela()['tryb'] == 'zespol' and c.get_tabela()['wersja'] == 2
    assert c.get_tabela()['grupy']['bizuteria']['ilosc'] == 17
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
    koniec(leader_client, 'A', tab(bizuteria=(8, 0, 0)), tryb='zespol')
    koniec(leader_client, 'B', tab(bizuteria=(9, 0, 0)), tryb='zespol')

    c = k()
    assert c.roznica is True
    assert c.powody_roznicy() == ['Brak 3 szt. (2 os. wpisało razem 17 przy 20 w paczce)']


def test_przekazanie_z_tabela(leader_client):
    osoba('A')
    osoba('B')
    karton(sztuk=20)
    start(leader_client, 'A')

    r = post(leader_client, '/api/package-time/przekaz', 'A',
             tabela=tab(bizuteria=(12, 0, 0)), tryb='zespol')
    assert r.status_code == 200, r.get_json()
    assert 'wpisano 12 szt.' in r.get_json()['message']

    start(leader_client, 'B')
    r = koniec(leader_client, 'B', tab(bizuteria=(8, 0, 0)), tryb='zespol')

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
    koniec(leader_client, 'A', tab(bizuteria=(8, 0, 0)), tryb='zespol')
    koniec(leader_client, 'B', tab(bizuteria=(9, 0, 0)), tryb='zespol')
    c = k()
    udzial_b = next(u for u in c.udzialy if u.user.barcode_id == 'B')

    r = leader_client.put(f'/api/packages/{c.id}/tabela', json={
        'udzial_id': udzial_b.id, 'tabela': tab(bizuteria=(12, 0, 0))})

    assert r.status_code == 200, r.get_json()
    c = k()
    assert c.get_scan_categories() == {'labelling_on': 20}
    assert c.roznica is False


# ── stare tabele (wersja 1, paczki 15–22.10.2026) — tylko odczyt ─────────────

# Tak zapisal serwer wersji 1 przyklad z dokumentu dla operacji (41 szt.).
STARA = {
    'tryb': 'wzor',
    'grupy': {
        'bizuteria': {'ilosc': 20, 'brak': 1, 'nadwyzka': 0, 'uszkodzone': 0,
                      'podwojnie': 2, 'potrojnie': 3, 'pojedynczo': 14},
        'akcesoria': {'ilosc': 12, 'brak': 0, 'nadwyzka': 1, 'uszkodzone': 1,
                      'podwojnie': 1, 'potrojnie': 0, 'pojedynczo': 11},
        'okulary': {'ilosc': 5, 'brak': 0, 'nadwyzka': 0, 'uszkodzone': 0,
                    'podwojnie': 0, 'potrojnie': 0, 'pojedynczo': 5},
        'tekstylia': {'ilosc': 4, 'brak': 0, 'nadwyzka': 0, 'uszkodzone': 0,
                      'podwojnie': 0, 'potrojnie': 0, 'pojedynczo': 4},
    },
    'dodatki': {'sortowanie_inne': 2, 'karta_uszkodzona': 1, 'karta_algorytm': 1, 'worki': 3},
}


def test_stara_tabela_liczy_sie_po_staremu():
    """Rozliczenie, Normy i ❗ zapisanych paczek nie zmieniaja sie wstecz."""
    assert kategorie_z_tabeli(STARA) == {
        'labelling_on': 14, 'labelling_tvl': 3, 'labelling_try': 6,
        'accessoire': 12, 'sunglasses': 5, 'textile': 4, 'sorting': 3,
        'card_facture': 2, 'labelling_polybag': 3,
    }
    assert sztuki_tabeli(STARA) == 14 + 2 + 3 + 11 + 1 + 1 + 5 + 4
    assert roznice_tabeli(STARA, 41) == ['Biżuteria: brak 1', 'Akcesoria: nadwyżka 1, uszkodzone 1']


def test_stara_tabela_na_wersje_2():
    nowa = na_wersje_2(STARA)

    assert nowa['wersja'] == 2 and nowa['tryb'] == 'wzor'
    assert nowa['grupy']['bizuteria'] == {'ilosc': 14, 'uszkodzone': 0, 'niesprocesowane': 2}
    assert nowa['grupy']['akcesoria'] == {'ilosc': 11, 'uszkodzone': 1, 'niesprocesowane': 0}
    assert (nowa['podwojnie'], nowa['potrojnie'], nowa['karty']) == (3, 3, 2)
    assert na_wersje_2(nowa) is nowa and na_wersje_2(None) is None


def test_suma_tabel_starej_i_nowej_osoby():
    """Paczka zespolu zaczeta przed wdrozeniem, dokonczona po nim."""
    stara_osoba = {'tryb': 'zespol', 'dodatki': {},
                   'grupy': {'bizuteria': {'pojedynczo': 5, 'podwojnie': 1, 'potrojnie': 0,
                                           'uszkodzone': 1, 'ilosc': 7}}}
    nowa_osoba = tab(podwojnie=1, bizuteria=(6, 0, 0))
    nowa_osoba['tryb'] = 'zespol'

    suma = suma_tabel([stara_osoba, nowa_osoba])

    assert suma['wersja'] == 2
    assert suma['grupy']['bizuteria'] == {'ilosc': 11, 'uszkodzone': 1, 'niesprocesowane': 0}
    assert suma['podwojnie'] == 2
    assert sztuki_tabeli(suma) == sztuki_tabeli(stara_osoba) + sztuki_tabeli(nowa_osoba)


def test_suma_samych_starych_tabel_bez_zmian():
    t = {'tryb': 'zespol', 'dodatki': {},
         'grupy': {'bizuteria': {'pojedynczo': 5, 'podwojnie': 1, 'potrojnie': 0,
                                 'uszkodzone': 1, 'ilosc': 7}}}

    suma = suma_tabel([t, t])

    assert 'wersja' not in suma
    assert suma['grupy']['bizuteria']['pojedynczo'] == 10


def test_okno_lidera_dla_starej_paczki_dostaje_nowa_tabele(leader_client):
    c = karton()
    c.scan_start_at = c.scan_end_at = datetime.utcnow()
    c.set_tabela(STARA)
    c.set_scan_categories(kategorie_z_tabeli(STARA))
    db.session.commit()

    assert k().edytor_ilosci() == 'tabela'
    html = leader_client.get('/paczki?status=wszystkie&date_typ=plik'
                             f'&date_from={DZIEN}&date_to={DZIEN}').get_data(as_text=True)
    assert '&#34;niesprocesowane&#34;: 2' in html or '"niesprocesowane": 2' in html

    # Zapis lidera = juz nowe zasady (Podwojne innych grup → Labelling twice).
    r = leader_client.put(f'/api/packages/{k().id}/tabela', json={'tabela': na_wersje_2(STARA)})

    assert r.status_code == 200, r.get_json()
    c = k()
    assert c.get_tabela()['wersja'] == 2
    assert c.get_scan_categories()['labelling_tvl'] == 4.5
    assert 'labelling_polybag' not in c.get_scan_categories()


def test_zespol_ze_stara_i_nowa_osoba_liczy_sie_z_sumy(leader_client):
    a, b = osoba('A'), osoba('B')
    c = karton(sztuk=20)
    start(leader_client, 'A')
    post(leader_client, '/api/package-time/dolacz', 'B')
    # A skonczyl przed wdrozeniem — jego udzial ma tabele w wersji 1.
    c = k()
    ua = next(u for u in c.udzialy if u.user_id == a.id)
    ua.end_at = datetime.utcnow()
    ua.set_tabela({'tryb': 'zespol', 'dodatki': {},
                   'grupy': {'bizuteria': {'pojedynczo': 8, 'podwojnie': 2, 'potrojnie': 0,
                                           'uszkodzone': 0, 'ilosc': 10}}})
    przelicz_ilosci_udzialow(c, None)
    db.session.commit()

    r = koniec(leader_client, 'B', tab(bizuteria=(10, 0, 0)), tryb='zespol')

    assert r.status_code == 200, r.get_json()
    c = k()
    assert c.scan_end_at is not None
    assert c.get_tabela()['wersja'] == 2
    assert c.get_scan_categories() == {'labelling_on': 18, 'labelling_tvl': 3}
    assert c.roznica is False, '10 + 10 = 20 szt.'


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

    assert 'Biżuteria → „Ilość (pojedyncze)”' in html
    assert 'Amount × stawka' not in html


def test_kazda_kategoria_ma_opis_zrodla():
    assert set(ZRODLO_KATEGORII) == set(STAT_CATEGORIES)


def test_normy_maja_dymek_ktore_pola_sie_licza(leader_client):
    html = leader_client.get('/stats').get_data(as_text=True)

    assert 'Ilość + Uszkodzone + Niesprocesowane' in html


def test_dashboard_ma_licznik_do_potwierdzenia(leader_client):
    html = leader_client.get('/dashboard').get_data(as_text=True)

    assert 'doPotwierdzeniaVal' in html
