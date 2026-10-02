"""Listy rozwijane na koncie uzytkownika: rodzaj pracownika i nazwa zmiany.

Tresc obu list ustala admin (`UserOption`); lider tylko wybiera z nich przy
zakladaniu operatora. Na koncie trzymamy id pozycji, wiec zmiana nazwy przenosi
sie na wszystkich, a usuniecie pozycji w uzyciu jest odrzucane.
"""
import app as logistat
from conftest import make_user


def opcja(kind, name):
    return logistat.UserOption.query.filter_by(kind=kind, name=name).first()


def test_seed_zaklada_domyslne_pozycje(flask_app):
    lista = logistat.user_options_by_kind()

    assert [o.name for o in lista['worker_type']] == ['Logwin', 'Agencja 1', 'Agencja 2']
    assert [o.name for o in lista['shift_group']] == ['Zmiana A', 'Zmiana B', 'Zmiana C']


def test_seed_nie_dubluje_po_restarcie(flask_app):
    logistat.seed_data()

    assert logistat.UserOption.query.filter_by(kind='worker_type').count() == 3


# ── Przypisanie na koncie ────────────────────────────────────────────────────

def test_lider_zaklada_operatora_z_obiema_listami(leader_client):
    logwin, zmiana_b = opcja('worker_type', 'Logwin'), opcja('shift_group', 'Zmiana B')

    r = leader_client.post('/api/users', json={
        'username': 'op-listy', 'display_name': 'Op', 'role': 'operator',
        'worker_type_id': logwin.id, 'shift_group_id': str(zmiana_b.id),
    })

    assert r.status_code == 201
    d = r.get_json()
    assert d['worker_type'] == 'Logwin' and d['worker_type_id'] == logwin.id
    assert d['shift_group'] == 'Zmiana B'


def test_edycja_zmienia_i_czysci_pozycje(leader_client):
    op = make_user('operator')
    agencja = opcja('worker_type', 'Agencja 1')

    r = leader_client.put(f'/api/users/{op.id}', json={'worker_type_id': agencja.id})
    assert r.status_code == 200 and r.get_json()['worker_type'] == 'Agencja 1'

    r = leader_client.put(f'/api/users/{op.id}', json={'worker_type_id': None})
    assert r.status_code == 200 and r.get_json()['worker_type'] is None


def test_edycja_bez_pola_nie_rusza_pozycji(leader_client):
    op = make_user('operator')
    op.shift_group_id = opcja('shift_group', 'Zmiana A').id
    logistat.db.session.commit()

    leader_client.put(f'/api/users/{op.id}', json={'display_name': 'Nowe'})

    assert logistat.db.session.get(logistat.User, op.id).shift_group.name == 'Zmiana A'


def test_pozycja_z_innej_listy_odrzucona(leader_client):
    """Id zmiany wpisany w rodzaj pracownika to blad, nie ciche przypisanie."""
    zmiana = opcja('shift_group', 'Zmiana A')

    r = leader_client.post('/api/users', json={
        'username': 'op-zla', 'display_name': 'X', 'worker_type_id': zmiana.id,
    })

    assert r.status_code == 400
    assert logistat.User.query.filter_by(username='op-zla').first() is None


def test_nieistniejaca_pozycja_odrzucona(leader_client):
    op = make_user('operator')

    r = leader_client.put(f'/api/users/{op.id}', json={'shift_group_id': 999999})

    assert r.status_code == 400


# ── Zarzadzanie listami (admin) ──────────────────────────────────────────────

def test_lider_widzi_listy_ale_ich_nie_zmienia(leader_client):
    """@admin_required odsyla przekierowaniem (302), jak wszedzie w aplikacji."""
    logwin = opcja('worker_type', 'Logwin')

    assert leader_client.get('/api/user-options').status_code == 200
    assert leader_client.post('/api/user-options',
                              json={'kind': 'worker_type', 'name': 'X'}).status_code == 302
    assert leader_client.put(f'/api/user-options/{logwin.id}',
                             json={'name': 'X'}).status_code == 302
    assert leader_client.delete(f'/api/user-options/{logwin.id}').status_code == 302

    assert opcja('worker_type', 'X') is None
    assert opcja('worker_type', 'Logwin') is not None


def test_admin_dodaje_pozycje(admin_client):
    r = admin_client.post('/api/user-options', json={'kind': 'worker_type', 'name': 'Randstad'})

    assert r.status_code == 201
    assert opcja('worker_type', 'Randstad') is not None
    # nowa trafia na koniec listy
    assert [o.name for o in logistat.user_options_by_kind()['worker_type']][-1] == 'Randstad'


def test_duplikat_i_zly_rodzaj_odrzucone(admin_client):
    assert admin_client.post('/api/user-options',
                             json={'kind': 'worker_type', 'name': 'Logwin'}).status_code == 409
    assert admin_client.post('/api/user-options',
                             json={'kind': 'cokolwiek', 'name': 'X'}).status_code == 400
    assert admin_client.post('/api/user-options',
                             json={'kind': 'worker_type', 'name': '  '}).status_code == 400


def test_ta_sama_nazwa_w_dwoch_listach_dozwolona(admin_client):
    r = admin_client.post('/api/user-options', json={'kind': 'shift_group', 'name': 'Logwin'})

    assert r.status_code == 201


def test_zmiana_nazwy_widoczna_u_przypisanych(admin_client):
    agencja = opcja('worker_type', 'Agencja 1')
    op = make_user('operator')
    op.worker_type_id = agencja.id
    logistat.db.session.commit()

    r = admin_client.put(f'/api/user-options/{agencja.id}', json={'name': 'Adecco'})

    assert r.status_code == 200
    users = {u['id']: u for u in admin_client.get('/api/users').get_json()}
    assert users[op.id]['worker_type'] == 'Adecco'


def test_usuniecie_pozycji_w_uzyciu_odrzucone(admin_client):
    zmiana = opcja('shift_group', 'Zmiana C')
    op = make_user('operator')
    op.shift_group_id = zmiana.id
    logistat.db.session.commit()

    r = admin_client.delete(f'/api/user-options/{zmiana.id}')

    assert r.status_code == 409
    assert opcja('shift_group', 'Zmiana C') is not None


def test_usuniecie_wolnej_pozycji(admin_client):
    zmiana = opcja('shift_group', 'Zmiana C')

    assert admin_client.delete(f'/api/user-options/{zmiana.id}').status_code == 200
    assert opcja('shift_group', 'Zmiana C') is None
