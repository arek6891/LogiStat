"""Filtry na ekranie „Paczki (dane)" + odblokowanie zablokowanej paczki.

Domyslnie widac tylko paczki niezrobione („zrobiona" = ma `scan_end_at`, ta sama
definicja co `finished` na /scan-package). Filtr bledow liczy sie w Pythonie,
bo ilosci ze skanu siedza w JSON-ie w kolumnie tekstowej — SQL ich nie widzi.
"""
from datetime import date, datetime, timedelta

import app as logistat
from conftest import make_user

ZIEL = date(2026, 9, 10)


def karton(barcode, stueckzahl=10, **kw):
    kw.setdefault('ziel_datum', ZIEL)
    kw.setdefault('uebergabe_nr', 'UB-1')
    c = logistat.ImportedCarton(barcode=barcode, land='PL', stueckzahl=stueckzahl, **kw)
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

    widoczne = kody(leader_client.get(
        f'/paczki?pokaz_zrobione=1&date_from={ZIEL}&date_to={ZIEL}'))

    assert {'WTOKU', 'GOTOWA'} <= widoczne


def test_pokaz_zrobione_bez_daty_nie_dziala(leader_client):
    """Bez zakresu dat widok objalby cala historie — zakres jest wymagany."""
    karton('WTOKU')
    karton('GOTOWA', scan_end_at=datetime.utcnow())

    odpowiedz = leader_client.get('/paczki?pokaz_zrobione=1')
    widoczne = kody(odpowiedz)

    assert 'WTOKU' in widoczne
    assert 'GOTOWA' not in widoczne
    assert 'wymaga zakresu dat' in odpowiedz.get_data(as_text=True)


def test_pokaz_zrobione_wystarczy_jedna_granica_daty(leader_client):
    karton('GOTOWA', scan_end_at=datetime.utcnow())

    widoczne = kody(leader_client.get(f'/paczki?pokaz_zrobione=1&date_from={ZIEL}'))

    assert 'GOTOWA' in widoczne


def test_bez_wyboru_osoby_widac_paczki_wszystkich(leader_client):
    """Pusty filtr pracownika = wszyscy, takze przy „pokaz zrobione" z data."""
    a = make_user('operator', username='op-x')
    b = make_user('operator', username='op-y')
    karton('OD-A', scan_end_by=a.id, scan_end_at=datetime.utcnow())
    karton('OD-B', scan_end_by=b.id, scan_end_at=datetime.utcnow())

    widoczne = kody(leader_client.get(
        f'/paczki?pokaz_zrobione=1&date_from={ZIEL}&date_to={ZIEL}'))

    assert {'OD-A', 'OD-B'} <= widoczne


# ── filtr po typie daty (Ziel-Datum / import / start / koniec) ───────────────

def test_domyslny_typ_daty_to_ziel_datum(leader_client):
    karton('W-ZAKRESIE')
    karton('POZA-ZAKRESEM', ziel_datum=date(2026, 1, 1))

    widoczne = kody(leader_client.get(f'/paczki?date_from={ZIEL}&date_to={ZIEL}'))

    assert 'W-ZAKRESIE' in widoczne
    assert 'POZA-ZAKRESEM' not in widoczne


def test_filtr_po_dacie_importu(leader_client):
    dzis = logistat.local_today()
    karton('DZIS', imported_at=datetime.utcnow())
    karton('DAWNO', imported_at=datetime(2026, 1, 2, 12, 0))

    widoczne = kody(leader_client.get(
        f'/paczki?date_typ=import&date_from={dzis}&date_to={dzis}'))

    assert 'DZIS' in widoczne
    assert 'DAWNO' not in widoczne


def test_filtr_po_dacie_startu(leader_client):
    dzis = logistat.local_today()
    karton('START-DZIS', scan_start_at=datetime.utcnow())
    karton('START-DAWNO', scan_start_at=datetime(2026, 1, 2, 12, 0))

    widoczne = kody(leader_client.get(
        f'/paczki?date_typ=start&date_from={dzis}&date_to={dzis}'))

    assert 'START-DZIS' in widoczne
    assert 'START-DAWNO' not in widoczne


def test_filtr_po_dacie_konca_zdejmuje_domyslne_niezrobione(leader_client):
    """Sam filtr po koncu wybiera tylko zakonczone — domyslne „tylko
    niezrobione" dawaloby zawsze pusta liste, wiec musi zostac zdjete."""
    dzis = logistat.local_today()
    karton('KONIEC-DZIS', scan_end_at=datetime.utcnow())
    karton('NIEZROBIONA')

    widoczne = kody(leader_client.get(
        f'/paczki?date_typ=koniec&date_from={dzis}&date_to={dzis}'))

    assert 'KONIEC-DZIS' in widoczne
    assert 'NIEZROBIONA' not in widoczne


def test_filtr_po_koncu_lapie_paczki_wszystkich_mimo_obcego_ziel_datum(leader_client):
    """Regresja zgloszonego objawu: przy filtrze po Ziel-Datum z widoku znikaly
    paczki, ktorych `ziel_datum` nie pokrywa sie z dniem skanowania — wygladalo
    to, jakby filtr pracownika gubil ludzi. Filtr po dacie konca ma je pokazac,
    dla wszystkich pracownikow naraz (pusty filtr osoby)."""
    dzis = logistat.local_today()
    a = make_user('operator', username='op-p')
    b = make_user('operator', username='op-q')
    # Ziel-Datum daleko poza zakresem, ale zakonczone dzisiaj.
    karton('SKAN-A', ziel_datum=date(2026, 1, 5),
           scan_end_by=a.id, scan_end_at=datetime.utcnow())
    karton('SKAN-B', ziel_datum=date(2026, 2, 9),
           scan_end_by=b.id, scan_end_at=datetime.utcnow())

    po_ziel = kody(leader_client.get(
        f'/paczki?pokaz_zrobione=1&date_from={dzis}&date_to={dzis}'))
    po_koncu = kody(leader_client.get(
        f'/paczki?date_typ=koniec&date_from={dzis}&date_to={dzis}'))

    assert not {'SKAN-A', 'SKAN-B'} & po_ziel, 'Ziel-Datum poza zakresem — maja wypasc'
    assert {'SKAN-A', 'SKAN-B'} <= po_koncu, 'Filtr po koncu ma pokazac oba, bez wyboru osoby'


def test_gorna_granica_daty_nie_lapie_nastepnej_doby(leader_client):
    """Granica jest polotwarta: paczka z poczatku kolejnej doby lokalnej
    nie moze wpasc do zakresu konczacego sie dzien wczesniej."""
    dzien = date(2026, 6, 15)
    poczatek_nastepnej = logistat.local_day_bounds(dzien + timedelta(days=1))[0]
    karton('W-DNIU', scan_end_at=logistat.local_day_bounds(dzien)[0])
    karton('NASTEPNY-DZIEN', scan_end_at=poczatek_nastepnej)

    widoczne = kody(leader_client.get(
        f'/paczki?date_typ=koniec&date_from={dzien}&date_to={dzien}'))

    assert 'W-DNIU' in widoczne
    assert 'NASTEPNY-DZIEN' not in widoczne


def test_nieznany_typ_daty_wraca_do_ziel_datum(leader_client):
    karton('W-ZAKRESIE')
    karton('POZA-ZAKRESEM', ziel_datum=date(2026, 1, 1))

    widoczne = kody(leader_client.get(
        f'/paczki?date_typ=bzdura&date_from={ZIEL}&date_to={ZIEL}'))

    assert 'W-ZAKRESIE' in widoczne
    assert 'POZA-ZAKRESEM' not in widoczne


def test_stronicowanie_zachowuje_typ_daty(leader_client):
    for i in range(logistat.PACZKI_NA_STRONE + 5):
        karton(f'STRONA-{i}')

    html = leader_client.get(f'/paczki?date_typ=ziel&date_from={ZIEL}').get_data(as_text=True)

    assert 'date_typ=ziel' in html


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
