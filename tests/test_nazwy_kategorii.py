"""Nazwy kategorii widziane przez pracownika (koniec paczki, ✎ Ilosci, cennik)
ustawia admin. Format: najpierw polska nazwa, w nawiasie angielska ze
Statystyk ogolnych — „Niesprocesowane (Sorting)". Angielskiej czesci nie da sie
zmienic: po niej idzie rozliczenie i naglowki eksportu Excel.
"""
import io

import openpyxl

import app as logistat


def ustaw(client, **nazwy):
    return client.put('/api/category-labels', json={'nazwy': nazwy})


def test_domyslnie_polska_nazwa_a_w_nawiasie_angielska(flask_app):
    assert logistat.etykieta_kategorii('sorting') == 'Sortowanie (Sorting)'
    assert logistat.etykieta_kategorii('labelling_on') == 'Etykietowanie pojedyncze (Labelling one)'


def test_admin_zmienia_nazwe_widoczna_przy_koncu_paczki(admin_client):
    r = ustaw(admin_client, sorting='Niesprocesowane')

    assert r.status_code == 200
    assert r.get_json()['etykiety']['sorting'] == 'Niesprocesowane (Sorting)'
    html = admin_client.get('/scan-paczki').get_data(as_text=True)
    assert 'Niesprocesowane (Sorting)' in html
    assert 'Sortowanie (Sorting)' not in html


def test_nazwa_trafia_tez_do_okna_ilosci_na_liscie_paczek(admin_client):
    ustaw(admin_client, sorting='Niesprocesowane')

    assert 'Niesprocesowane (Sorting)' in admin_client.get('/paczki').get_data(as_text=True)


def test_pusta_nazwa_wraca_do_domyslnej_i_nie_zostawia_wpisu(admin_client):
    ustaw(admin_client, sorting='Niesprocesowane')
    r = ustaw(admin_client, sorting='   ')

    assert r.status_code == 200
    assert logistat.etykieta_kategorii('sorting') == 'Sortowanie (Sorting)'
    assert logistat.db.session.get(logistat.AppSetting, 'kategoria_pl:sorting') is None


def test_wpisanie_domyslnej_nie_zapisuje_kopii(admin_client):
    """Zapisana kopia domyslnej zamrozilaby ja — zmiana domyslnej w kodzie
    przestalaby dzialac dla tej kategorii."""
    ustaw(admin_client, sorting='Sortowanie')

    assert logistat.db.session.get(logistat.AppSetting, 'kategoria_pl:sorting') is None


def test_nadmiarowe_spacje_sa_sciskane(admin_client):
    ustaw(admin_client, sorting='  Nie   sprocesowane ')

    assert logistat.etykieta_kategorii('sorting') == 'Nie sprocesowane (Sorting)'


def test_eksport_excel_zostaje_po_angielsku(admin_client):
    ustaw(admin_client, sorting='Niesprocesowane', textile='Ubrania')

    r = admin_client.get('/general-stats/export')
    ws = openpyxl.load_workbook(io.BytesIO(r.data)).active
    naglowki = [str(c.value) for row in ws.iter_rows(max_row=3) for c in row if c.value]

    assert 'Sorting' in naglowki
    assert not any('Niesprocesowane' in n or 'Ubrania' in n for n in naglowki)


def test_komunikat_bledu_ilosci_uzywa_nazwy_dla_pracownika(admin_client):
    ustaw(admin_client, sorting='Niesprocesowane')

    _, blad = logistat.parse_scan_categories({'sorting': 'abc'})

    assert blad and 'Niesprocesowane (Sorting)' in blad


def test_jedno_zapytanie_na_wszystkie_etykiety(admin_client, queries):
    ustaw(admin_client, sorting='Niesprocesowane')
    przed = len(queries.matching('app_setting'))

    logistat.etykiety_kategorii()

    assert len(queries.matching('app_setting')) - przed == 1


def test_lider_nie_zmieni_nazw(leader_client):
    r = ustaw(leader_client, sorting='X')

    assert r.status_code == 302
    assert logistat.db.session.get(logistat.AppSetting, 'kategoria_pl:sorting') is None


def test_nieznana_kategoria_daje_400(admin_client):
    r = ustaw(admin_client, nie_ma_takiej='X')

    assert r.status_code == 400
    assert 'Nieznana kategoria' in r.get_json()['error']


def test_za_dluga_nazwa_daje_400(admin_client):
    r = ustaw(admin_client, sorting='x' * 61)

    assert r.status_code == 400
    assert logistat.db.session.get(logistat.AppSetting, 'kategoria_pl:sorting') is None


def test_zle_cialo_daje_400(admin_client):
    assert admin_client.put('/api/category-labels', json={'nazwy': ['x']}).status_code == 400
    assert ustaw(admin_client, sorting=5).status_code == 400


def test_nazwa_jest_escapowana_na_ekranie(admin_client):
    ustaw(admin_client, sorting='<b>X</b>')

    html = admin_client.get('/scan-paczki').get_data(as_text=True)

    assert '<b>X</b> (Sorting)' not in html
    assert '&lt;b&gt;X&lt;/b&gt; (Sorting)' in html
