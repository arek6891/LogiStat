"""Filtry na ekranie „Paczki (dane)" + odblokowanie zablokowanej paczki.

Domyslnie widac tylko paczki niezrobione („zrobiona" = ma `scan_end_at`, ta sama
definicja co `finished` na /scan-package). Filtr bledow liczy sie w Pythonie,
bo ilosci ze skanu siedza w JSON-ie w kolumnie tekstowej — SQL ich nie widzi.
"""
from datetime import date, datetime

import app as logistat
from conftest import make_user

ZIEL = date(2026, 9, 10)


def karton(barcode, stueckzahl=10, **kw):
    c = logistat.ImportedCarton(barcode=barcode, land='PL', stueckzahl=stueckzahl,
                                ziel_datum=ZIEL, uebergabe_nr='UB-1', **kw)
    logistat.db.session.add(c)
    logistat.db.session.commit()
    return c


def kody(odpowiedz):
    """Barcody widoczne na wyrenderowanej stronie."""
    html = odpowiedz.get_data(as_text=True)
    return {c.barcode for c in logistat.ImportedCarton.query.all() if c.barcode in html}


# ── widok domyslny ───────────────────────────────────────────────────────────

def test_domyslnie_widac_tylko_niezrobione(leader_client):
    karton('WTOKU')
    karton('GOTOWA', scan_end_at=datetime.utcnow())

    widoczne = kody(leader_client.get('/paczki'))

    assert 'WTOKU' in widoczne
    assert 'GOTOWA' not in widoczne


def test_pokaz_zrobione_dokłada_zakonczone(leader_client):
    karton('WTOKU')
    karton('GOTOWA', scan_end_at=datetime.utcnow())

    widoczne = kody(leader_client.get('/paczki?pokaz_zrobione=1'))

    assert {'WTOKU', 'GOTOWA'} <= widoczne


# ── filtr po osobie ──────────────────────────────────────────────────────────

def test_filtr_po_osobie_lapie_start_koniec_i_przejecie(leader_client):
    a = make_user('operator', username='op-a')
    b = make_user('operator', username='op-b')
    karton('START-A', scan_start_by=a.id, scan_start_at=datetime.utcnow())
    karton('KONIEC-A', scan_end_by=a.id)
    karton('PRZEJETA-A', processed_by=a.id)
    karton('OBCA-B', scan_start_by=b.id, scan_start_at=datetime.utcnow())

    widoczne = kody(leader_client.get(f'/paczki?osoba={a.id}&pokaz_zrobione=1'))

    assert {'START-A', 'KONIEC-A', 'PRZEJETA-A'} <= widoczne
    assert 'OBCA-B' not in widoczne


def test_filtr_double_rate(leader_client):
    karton('DR', double_rate=True)
    karton('ZWYKLA', double_rate=False)

    widoczne = kody(leader_client.get('/paczki?double_rate=1'))

    assert 'DR' in widoczne
    assert 'ZWYKLA' not in widoczne


# ── filtr bledow ─────────────────────────────────────────────────────────────

def test_blad_paczka_rozpoczeta_bez_konca(flask_app):
    c = karton('WISI', scan_start_at=datetime.utcnow())

    bledy = logistat.bledy_paczki(c)

    assert any('nie zakończona' in b for b in bledy)


def test_paczka_zamknieta_nie_jest_bledem(flask_app):
    c = karton('OK', scan_start_at=datetime.utcnow(), scan_end_at=datetime.utcnow())

    assert logistat.bledy_paczki(c) == []


def test_ilosc_ponad_10_procent_to_blad(flask_app):
    c = karton('ZA_DUZO', stueckzahl=10, scan_end_at=datetime.utcnow())
    c.set_scan_categories({'labelling_on': 12})       # +20%
    logistat.db.session.commit()

    bledy = logistat.bledy_paczki(c)

    assert any('labelling' in b.lower() for b in bledy)


def test_ilosc_w_granicy_10_procent_nie_jest_bledem(flask_app):
    c = karton('GRANICA', stueckzahl=10, scan_end_at=datetime.utcnow())
    c.set_scan_categories({'labelling_on': 11})       # rowno +10%
    logistat.db.session.commit()

    assert logistat.bledy_paczki(c) == []


def test_ilosc_ponizej_stueckzahl_nie_jest_bledem(flask_app):
    c = karton('MNIEJ', stueckzahl=100, scan_end_at=datetime.utcnow())
    c.set_scan_categories({'labelling_on': 40})
    logistat.db.session.commit()

    assert logistat.bledy_paczki(c) == []


def test_filtr_bledow_pokazuje_takze_zakonczone(leader_client):
    """Blad ilosci wystepuje na paczce zrobionej — filtr musi ja pokazac."""
    c = karton('ZLA_ILOSC', stueckzahl=5, scan_end_at=datetime.utcnow())
    c.set_scan_categories({'labelling_on': 50})
    logistat.db.session.commit()
    karton('CZYSTA')

    widoczne = kody(leader_client.get('/paczki?bledy=1'))

    assert 'ZLA_ILOSC' in widoczne
    assert 'CZYSTA' not in widoczne


def test_stronicowanie_filtra_bledow_tnie_wyniki(leader_client):
    for i in range(logistat.PACZKI_NA_STRONE + 5):
        karton(f'WISI-{i:03d}', scan_start_at=datetime.utcnow())

    r1 = leader_client.get('/paczki?bledy=1')
    r2 = leader_client.get('/paczki?bledy=1&page=2')

    assert len(kody(r1)) == logistat.PACZKI_NA_STRONE
    assert len(kody(r2)) == 5


# ── odblokowanie ─────────────────────────────────────────────────────────────

def test_odblokowanie_kasuje_start(leader_client):
    w = make_user('operator', barcode_id='W1')
    c = karton('ZABLOKOWANA', scan_start_at=datetime.utcnow(), scan_start_by=w.id)

    r = leader_client.post(f'/api/packages/{c.id}/unlock-scan')

    assert r.status_code == 200
    odswiezona = logistat.ImportedCarton.query.filter_by(barcode='ZABLOKOWANA').first()
    assert odswiezona.scan_start_at is None
    assert odswiezona.scan_start_by is None
    assert odswiezona.modified_by is not None


def test_po_odblokowaniu_inny_pracownik_moze_zaczac(leader_client):
    make_user('operator', barcode_id='W1')
    make_user('operator', barcode_id='W2')
    c = karton('P1')
    leader_client.post('/api/package-time/start',
                       json={'employee_barcode': 'W1', 'package_barcode': 'P1'})
    zajeta = leader_client.post('/api/package-time/start',
                                json={'employee_barcode': 'W2', 'package_barcode': 'P1'})
    assert zajeta.status_code == 409

    leader_client.post(f'/api/packages/{c.id}/unlock-scan')
    po = leader_client.post('/api/package-time/start',
                            json={'employee_barcode': 'W2', 'package_barcode': 'P1'})

    assert po.status_code == 200


def test_zakonczonej_paczki_nie_odblokujemy(leader_client):
    c = karton('SKONCZONA', scan_start_at=datetime.utcnow(), scan_end_at=datetime.utcnow())

    r = leader_client.post(f'/api/packages/{c.id}/unlock-scan')

    assert r.status_code == 409


def test_nierozpoczetej_paczki_nie_ma_co_odblokowywac(leader_client):
    c = karton('NOWA')

    r = leader_client.post(f'/api/packages/{c.id}/unlock-scan')

    assert r.status_code == 400


def test_operator_nie_odblokuje(client):
    c = karton('P1', scan_start_at=datetime.utcnow())

    r = client.post(f'/api/packages/{c.id}/unlock-scan')

    assert r.status_code in (302, 401, 403)


def test_widok_domyslny_pokazuje_blad_i_przycisk_odblokowania(leader_client):
    """Sciezka lidera: zablokowana paczka musi byc widoczna BEZ wlaczania filtrow."""
    w = make_user('operator', username='op-x')
    karton('WISZACA', scan_start_at=datetime.utcnow(), scan_start_by=w.id)

    html = leader_client.get('/paczki').get_data(as_text=True)

    assert 'WISZACA' in html
    assert 'nie zakończona' in html, 'badge błędu'
    assert 'Odblokuj' in html, 'przycisk odblokowania'
