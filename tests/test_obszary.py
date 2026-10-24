"""Kafelki po zalogowaniu: Magazyn / Post-Process / Akcje - Displays / Ustawienia
(operacja 2026-10-24).

- rola → kafelki: stanowisko = Magazyn, lider = Magazyn + Post-Process + Akcje - Displays,
  admin = wszystkie cztery; konto stanowiska po zalogowaniu od razu w Magazynie,
- kafelek wybiera tylko MENU (wersja lagodna, operacja 2026-10-24): ekran z innego
  kafelka roli otwiera sie i przelacza menu; API kafelka nie zmienia,
- konto stanowiska nie wejdzie na zaden ekran ani API Post-Process / Ustawien,
- kazda trasa aplikacji jest przypisana do kafelka albo do wspolnych.
"""
import pytest
from conftest import login, make_user

from logistat.obszary import DISPLAYS, MAGAZYN, POST_PROCESS, USTAWIENIA, obszary_endpointu, \
    wszystkie_przypisane


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

def test_stanowisko_loguje_sie_i_trafia_od_razu_do_magazynu(client):
    _, r = zaloguj(client, 'stanowisko')
    assert r.status_code == 302 and r.headers['Location'].endswith('/start')

    r = client.get('/start')

    assert r.status_code == 302 and r.headers['Location'].endswith('/scan-paczki')
    with client.session_transaction() as s:
        assert s['obszar'] == MAGAZYN and s.permanent is True
    assert client.get('/scan-paczki').status_code == 200
    assert client.get('/time-tracking').status_code == 200


def test_stanowisko_nie_wejdzie_do_post_process_ani_ustawien(client):
    zaloguj(client, 'stanowisko')
    client.get('/start')

    for adres in ('/dashboard', '/paczki', '/admin/panel', '/admin/users'):
        r = client.get(adres)
        assert r.status_code == 302 and '/start' in r.headers['Location'], adres
    for adres in ('/api/dashboard', '/api/users', '/api/general-stats'):
        assert client.get(adres).status_code == 403, adres
    assert client.post('/start/post_process').status_code == 403


def test_stanowisko_nie_dostanie_api_lidera_ani_admina(client):
    zaloguj(client, 'stanowisko')

    assert client.put('/api/settings', json={}).status_code == 403
    assert client.post('/api/users', json={}).status_code == 403
    assert client.get('/api/employee-lookup?barcode=x').status_code in (400, 404)


def test_stanowisko_menu_bez_lidera_i_hasla(client):
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

def test_lider_widzi_trzy_kafelki_admin_cztery(client):
    zaloguj(client, 'leader')
    html = client.get('/start').get_data(as_text=True)
    assert 'data-obszar="magazyn"' in html and 'data-obszar="post_process"' in html
    assert 'data-obszar="displays"' in html and 'Akcje - Displays' in html
    assert 'data-obszar="ustawienia"' not in html
    assert wybierz(client, USTAWIENIA).status_code == 403

    client.post('/logout')
    zaloguj(client, 'admin')
    html = client.get('/start').get_data(as_text=True)
    assert html.count('data-obszar=') == 4


def test_kafelek_wybiera_tylko_menu(client):
    """Lider w Magazynie otwiera Dashboard — ekran sie otwiera, menu przelacza
    sie na Post-Process. API innego kafelka dziala i NIE przestawia menu, wiec
    dwie karty na roznych kafelkach pracuja obie."""
    zaloguj(client, 'leader')
    r = wybierz(client, MAGAZYN)
    assert r.headers['Location'].endswith('/scan-paczki')

    assert client.get('/api/dashboard').status_code == 200
    with client.session_transaction() as s:
        assert s['obszar'] == MAGAZYN, 'API nie zmienia kafelka'

    html = client.get('/dashboard').get_data(as_text=True)
    assert 'Przydzielanie' in html and 'Czasy paczek' not in html
    with client.session_transaction() as s:
        assert s['obszar'] == POST_PROCESS
    assert client.get('/api/employee-lookup?barcode=x').status_code in (400, 404)


def test_menu_pokazuje_tylko_wybrany_kafelek(client):
    zaloguj(client, 'admin')
    wybierz(client, POST_PROCESS)

    html = client.get('/dashboard').get_data(as_text=True)

    assert 'Przydzielanie' in html and '⬅ Kafelki' in html
    assert 'Czasy paczek' not in html and 'Panel Admina' not in html


def test_link_do_ekranu_bez_wybranego_kafelka_wybiera_go_sam(client):
    """Zakladka /paczki po zalogowaniu lidera — otwiera sie od razu, menu Post-Process."""
    zaloguj(client, 'leader')

    assert client.get('/paczki').status_code == 200
    with client.session_transaction() as s:
        assert s['obszar'] == POST_PROCESS


def test_wybor_kafelka_otwiera_jego_start(client):
    zaloguj(client, 'admin')

    assert client.post('/start/post_process').headers['Location'].endswith('/dashboard')
    assert client.post('/start/displays').headers['Location'].endswith('/displays')
    assert client.post('/start/ustawienia').headers['Location'].endswith('/admin/panel')


def test_logowanie_zeruje_wybrany_kafelek(client):
    u, _ = zaloguj(client, 'leader')
    wybierz(client, MAGAZYN)
    client.post('/logout')
    login(client, u.username)

    with client.session_transaction() as s:
        assert 'obszar' not in s
        assert not s.permanent, 'tylko stanowisko ma stala sesje'


# ── Akcje - Displays (nowy modul, na razie pusty) ────────────────────────────

def test_displays_dla_lidera_i_admina_nie_dla_stanowiska(client):
    for rola in ('leader', 'admin'):
        zaloguj(client, rola)
        wybierz(client, DISPLAYS)
        html = client.get('/displays').get_data(as_text=True)
        assert 'w przygotowaniu' in html and '📺 Akcje - Displays' in html, rola
        assert 'Przydzielanie' not in html, 'menu tylko kafelka Displays'
        client.post('/logout')

    zaloguj(client, 'stanowisko')
    r = client.get('/displays')
    assert r.status_code == 302 and '/start' in r.headers['Location']
    assert wybierz(client, DISPLAYS).status_code == 403


# ── menu A→Z ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('obszar,adres', [(MAGAZYN, '/scan-paczki'),
                                          (POST_PROCESS, '/dashboard'),
                                          (USTAWIENIA, '/admin/panel')])
def test_menu_kafelka_alfabetycznie(client, obszar, adres):
    """Operacja 2026-10-24: pozycje menu po lewej od A (gora) do Z (dol)."""
    import re
    zaloguj(client, 'admin')
    wybierz(client, obszar)
    html = client.get(adres).get_data(as_text=True)
    menu = html[html.index('class="sidebar-nav"'):html.index('class="sidebar-footer"')]
    nazwy = [n.strip() for n in re.findall(r'</span>\s*([^<]+?)\s*</a>', menu)]
    alfabet = ' aąbcćdeęfghijklłmnńoóprsśtuwyzźż'
    assert len(nazwy) > 1
    assert nazwy == sorted(nazwy, key=lambda t: [alfabet.find(c) for c in t.lower()])


# ── zakladanie kont stanowisk ────────────────────────────────────────────────

def test_konto_stanowiska_zaklada_tylko_admin(client):
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
    DISPLAYS: ['/displays'],
    USTAWIENIA: ['/admin/panel', '/admin/activities', '/admin/country-mapping',
                 '/admin/user-options', '/admin/category-labels', '/admin/settings',
                 '/admin/cost-mapping'],
}


@pytest.mark.parametrize('obszar', [MAGAZYN, POST_PROCESS, DISPLAYS, USTAWIENIA])
def test_strony_kafelka_wolaja_api_swojego_kafelka(client, obszar):
    """Mapa w logistat/obszary.py jest reczna: kazdy adres /api/… z HTML-a
    i skryptow strony kafelka pasuje do trasy przypisanej temu kafelkowi —
    inaczej konto stanowiska (tylko Magazyn) dostaloby 403 na swoim ekranie."""
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
