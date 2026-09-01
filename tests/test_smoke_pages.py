"""Kazda strona musi sie wyrenderowac. Lapie bledy w szablonach (np. brakujacy
helper w base.html) i regresje uprawnien na trasach."""
import pytest

import app as logistat

# Trasy renderujace strony (bez API i eksportow)
STRONY_ADMINA = [
    '/dashboard', '/forecast', '/scanner/1', '/scanner/2', '/assignment',
    '/data-entry', '/stats', '/scan-package', '/scan-paczki', '/paczki',
    '/time-tracking', '/worker-times', '/profile',
    '/admin/users', '/admin/activities', '/admin/panel',
    '/admin/country-mapping', '/admin/cost-mapping', '/admin/settings',
    '/import-csv', '/general-stats',
]

# Strony dostepne liderowi (bez sekcji admin-only)
STRONY_LIDERA = [
    '/dashboard', '/forecast', '/scanner/1', '/assignment', '/data-entry',
    '/stats', '/scan-package', '/scan-paczki', '/paczki', '/time-tracking',
    '/worker-times', '/profile', '/admin/users',
]

TYLKO_ADMIN = [
    '/admin/activities', '/admin/panel', '/admin/country-mapping',
    '/admin/cost-mapping', '/admin/settings', '/import-csv', '/general-stats',
]


@pytest.mark.parametrize('url', STRONY_ADMINA)
def test_strona_renderuje_sie_dla_admina(admin_client, url):
    r = admin_client.get(url)

    assert r.status_code == 200, f'{url} -> {r.status_code}'


@pytest.mark.parametrize('url', STRONY_LIDERA)
def test_strona_renderuje_sie_dla_lidera(leader_client, url):
    r = leader_client.get(url)

    assert r.status_code == 200, f'{url} -> {r.status_code}'


@pytest.mark.parametrize('url', TYLKO_ADMIN)
def test_strony_admin_only_odsylaja_lidera(leader_client, url):
    r = leader_client.get(url)

    assert r.status_code == 302, f'{url} powinno byc tylko dla admina'


@pytest.mark.parametrize('url', ['/dashboard', '/paczki', '/admin/panel'])
def test_niezalogowany_idzie_na_login(client, url):
    r = client.get(url)

    assert r.status_code == 302
    assert '/login' in r.headers['Location']


def test_login_renderuje_sie(client):
    assert client.get('/login').status_code == 200


def test_cache_buster_wstawia_mtime(admin_client):
    """base.html ma `static_v('style.css')` — wersja z mtime pliku, nie recznie
    wpisane ?v=6."""
    html = admin_client.get('/dashboard').get_data(as_text=True)

    assert 'style.css?v=' in html
    wersja = html.split('style.css?v=')[1].split('"')[0]
    assert wersja.isdigit() and len(wersja) >= 10, f'oczekiwano mtime, jest {wersja!r}'


def test_escapehtml_jest_dostepny_wszedzie(admin_client):
    for url in ('/dashboard', '/scan-package', '/worker-times'):
        html = admin_client.get(url).get_data(as_text=True)
        assert 'function escapeHtml' in html, url


def test_lider_nie_widzi_opcji_admina_w_formularzu(leader_client):
    html = leader_client.get('/admin/users').get_data(as_text=True)

    assert '<option value="admin">' not in html
    assert '<option value="leader">' not in html
    assert '<option value="operator">' in html


def test_admin_widzi_wszystkie_role(admin_client):
    html = admin_client.get('/admin/users').get_data(as_text=True)

    assert '<option value="admin">' in html


def test_eksport_excela_zwraca_plik(admin_client):
    r = admin_client.get('/general-stats/export')

    assert r.status_code == 200
    assert 'spreadsheetml' in r.headers['Content-Type']
    assert r.get_data()[:2] == b'PK', 'xlsx to zip'


def test_eksport_forecastu_zwraca_plik(leader_client):
    r = leader_client.get('/api/forecast/export?date_from=2026-09-01&date_to=2026-09-05')

    assert r.status_code == 200
    assert r.get_data()[:2] == b'PK'


def test_dashboard_api_odpowiada(leader_client):
    d = leader_client.get('/api/dashboard').get_json()

    assert set(d) >= {'total_cartons', 'done_today', 'per_worker', 'as_of'}
