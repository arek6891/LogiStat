"""Dekoracje — stock gotowych stojakow (operacja 2026-10-28).

- stanowisko: skan nosnika (nieznany = nowy stojak), potem skan strefy → ruch
  (kto, kiedy, skad, dokad); ta sama strefa = bez ruchu; kod strefy w polu
  nosnika i nieznana / wylaczona strefa → 400,
- strefy = lista admina (nazwa = kod na etykiecie, regula numeru POS), uzyta → 409
  przy usuwaniu, etykiety stref jako PDF,
- lider: POS tylko z listy Etykiet POS, akcja niezakonczona, strefa recznie = ruch
  „recznie”; POS przypisany do stojaka nie znika z listy etykiet,
- konto stanowiska skanuje, ale tabeli stocku nie widzi.
Dane syntetyczne.
"""
import io

import openpyxl
import pytest
from conftest import login, make_user

from logistat.dekoracje import STREFA, kod_nosnika, kod_strefy
from logistat.models import PosDekoracji, RuchStojaka, SlownikDekoracji, StojakDekoracji


def strefa(admin_client, nazwa):
    r = admin_client.post('/api/dekoracje/slownik', json={'rodzaj': STREFA, 'nazwa': nazwa})
    assert r.status_code == 201, r.get_json()
    return r.get_json()


@pytest.fixture
def strefy(admin_client):
    return {n: strefa(admin_client, n)['id'] for n in ('A1', 'B2', 'WYSYLKA')}


@pytest.fixture
def stanowisko(flask_app):
    klient = flask_app.test_client()
    login(klient, make_user('stanowisko').username)
    return klient


def skan(klient, nosnik, kod_strefy_, status=200):
    r = klient.post('/api/dekoracje/skan', json={'nosnik': nosnik, 'strefa': kod_strefy_})
    assert r.status_code == status, r.get_json()
    return r.get_json()


def lista_pos(klient, *numery):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['POS'])
    for n in numery:
        ws.append([n])
    bufor = io.BytesIO()
    wb.save(bufor)
    bufor.seek(0)
    r = klient.post('/api/dekoracje/pos/import', data={'file': (bufor, 'pos.xlsx')},
                    content_type='multipart/form-data')
    assert r.status_code == 200, r.get_json()


# ── czysta logika ────────────────────────────────────────────────────────────

def test_kody():
    assert kod_nosnika(' n-0042 ') == 'N-0042'
    assert kod_nosnika('%00123') == '%00123', 'nosnik: dowolne drukowalne ASCII'
    assert kod_nosnika('') is None and kod_nosnika('Ż1') is None and kod_nosnika('A' * 51) is None
    assert kod_strefy('a1') == 'A1'
    assert kod_strefy('Strefa A') == 'STREFAA'
    assert kod_strefy('Półka') is None and kod_strefy('A' * 30) is None


# ── stanowisko ───────────────────────────────────────────────────────────────

def test_skan_zaklada_stojak_i_zapisuje_ruchy(stanowisko, strefy):
    r = stanowisko.get('/api/dekoracje/nosnik?kod=n-1')
    assert r.status_code == 200 and r.get_json() == {'nowy': True, 'nosnik': 'N-1', 'stojak': None}

    w = skan(stanowisko, 'n-1', 'a1')
    assert w['nowy'] and w['przeniesiono'] and w['stojak']['strefa'] == 'A1'
    w = skan(stanowisko, 'N-1', 'A1')
    assert not w['nowy'] and not w['przeniesiono'], 'ta sama strefa — bez ruchu'
    w = skan(stanowisko, 'N-1', 'WYSYLKA')
    assert w['przeniesiono'] and w['stojak']['strefa'] == 'WYSYLKA'

    assert StojakDekoracji.query.count() == 1
    ruchy = RuchStojaka.query.order_by(RuchStojaka.id).all()
    assert [(r.z_strefy_id, r.do_strefy_id, r.recznie) for r in ruchy] == [
        (None, strefy['A1'], False), (strefy['A1'], strefy['WYSYLKA'], False)]
    assert all(r.kto_id is not None and r.kiedy is not None for r in ruchy)
    d = stanowisko.get('/api/dekoracje/nosnik?kod=N-1').get_json()
    assert not d['nowy'] and d['stojak']['strefa'] == 'WYSYLKA' and d['stojak']['ostatni_ruch']


def test_skan_bledy(stanowisko, admin_client, strefy):
    assert stanowisko.get('/api/dekoracje/nosnik?kod=').status_code == 400
    r = stanowisko.get('/api/dekoracje/nosnik?kod=a1')
    assert r.status_code == 400 and 'kod strefy' in r.get_json()['error']
    skan(stanowisko, 'A1', 'B2', status=400)
    assert 'Nieznana strefa' in skan(stanowisko, 'N-1', 'XYZ', status=400)['error']
    admin_client.put(f'/api/dekoracje/slownik/{strefy["B2"]}', json={'aktywna': False})
    skan(stanowisko, 'N-1', 'B2', status=400)
    assert StojakDekoracji.query.count() == 0, 'bledny skan niczego nie zaklada'


def test_strefy_w_liscie_admina(admin_client, stanowisko, strefy):
    assert admin_client.post('/api/dekoracje/slownik', json={'rodzaj': STREFA, 'nazwa': 'Półka 1'}).status_code == 400
    assert strefa(admin_client, ' c 3 ')['nazwa'] == 'C3'
    assert admin_client.put(f'/api/dekoracje/slownik/{strefy["B2"]}', json={'nazwa': 'b-22'}).get_json()['nazwa'] == 'B-22'
    skan(stanowisko, 'N-1', 'A1')
    assert admin_client.delete(f'/api/dekoracje/slownik/{strefy["A1"]}').status_code == 409
    skan(stanowisko, 'N-1', 'WYSYLKA')
    assert admin_client.delete(f'/api/dekoracje/slownik/{strefy["A1"]}').status_code == 409, \
        'strefa z historii ruchow tez zostaje'
    assert admin_client.delete(f'/api/dekoracje/slownik/{strefy["B2"]}').status_code == 200


def test_etykiety_stref(admin_client, strefy):
    r = admin_client.post('/admin/dekoracje/strefy/etykiety')
    assert r.status_code == 200 and r.headers['Content-Type'] == 'application/pdf'
    assert b'(WYSYLKA) Tj' in r.data and b'(A1) Tj' in r.data
    admin_client.put(f'/api/dekoracje/slownik/{strefy["A1"]}', json={'aktywna': False})
    assert b'(A1) Tj' not in admin_client.post('/admin/dekoracje/strefy/etykiety').data


def test_strefy_nie_trafiaja_do_listy_akcji(leader_client, strefy):
    from logistat.dekoracje_dane import listy_dla_akcji
    from logistat.extensions import db
    from logistat.models import AkcjaDekoracji
    r = leader_client.post('/api/dekoracje/akcje', json={'nazwa': 'A', 'od': '2026-11-01', 'do': '2026-11-02',
                                                         'typ_dostawy': 'beeline'})
    a = db.session.get(AkcjaDekoracji, r.get_json()['id'])
    assert STREFA not in listy_dla_akcji(a)


# ── tabela lidera ────────────────────────────────────────────────────────────

def test_lider_przypisuje_pos_akcje_i_strefe(leader_client, stanowisko, strefy):
    skan(stanowisko, 'N-1', 'A1')
    s = StojakDekoracji.query.one()
    lista_pos(leader_client, 'PL-1')
    akcja = leader_client.post('/api/dekoracje/akcje', json={'nazwa': 'Gwiazdka', 'od': '2026-11-01',
                                                             'do': '2026-12-20', 'typ_dostawy': 'beeline'}).get_json()
    url = f'/api/dekoracje/stojaki/{s.id}'

    r = leader_client.put(url, json={'pos': 'PL-9'})
    assert r.status_code == 400 and 'Etykiet POS' in r.get_json()['error']
    d = leader_client.put(url, json={'pos': 'pl-1'}).get_json()
    assert d['pos'] == 'PL-1' and d['strefa'] == 'A1'
    d = leader_client.put(url, json={'akcja_id': akcja['id']}).get_json()
    assert d['akcja'] == 'Gwiazdka' and d['pos'] == 'PL-1', 'czesciowy zapis nie rusza innych pol'
    d = leader_client.put(url, json={'strefa_id': strefy['B2']}).get_json()
    assert d['strefa'] == 'B2'
    ruchy = leader_client.get(url + '/ruchy').get_json()
    assert [(r['z'], r['do'], r['recznie']) for r in ruchy] == [('A1', 'B2', True), (None, 'A1', False)]

    # POS przypisany do stojaka nie znika z listy etykiet
    p = PosDekoracji.query.filter_by(numer='PL-1').one()
    assert leader_client.delete(f'/api/dekoracje/pos/{p.id}').status_code == 409

    # akcja zakonczona: zostaje przy stojaku, ale nowego stojaka sie do niej nie przypisze
    leader_client.put(f'/api/dekoracje/akcje/{akcja["id"]}/status', json={'zakonczona': True})
    assert leader_client.put(url, json={'akcja_id': akcja['id']}).status_code == 200
    skan(stanowisko, 'N-2', 'A1')
    s2 = StojakDekoracji.query.filter_by(nosnik='N-2').one()
    assert leader_client.put(f'/api/dekoracje/stojaki/{s2.id}', json={'akcja_id': akcja['id']}).status_code == 400

    html = leader_client.get('/displays/stock').get_data(as_text=True)
    assert '🗃️ Stock stojaków' in html and 'N-2' in html


def test_usuniecie_stojaka_z_historia(leader_client, stanowisko, strefy):
    skan(stanowisko, 'N-1', 'A1')
    skan(stanowisko, 'N-1', 'B2')
    s = StojakDekoracji.query.one()
    assert leader_client.delete(f'/api/dekoracje/stojaki/{s.id}').status_code == 200
    assert StojakDekoracji.query.count() == 0 and RuchStojaka.query.count() == 0


@pytest.mark.parametrize('body', [{'strefa_id': 999999}, {'strefa_id': True}, {'akcja_id': 'x'}])
def test_lider_bledne_pola(leader_client, stanowisko, strefy, body):
    skan(stanowisko, 'N-1', 'A1')
    s = StojakDekoracji.query.one()
    assert leader_client.put(f'/api/dekoracje/stojaki/{s.id}', json=body).status_code == 400


def test_typ_stojaka_nie_jest_strefa(leader_client, stanowisko, strefy):
    skan(stanowisko, 'N-1', 'A1')
    s = StojakDekoracji.query.one()
    twin = SlownikDekoracji.query.filter_by(nazwa='Twin').one()
    assert leader_client.put(f'/api/dekoracje/stojaki/{s.id}', json={'strefa_id': twin.id}).status_code == 400


def test_stanowisko_skanuje_ale_nie_widzi_tabeli(stanowisko, strefy):
    assert stanowisko.get('/dekoracje/skan').status_code == 200
    r = stanowisko.get('/displays/stock')
    assert r.status_code == 302 and '/start' in r.headers['Location']
    skan(stanowisko, 'N-1', 'A1')
    s = StojakDekoracji.query.one()
    assert stanowisko.put(f'/api/dekoracje/stojaki/{s.id}', json={'pos': ''}).status_code == 403
