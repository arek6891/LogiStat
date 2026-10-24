"""Kafelki po zalogowaniu: Magazyn / Post-Process / Ustawienia (operacja 2026-10-24).

- rola → kafelki: stanowisko = Magazyn, lider = Magazyn + Post-Process,
  admin = wszystkie trzy; konto stanowiska po zalogowaniu od razu w Magazynie,
- kafelek = twarda blokada: ekran spoza wybranego kafelka odsyla do kafelkow,
  API dostaje 403 JSON — takze dla lidera i admina,
- konto stanowiska nie wejdzie na zaden ekran ani API Post-Process / Ustawien,
- kazda trasa aplikacji jest przypisana do kafelka albo do wspolnych.
"""
import pytest
from conftest import login, make_user

from logistat.obszary import MAGAZYN, POST_PROCESS, USTAWIENIA, obszary_endpointu, \
    wszystkie_przypisane


@pytest.fixture
def z_kafelkami(flask_app):
    flask_app.config['OBSZARY_WYMUSZANE'] = True
    yield flask_app
    flask_app.config['OBSZARY_WYMUSZANE'] = False


def zaloguj(client, rola):
    u = make_user(rola)
    r = login(client, u.username)
    return u, r


def wybierz(client, obszar):
    return client.post(f'/start/{obszar}')


# ── mapa tras ────────────────────────────────────────────────────────────────

def test_kazda_trasa_ma_kafelek(flask_app):
    nieprzypisane = sorted(r.endpoint for r in flask_app.url_map.iter_rules()
                           if r.endpoint not in wszystkie_przypisane())
    assert nieprzypisane == [], 'nowa trasa → dopisz ja w logistat/obszary.py'


def test_ekrany_stanowisk_sa_w_magazynie():
    for ep in ('stanowisko.scan_paczki', 'stanowisko.api_package_time_end',
               'czas_pracy.api_time_scan', 'stanowisko.scanner'):
        assert obszary_endpointu(ep) == {MAGAZYN}
    assert obszary_endpointu('admin.api_settings_update') == {USTAWIENIA}
    assert obszary_endpointu('dashboard.api_dashboard') == {POST_PROCESS}


# ── stanowisko ───────────────────────────────────────────────────────────────

def test_stanowisko_loguje_sie_i_trafia_od_razu_do_magazynu(client, z_kafelkami):
    _, r = zaloguj(client, 'stanowisko')
    assert r.status_code == 302 and r.headers['Location'].endswith('/start')

    r = client.get('/start')

    assert r.status_code == 302 and r.headers['Location'].endswith('/scan-paczki')
    with client.session_transaction() as s:
        assert s['obszar'] == MAGAZYN and s.permanent is True
    assert client.get('/scan-paczki').status_code == 200
    assert client.get('/time-tracking').status_code == 200


def test_stanowisko_nie_wejdzie_do_post_process_ani_ustawien(client, z_kafelkami):
    zaloguj(client, 'stanowisko')
    client.get('/start')

    for adres in ('/dashboard', '/paczki', '/admin/panel', '/admin/users'):
        r = client.get(adres)
        assert r.status_code == 302 and '/start' in r.headers['Location'], adres
    for adres in ('/api/dashboard', '/api/users', '/api/general-stats'):
        assert client.get(adres).status_code == 403, adres
    assert client.post('/start/post_process').status_code == 403


def test_stanowisko_zablokowane_dekoratorem_takze_bez_kafelkow(client):
    """Uprawnienia roli nie zaleza od blokady kafelkow (testy maja ja wylaczona)."""
    zaloguj(client, 'stanowisko')

    assert client.get('/api/dashboard').status_code == 403
    assert client.put('/api/settings', json={}).status_code == 403
    assert client.get('/api/employee-lookup?barcode=x').status_code in (400, 404)


def test_stanowisko_menu_bez_lidera_i_hasla(client, z_kafelkami):
    zaloguj(client, 'stanowisko')
    client.get('/start')

    html = client.get('/scan-paczki').get_data(as_text=True)

    assert 'Czasy paczek' in html and 'Skaner zmian' in html
    assert 'Dashboard' not in html and 'Panel Admina' not in html
    assert 'Zmień hasło' not in html and '⬅ Kafelki' not in html


def test_operator_dalej_sie_nie_loguje(client):
    u = make_user('operator')
    u.set_password('haslo1234')
    from logistat.extensions import db
    db.session.commit()

    r = client.post('/login', data={'username': u.username, 'password': 'haslo1234'})

    assert r.status_code == 200 and 'Nieprawidłowy' in r.get_data(as_text=True)


# ── lider / admin ────────────────────────────────────────────────────────────

def test_lider_widzi_dwa_kafelki_admin_trzy(client, z_kafelkami):
    zaloguj(client, 'leader')
    html = client.get('/start').get_data(as_text=True)
    assert 'data-obszar="magazyn"' in html and 'data-obszar="post_process"' in html
    assert 'data-obszar="ustawienia"' not in html
    assert wybierz(client, USTAWIENIA).status_code == 403

    client.post('/logout')
    zaloguj(client, 'admin')
    html = client.get('/start').get_data(as_text=True)
    assert html.count('data-obszar=') == 3


def test_kafelek_to_twarda_blokada_dla_lidera(client, z_kafelkami):
    zaloguj(client, 'leader')
    r = wybierz(client, MAGAZYN)
    assert r.headers['Location'].endswith('/scan-paczki')

    r = client.get('/dashboard')
    assert r.status_code == 302 and '/start' in r.headers['Location']
    r = client.get('/api/dashboard')
    assert r.status_code == 403 and 'Post-Process' in r.get_json()['error']

    wybierz(client, POST_PROCESS)
    assert client.get('/dashboard').status_code == 200
    assert client.get('/api/employee-lookup?barcode=x').status_code == 403


def test_menu_pokazuje_tylko_wybrany_kafelek(client, z_kafelkami):
    zaloguj(client, 'admin')
    wybierz(client, POST_PROCESS)

    html = client.get('/dashboard').get_data(as_text=True)

    assert 'Przydzielanie' in html and '⬅ Kafelki' in html
    assert 'Czasy paczek' not in html and 'Panel Admina' not in html


def test_link_do_ekranu_bez_wybranego_kafelka_wybiera_go_sam(client, z_kafelkami):
    """Zakladka /paczki po zalogowaniu lidera — jeden pasujacy kafelek, bez przystanku."""
    zaloguj(client, 'leader')

    assert client.get('/paczki').status_code == 200
    with client.session_transaction() as s:
        assert s['obszar'] == POST_PROCESS


def test_next_po_wyborze_kafelka(client, z_kafelkami):
    zaloguj(client, 'leader')
    wybierz(client, MAGAZYN)
    r = client.get('/stats')
    assert '/start?next=' in r.headers['Location']

    r = client.post('/start/post_process', data={'next': '/stats'})

    assert r.headers['Location'].endswith('/stats')


def test_logowanie_zeruje_wybrany_kafelek(client, z_kafelkami):
    u, _ = zaloguj(client, 'leader')
    wybierz(client, MAGAZYN)
    client.post('/logout')
    login(client, u.username)

    with client.session_transaction() as s:
        assert 'obszar' not in s
        assert not s.permanent, 'tylko stanowisko ma stala sesje'


# ── zakladanie kont stanowisk ────────────────────────────────────────────────

def test_konto_stanowiska_zaklada_tylko_admin(client, z_kafelkami):
    zaloguj(client, 'leader')
    wybierz(client, POST_PROCESS)
    r = client.post('/api/users', json={'username': 'stanowisko1', 'display_name': 'Stanowisko 1',
                                        'role': 'stanowisko', 'password': 'tablet123'})
    assert r.status_code == 403

    client.post('/logout')
    zaloguj(client, 'admin')
    wybierz(client, POST_PROCESS)
    r = client.post('/api/users', json={'username': 'stanowisko1', 'display_name': 'Stanowisko 1',
                                        'role': 'stanowisko', 'password': 'tablet123'})
    assert r.status_code == 201, r.get_json()
    client.post('/logout')

    r = client.post('/login', data={'username': 'stanowisko1', 'password': 'tablet123'})
    assert r.status_code == 302


# ── strony kafelka siegaja tylko po API ze swojego kafelka ───────────────────

STRONY = {
    MAGAZYN: ['/scanner/1', '/time-tracking', '/scan-paczki', '/scan-package'],
    POST_PROCESS: ['/dashboard', '/forecast', '/assignment', '/data-entry', '/stats', '/paczki',
                   '/worker-times', '/import-csv', '/general-stats', '/admin/users'],
    USTAWIENIA: ['/admin/panel', '/admin/activities', '/admin/country-mapping',
                 '/admin/user-options', '/admin/category-labels', '/admin/settings',
                 '/admin/cost-mapping'],
}


@pytest.mark.parametrize('obszar', [MAGAZYN, POST_PROCESS, USTAWIENIA])
def test_strony_kafelka_wolaja_api_swojego_kafelka(client, z_kafelkami, obszar):
    """Mapa w logistat/obszary.py jest reczna — tu z wlaczona blokada: kazda
    strona kafelka otwiera sie, a kazdy adres /api/… z jej HTML-a i skryptow
    pasuje do trasy dostepnej w tym kafelku (inaczej ekran dostalby 403)."""
    import re
    from conftest import strona_z_js
    zaloguj(client, 'admin')
    wybierz(client, obszar)
    reguly = [(r.rule, r.endpoint) for r in client.application.url_map.iter_rules()
              if r.rule.startswith('/api/')]
    zle = []
    for adres in STRONY[obszar]:
        tekst = strona_z_js(client, adres)
        for api in set(re.findall(r'/api/[A-Za-z0-9_/-]+', tekst)):
            baza = api.rstrip('/')
            pasujace = [ep for regula, ep in reguly
                        if regula == baza or regula.startswith(baza + '/')]
            if not pasujace or not any(obszar in obszary_endpointu(ep) for ep in pasujace):
                zle.append((adres, api))
    assert zle == []


def test_wspolne_api_dziala_bez_wybranego_kafelka(client, z_kafelkami):
    """Karta otwarta przed wdrozeniem kafelkow (sesja bez `obszar`): API
    wspolne dwom kafelkom nie moze dostac 403 — nie da sie go wybrac samemu."""
    zaloguj(client, 'admin')

    assert client.get('/api/activities').status_code == 200
    with client.session_transaction() as s:
        assert 'obszar' not in s


def test_stanowisko_zostawia_panel_ilosci_przy_403_kafelka(client):
    js = client.get('/static/js/scan_paczki.js').get_data(as_text=True)

    assert 'res.status === 403 && data.obszar' in js
