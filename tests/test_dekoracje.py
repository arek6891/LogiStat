"""Dekoracje — akcje na Gantcie, indexy, historia, listy stojakow (operacja 2026-10-28).

- akcja: nazwa + daty (obie wymagane, koniec >= start); niezakonczona jest na Gantcie
  (po terminie z ostrzezeniem), „Zakończ akcję” → historia, „Przywróć” → z powrotem,
- zakonczona akcja tylko do odczytu (409), poza zmiana statusu,
- index: czesciowy zapis, haki lacznie = stojaki × haki na stojak, puste = NULL,
  suma akcji z pustym polem jest „niepelna”,
- typ / model stojaka z listy admina: wylaczona pozycja tylko w indexie, ktory ja ma;
  uzyta → nie da sie usunac (409),
- lider i admin tak, konto stanowiska nie.
"""
from datetime import timedelta

import pytest
from conftest import login, make_user, strona_z_js

from logistat.czas import local_today
from logistat.dekoracje import MODEL_STOJAKA, TYP_STOJAKA, haki_razem, podsumowanie
from logistat.extensions import db
from logistat.models import SlownikDekoracji
from logistat.obszary import DISPLAYS, obszary_endpointu


def nowa_akcja(client, nazwa='Akcja jesień', od=None, do=None, typ_dostawy='kontener'):
    od = od or local_today()
    do = do or od + timedelta(days=10)
    r = client.post('/api/dekoracje/akcje', json={'nazwa': nazwa, 'od': od.isoformat(), 'do': do.isoformat(),
                                                  'typ_dostawy': typ_dostawy})
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def nowy_index(client, akcja_id, **pola):
    r = client.post(f'/api/dekoracje/akcje/{akcja_id}/indexy')
    assert r.status_code == 201, r.get_json()
    ix = r.get_json()
    if pola:
        r = client.put(f'/api/dekoracje/indexy/{ix["id"]}', json=pola)
        assert r.status_code == 200, r.get_json()
        ix = r.get_json()
    return ix


def pozycja(rodzaj, nazwa):
    return SlownikDekoracji.query.filter_by(rodzaj=rodzaj, nazwa=nazwa).one()


# ── czysta logika ────────────────────────────────────────────────────────────

def test_haki_razem_i_suma_niepelna():
    assert haki_razem(4, 30) == 120
    assert haki_razem(None, 30) is None and haki_razem(4, None) is None
    s = podsumowanie([{'ilosc_stojakow': 4, 'haki_na_stojak': 30, 'rgd': 10},
                      {'ilosc_stojakow': 2, 'haki_na_stojak': None, 'rgd': 5}])
    assert s['ilosc_stojakow'] == {'suma': 6, 'pelna': True}
    assert s['haki'] == {'suma': 120, 'pelna': False}
    assert s['rgd'] == {'suma': 15, 'pelna': True}
    assert s['pos'] == {'suma': 0, 'pelna': False}
    assert podsumowanie([])['haki'] == {'suma': 0, 'pelna': True}


def test_seed_list_stojakow(flask_app):
    assert [p.nazwa for p in SlownikDekoracji.query.filter_by(rodzaj=TYP_STOJAKA)
            .order_by(SlownikDekoracji.kolejnosc)] == ['Twin', 'Solo']
    assert pozycja(MODEL_STOJAKA, 'Gondola').aktywna


# ── akcja ────────────────────────────────────────────────────────────────────

def test_akcja_na_gantcie_i_jej_ekran(leader_client):
    a = nowa_akcja(leader_client, nazwa='Gwiazdka <b>2026</b>')
    html = leader_client.get('/displays').get_data(as_text=True)
    assert 'Gwiazdka \\u003cb\\u003e2026' in html, 'nazwa tylko w danych JSON (bez HTML)'
    assert '<b>2026' not in html
    r = leader_client.get(f'/displays/akcje/{a["id"]}')
    assert r.status_code == 200 and '➕ Index' in r.get_data(as_text=True)


@pytest.mark.parametrize('od,do,blad', [
    ('', '2026-11-01', 'Podaj datę'),
    ('2026-11-01', None, 'Podaj datę'),
    ('2026-11-31', '2026-12-01', 'Podaj datę'),
    ('2026-11-10', '2026-11-09', 'przed datą startu'),
])
def test_akcja_bledne_daty(leader_client, od, do, blad):
    r = leader_client.post('/api/dekoracje/akcje', json={'nazwa': 'X', 'od': od, 'do': do})
    assert r.status_code == 400 and blad in r.get_json()['error']


def test_akcja_bez_nazwy(leader_client):
    r = leader_client.post('/api/dekoracje/akcje', json={'nazwa': '  ', 'od': '2026-11-01', 'do': '2026-11-02'})
    assert r.status_code == 400


def test_zmiana_naglowka_akcji(leader_client):
    a = nowa_akcja(leader_client)
    r = leader_client.put(f'/api/dekoracje/akcje/{a["id"]}',
                          json={'nazwa': 'Nowa nazwa', 'od': '2026-12-01', 'do': '2026-12-24'})
    assert r.status_code == 200
    assert r.get_json()['od'] == '2026-12-01' and r.get_json()['nazwa'] == 'Nowa nazwa'
    r = leader_client.put(f'/api/dekoracje/akcje/{a["id"]}',
                          json={'nazwa': 'Nowa nazwa', 'od': '2026-12-25', 'do': '2026-12-24'})
    assert r.status_code == 400


def test_po_terminie_zostaje_na_gantcie(leader_client):
    dzis = local_today()
    a = nowa_akcja(leader_client, od=dzis - timedelta(days=20), do=dzis - timedelta(days=1))
    assert a['po_terminie'] is True
    html = leader_client.get('/displays').get_data(as_text=True)
    assert f'"id": {a["id"]}' in html


def test_zakoncz_historia_przywroc(leader_client):
    a = nowa_akcja(leader_client, nazwa='Akcja Wielkanoc')
    url = f'/api/dekoracje/akcje/{a["id"]}/status'

    r = leader_client.put(url, json={'zakonczona': True})
    assert r.status_code == 200 and r.get_json()['zakonczona'] is True
    assert 'Akcja Wielkanoc' not in leader_client.get('/displays').get_data(as_text=True)
    hist = leader_client.get('/displays/historia').get_data(as_text=True)
    assert 'Akcja Wielkanoc' in hist and 'TEST-LEADER' in hist
    ekran = leader_client.get(f'/displays/akcje/{a["id"]}').get_data(as_text=True)
    assert 'Przywróć' in ekran and '➕ Index' not in ekran

    r = leader_client.put(url, json={'zakonczona': False})
    assert r.status_code == 200 and r.get_json()['zakonczona'] is False
    assert 'Akcja Wielkanoc' in leader_client.get('/displays').get_data(as_text=True)
    assert 'Akcja Wielkanoc' not in leader_client.get('/displays/historia').get_data(as_text=True)

    assert leader_client.put(url, json={'zakonczona': 'tak'}).status_code == 400


def test_zakonczona_akcja_tylko_do_odczytu(leader_client):
    a = nowa_akcja(leader_client)
    ix = nowy_index(leader_client, a['id'])
    leader_client.put(f'/api/dekoracje/akcje/{a["id"]}/status', json={'zakonczona': True})

    assert leader_client.put(f'/api/dekoracje/akcje/{a["id"]}',
                             json={'nazwa': 'X', 'od': a['od'], 'do': a['do']}).status_code == 409
    assert leader_client.post(f'/api/dekoracje/akcje/{a["id"]}/indexy').status_code == 409
    assert leader_client.put(f'/api/dekoracje/indexy/{ix["id"]}', json={'rgd': 5}).status_code == 409
    assert leader_client.delete(f'/api/dekoracje/indexy/{ix["id"]}').status_code == 409


# ── indexy ───────────────────────────────────────────────────────────────────

def test_index_haki_lacznie_i_sumy_akcji(leader_client):
    a = nowa_akcja(leader_client)
    twin = pozycja(TYP_STOJAKA, 'Twin')
    gondola = pozycja(MODEL_STOJAKA, 'Gondola')
    ix = nowy_index(leader_client, a['id'], ilosc_stojakow=12, haki_na_stojak=40, strony_na_stojak=2,
                    typ_id=twin.id, model_id=gondola.id, rgd=300, displays=24, akcesoria=150, pos=12,
                    prod_hakowania=180.5, prod_dekorowania=95)
    assert ix['haki'] == 480 and ix['nazwa'] == 'Index 1'
    assert ix['prod_hakowania'] == 180.5 and ix['typ_id'] == twin.id
    nowy_index(leader_client, a['id'], ilosc_stojakow=3)   # bez haków na stojak

    html = leader_client.get(f'/displays/akcje/{a["id"]}').get_data(as_text=True)
    assert 'Index 2' in html and 'niepełna' in html
    assert 'data-suma="ilosc_stojakow">15<' in html and 'data-suma="haki">480<' in html


def test_index_czesciowy_zapis_nie_rusza_innych_pol(leader_client):
    a = nowa_akcja(leader_client)
    ix = nowy_index(leader_client, a['id'], rgd=10, pos=4)
    r = leader_client.put(f'/api/dekoracje/indexy/{ix["id"]}', json={'pos': None, 'nazwa': 'IDX-77'})
    d = r.get_json()
    assert d['rgd'] == 10 and d['pos'] is None and d['nazwa'] == 'IDX-77'


@pytest.mark.parametrize('pole,wartosc', [
    ('ilosc_stojakow', -1), ('ilosc_stojakow', 1.5), ('rgd', True), ('pos', 'dużo'),
    ('haki_na_stojak', 100_000), ('prod_hakowania', -2), ('nazwa', ''),
])
def test_index_bledne_wartosci(leader_client, pole, wartosc):
    a = nowa_akcja(leader_client)
    ix = nowy_index(leader_client, a['id'])
    assert leader_client.put(f'/api/dekoracje/indexy/{ix["id"]}', json={pole: wartosc}).status_code == 400


def test_index_usun(leader_client):
    a = nowa_akcja(leader_client)
    ix = nowy_index(leader_client, a['id'])
    assert leader_client.delete(f'/api/dekoracje/indexy/{ix["id"]}').status_code == 200
    assert 'Index 1' not in leader_client.get(f'/displays/akcje/{a["id"]}').get_data(as_text=True)


def test_wylaczona_pozycja_tylko_w_indexie_ktory_ja_ma(leader_client):
    a = nowa_akcja(leader_client)
    solo = pozycja(TYP_STOJAKA, 'Solo')
    ma = nowy_index(leader_client, a['id'], typ_id=solo.id)
    nie_ma = nowy_index(leader_client, a['id'])
    solo.aktywna = False
    db.session.commit()

    assert leader_client.put(f'/api/dekoracje/indexy/{ma["id"]}', json={'typ_id': solo.id}).status_code == 200
    assert leader_client.put(f'/api/dekoracje/indexy/{nie_ma["id"]}', json={'typ_id': solo.id}).status_code == 400
    # Model z listy typów → 400.
    assert leader_client.put(f'/api/dekoracje/indexy/{nie_ma["id"]}',
                             json={'model_id': pozycja(TYP_STOJAKA, 'Twin').id}).status_code == 400
    html = leader_client.get(f'/displays/akcje/{a["id"]}').get_data(as_text=True)
    assert 'Solo (wyłączony)' in html


# ── listy w Supervisor ───────────────────────────────────────────────────────

def test_listy_admin_dodaje_lider_nie(client, flask_app):
    lider = make_user('leader')
    login(client, lider.username)
    assert client.post('/api/dekoracje/slownik', json={'rodzaj': TYP_STOJAKA, 'nazwa': 'Trio'}).status_code == 403
    client.post('/logout')
    login(client, make_user('admin').username)
    r = client.post('/api/dekoracje/slownik', json={'rodzaj': TYP_STOJAKA, 'nazwa': 'Trio'})
    assert r.status_code == 201
    assert client.post('/api/dekoracje/slownik', json={'rodzaj': TYP_STOJAKA, 'nazwa': 'Trio'}).status_code == 409
    html = client.get('/admin/dekoracje').get_data(as_text=True)
    assert 'Trio' in html and 'data-api="/api/dekoracje/slownik"' in html


def test_uzytej_pozycji_nie_da_sie_usunac(admin_client):
    a = nowa_akcja(admin_client)
    twin = pozycja(TYP_STOJAKA, 'Twin')
    nowy_index(admin_client, a['id'], typ_id=twin.id)
    assert admin_client.delete(f'/api/dekoracje/slownik/{twin.id}').status_code == 409
    assert admin_client.put(f'/api/dekoracje/slownik/{twin.id}', json={'aktywna': False}).status_code == 200
    solo = pozycja(TYP_STOJAKA, 'Solo')
    assert admin_client.delete(f'/api/dekoracje/slownik/{solo.id}').status_code == 200


# ── uprawnienia ──────────────────────────────────────────────────────────────

def test_stanowisko_nie_ma_dostepu(flask_app):
    klient = flask_app.test_client()
    login(klient, make_user('stanowisko').username)
    assert klient.post('/api/dekoracje/akcje', json={'nazwa': 'X', 'od': '2026-11-01',
                                                      'do': '2026-11-02'}).status_code == 403
    r = klient.get('/displays/historia')
    assert r.status_code == 302 and '/start' in r.headers['Location']


def test_ekran_akcji_wola_tylko_api_dekoracji(leader_client):
    import re
    a = nowa_akcja(leader_client)
    nowy_index(leader_client, a['id'])
    tekst = strona_z_js(leader_client, f'/displays/akcje/{a["id"]}')
    reguly = [(r.rule, r.endpoint) for r in leader_client.application.url_map.iter_rules()
              if r.rule.startswith('/api/')]
    for api in set(re.findall(r'/api/[A-Za-z0-9_/-]+', tekst)):
        baza = api.rstrip('/')
        pasujace = [ep for regula, ep in reguly if regula == baza or regula.startswith(baza + '/')]
        assert pasujace and any(DISPLAYS in obszary_endpointu(ep) for ep in pasujace), api
