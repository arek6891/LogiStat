"""Przeglad bezpieczenstwa 2026-11-09 — mniejsze punkty:

- zmiana hasla uniewaznia wczesniejsze sesje konta (ciasteczko skopiowane
  z tabletu stanowiska dzialalo do 30 dni po zmianie hasla),
- konto stanowiska nie dostaje loginow, rol i kodow identyfikatorow innych
  osob ani obecnosci z innych dni,
- nazwa pliku eksportu nie bierze surowego tekstu z zapytania,
- nieznany login kosztuje tyle samo co zle haslo (czas nie zdradza kont).
Dane syntetyczne.
"""
from datetime import timedelta

from conftest import PASSWORD, login, make_user

from logistat.czas import local_today
from logistat.extensions import db
from logistat.models import ShiftAttendance, get_or_create_shift


def klient_zalogowany(flask_app, user):
    k = flask_app.test_client()
    assert login(k, user.username).status_code == 302
    return k


# ── sesja a zmiana hasla ─────────────────────────────────────────────────────

def test_zmiana_hasla_przez_admina_wylogowuje_stare_sesje(flask_app, admin):
    st = make_user('stanowisko')
    tablet = klient_zalogowany(flask_app, st)
    assert tablet.get('/scan-paczki').status_code == 200

    adm = klient_zalogowany(flask_app, admin)
    r = adm.put(f'/api/users/{st.id}', json={'password': 'nowe-haslo-9'})
    assert r.status_code == 200, r.get_json()

    r = tablet.get('/api/employee-lookup?barcode=x')
    assert r.status_code == 401, 'stare ciasteczko po zmianie hasla nie moze dzialac'
    assert login(flask_app.test_client(), st.username, 'nowe-haslo-9').status_code == 302


def test_wlasna_zmiana_hasla_zostawia_te_karte(flask_app):
    lider = make_user('leader')
    ta = klient_zalogowany(flask_app, lider)
    inna = klient_zalogowany(flask_app, lider)

    r = ta.post('/profile', data={'current_password': PASSWORD, 'new_password': 'nowe-haslo-9',
                                  'confirm_password': 'nowe-haslo-9'})
    assert r.status_code == 302

    assert ta.get('/api/users').status_code == 200
    assert inna.get('/api/users').status_code == 401


def test_admin_zmienia_wlasne_haslo_i_zostaje_zalogowany(flask_app, admin):
    k = klient_zalogowany(flask_app, admin)
    assert k.put(f'/api/users/{admin.id}', json={'password': 'nowe-haslo-9'}).status_code == 200
    assert k.get('/api/users').status_code == 200


# ── konto stanowiska: mniej danych ───────────────────────────────────────────

def test_stanowisko_nie_dostaje_kodow_ani_loginow(flask_app):
    lider = make_user('leader', barcode_id='L-SEKRET')
    op = make_user('operator', barcode_id='OP-1')
    wczoraj = get_or_create_shift(local_today() - timedelta(days=1), 1)
    db.session.add(ShiftAttendance(shift_id=wczoraj.id, user_id=lider.id))
    db.session.commit()
    tablet = klient_zalogowany(flask_app, make_user('stanowisko'))

    r = tablet.post('/api/scan', json={'barcode': 'OP-1', 'shift_number': 1})
    assert r.status_code == 201
    assert r.get_json()['user'] == {'id': op.id, 'display_name': op.display_name}
    assert r.get_json()['attendance']['user'] == {'id': op.id, 'display_name': op.display_name}

    dzis = tablet.get('/api/shift/attendances?shift_number=1').get_json()
    assert [a['user'] for a in dzis['attendances']] == [{'id': op.id, 'display_name': op.display_name}]
    r = tablet.get(f'/api/shift/attendances?date={wczoraj.date.isoformat()}&shift_number=1')
    assert 'L-SEKRET' not in r.get_data(as_text=True), 'stanowisko widzi tylko dzisiejsza zmiane'


def test_lider_dalej_widzi_pelne_dane(flask_app):
    make_user('operator', barcode_id='OP-2')
    k = klient_zalogowany(flask_app, make_user('leader'))
    r = k.post('/api/scan', json={'barcode': 'OP-2', 'shift_number': 1})
    assert r.get_json()['user']['barcode_id'] == 'OP-2'


# ── nazwy plikow eksportu ────────────────────────────────────────────────────

def test_nazwa_pliku_eksportu_bez_tekstu_z_zapytania(admin_client):
    zly = 'x"; filename=evil.exe; a="'
    for adres in ('/api/forecast/export', '/general-stats/export'):
        r = admin_client.get(adres, query_string={'date_from': zly, 'date_to': zly})
        assert r.status_code == 200, adres
        naglowek = r.headers['Content-Disposition']
        assert 'evil' not in naglowek and naglowek.count('"') == 2, (adres, naglowek)


# ── czas logowania ───────────────────────────────────────────────────────────

def test_nieznany_login_tez_liczy_hash(client, monkeypatch):
    import logistat.web.auth as auth
    wolania = []
    prawdziwe = auth.check_password_hash
    monkeypatch.setattr(auth, 'check_password_hash',
                        lambda h, p: wolania.append(p) or prawdziwe(h, p))

    r = client.post('/login', data={'username': 'nie-ma-takiego', 'password': 'cokolwiek'})

    assert r.status_code == 200 and wolania == ['cokolwiek']
