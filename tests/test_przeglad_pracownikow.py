"""Przeglad ogolny pracownikow na ekranie Statystyki (`/api/stats/overview`).

Wydajnosc liczy sie z ZAKONCZONYCH PACZEK, nie z `DailyStat` — wpis ilosci jest
uzupelniany sporadycznie, a skan paczek leci przy kazdej sztuce. Odniesieniem
jest mediana zespolu z okresu, nie zadana z gory norma (takiej system nie ma).
"""
from datetime import date, datetime, timedelta

import app as logistat
from conftest import make_user

ZIEL = date(2026, 9, 10)


def paczka(barcode, kto, sztuk, start, koniec):
    c = logistat.ImportedCarton(barcode=barcode, land='PL', stueckzahl=sztuk,
                                ziel_datum=ZIEL, uebergabe_nr='UB-1',
                                scan_start_at=start, scan_start_by=kto.id,
                                scan_end_at=koniec, scan_end_by=kto.id)
    logistat.db.session.add(c)
    logistat.db.session.commit()
    return c


def godziny_pracy(kto, ile_paczek, sztuk_na_paczke, minut_na_paczke, dzien=None):
    """`ile_paczek` paczek jedna po drugiej, bez nakladania sie."""
    dzien = dzien or logistat.local_today()
    baza = logistat.local_day_bounds(dzien)[0] + timedelta(hours=1)
    for i in range(ile_paczek):
        start = baza + timedelta(minutes=i * minut_na_paczke * 2)
        # Dzien w barcodzie, bo ten sam pracownik bywa obsadzany w kilku dniach
        # w jednym tescie, a barcode jest unikalny w calej tabeli.
        paczka(f'{kto.username}-{dzien:%m%d}-{i}', kto, sztuk_na_paczke,
               start, start + timedelta(minutes=minut_na_paczke))


def przeglad(client, **params):
    from urllib.parse import urlencode
    r = client.get('/api/stats/overview' + ('?' + urlencode(params) if params else ''))
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def wiersz(dane, nazwa):
    for r in dane['pracownicy'] + dane['za_malo_danych']:
        if r['display_name'] == nazwa:
            return r
    return None


# ── podstawowe liczenie ──────────────────────────────────────────────────────

def test_sztuki_na_godzine(leader_client):
    a = make_user('operator', username='szybka', display_name='Szybka')
    godziny_pracy(a, ile_paczek=4, sztuk_na_paczke=30, minut_na_paczke=30)

    r = wiersz(przeglad(leader_client), 'Szybka')

    assert r['paczek'] == 4
    assert r['sztuk'] == 120
    assert r['godzin'] == 2.0          # 4 x 30 min
    assert r['szt_h'] == 60.0          # 120 szt / 2 h


def test_ranking_sortuje_od_najlepszego(leader_client):
    a = make_user('operator', username='a', display_name='Ala')
    b = make_user('operator', username='b', display_name='Basia')
    godziny_pracy(a, 3, sztuk_na_paczke=100, minut_na_paczke=30)   # 200 szt/h
    godziny_pracy(b, 3, sztuk_na_paczke=25,  minut_na_paczke=30)   # 50 szt/h

    nazwy = [r['display_name'] for r in przeglad(leader_client)['pracownicy']]

    assert nazwy == ['Ala', 'Basia']


# ── nakladajace sie paczki ───────────────────────────────────────────────────

def test_nakladajace_sie_paczki_nie_licza_czasu_dwa_razy(leader_client):
    """Nic w schemacie nie zabrania trzymania dwoch paczek otwartych naraz.
    Suma dlugosci liczylaby ten sam kwadrans dwa razy i zanizala szt./h."""
    a = make_user('operator', username='rownolegle', display_name='Równolegle')
    baza = logistat.local_day_bounds(logistat.local_today())[0] + timedelta(hours=1)
    # Dwie paczki po godzinie, calkowicie na sobie -> 1 h pracy, nie 2 h.
    paczka('R-1', a, 50, baza, baza + timedelta(hours=1))
    paczka('R-2', a, 50, baza, baza + timedelta(hours=1))
    paczka('R-3', a, 50, baza + timedelta(hours=2), baza + timedelta(hours=3))

    r = wiersz(przeglad(leader_client), 'Równolegle')

    assert r['godzin'] == 2.0, 'zlaczone okresy: 1 h + 1 h, nie 3 h'
    assert r['szt_h'] == 75.0          # 150 szt / 2 h


# ── prog minimalnej liczby paczek ────────────────────────────────────────────

def test_ponizej_progu_ladujemy_w_za_malo_danych(leader_client):
    duzo = make_user('operator', username='duzo', display_name='Duzo')
    malo = make_user('operator', username='malo', display_name='Malo')
    godziny_pracy(duzo, 5, 40, 30)
    godziny_pracy(malo, 1, 999, 1)     # jedna paczka -> ekstremalne szt./h

    dane = przeglad(leader_client)

    assert [r['display_name'] for r in dane['pracownicy']] == ['Duzo']
    assert [r['display_name'] for r in dane['za_malo_danych']] == ['Malo']


def test_za_malo_danych_nie_znika_ze_statystyk(leader_client):
    """Ta osoba pracowala — ukrycie jej sugerowaloby, ze nie."""
    malo = make_user('operator', username='malo', display_name='Malo')
    godziny_pracy(malo, 1, 60, 30)

    r = wiersz(przeglad(leader_client), 'Malo')

    assert r is not None
    assert r['paczek'] == 1 and r['sztuk'] == 60
    assert r['ocena'] is None, 'bez oceny, ale widoczna'


def test_prog_minimalny_jest_konfigurowalny(leader_client):
    logistat.set_setting('min_packages_rank', 1)
    logistat.db.session.commit()
    malo = make_user('operator', username='malo', display_name='Malo')
    godziny_pracy(malo, 1, 60, 30)

    dane = przeglad(leader_client)

    assert [r['display_name'] for r in dane['pracownicy']] == ['Malo']
    assert dane['za_malo_danych'] == []


# ── ocena wzgledem mediany ───────────────────────────────────────────────────

def test_mediana_a_nie_srednia(leader_client):
    """Jedna osoba z ekstremalnym wynikiem nie moze przesunac poprzeczki reszcie."""
    for nazwa, sztuk in (('A', 50), ('B', 50), ('C', 5000)):
        u = make_user('operator', username=nazwa.lower(), display_name=nazwa)
        godziny_pracy(u, 3, sztuk_na_paczke=sztuk, minut_na_paczke=30)

    dane = przeglad(leader_client)

    # Mediana z (100, 100, 10000) szt/h = 100, srednia bylaby ~3400.
    assert dane['mediana_szt_h'] == 100.0


def test_oceny_dobra_ok_slaba(leader_client):
    # progi domyslne: dobra >= 110% mediany, slaba <= 90%
    for nazwa, sztuk in (('Srednia1', 50), ('Srednia2', 50), ('Lepsza', 100), ('Slabsza', 20)):
        u = make_user('operator', username=nazwa.lower(), display_name=nazwa)
        godziny_pracy(u, 3, sztuk_na_paczke=sztuk, minut_na_paczke=30)

    dane = przeglad(leader_client)
    oceny = {r['display_name']: r['ocena'] for r in dane['pracownicy']}

    assert oceny['Lepsza'] == 'dobra'
    assert oceny['Slabsza'] == 'slaba'
    assert oceny['Srednia1'] == 'ok'


def test_progi_oceny_sa_konfigurowalne(leader_client):
    logistat.set_setting('norm_good_pct', 250)
    logistat.db.session.commit()
    for nazwa, sztuk in (('A', 50), ('B', 50), ('Lepsza', 100)):
        u = make_user('operator', username=nazwa.lower(), display_name=nazwa)
        godziny_pracy(u, 3, sztuk_na_paczke=sztuk, minut_na_paczke=30)

    dane = przeglad(leader_client)
    oceny = {r['display_name']: r['ocena'] for r in dane['pracownicy']}

    # Mediana (100, 100, 200) = 100, wiec „Lepsza" ma 200% — przy progu 250 to
    # juz za malo na „dobra".
    assert wiersz(dane, 'Lepsza')['proc_mediany'] == 200
    assert oceny['Lepsza'] == 'ok'


def test_prog_dobrego_wyniku_jest_domkniety(leader_client):
    """Rowno na progu = juz „dobra" (`>=`), nie „ok"."""
    logistat.set_setting('norm_good_pct', 200)
    logistat.db.session.commit()
    for nazwa, sztuk in (('A', 50), ('B', 50), ('Rowno', 100)):
        u = make_user('operator', username=nazwa.lower(), display_name=nazwa)
        godziny_pracy(u, 3, sztuk_na_paczke=sztuk, minut_na_paczke=30)

    dane = przeglad(leader_client)

    assert wiersz(dane, 'Rowno')['proc_mediany'] == 200
    assert wiersz(dane, 'Rowno')['ocena'] == 'dobra'


# ── zakres dat ───────────────────────────────────────────────────────────────

def test_filtr_dat_obcina_okres(leader_client):
    a = make_user('operator', username='a', display_name='Ala')
    wczoraj = logistat.local_today() - timedelta(days=1)
    godziny_pracy(a, 3, 40, 30)                      # dzis
    godziny_pracy(a, 3, 40, 30, dzien=wczoraj)

    dzis = logistat.local_today().isoformat()
    tylko_dzis = wiersz(przeglad(leader_client, date_from=dzis, date_to=dzis), 'Ala')

    assert tylko_dzis['paczek'] == 3, 'wczorajsze paczki poza zakresem'


def test_gorna_granica_nie_lapie_nastepnej_doby(leader_client):
    a = make_user('operator', username='a', display_name='Ala')
    dzien = date(2026, 6, 15)
    godziny_pracy(a, 3, 40, 30, dzien=dzien)
    godziny_pracy(a, 3, 40, 30, dzien=dzien + timedelta(days=1))

    r = wiersz(przeglad(leader_client, date_from=str(dzien), date_to=str(dzien)), 'Ala')

    assert r['paczek'] == 3


# ── przypadki brzegowe ───────────────────────────────────────────────────────

def test_brak_danych_nie_wywala(leader_client):
    dane = przeglad(leader_client)

    assert dane['pracownicy'] == []
    assert dane['mediana_szt_h'] is None
    assert dane['podsumowanie']['paczek'] == 0


def test_paczka_bez_startu_liczy_sztuki_ale_nie_czas(leader_client):
    a = make_user('operator', username='a', display_name='Ala')
    c = logistat.ImportedCarton(barcode='BEZ-STARTU', land='PL', stueckzahl=10,
                                ziel_datum=ZIEL, uebergabe_nr='UB-1',
                                scan_end_at=datetime.utcnow(), scan_end_by=a.id)
    logistat.db.session.add(c)
    logistat.db.session.commit()

    r = wiersz(przeglad(leader_client), 'Ala')

    assert r['sztuk'] == 10
    assert r['godzin'] == 0.0
    assert r['szt_h'] is None, 'bez zmierzonego czasu nie udajemy zera'
    assert r in przeglad(leader_client)['za_malo_danych']


def test_zerowy_czas_nie_dzieli_przez_zero(leader_client):
    """Paczka zaczeta i zakonczona w tej samej sekundzie."""
    a = make_user('operator', username='a', display_name='Ala')
    t = logistat.local_day_bounds(logistat.local_today())[0] + timedelta(hours=1)
    for i in range(3):
        paczka(f'ZERO-{i}', a, 10, t, t)

    r = wiersz(przeglad(leader_client), 'Ala')

    assert r['szt_h'] is None
    assert r['ocena'] is None


def test_zdezaktywowana_osoba_jest_widoczna_i_oznaczona(leader_client):
    """Soft-delete nie kasuje jej pracy z sum, ale ekran musi dac znac, ze jej
    juz nie ma — inaczej lider planuje rozmowe z kims, kto odszedl."""
    a = make_user('operator', username='byla', display_name='Byla')
    godziny_pracy(a, 4, 40, 30)
    a.is_active_user = False
    logistat.db.session.commit()

    r = wiersz(przeglad(leader_client), 'Byla')

    assert r is not None, 'jej paczki nadal licza sie do sum'
    assert r['is_active_user'] is False, 'ekran ma czym oznaczyc plakietke'


def test_szablon_oznacza_nieaktywnych(leader_client):
    html = leader_client.get('/stats').get_data(as_text=True)

    assert 'plakietkaNieaktywna' in html, 'plakietka musi byc renderowana'
    assert 'is_active_user' in html


# ── cel wpisany przez lidera ─────────────────────────────────────────────────

def ustaw_cel(client, wartosc):
    return client.put('/api/stats/target', json={'target_szt_h': wartosc})


def test_bez_celu_kolumny_celu_sa_puste(leader_client):
    a = make_user('operator', username='a', display_name='Ala')
    godziny_pracy(a, 3, 50, 30)

    dane = przeglad(leader_client)

    assert dane['cel_szt_h'] is None
    assert dane['spelnia_cel'] is None
    assert wiersz(dane, 'Ala')['proc_celu'] is None
    assert wiersz(dane, 'Ala')['ocena_celu'] is None


def test_cel_daje_druga_statystyke_obok_mediany(leader_client):
    """Mediana zostaje bez zmian — cel to DODATKOWA kolumna, nie zamiennik."""
    for nazwa, sztuk in (('A', 50), ('B', 50), ('Lepsza', 100)):
        u = make_user('operator', username=nazwa.lower(), display_name=nazwa)
        godziny_pracy(u, 3, sztuk_na_paczke=sztuk, minut_na_paczke=30)
    ustaw_cel(leader_client, 200)                  # mediana zespolu = 100 szt/h

    dane = przeglad(leader_client)
    lepsza = wiersz(dane, 'Lepsza')
    a = wiersz(dane, 'A')

    assert dane['cel_szt_h'] == 200
    assert dane['mediana_szt_h'] == 100.0, 'mediana liczona jak dotad'
    assert lepsza['proc_mediany'] == 200 and lepsza['proc_celu'] == 100
    assert a['proc_mediany'] == 100 and a['proc_celu'] == 50


def test_ocena_celu_jest_dwustanowa(leader_client):
    """Cel to poprzeczka: rowno 100% = spelnia (a nie „tylko ok", jak przy
    pasmach wokol mediany)."""
    for nazwa, sztuk in (('A', 50), ('B', 50), ('Rowno', 100)):
        u = make_user('operator', username=nazwa.lower(), display_name=nazwa)
        godziny_pracy(u, 3, sztuk_na_paczke=sztuk, minut_na_paczke=30)
    ustaw_cel(leader_client, 200)

    dane = przeglad(leader_client)

    assert wiersz(dane, 'Rowno')['ocena_celu'] == 'spelnia'
    assert wiersz(dane, 'A')['ocena_celu'] == 'ponizej'
    assert dane['spelnia_cel'] == 1


def test_cel_zero_wylacza_kolumne(leader_client):
    a = make_user('operator', username='a', display_name='Ala')
    godziny_pracy(a, 3, 50, 30)
    ustaw_cel(leader_client, 300)
    assert przeglad(leader_client)['cel_szt_h'] == 300

    ustaw_cel(leader_client, 0)

    dane = przeglad(leader_client)
    assert dane['cel_szt_h'] is None, '0 znaczy „nie ustawiono", nie „cel = 0"'
    assert wiersz(dane, 'Ala')['proc_celu'] is None, 'zadnego dzielenia przez zero'


def test_cel_bez_nikogo_w_rankingu_nie_zglasza_kompletu(leader_client):
    """„0 / 0" czytaloby sie jak komplet spelniajacych — a nikogo nie zmierzono."""
    malo = make_user('operator', username='malo', display_name='Malo')
    godziny_pracy(malo, 1, 60, 30)                 # ponizej progu 3 paczek
    ustaw_cel(leader_client, 200)

    dane = przeglad(leader_client)

    assert dane['cel_szt_h'] == 200
    assert dane['pracownicy'] == []
    assert dane['spelnia_cel'] is None


def test_lider_moze_ustawic_cel(leader_client):
    r = ustaw_cel(leader_client, 250)

    assert r.status_code == 200
    assert r.get_json()['target_szt_h'] == 250


def test_operator_nie_ustawi_celu(client):
    r = ustaw_cel(client, 250)

    assert r.status_code in (302, 401, 403)


def test_cel_odrzuca_smieci(leader_client):
    assert ustaw_cel(leader_client, 'duzo').status_code == 400
    assert ustaw_cel(leader_client, -5).status_code == 400
    assert leader_client.put('/api/stats/target', json={}).status_code == 400


def test_endpoint_celu_nie_rusza_innych_ustawien(leader_client):
    """Lider dostal zapis do JEDNEGO klucza, nie do calych ustawien."""
    przed = logistat.get_setting_int('max_work_minutes', 660)

    leader_client.put('/api/stats/target',
                      json={'target_szt_h': 100, 'max_work_minutes': 1})

    assert logistat.get_setting_int('max_work_minutes', 660) == przed


# ── skok do paczek zakonczonych przez osobe ──────────────────────────────────

def test_link_do_paczek_pokazuje_paczki_tej_osoby(leader_client):
    """Ekran linkuje do /paczki?osoba=..&date_typ=koniec&daty — sprawdzamy, ze
    taki adres faktycznie zwraca jej zakonczone paczki."""
    a = make_user('operator', username='ala', display_name='Ala')
    b = make_user('operator', username='basia', display_name='Basia')
    dzis = logistat.local_today()
    godziny_pracy(a, 3, 40, 30, dzien=dzis)
    godziny_pracy(b, 3, 40, 30, dzien=dzis)

    html = leader_client.get(
        f'/paczki?osoba={a.id}&date_typ=koniec&date_from={dzis}&date_to={dzis}'
    ).get_data(as_text=True)

    # Pelne barcody, nie prefiks: `'ala-' in html` trafiloby tez w atrybut albo
    # klase i test przechodzilby niezaleznie od dzialania filtra.
    widoczne = {c.barcode for c in logistat.ImportedCarton.query.all()
                if c.barcode in html}

    assert widoczne == {f'ala-{dzis:%m%d}-{i}' for i in range(3)}


def test_szablon_buduje_link_do_paczek(leader_client):
    html = leader_client.get('/stats').get_data(as_text=True)

    assert 'linkDoPaczek' in html
    assert "date_typ: 'koniec'" in html


# ── uprawnienia ──────────────────────────────────────────────────────────────

def test_operator_nie_zobaczy_przegladu(client):
    r = client.get('/api/stats/overview')

    assert r.status_code in (302, 401, 403)


def test_ekran_statystyk_ma_zakladke_przegladu(leader_client):
    html = leader_client.get('/stats').get_data(as_text=True)

    assert 'Przegląd ogólny' in html
    assert 'id="przegladBody"' in html
