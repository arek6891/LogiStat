"""Zadania dodatkowe (operacja 2026-11-02, zastepuja Wpis ilosci): osoba, dzial,
czas od–do, czynnosc dodatkowa z listy admina, komentarz; eksport do Excela."""
import io
from datetime import date, timedelta

import pytest
from openpyxl import load_workbook

from conftest import make_user

from logistat.czas import local_day_bounds
from logistat.extensions import db
from logistat.models import CzynnoscDodatkowa, ShiftAttendance, ZadanieDodatkowe, get_or_create_shift

DZIEN = date(2026, 9, 2)
POLNOC = local_day_bounds(DZIEN)[0]   # 00:00 w Warszawie jako naive UTC


def godz(h):
    """Godzina lokalna dnia DZIEN (24+ = nastepny dzien) jako tekst z przegladarki."""
    return (POLNOC + timedelta(hours=h)).isoformat()


def wiersz(osoba, **zmiany):
    body = {'date': DZIEN.isoformat(), 'shift': 1, 'user_id': osoba.id, 'dzial': 'zwroty',
            'od': godz(8), 'do': godz(10.5), 'czynnosc_id': None, 'komentarz': ''}
    body.update(zmiany)
    return body


def test_domyslne_czynnosci_z_seeda(flask_app):
    assert {c.nazwa for c in CzynnoscDodatkowa.query.all()} >= {'5S', 'Sprzątanie'}


def test_lider_dodaje_zmienia_i_usuwa(leader_client, leader):
    ola = make_user('operator', display_name='Ola')
    piec_s = CzynnoscDodatkowa.query.filter_by(nazwa='5S').one()

    r = leader_client.post('/api/zadania-dodatkowe', json=wiersz(ola, komentarz='  regały  '))
    assert r.status_code == 201
    z_id = r.get_json()['id']
    z = db.session.get(ZadanieDodatkowe, z_id)
    assert (z.dzial, z.komentarz, z.wpisal_id) == ('zwroty', 'regały', leader.id)
    assert z.do - z.od == timedelta(hours=2.5)

    r = leader_client.put(f'/api/zadania-dodatkowe/{z_id}',
                          json=wiersz(ola, dzial='dekoracje', czynnosc_id=piec_s.id, do=godz(12)))
    assert r.status_code == 200
    db.session.expire_all()
    z = db.session.get(ZadanieDodatkowe, z_id)
    assert (z.dzial, z.czynnosc_id, z.zmienil_id) == ('dekoracje', piec_s.id, leader.id)

    dane = leader_client.get(f'/api/zadania-dodatkowe?date={DZIEN}&shift=1').get_json()
    assert [w['id'] for w in dane['wiersze']] == [z_id]
    assert [d['klucz'] for d in dane['dzialy']] == ['post_process', 'dekoracje', 'zwroty', 'magazyn']
    assert dane['wiersze'][0]['od'].endswith('Z')

    assert leader_client.delete(f'/api/zadania-dodatkowe/{z_id}').status_code == 200
    assert ZadanieDodatkowe.query.count() == 0


def test_kilka_wierszy_jednej_osoby_i_druga_zmiana_po_polnocy(leader_client):
    ola = make_user('operator')
    assert leader_client.post('/api/zadania-dodatkowe', json=wiersz(ola)).status_code == 201
    r = leader_client.post('/api/zadania-dodatkowe',
                           json=wiersz(ola, shift=2, od=godz(22), do=godz(26)))
    assert r.status_code == 201, r.get_json()
    assert ZadanieDodatkowe.query.filter_by(user_id=ola.id).count() == 2


@pytest.mark.parametrize('zmiana,blad', [
    ({'user_id': None}, 'user_id'),
    ({'dzial': 'kuchnia'}, 'dział'),
    ({'dzial': None}, 'dział'),
    ({'do': godz(8)}, 'po początku'),
    ({'od': godz(6), 'do': godz(23)}, '16 h'),
    ({'od': godz(-2)}, 'dniu zmiany'),
    ({'od': godz(29), 'do': godz(30.5)}, 'dniu zmiany'),
    ({'od': 'wczoraj'}, 'format czasu'),
    ({'czynnosc_id': 999999}, 'odśwież'),
    ({'komentarz': 'x' * 301}, '300'),
])
def test_walidacja(leader_client, zmiana, blad):
    ola = make_user('operator')
    r = leader_client.post('/api/zadania-dodatkowe', json=wiersz(ola, **zmiana))
    assert r.status_code == 400 and blad in r.get_json()['error']
    assert ZadanieDodatkowe.query.count() == 0


def test_wylaczona_czynnosc_zostaje_tam_gdzie_juz_jest(leader_client):
    ola = make_user('operator')
    c = CzynnoscDodatkowa.query.filter_by(nazwa='5S').one()
    z_id = leader_client.post('/api/zadania-dodatkowe', json=wiersz(ola, czynnosc_id=c.id)).get_json()['id']
    c.aktywna = False
    db.session.commit()

    assert leader_client.put(f'/api/zadania-dodatkowe/{z_id}',
                             json=wiersz(ola, czynnosc_id=c.id, komentarz='ok')).status_code == 200
    r = leader_client.post('/api/zadania-dodatkowe', json=wiersz(ola, czynnosc_id=c.id))
    assert r.status_code == 400
    dane = leader_client.get(f'/api/zadania-dodatkowe?date={DZIEN}&shift=1').get_json()
    assert c.id in {x['id'] for x in dane['czynnosci']}, 'wylaczona, ale uzyta na tej zmianie'


def test_osoby_obecni_na_zmianie_oznaczeni(leader_client):
    ola, ala = make_user('operator', display_name='Ola'), make_user('operator', display_name='Ala')
    make_user('stanowisko', display_name='Komputer')
    zmiana = get_or_create_shift(DZIEN, 1)
    db.session.add(ShiftAttendance(shift_id=zmiana.id, user_id=ola.id))
    db.session.commit()
    osoby = {o['nazwa']: o for o in leader_client.get(
        f'/api/zadania-dodatkowe?date={DZIEN}&shift=1').get_json()['osoby']}
    assert osoby['Ola']['obecny'] is True and osoby['Ala']['obecny'] is False
    assert 'Komputer' not in osoby


def test_eksport_excel(leader_client):
    ola = make_user('operator', display_name='Ola')
    c = CzynnoscDodatkowa.query.filter_by(nazwa='Sprzątanie').one()
    leader_client.post('/api/zadania-dodatkowe', json=wiersz(ola, czynnosc_id=c.id, komentarz='hala B'))
    r = leader_client.get(f'/zadania-dodatkowe/export?date_from={DZIEN}&date_to={DZIEN}')
    assert r.status_code == 200
    ws = load_workbook(io.BytesIO(r.data)).active
    assert [c.value for c in ws[1]][:4] == ['Data', 'Zmiana', 'Pracownik', 'Dział']
    w = [c.value for c in ws[2]]
    assert w[1:4] == [1, 'Ola', 'Zwroty']
    assert (w[4].hour, w[4].minute, w[5].hour, w[5].minute) == (8, 0, 10, 30), 'czas lokalny'
    assert w[6] == 2.5 and w[7:9] == ['Sprzątanie', 'hala B']
    assert ws.max_row == 2


def test_stary_wpis_ilosci_przekierowuje(leader_client):
    r = leader_client.get('/data-entry')
    assert r.status_code == 302 and r.headers['Location'].endswith('/zadania-dodatkowe')


def test_lista_czynnosci_admin(admin_client):
    r = admin_client.post('/api/zadania/czynnosci', json={'rodzaj': 'czynnosc', 'nazwa': ' Inwentaryzacja '})
    assert r.status_code == 201 and r.get_json()['nazwa'] == 'Inwentaryzacja'
    assert admin_client.post('/api/zadania/czynnosci', json={'nazwa': 'Inwentaryzacja'}).status_code == 409

    c = CzynnoscDodatkowa.query.filter_by(nazwa='5S').one()
    ola = make_user('operator')
    db.session.add(ZadanieDodatkowe(shift_id=get_or_create_shift(DZIEN, 1).id, user_id=ola.id,
                                    dzial='magazyn', od=POLNOC + timedelta(hours=8),
                                    do=POLNOC + timedelta(hours=9), czynnosc_id=c.id))
    db.session.commit()
    assert admin_client.delete(f'/api/zadania/czynnosci/{c.id}').status_code == 409
    assert admin_client.put(f'/api/zadania/czynnosci/{c.id}', json={'aktywna': False}).status_code == 200
    html = admin_client.get('/admin/zadania/czynnosci').get_data(as_text=True)
    assert 'Inwentaryzacja' in html and 'data-api="/api/zadania/czynnosci"' in html


def test_lider_nie_zmienia_listy_czynnosci(leader_client):
    assert leader_client.post('/api/zadania/czynnosci', json={'nazwa': 'X'}).status_code == 403
    assert leader_client.get('/admin/zadania/czynnosci').status_code in (302, 403)


def test_lista_pracownikow_linkuje_normy_i_czasy(leader_client):
    ola = make_user('operator', display_name='Ola')
    html = leader_client.get('/admin/users').get_data(as_text=True)
    assert f'href="/stats?user={ola.id}"' in html
    assert f'href="/worker-times?user_id={ola.id}"' in html
    assert f'/zwroty/dashboard#osoba-{ola.id}' in html
