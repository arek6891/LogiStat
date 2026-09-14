"""Ilosci per kategoria ze skanu paczki — zrodlo rozliczenia.

Odkad `category_data` moze pochodzic ze skanow, `GeneralStat.category_source`
rozdziela dwa swiaty: linie 'manual' (wpisane recznie, sprzed skanowania) sa
nietykalne dla przeliczania, linie 'scan' sa suma kartonow. Najwazniejszy test
w tym pliku to ten, ktory pilnuje, ze przeliczenie NIE zeruje recznych linii —
to jest blad, ktory kosztuje pieniadze i nie rzuca sie w oczy.
"""
from datetime import date

import app as logistat
from conftest import make_user
from test_import_aggregation import ZIEL, gstat, row


def make_carton(barcode='P1', stueckzahl=10, uebergabe_nr='UB-1'):
    c = logistat.ImportedCarton(barcode=barcode, land='PL', stueckzahl=stueckzahl,
                                ziel_datum=ZIEL, uebergabe_nr=uebergabe_nr)
    logistat.db.session.add(c)
    logistat.db.session.commit()
    return c


def carton(barcode='P1'):
    return logistat.ImportedCarton.query.filter_by(barcode=barcode).first()


def start(client, emp, pkg='P1'):
    return client.post('/api/package-time/start',
                       json={'employee_barcode': emp, 'package_barcode': pkg})


def end(client, emp, pkg='P1', categories=None):
    tresc = {'employee_barcode': emp, 'package_barcode': pkg}
    if categories is not None:
        tresc['categories'] = categories
    return client.post('/api/package-time/end', json=tresc)


def amount(stat, kategoria):
    return stat.get_category_data().get(kategoria, {}).get('amount', 0)


# ── zapis ilosci przy skanie ────────────────────────────────────────────────

def test_koniec_z_iloscami_zapisuje_je_na_kartonie(leader_client):
    make_user('operator', barcode_id='W1')
    make_carton()
    start(leader_client, 'W1')

    r = end(leader_client, 'W1', categories={'textile': 6, 'sorting': 4})

    assert r.status_code == 200
    assert carton().get_scan_categories() == {'textile': 6, 'sorting': 4}


def test_ilosci_ze_skanu_trafiaja_do_statystyk_ogolnych(leader_client, acting_admin):
    make_user('operator', barcode_id='W1')
    logistat.process_import_rows([row('P1', 10)])
    start(leader_client, 'W1')
    end(leader_client, 'W1', categories={'textile': 6, 'sorting': 4})

    s = gstat()
    assert s.category_source == 'scan'
    assert amount(s, 'textile') == 6
    assert amount(s, 'sorting') == 4


def test_linia_sumuje_skany_z_wielu_paczek(leader_client, acting_admin):
    make_user('operator', barcode_id='W1')
    logistat.process_import_rows([row('P1', 10), row('P2', 10)])

    for pkg in ('P1', 'P2'):
        start(leader_client, 'W1', pkg)
        end(leader_client, 'W1', pkg, categories={'textile': 5})

    assert amount(gstat(), 'textile') == 10


def test_koniec_bez_ilosci_nie_przelacza_linii_na_scan(leader_client, acting_admin):
    """Zgodnosc wsteczna: stary klient nie wysyla `categories`."""
    make_user('operator', barcode_id='W1')
    logistat.process_import_rows([row('P1', 10)])
    start(leader_client, 'W1')

    assert end(leader_client, 'W1').status_code == 200
    assert gstat().category_source == 'manual'


# ── NAJWAZNIEJSZE: przeliczanie nie tyka linii recznych ─────────────────────

def _linia_z_recznymi_kategoriami():
    logistat.process_import_rows([row('B1', 10)])
    s = gstat()
    s.set_category_data({'textile': {'amount': 120, 'cost': 0.0}})
    s.category_source = 'manual'
    logistat.db.session.commit()
    return s


def test_import_nowego_kartonu_nie_zeruje_recznych_kategorii(acting_admin):
    _linia_z_recznymi_kategoriami()

    logistat.process_import_rows([row('B2', 5)])

    s = gstat()
    assert s.amounts == 15            # suma kartonow sie zaktualizowala
    assert amount(s, 'textile') == 120  # a reczne kategorie przetrwaly


def test_recompute_wprost_nie_zeruje_recznych_kategorii(acting_admin):
    _linia_z_recznymi_kategoriami()

    logistat.recompute_general_stat('UB-1', 'PL', ZIEL)
    logistat.db.session.commit()

    assert amount(gstat(), 'textile') == 120


def test_reczne_dodanie_paczki_nie_zeruje_recznych_kategorii(acting_admin):
    _linia_z_recznymi_kategoriami()

    logistat.process_import_rows([row('M1', 7, added_manually=True)])

    assert amount(gstat(), 'textile') == 120


def test_zmiana_grupy_paczki_nie_zeruje_recznych_kategorii(leader_client, acting_admin):
    _linia_z_recznymi_kategoriami()
    reczna = logistat.process_import_rows([row('M1', 7, added_manually=True)])
    karton = carton('M1')

    leader_client.put(f'/api/packages/{karton.id}', json={
        'barcode': 'M1', 'stueckzahl': 7, 'land': 'PL',
        'ziel_datum': ZIEL.isoformat(), 'uebergabe_nr': 'UB-2',
    })

    assert amount(gstat(), 'textile') == 120


# ── blokada recznej edycji linii zasilanych skanem ──────────────────────────

def test_linia_scan_odrzuca_reczna_edycje_kategorii(admin_client, acting_admin):
    make_user('operator', barcode_id='W1')
    logistat.process_import_rows([row('P1', 10)])
    start(admin_client, 'W1')
    end(admin_client, 'W1', categories={'textile': 6})

    r = admin_client.put(f'/api/general-stats/{gstat().id}',
                         json={'category_data': {'textile': {'amount': 999}}})

    assert r.status_code == 400
    assert amount(gstat(), 'textile') == 6


def test_linia_manual_dalej_pozwala_na_reczna_edycje(admin_client, acting_admin):
    _linia_z_recznymi_kategoriami()

    r = admin_client.put(f'/api/general-stats/{gstat().id}',
                         json={'category_data': {'textile': {'amount': 200}}})

    assert r.status_code == 200
    assert amount(gstat(), 'textile') == 200


def test_zolty_wiersz_double_rate_zostaje_reczny(admin_client, acting_admin):
    make_user('operator', barcode_id='W1')
    logistat.process_import_rows([row('P1', 10)])
    start(admin_client, 'W1')
    end(admin_client, 'W1', categories={'textile': 6})

    r = admin_client.put(f'/api/general-stats/{gstat().id}',
                         json={'double_rate_category_data': {'textile': {'amount': 3}}})

    assert r.status_code == 200
    assert gstat().get_double_rate_category_data()['textile']['amount'] == 3


# ── korekta pomylki przez lidera ────────────────────────────────────────────

def test_lider_poprawia_ilosci_takze_na_paczce_z_importu(leader_client, acting_admin):
    make_user('operator', barcode_id='W1')
    logistat.process_import_rows([row('P1', 10)])
    start(leader_client, 'W1')
    end(leader_client, 'W1', categories={'textile': 500})   # literowka

    r = leader_client.put(f'/api/packages/{carton().id}/categories',
                          json={'categories': {'textile': 50}})

    assert r.status_code == 200
    assert carton().get_scan_categories() == {'textile': 50}
    assert amount(gstat(), 'textile') == 50


def test_korekta_zostawia_slad_kto_zmienil(leader_client, leader, acting_admin):
    logistat.process_import_rows([row('P1', 10)])

    leader_client.put(f'/api/packages/{carton().id}/categories',
                      json={'categories': {'textile': 5}})

    assert carton().modified_by == leader.id
    assert carton().modified_at is not None


# ── walidacja ───────────────────────────────────────────────────────────────

def test_nieznana_kategoria_odrzucona(leader_client, acting_admin):
    logistat.process_import_rows([row('P1', 10)])

    r = leader_client.put(f'/api/packages/{carton().id}/categories',
                          json={'categories': {'nie_ma_takiej': 5}})

    assert r.status_code == 400


def test_ujemna_ilosc_odrzucona(leader_client, acting_admin):
    logistat.process_import_rows([row('P1', 10)])

    r = leader_client.put(f'/api/packages/{carton().id}/categories',
                          json={'categories': {'textile': -1}})

    assert r.status_code == 400


def test_nieliczbowa_ilosc_odrzucona(leader_client, acting_admin):
    logistat.process_import_rows([row('P1', 10)])

    r = leader_client.put(f'/api/packages/{carton().id}/categories',
                          json={'categories': {'textile': 'duzo'}})

    assert r.status_code == 400


def test_suma_kategorii_nie_musi_sie_zgadzac_ze_stueckzahl(leader_client, acting_admin):
    """Swiadoma decyzja: rozbieznosc nie blokuje pracy."""
    make_user('operator', barcode_id='W1')
    logistat.process_import_rows([row('P1', 10)])
    start(leader_client, 'W1')

    r = end(leader_client, 'W1', categories={'textile': 999})

    assert r.status_code == 200


# ── usunieta kategoria ──────────────────────────────────────────────────────

def test_carton_labeling_nie_istnieje_juz_w_systemie():
    assert 'carton_labeling' not in logistat.STAT_CATEGORIES
    assert 'carton_labeling' not in logistat.STAT_CATEGORY_LABELS


def test_historyczna_kategoria_nie_dolicza_sie_do_kosztu(acting_admin):
    """Stary wiersz moze miec w JSON-ie klucz usunietej kategorii."""
    logistat.process_import_rows([row('B1', 10)])
    s = gstat()
    s.set_category_data({'carton_labeling': {'amount': 500, 'cost': 0.0}})
    logistat.db.session.commit()

    d = gstat().to_dict()

    assert 'carton_labeling' not in d['category_data']
    assert d['total_cost'] == 0.0


# ── pokrycie skanami ────────────────────────────────────────────────────────

def test_api_pokazuje_ile_paczek_zeskanowano(admin_client, acting_admin):
    make_user('operator', barcode_id='W1')
    logistat.process_import_rows([row('P1', 10), row('P2', 10), row('P3', 10)])
    start(admin_client, 'W1')
    end(admin_client, 'W1', categories={'textile': 5})

    linia = admin_client.get('/api/general-stats').get_json()[0]

    assert linia['scanned_cartons'] == 1
    assert linia['total_cartons'] == 3


# ── ekrany ──────────────────────────────────────────────────────────────────

def test_ekran_skanowania_ma_pola_wszystkich_kategorii(leader_client):
    html = leader_client.get('/scan-paczki').get_data(as_text=True)

    for kat in logistat.STAT_CATEGORIES:
        assert f'id="qty-{kat}"' in html
    assert 'end-qty-stueckzahl' in html          # ilosc sztuk pokazana pracownikowi
    assert 'Labelling one' in html               # nowe etykiety
    assert 'Carton labeling' not in html


def test_paczki_maja_przycisk_korekty_ilosci(leader_client, acting_admin):
    logistat.process_import_rows([row('P1', 10)])

    html = leader_client.get('/paczki').get_data(as_text=True)

    assert 'otworzQty(this)' in html
    assert '✎ Ilości' in html


def test_statystyki_blokuja_pole_linii_ze_skanu(admin_client, acting_admin):
    make_user('operator', barcode_id='W1')
    logistat.process_import_rows([row('P1', 10)])
    start(admin_client, 'W1')
    end(admin_client, 'W1', categories={'textile': 6})

    html = admin_client.get('/general-stats').get_data(as_text=True)

    assert 'cat-amount locked' in html           # pole ilosci tylko do odczytu
    assert '🔒 1/1' in html                      # licznik pokrycia skanami


def test_statystyki_zostawiaja_edytowalna_linie_reczna(admin_client, acting_admin):
    _linia_z_recznymi_kategoriami()

    html = admin_client.get('/general-stats').get_data(as_text=True)

    assert 'cat-amount locked' not in html
    assert 'cat-amount inline-input' in html


# ── stara linia z recznymi ilosciami nie daje sie nadpisac skanem ────────────

def test_skan_nie_kasuje_recznych_ilosci_starej_linii(leader_client, acting_admin):
    """Pierwszy zeskanowany karton nie moze zastapic calego rozliczenia."""
    _linia_z_recznymi_kategoriami()          # manual, textile=120
    make_user('operator', barcode_id='W1')

    start(leader_client, 'W1', 'B1')
    r = end(leader_client, 'W1', 'B1', categories={'textile': 6})

    assert r.status_code == 200
    s = gstat()
    assert s.category_source == 'manual'     # linia sie NIE przelaczyla
    assert amount(s, 'textile') == 120       # reczne rozliczenie nietkniete
    # ...a ilosci ze skanu i tak sa zapisane na kartonie — nic nie zginelo
    assert carton('B1').get_scan_categories() == {'textile': 6}


def test_admin_moze_swiadomie_przelaczyc_linie_na_skany(admin_client, acting_admin):
    _linia_z_recznymi_kategoriami()
    make_user('operator', barcode_id='W1')
    start(admin_client, 'W1', 'B1')
    end(admin_client, 'W1', 'B1', categories={'textile': 6})

    r = admin_client.post(f'/api/general-stats/{gstat().id}/use-scan')

    assert r.status_code == 200
    s = gstat()
    assert s.category_source == 'scan'
    assert amount(s, 'textile') == 6


def test_swieza_linia_z_importu_przelacza_sie_przy_pierwszym_skanie(leader_client, acting_admin):
    """Pusta linia nie ma czego stracic — tu przelaczenie ma byc automatyczne."""
    logistat.process_import_rows([row('P1', 10)])
    make_user('operator', barcode_id='W1')

    start(leader_client, 'W1')
    end(leader_client, 'W1', categories={'textile': 6})

    assert gstat().category_source == 'scan'
    assert amount(gstat(), 'textile') == 6
