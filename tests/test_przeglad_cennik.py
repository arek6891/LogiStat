"""Cennik (/admin/cost-mapping) — poprawki z przegladu 2026-10-24.

Blad wczytania stawek (np. chwilowy blad proxy) pokazywal formularz z samymi
zerami i dalo sie go zapisac — reszta stawek miesiaca szla na 0, koszty w
Statystykach ogolnych tez. Serwer nie sprawdzal tez miesiaca ani wartosci.
"""
import pytest

from logistat.models import CostMapping


def test_zapis_poprawnych_stawek(admin_client):
    r = admin_client.put('/api/cost-mapping/2026/10', json={'rates': {'textile': 0.25, 'sorting': 0}})

    assert r.status_code == 200
    assert CostMapping.query.one().get_rates_data() == {'textile': 0.25, 'sorting': 0}


@pytest.mark.parametrize('miesiac,cialo', [
    (13, {'rates': {'textile': 1}}),
    (0, {'rates': {'textile': 1}}),
    (10, {'rates': ['textile']}),
    (10, {'rates': {'textile': -1}}),
    (10, {'rates': {'textile': 'abc'}}),
    (10, {'rates': {'nieznana': 1}}),
])
def test_zle_stawki_400_nic_nie_zapisane(admin_client, miesiac, cialo):
    r = admin_client.put(f'/api/cost-mapping/2026/{miesiac}', json=cialo)

    assert r.status_code == 400
    assert CostMapping.query.count() == 0


def test_strona_nie_pokazuje_zer_po_bledzie_wczytania():
    js = open('static/js/admin_cost_mapping.js', encoding='utf-8').read()
    assert "res.ok ? await res.json() : {}" not in js
