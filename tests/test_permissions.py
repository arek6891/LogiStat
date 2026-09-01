"""Granice uprawnien wokol kont uzytkownikow.

Trasa /admin/users i endpointy /api/users sa dostepne dla lidera (lider
zaklada operatorow na zmianie). Ale lider nie moze przez nie zdobyc admina:
ani zalozyc konta admina, ani podniesc sobie roli, ani zmienic hasla admina.
"""
import app as logistat
from conftest import PASSWORD, login, make_user


def user(username):
    return logistat.User.query.filter_by(username=username).first()


# ── Lider nie eskaluje uprawnien ─────────────────────────────────────────────

def test_lider_nie_zaklada_konta_admina(leader_client):
    r = leader_client.post('/api/users', json={
        'username': 'podstawiony', 'display_name': 'X',
        'role': 'admin', 'password': 'haslo123',
    })

    assert r.status_code == 403
    assert user('podstawiony') is None


def test_lider_nie_zaklada_konta_lidera(leader_client):
    r = leader_client.post('/api/users', json={
        'username': 'nowy-lider', 'display_name': 'X',
        'role': 'leader', 'password': 'haslo123',
    })

    assert r.status_code == 403
    assert user('nowy-lider') is None


def test_lider_zaklada_operatora(leader_client):
    r = leader_client.post('/api/users', json={
        'username': 'operator-1', 'display_name': 'Operator', 'barcode_id': 'OP1',
    })

    assert r.status_code == 201
    assert user('operator-1').role == 'operator'


def test_lider_nie_podnosi_sobie_roli(leader_client, leader):
    r = leader_client.put(f'/api/users/{leader.id}', json={'role': 'admin'})

    assert r.status_code == 403
    assert user(leader.username).role == 'leader'


def test_lider_nie_promuje_operatora(leader_client):
    op = make_user('operator', username='op-x')

    r = leader_client.put(f'/api/users/{op.id}', json={'role': 'admin'})

    assert r.status_code == 403
    assert user('op-x').role == 'operator'


def test_lider_nie_zmienia_hasla_adminowi(client, leader, admin):
    login(client, leader.username)

    r = client.put(f'/api/users/{admin.id}', json={'password': 'przejete123'})

    assert r.status_code == 403
    assert user(admin.username).check_password(PASSWORD), 'haslo admina nietkniete'
    assert not user(admin.username).check_password('przejete123')


def test_lider_nie_dezaktywuje_admina(client, leader, admin):
    login(client, leader.username)

    r = client.delete(f'/api/users/{admin.id}')

    assert r.status_code == 403
    assert user(admin.username).is_active_user is True


def test_lider_nie_dezaktywuje_flaga_is_active_user(client, leader, admin):
    login(client, leader.username)

    r = client.put(f'/api/users/{admin.id}', json={'is_active_user': False})

    assert r.status_code == 403
    assert user(admin.username).is_active_user is True


def test_lider_edytuje_operatora(leader_client):
    op = make_user('operator', username='op-y', barcode_id='OPY')

    r = leader_client.put(f'/api/users/{op.id}',
                          json={'display_name': 'Nowa Nazwa', 'barcode_id': 'OPY2'})

    assert r.status_code == 200
    assert user('op-y').display_name == 'Nowa Nazwa'
    assert user('op-y').barcode_id == 'OPY2'


def test_lider_dezaktywuje_operatora(leader_client):
    op = make_user('operator', username='op-z')

    r = leader_client.delete(f'/api/users/{op.id}')

    assert r.status_code == 200
    assert user('op-z').is_active_user is False


# ── Admin moze wszystko ──────────────────────────────────────────────────────

def test_admin_zaklada_konto_admina(admin_client):
    r = admin_client.post('/api/users', json={
        'username': 'admin-2', 'display_name': 'Admin 2',
        'role': 'admin', 'password': 'haslo123',
    })

    assert r.status_code == 201
    assert user('admin-2').role == 'admin'
    assert user('admin-2').check_password('haslo123')


def test_admin_zmienia_role_i_haslo(admin_client):
    op = make_user('operator', username='op-w')

    r = admin_client.put(f'/api/users/{op.id}',
                         json={'role': 'leader', 'password': 'haslo123'})

    assert r.status_code == 200
    assert user('op-w').role == 'leader'
    assert user('op-w').check_password('haslo123')


def test_nieznana_rola_odrzucona(admin_client):
    r = admin_client.post('/api/users', json={
        'username': 'dziwny', 'display_name': 'X', 'role': 'superadmin',
    })

    assert r.status_code == 400
    assert user('dziwny') is None


def test_nie_da_sie_usunac_ostatniego_admina(admin_client, admin):
    """Zabezpieczenie przed zablokowaniem sobie dostepu do panelu."""
    seed_admin = logistat.User.query.filter_by(username='admin').first()
    admin_client.delete(f'/api/users/{seed_admin.id}')

    r = admin_client.delete(f'/api/users/{admin.id}')

    assert r.status_code == 400
    assert user(admin.username).is_active_user is True


def test_nie_da_sie_zdegradowac_ostatniego_admina(admin_client, admin):
    seed_admin = logistat.User.query.filter_by(username='admin').first()
    admin_client.delete(f'/api/users/{seed_admin.id}')

    r = admin_client.put(f'/api/users/{admin.id}', json={'role': 'leader'})

    assert r.status_code == 400
    assert user(admin.username).role == 'admin'


# ── Dezaktywacja faktycznie odbiera dostep ───────────────────────────────────

def test_dezaktywowany_lider_sie_nie_zaloguje(client, admin):
    lider = make_user('leader', username='lider-out')
    lider.is_active_user = False
    logistat.db.session.commit()

    login(client, 'lider-out')

    assert client.get('/dashboard').status_code == 302, 'brak dostepu po dezaktywacji'


def test_dezaktywacja_unieważnia_istniejaca_sesje(client, admin_client, admin):
    lider = make_user('leader', username='lider-live')
    sesja = logistat.app.test_client()
    login(sesja, 'lider-live')
    assert sesja.get('/dashboard').status_code == 200

    admin_client.delete(f'/api/users/{lider.id}')

    assert sesja.get('/dashboard').status_code == 302, \
        'dezaktywacja musi wyrzucic z aktywnej sesji'


def test_aktywny_lider_sie_loguje(client, leader):
    login(client, leader.username)

    assert client.get('/dashboard').status_code == 200


def test_operator_bez_hasla_sie_nie_zaloguje(client):
    make_user('operator', username='op-login')

    login(client, 'op-login', 'cokolwiek')

    assert client.get('/dashboard').status_code == 302
