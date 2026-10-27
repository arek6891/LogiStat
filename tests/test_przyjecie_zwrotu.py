"""Magazyn → Przyjęcie zwrotu (operacja 2026-10-27): stanowisko zapisuje zwrot,
ktory staje sie wierszem Zwrotow Paczek (ekran, Excel, Sorting returns).
Dane syntetyczne — nigdy wiersze z pliku operacji."""
import io
import itertools
from datetime import date, datetime, timedelta

import openpyxl
import pytest

from conftest import login, make_user, strona_z_js

from logistat.czas import local_today, teraz_utc
from logistat.extensions import db
from logistat.models import (
    Activity, ActivityAssignment, LicencjaZwrotow, PrzydzialZwrotow, ZwrotPaczki, get_or_create_shift)
from logistat.przyjecie_zwrotu import CZYNNOSC_ZWROTOW, ETYKIETY_DOMYSLNE, monat, pos_nummer, woche
from logistat.zwroty_dane import wiersze_zwrotow


_licznik = itertools.count()


def zwrot(**zmiany):
    body = {
        'token': f'token-{next(_licznik):06d}',
        'paketnummer': '%0000000000000000042', 'brand': 'ACC', 'pos_nummer': 'ab12',
        'kurier': 'UPS', 'retoure': 1, 'defekt': 0, 'neuwarenueberschuss': 0, 'silber': 2,
        'defektes_silber': 0, 'reduzierte_ware': 0, 'verpackungsvorschrift': 'Yes',
    }
    body.update(zmiany)
    return body


def obsadz(stanowisko, *osoby, minut_temu=5):
    """Przydzial jak u lidera: osoby na czynnosci „Zwroty” dzisiejszej zmiany 1
    i otwarty wiersz na stanowisku (od kilku minut)."""
    zmiana = get_or_create_shift(local_today(), 1)
    zwroty = Activity.query.filter_by(name=CZYNNOSC_ZWROTOW).one()
    for o in osoby:
        db.session.add(ActivityAssignment(shift_id=zmiana.id, user_id=o.id, activity_id=zwroty.id))
        db.session.add(PrzydzialZwrotow(shift_id=zmiana.id, user_id=o.id, stanowisko_id=stanowisko.id,
                                        od=teraz_utc() - timedelta(minutes=minut_temu)))
    db.session.commit()
    return zmiana


@pytest.fixture
def stanowisko(flask_app):
    return make_user('stanowisko')


@pytest.fixture
def stanowisko_client(flask_app, stanowisko):
    """Osobny klient (admin_client / leader_client dziela jeden `client`), stanowisko
    z jedna osoba przydzielona — bez obsady przyjecie jest zablokowane."""
    obsadz(stanowisko, make_user('operator'))
    klient = flask_app.test_client()
    login(klient, stanowisko.username)
    return klient


# ── czysta logika ────────────────────────────────────────────────────────────

def test_monat_i_woche_jak_w_arkuszu():
    assert monat(date(2026, 9, 2)) == 'wrzesień-2026'
    assert woche(date(2026, 9, 2)) == '36-2026'
    assert monat(date(2026, 12, 31)) == 'grudzień-2026'
    # Tydzien ISO: 01.01.2027 (piatek) nalezy do 53. tygodnia 2026.
    assert woche(date(2027, 1, 1)) == '53-2026'


@pytest.mark.parametrize('wpisane,wynik', [
    ('ab12', 'AB12'), (' po 77-x ', 'PO77-X'), ('', None), ('ąę', None), ('-12', None),
    (None, None), (12, None), ('A' * 51, None),
])
def test_pos_nummer_duze_litery(wpisane, wynik):
    assert pos_nummer(wpisane) == wynik


# ── zapis ze stanowiska ──────────────────────────────────────────────────────

def test_stanowisko_przyjmuje_zwrot_i_jest_w_raporcie(stanowisko_client):
    r = stanowisko_client.post('/api/zwroty/przyjecie', json=zwrot())

    assert r.status_code == 201, r.get_json()
    z = ZwrotPaczki.query.one()
    assert (z.pos_nummer, z.kurier, z.silber, z.retoure) == ('AB12', 'UPS', 2, 1)
    dzis = local_today()
    assert wiersze_zwrotow(dzis, dzis) == [(
        '%0000000000000000042', 'ACC', dzis, 'AB12', 0, 1, 0, 1, 0, 0, 2, 0, 0, 'Yes',
        monat(dzis), woche(dzis))]


def test_ten_sam_token_nie_dubluje_wiersza(stanowisko_client):
    """Podwojny klik / ponowienie po bledzie sieci — Sorting returns idzie na fakture."""
    body = zwrot(token='staly-token-123')
    assert stanowisko_client.post('/api/zwroty/przyjecie', json=body).status_code == 201
    r = stanowisko_client.post('/api/zwroty/przyjecie', json=body)

    assert r.status_code == 200 and r.get_json()['powtorzony'] is True
    assert ZwrotPaczki.query.count() == 1


def test_powtorzony_paketnummer_to_nowy_wiersz(stanowisko_client):
    """W arkuszu operacji Paketnummer sie powtarza; kazde przyjecie to wiersz."""
    stanowisko_client.post('/api/zwroty/przyjecie', json=zwrot(token='pierwszy-1'))
    stanowisko_client.post('/api/zwroty/przyjecie', json=zwrot(token='drugi-22'))
    assert ZwrotPaczki.query.count() == 2


def test_brak_pos_to_no(stanowisko_client):
    stanowisko_client.post('/api/zwroty/przyjecie', json=zwrot(pos_nummer='NO'))
    assert ZwrotPaczki.query.one().pos_nummer == 'NO'


@pytest.mark.parametrize('zmiana,blad', [
    ({'retoure': 0}, 'Retoure'),
    ({'retoure': None}, 'Retoure'),
    ({'defekt': -1}, 'Defekt'),
    ({'silber': '3'}, 'Silber_in_Stück'),
    ({'reduzierte_ware': True}, 'Reduzierte_ware'),
    ({'defektes_silber': 100_000}, 'Defektes_Silber_in_Stück'),
    ({'paketnummer': '  '}, 'numer paczki'),
    ({'pos_nummer': ''}, 'POS'),
    ({'brand': 'NIEZNANY'}, 'Brand'),
    ({'kurier': 'FedEx'}, 'kurier'),
    ({'verpackungsvorschrift': None}, 'Verpackungsvorschrift'),
    ({'token': 'krotki'}, 'identyfikatora'),
])
def test_walidacja(stanowisko_client, zmiana, blad):
    r = stanowisko_client.post('/api/zwroty/przyjecie', json=zwrot(**zmiana))
    assert r.status_code == 400 and blad in r.get_json()['error']
    assert ZwrotPaczki.query.count() == 0


def test_wylaczony_brand_odrzucony(stanowisko_client):
    LicencjaZwrotow.query.filter_by(rodzaj='brand', nazwa='ACC').one().aktywna = False
    db.session.commit()
    r = stanowisko_client.post('/api/zwroty/przyjecie', json=zwrot())
    assert r.status_code == 400 and 'odśwież' in r.get_json()['error']


def test_data_ustawia_serwer(stanowisko_client):
    """Date / Monat / Woche z chwili przyjecia — pole z przegladarki nic nie zmienia."""
    stanowisko_client.post('/api/zwroty/przyjecie', json=zwrot(przyjeto_at='2020-01-01T00:00:00'))
    dzis = local_today()
    assert wiersze_zwrotow(dzis, dzis)[0][2] == dzis


def test_ekran_dla_stanowiska_z_napisami_z_ustawien(stanowisko_client):
    html = strona_z_js(stanowisko_client, '/zwroty/przyjecie')
    assert ETYKIETY_DOMYSLNE['paketnummer'] in html
    for przycisk in ('ACC', 'SIX', 'NK', 'ITS', 'DPD', 'UPS', 'Other', 'VKM'):
        assert f'"{przycisk}"' in html
    assert 'Paketnummer' not in html.split('<script>')[1], 'pracownik nie widzi naglowkow raportu'


def test_napisy_ustawia_admin(admin_client):
    r = admin_client.put('/api/zwroty/etykiety', json={'etykiety': {'paketnummer': 'Skanuj paczkę'}})
    assert r.status_code == 200 and r.get_json()['etykiety']['paketnummer'] == 'Skanuj paczkę'
    # Pusty napis = powrot do domyslnego.
    r = admin_client.put('/api/zwroty/etykiety', json={'etykiety': {'paketnummer': ''}})
    assert r.get_json()['etykiety']['paketnummer'] == ETYKIETY_DOMYSLNE['paketnummer']
    assert admin_client.put('/api/zwroty/etykiety',
                            json={'etykiety': {'xxx': 'a'}}).status_code == 400


def test_lider_nie_zmienia_ustawien(leader_client):
    assert leader_client.put('/api/zwroty/etykiety', json={'etykiety': {}}).status_code == 403
    assert leader_client.post('/api/zwroty/licencje',
                              json={'rodzaj': 'kurier', 'nazwa': 'GLS'}).status_code == 403


def test_nowy_kurier_to_nowa_kolumna(admin_client):
    r = admin_client.post('/api/zwroty/licencje', json={'rodzaj': 'kurier', 'nazwa': 'GLS'})
    assert r.status_code == 201
    r = admin_client.get('/zwroty/paczki/export')
    ws = openpyxl.load_workbook(io.BytesIO(r.data)).active
    assert [c.value for c in ws[1]][4:8] == ['DPD', 'UPS', 'Other', 'GLS']


def test_wylaczony_kurier_zostaje_kolumna_gdy_ma_zwroty(stanowisko_client, admin_client):
    """Wylaczenie kuriera nie moze wyzerowac jego paczek w raporcie."""
    stanowisko_client.post('/api/zwroty/przyjecie', json=zwrot(kurier='DPD'))
    LicencjaZwrotow.query.filter_by(rodzaj='kurier', nazwa='DPD').one().aktywna = False
    db.session.commit()
    dzis = local_today()
    html = admin_client.get('/zwroty/paczki').get_data(as_text=True)

    assert '<th>DPD</th>' in html
    wiersz = wiersze_zwrotow(dzis, dzis)[0]
    assert wiersz[4:7] == (0, 0, 1), 'kolumny: UPS, Other, DPD (wylaczony na koncu)'


def test_filtry_raportu(stanowisko_client):
    stanowisko_client.post('/api/zwroty/przyjecie', json=zwrot(token='filtr-aaa1', paketnummer='%111222'))
    stanowisko_client.post('/api/zwroty/przyjecie', json=zwrot(token='filtr-bbb2', paketnummer='%999', brand='SIX'))
    dzis = local_today()

    assert [w[0] for w in wiersze_zwrotow(dzis, dzis, paketnummer='1122')] == ['%111222']
    assert [w[0] for w in wiersze_zwrotow(dzis, dzis, brand='SIX')] == ['%999']
    assert wiersze_zwrotow(date(2020, 1, 1), date(2020, 1, 2)) == []


def test_granica_doby_po_czasie_lokalnym(flask_app):
    db.session.add(ZwrotPaczki(paketnummer='%1', brand='ACC', pos_nummer='NO', kurier='UPS',
                               retoure=1, verpackungsvorschrift='Yes', token='granica-1',
                               przyjeto_at=datetime(2026, 9, 1, 22, 30)))  # 02.09 00:30 w Warszawie
    db.session.commit()
    assert wiersze_zwrotow(date(2026, 9, 1), date(2026, 9, 1)) == []
    assert wiersze_zwrotow(date(2026, 9, 2), date(2026, 9, 2))[0][2] == date(2026, 9, 2)


def test_admin_widzi_strone_ustawien(admin_client):
    html = admin_client.get('/admin/zwroty/przyjecie').get_data(as_text=True)
    assert 'Napisy na ekranach' in html and 'Kurierzy' in html and 'Verpackungsvorschrift' in html


# ── poprawka i usuniecie przez lidera (operacja 2026-10-27) ─────────────────

def test_lider_poprawia_zwrot(stanowisko_client, leader_client):
    stanowisko_client.post('/api/zwroty/przyjecie', json=zwrot())
    z = ZwrotPaczki.query.one()
    przyjety = z.przyjeto_at
    r = leader_client.put(f'/api/zwroty/przyjecie/{z.id}', json=zwrot(
        paketnummer='%POPRAWIONY', brand='SIX', pos_nummer='xy9', retoure=3, kurier='DPD'))

    assert r.status_code == 200, r.get_json()
    db.session.expire_all()
    z = ZwrotPaczki.query.one()
    assert (z.paketnummer, z.brand, z.pos_nummer, z.retoure, z.kurier) == ('%POPRAWIONY', 'SIX', 'XY9', 3, 'DPD')
    assert z.przyjeto_at == przyjety, 'data przyjecia sie nie zmienia'
    assert z.zmienil_id is not None and z.zmieniono_at is not None


def test_poprawka_z_wylaczonym_brandem_przechodzi(stanowisko_client, leader_client):
    stanowisko_client.post('/api/zwroty/przyjecie', json=zwrot())
    z = ZwrotPaczki.query.one()
    LicencjaZwrotow.query.filter_by(rodzaj='brand', nazwa='ACC').one().aktywna = False
    db.session.commit()
    assert leader_client.put(f'/api/zwroty/przyjecie/{z.id}', json=zwrot(retoure=2)).status_code == 200
    assert leader_client.put(f'/api/zwroty/przyjecie/{z.id}',
                             json=zwrot(brand='XXX')).status_code == 400
    assert leader_client.put(f'/api/zwroty/przyjecie/{z.id}',
                             json=zwrot(retoure=0)).status_code == 400


def test_lider_usuwa_zwrot(stanowisko_client, leader_client):
    stanowisko_client.post('/api/zwroty/przyjecie', json=zwrot())
    z = ZwrotPaczki.query.one()
    html = leader_client.get('/zwroty/paczki').get_data(as_text=True)
    assert f'data-id="{z.id}"' in html and 'js-popraw' in html

    assert leader_client.delete(f'/api/zwroty/przyjecie/{z.id}').status_code == 200
    assert ZwrotPaczki.query.count() == 0
    assert leader_client.delete(f'/api/zwroty/przyjecie/{z.id}').status_code == 404


def test_stanowisko_nie_poprawia_ani_nie_usuwa(stanowisko_client):
    stanowisko_client.post('/api/zwroty/przyjecie', json=zwrot())
    z = ZwrotPaczki.query.one()
    assert stanowisko_client.put(f'/api/zwroty/przyjecie/{z.id}', json=zwrot()).status_code == 403
    assert stanowisko_client.delete(f'/api/zwroty/przyjecie/{z.id}').status_code == 403
