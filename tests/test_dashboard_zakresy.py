"""Dashboard: zakres dat w Podsumowaniu i zakladka „Per Loading date" (2026-10-12).

Podsumowanie dalej liczy tylko niezrobione — zakres zaweza je po Loading date
(data pliku). Per Loading date = plan pliku (jak „Wybrany dzien") dla kazdej
daty z zakresu + suma.
"""
from datetime import date, datetime

import app as logistat


def karton(barcode, dzien, szt=10, start=None, koniec=None):
    c = logistat.ImportedCarton(barcode=barcode, land='PL', stueckzahl=szt, uebergabe_nr='UB-1',
                                data_pliku=dzien, scan_start_at=start, scan_end_at=koniec)
    logistat.db.session.add(c)
    return c


def dane():
    t = datetime(2026, 9, 20, 8, 0)
    karton('A1', date(2026, 9, 1), 10)
    karton('A2', date(2026, 9, 1), 20, start=t, koniec=t)
    karton('B1', date(2026, 9, 5), 5, start=t)
    karton('C1', date(2026, 9, 9), 7)
    karton('Z0', None, 3)
    logistat.db.session.commit()


# ── Podsumowanie z zakresem ──────────────────────────────────────────────────

def test_podsumowanie_bez_zakresu_jak_dotad(leader_client):
    dane()

    z = leader_client.get('/api/dashboard/zalegle').get_json()

    assert (z['paczek'], z['sztuk']) == (4, 25)
    assert [d['data_pliku'] for d in z['dni']] == [None, '2026-09-01', '2026-09-05', '2026-09-09']
    assert z == leader_client.get('/api/dashboard').get_json()['zalegle']


def test_podsumowanie_zaweza_po_loading_date(leader_client):
    dane()

    z = leader_client.get('/api/dashboard/zalegle?date_from=2026-09-02&date_to=2026-09-09').get_json()

    assert (z['paczek'], z['sztuk']) == (2, 12), 'bez paczek bez daty i spoza zakresu'
    assert z['dni'] == [
        {'data_pliku': '2026-09-05', 'paczek': 1, 'sztuk': 5, 'w_toku': 1},
        {'data_pliku': '2026-09-09', 'paczek': 1, 'sztuk': 7, 'w_toku': 0},
    ]


def test_podsumowanie_jednostronny_zakres(leader_client):
    dane()

    z = leader_client.get('/api/dashboard/zalegle?date_to=2026-09-01').get_json()

    assert z['dni'] == [{'data_pliku': '2026-09-01', 'paczek': 1, 'sztuk': 10, 'w_toku': 0}]


def test_podsumowanie_zle_daty(leader_client):
    assert leader_client.get('/api/dashboard/zalegle?date_from=bzdura').status_code == 400
    assert leader_client.get(
        '/api/dashboard/zalegle?date_from=2026-09-09&date_to=2026-09-01').status_code == 400


# ── Per Loading date ─────────────────────────────────────────────────────────

def test_per_loading_date_wiersz_na_dzien_i_suma(leader_client):
    dane()

    d = leader_client.get(
        '/api/dashboard/loading-dates?date_from=2026-09-01&date_to=2026-09-30').get_json()

    assert [r['data_pliku'] for r in d['dni']] == ['2026-09-09', '2026-09-05', '2026-09-01']
    wrz = d['dni'][2]
    assert (wrz['paczek'], wrz['sztuk'], wrz['zrobione'], wrz['zrobione_sztuk']) == (2, 30, 1, 20)
    assert (wrz['pozostalo'], wrz['pozostalo_sztuk'], wrz['procent']) == (1, 10, 50.0)
    assert d['dni'][1]['w_toku'] == 1
    s = d['suma']
    assert (s['paczek'], s['sztuk'], s['zrobione'], s['pozostalo'], s['w_toku']) == (4, 42, 1, 3, 1)
    assert s['procent'] == 25.0


def test_per_loading_date_zgadza_sie_z_wybranym_dniem(leader_client):
    dane()

    d = leader_client.get(
        '/api/dashboard/loading-dates?date_from=2026-09-01&date_to=2026-09-01').get_json()

    assert d['dni'] == [leader_client.get('/api/dashboard/plik?date=2026-09-01').get_json()]


def test_per_loading_date_domyslnie_biezacy_miesiac(leader_client):
    d = leader_client.get('/api/dashboard/loading-dates').get_json()

    dzis = logistat.local_today()
    assert (d['date_from'], d['date_to']) == (dzis.replace(day=1).isoformat(), dzis.isoformat())
    assert d['dni'] == [] and d['suma']['paczek'] == 0


def test_per_loading_date_zle_zakresy(leader_client):
    url = '/api/dashboard/loading-dates'
    assert leader_client.get(url + '?date_from=2026-09-09&date_to=2026-09-01').status_code == 400
    assert leader_client.get(url + '?date_from=2024-01-01&date_to=2026-01-01').status_code == 400
    assert leader_client.get(url + '?date_to=xx').status_code == 400


def test_nowe_api_tylko_dla_zalogowanych(client):
    for url in ('/api/dashboard/zalegle', '/api/dashboard/loading-dates'):
        assert client.get(url).status_code in (302, 401)


def test_dashboard_ma_zakladke_i_filtr(leader_client):
    html = leader_client.get('/dashboard').get_data(as_text=True)

    assert 'id="tab-dni"' in html and 'Per Loading date' in html
    assert 'id="zalOd"' in html and 'id="zalDo"' in html
