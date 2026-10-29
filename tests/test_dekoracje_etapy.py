"""Dekoracje — kamienie milowe akcji (operacja 2026-10-29).

- 9 stalych etapow (w bazie klucz), termin od–do wewnatrz dat akcji, obie daty
  razem albo obie puste; „nie dotyczy” tylko Picking,
- stan liczy serwer: ⏳ konczy sie (≤ DNI_OSTRZEZENIA_ETAPU dni do konca, koniec
  wlacznie), ⚠ po terminie; bez dat bez ostrzezenia,
- zmiana dat akcji nie moze zostawic etapu poza nimi (400), zakonczona akcja 409,
- Gantt dostaje ostrzezenia etapow.
Dane syntetyczne.
"""
from datetime import date, timedelta

import pytest
from test_dekoracje import nowa_akcja

from logistat.czas import local_today
from logistat.dekoracje import DNI_OSTRZEZENIA_ETAPU, ETAPY_AKCJI, KLUCZE_ETAPOW, stan_etapu
from logistat.models import EtapAkcji


def url(akcja, etap):
    return f'/api/dekoracje/akcje/{akcja["id"]}/etapy/{etap}'


def termin(client, akcja, etap, od, do, status=200):
    r = client.put(url(akcja, etap), json={'od': od.isoformat() if od else '', 'do': do.isoformat() if do else ''})
    assert r.status_code == status, r.get_json()
    return r.get_json()


# ── czysta logika ────────────────────────────────────────────────────────────

def test_lista_etapow():
    assert len(ETAPY_AKCJI) == 9 and len(set(KLUCZE_ETAPOW)) == 9
    assert [k for k, _, _, opcjonalny in ETAPY_AKCJI if opcjonalny] == ['picking']


def test_stan_etapu_granice():
    dzis = date(2026, 11, 10)
    do = dzis + timedelta(days=DNI_OSTRZEZENIA_ETAPU)
    assert stan_etapu(None, None, dzis) == 'bez_terminu'
    assert stan_etapu(dzis, dzis, dzis, nie_dotyczy=True) == 'nie_dotyczy'
    assert stan_etapu(dzis + timedelta(days=1), dzis + timedelta(days=9), dzis) == 'planowany'
    assert stan_etapu(dzis - timedelta(days=1), dzis + timedelta(days=9), dzis) == 'w_toku'
    assert stan_etapu(dzis, do + timedelta(days=1), dzis) == 'w_toku'
    assert stan_etapu(dzis - timedelta(days=5), do, dzis) == 'konczy_sie'
    assert stan_etapu(dzis - timedelta(days=5), dzis, dzis) == 'konczy_sie', 'dzien konca wlacznie'
    assert stan_etapu(dzis - timedelta(days=5), dzis - timedelta(days=1), dzis) == 'po_terminie'
    # Krotki etap w przyszlosci, ale konczy sie za ≤ N dni → tez ⏳
    assert stan_etapu(dzis + timedelta(days=1), dzis + timedelta(days=1), dzis) == 'konczy_sie'


# ── API ──────────────────────────────────────────────────────────────────────

def test_termin_etapu_i_stan(leader_client):
    dzis = local_today()
    a = nowa_akcja(leader_client, od=dzis - timedelta(days=10), do=dzis + timedelta(days=20))
    e = termin(leader_client, a, 'komponenty', dzis - timedelta(days=10), dzis - timedelta(days=1))
    assert e['stan'] == 'po_terminie' and e['nazwa'] == 'Dostawa komponentów'
    e = termin(leader_client, a, 'produkty', dzis - timedelta(days=2), dzis + timedelta(days=1))
    assert e['stan'] == 'konczy_sie'
    termin(leader_client, a, 'wysylka', dzis + timedelta(days=15), dzis + timedelta(days=20))

    d = leader_client.get(f'/displays/akcje/{a["id"]}').get_data(as_text=True)
    assert '🏁 Kamienie milowe' in d and '"klucz": "komponenty"' in d   # tojson: ASCII

    # ponowny zapis aktualizuje ten sam wiersz; obie puste = bez terminu
    termin(leader_client, a, 'wysylka', dzis + timedelta(days=16), dzis + timedelta(days=19))
    assert EtapAkcji.query.filter_by(etap='wysylka').count() == 1
    assert termin(leader_client, a, 'wysylka', None, None)['stan'] == 'bez_terminu'


@pytest.mark.parametrize('od, do, blad', [
    (0, None, 'obie daty'),
    (5, 2, 'przed datą startu'),
    (-1, 3, 'w datach akcji'),
    (2, 11, 'w datach akcji'),
])
def test_termin_etapu_bledny(leader_client, od, do, blad):
    start = date(2026, 11, 1)
    a = nowa_akcja(leader_client, od=start, do=start + timedelta(days=10))
    body = {'od': (start + timedelta(days=od)).isoformat(),
            'do': (start + timedelta(days=do)).isoformat() if do is not None else ''}
    r = leader_client.put(url(a, 'assembly'), json=body)
    assert r.status_code == 400 and blad in r.get_json()['error']
    assert EtapAkcji.query.count() == 0


def test_nie_dotyczy_tylko_picking(leader_client):
    a = nowa_akcja(leader_client)
    r = leader_client.put(url(a, 'picking'), json={'nie_dotyczy': True})
    assert r.status_code == 200 and r.get_json()['stan'] == 'nie_dotyczy'
    assert leader_client.put(url(a, 'hakowanie'), json={'nie_dotyczy': True}).status_code == 400
    assert leader_client.put(url(a, 'nieznany'), json={'od': ''}).status_code == 404


def test_daty_akcji_nie_moga_zgubic_etapu(leader_client):
    start = date(2026, 11, 1)
    a = nowa_akcja(leader_client, od=start, do=start + timedelta(days=30))
    termin(leader_client, a, 'pakowanie', start + timedelta(days=20), start + timedelta(days=25))
    r = leader_client.put(f'/api/dekoracje/akcje/{a["id"]}', json={
        'nazwa': a['nazwa'], 'od': start.isoformat(), 'do': (start + timedelta(days=22)).isoformat()})
    assert r.status_code == 400 and 'Pakowanie' in r.get_json()['error']
    r = leader_client.put(f'/api/dekoracje/akcje/{a["id"]}', json={
        'nazwa': a['nazwa'], 'od': start.isoformat(), 'do': (start + timedelta(days=25)).isoformat()})
    assert r.status_code == 200


def test_zakonczona_akcja_etapy_tylko_do_odczytu(leader_client):
    a = nowa_akcja(leader_client)
    leader_client.put(f'/api/dekoracje/akcje/{a["id"]}/status', json={'zakonczona': True})
    dzis = local_today()
    termin(leader_client, a, 'komponenty', dzis, dzis, status=409)


def test_gantt_pokazuje_ostrzezenia(leader_client):
    dzis = local_today()
    a = nowa_akcja(leader_client, od=dzis - timedelta(days=10), do=dzis + timedelta(days=20))
    termin(leader_client, a, 'komponenty', dzis - timedelta(days=10), dzis - timedelta(days=1))
    termin(leader_client, a, 'opakowania', dzis, dzis)
    nowa_akcja(leader_client, nazwa='Spokojna')
    from logistat.dekoracje_dane import akcje_gantt
    akcje = {x['nazwa']: x for x in akcje_gantt(dzis)}
    assert [(o['nazwa'], o['stan']) for o in akcje[a['nazwa']]['ostrzezenia']] == [
        ('Dostawa komponentów', 'po_terminie'), ('Dostawa materiałów opakowaniowych', 'konczy_sie')]
    assert akcje['Spokojna']['ostrzezenia'] == []
    assert 'ostrzezenia' in leader_client.get('/displays').get_data(as_text=True)
