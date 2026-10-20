"""Cel szt./h obowiazuje od dnia zapisu, az ktos go zmieni (2026-10-13, operacje).

Normy licza „% celu" celem z dnia pracy: kazda godzina skanowania wazy cel ze
swojego dnia, wiec zmiana celu nie przelicza starych dni. Lista zmian (kto, kiedy)
pod polem celu.
"""
from datetime import date, timedelta

from conftest import make_user
from test_przeglad_pracownikow import godziny_pracy, przeglad, wiersz

from logistat.czas import local_today
from logistat.extensions import db
from logistat.models import HistoriaCelu, POCZATEK_HISTORII_CELU, set_setting


D1 = date(2026, 9, 14)
D2 = date(2026, 9, 15)


def cel_od(dzien, wartosc):
    db.session.merge(HistoriaCelu(dzien=dzien, wartosc=wartosc))
    set_setting('target_szt_h', wartosc)
    db.session.commit()


def dwa_dni(nazwa='Ala'):
    """Ten sam wynik (100 szt./h, po 1,5 h) w obu dniach; cel 100 → 200 od D2."""
    u = make_user('operator', username=nazwa.lower(), display_name=nazwa)
    godziny_pracy(u, 3, sztuk_na_paczke=50, minut_na_paczke=30, dzien=D1)
    godziny_pracy(u, 3, sztuk_na_paczke=50, minut_na_paczke=30, dzien=D2)
    cel_od(POCZATEK_HISTORII_CELU, 100)
    cel_od(D2, 200)
    return u


def test_procent_celu_z_celow_dni_pracy(leader_client):
    dwa_dni()

    dane = przeglad(leader_client, date_from=D1.isoformat(), date_to=D2.isoformat())
    r = wiersz(dane, 'Ala')

    assert r['szt_h'] == 100
    assert r['cel_szt_h'] == 150, 'po 1,5 h przy celu 100 i 200'
    assert r['proc_celu'] == 67
    assert dane['cel_szt_h'] == 150
    assert dane['cele_w_okresie'] == [{'od': None, 'wartosc': 100},
                                      {'od': D2.isoformat(), 'wartosc': 200}]


def test_stary_dzien_liczony_starym_celem(leader_client):
    dwa_dni()

    dane = przeglad(leader_client, date_from=D1.isoformat(), date_to=D1.isoformat())

    assert wiersz(dane, 'Ala')['proc_celu'] == 100
    assert wiersz(dane, 'Ala')['ocena_celu'] == 'spelnia'
    assert dane['cel_szt_h'] == 100
    assert dane['cele_w_okresie'] == [{'od': None, 'wartosc': 100}]


def test_nowy_dzien_liczony_nowym_celem(leader_client):
    dwa_dni()

    dane = przeglad(leader_client, date_from=D2.isoformat(), date_to=D2.isoformat())

    assert wiersz(dane, 'Ala')['proc_celu'] == 50
    assert dane['cele_w_okresie'] == [{'od': D2.isoformat(), 'wartosc': 200}]


def test_godziny_z_dnia_bez_celu_nie_wchodza(leader_client):
    u = make_user('operator', username='ala', display_name='Ala')
    godziny_pracy(u, 3, 50, 30, dzien=D1)
    godziny_pracy(u, 3, 50, 30, dzien=D2)
    cel_od(POCZATEK_HISTORII_CELU, 0)
    cel_od(D2, 200)

    r = wiersz(przeglad(leader_client, date_from=D1.isoformat(), date_to=D2.isoformat()), 'Ala')

    assert r['cel_szt_h'] == 200


def test_okres_bez_pracy_pokazuje_cel_ostatniego_dnia(leader_client):
    cel_od(POCZATEK_HISTORII_CELU, 100)
    cel_od(D2, 200)

    assert przeglad(leader_client, date_from=D1.isoformat(),
                    date_to=D1.isoformat())['cel_szt_h'] == 100


def test_ocena_osoby_bierze_jej_cel(leader_client):
    u = dwa_dni()

    n = leader_client.get(f'/api/stats/user/{u.id}?date_from={D1}&date_to={D2}').get_json()

    assert n['norma']['cel_szt_h'] == 150
    assert n['norma']['wiersz']['proc_celu'] == 67


def test_wykres_ma_cel_kazdego_dnia(leader_client):
    u = dwa_dni()

    d = leader_client.get(f'/api/stats/user/{u.id}?date_from={D1}&date_to={D2}').get_json()

    assert [p['cel'] for p in d['wykres_dzienny']] == [100, 200]
    assert d['wykres_miesieczny'][0]['cel'] == 150


def test_zapis_celu_pamieta_kto_i_kiedy(leader_client):
    r = leader_client.put('/api/stats/target', json={'target_szt_h': 320})

    h = r.get_json()['historia']
    assert h[0]['od'] == local_today().isoformat()
    assert h[0]['wartosc'] == 320
    assert h[0]['zmienil'] and h[0]['zmieniono_at'].endswith('Z')
    assert h[-1]['od'] is None, 'zasiew „od poczatku" na koncu listy'


def test_strona_norm_pokazuje_historie(leader_client):
    leader_client.put('/api/stats/target', json={'target_szt_h': 320})

    html = leader_client.get('/stats').get_data(as_text=True)

    assert 'id="historiaCeluDane"' in html
    assert '"wartosc": 320' in html


