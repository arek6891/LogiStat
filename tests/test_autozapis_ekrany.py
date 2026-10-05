"""Ekrany wsadowe zapisuja sie same — zapominany przycisk „Zapisz" gubil prace
(operacja, 2026-10). Logika siedzi w JS (`autoZapis` w base.html) i pytest jej
nie wykona; te testy pilnuja tylko, zeby przycisk nie wrocil, a strony mialy
wskaznik stanu i wspolny helper. Zachowanie sprawdzone w przegladarce.
"""
import pytest

EKRANY_AUTOZAPISU = {
    '/assignment': 'saveAssignments()">',
    '/data-entry': 'saveEntries()">',
    '/forecast': 'saveAll()">',
    '/general-stats': 'saveAll()">',
}


@pytest.mark.parametrize('url,stary_przycisk', EKRANY_AUTOZAPISU.items())
def test_ekran_wsadowy_ma_autozapis_zamiast_przycisku(admin_client, url, stary_przycisk):
    html = admin_client.get(url).get_data(as_text=True)

    assert 'id="autoZapisStatus"' in html
    assert 'autoZapis.zaplanuj(' in html
    assert stary_przycisk not in html


@pytest.mark.parametrize('url', ['/data-entry', '/forecast', '/general-stats'])
def test_pola_zapisuja_sie_po_pauzie_w_pisaniu(admin_client, url):
    """Sam `change` gubil ostatnia liczbe przy zamknieciu karty z kursorem w polu."""
    assert 'autoZapis.poWpisaniu(' in admin_client.get(url).get_data(as_text=True)


def test_helper_autozapisu_i_straznik_modali_sa_w_base(admin_client):
    html = admin_client.get('/dashboard').get_data(as_text=True)

    assert 'const autoZapis' in html
    assert 'async function zapiszJson' in html
    assert 'function poWpisaniu' in html
    assert "hasAttribute('data-modal-guard')" in html


@pytest.mark.parametrize('url,modal', [
    ('/admin/users', 'id="userModal" data-modal-guard'),
    ('/admin/activities', 'id="activityModal" data-modal-guard'),
    ('/admin/country-mapping', 'id="mappingModal" data-modal-guard'),
    ('/paczki', 'id="addPackageModal" data-modal-guard'),
    ('/worker-times', 'id="eventModal" data-modal-guard'),
])
def test_modal_z_formularzem_jest_chroniony(admin_client, url, modal):
    assert modal in admin_client.get(url).get_data(as_text=True)


@pytest.mark.parametrize('nr', [1, 2])
def test_skaner_oznacza_zmiane_kolorem(admin_client, nr):
    html = admin_client.get(f'/scanner/{nr}').get_data(as_text=True)

    assert f'class="scanner-page" data-shift="{nr}"' in html
    assert f'class="scanner-shift-badge" data-shift="{nr}"' in html
