"""Przydzielanie zapisuje sie samo po kazdym przeciagnieciu, a zapis podmienia
CALY przydzial zmiany. Dwoch liderow na tej samej zmianie nadpisywaloby sobie
prace po cichu — dlatego zapis niesie wersje, ktora klient wczytal, i na
nieaktualnej dostaje 409 zamiast nadpisac cudzy przydzial.
"""
import threading

import app as logistat
from conftest import login, make_user

DZIEN = '2026-09-01'


def przydzial(client, user_id, activity_id, wersja=None, shift_number=1):
    body = {'date': DZIEN, 'shift_number': shift_number,
            'assignments': [{'user_id': user_id, 'activity_id': activity_id}]}
    if wersja is not None:
        body['wersja'] = wersja
    return client.post('/api/assignment/save', json=body)


def wczytaj(client, shift_number=1):
    r = client.get(f'/api/assignment/data?date={DZIEN}&shift_number={shift_number}')
    assert r.status_code == 200
    return r.get_json()


def test_odczyt_zwraca_wersje_takze_dla_nieistniejacej_zmiany(leader_client):
    assert wczytaj(leader_client)['wersja'] == logistat.wersja_przydzialu([])


def test_zapis_zwraca_wersje_zgodna_z_odczytem(leader_client):
    u = make_user('operator')
    akt = logistat.Activity.query.first()
    v0 = wczytaj(leader_client)['wersja']

    r = przydzial(leader_client, u.id, akt.id, wersja=v0)

    assert r.status_code == 200
    assert r.get_json()['wersja'] == wczytaj(leader_client)['wersja']
    assert r.get_json()['wersja'] != v0


def test_kolejne_zapisy_z_wersja_z_poprzedniego_przechodza(leader_client):
    """Tak pracuje autozapis: kazdy zapis bierze wersje z odpowiedzi poprzedniego."""
    u = make_user('operator')
    a1, a2 = logistat.Activity.query.limit(2).all()
    v = wczytaj(leader_client)['wersja']

    for akt in (a1, a2, a1):
        r = przydzial(leader_client, u.id, akt.id, wersja=v)
        assert r.status_code == 200
        v = r.get_json()['wersja']

    assert logistat.ActivityAssignment.query.one().activity_id == a1.id


def test_nieaktualna_wersja_daje_409_i_nie_nadpisuje(flask_app):
    u = make_user('operator')
    a1, a2 = logistat.Activity.query.limit(2).all()
    lider_a, lider_b = make_user('leader'), make_user('leader')
    ka, kb = flask_app.test_client(), flask_app.test_client()
    login(ka, lider_a.username)
    login(kb, lider_b.username)

    # Obaj otwieraja te sama zmiane...
    va = wczytaj(ka)['wersja']
    vb = wczytaj(kb)['wersja']
    # ...A przeciaga pierwszy...
    assert przydzial(ka, u.id, a1.id, wersja=va).status_code == 200
    # ...B przeciaga na starym obrazie tablicy.
    r = przydzial(kb, u.id, a2.id, wersja=vb)

    assert r.status_code == 409
    dane = r.get_json()
    assert dane['konflikt'] is True
    assert 'Ktoś inny' in dane['error']
    assert dane['wersja'] == wczytaj(kb)['wersja']
    assert logistat.ActivityAssignment.query.one().activity_id == a1.id, \
        'zapis z nieaktualna wersja nie moze nadpisac przydzialu drugiego lidera'


def test_wersja_dotyczy_tylko_swojej_zmiany(leader_client):
    u = make_user('operator')
    akt = logistat.Activity.query.first()
    v2 = wczytaj(leader_client, shift_number=2)['wersja']

    assert przydzial(leader_client, u.id, akt.id, shift_number=1).status_code == 200
    r = przydzial(leader_client, u.id, akt.id, wersja=v2, shift_number=2)

    assert r.status_code == 200, 'zapis na zmianie 1 nie unieważnia wersji zmiany 2'


def test_zapis_bez_wersji_dziala_jak_dawniej(leader_client):
    u = make_user('operator')
    akt = logistat.Activity.query.first()
    assert przydzial(leader_client, u.id, akt.id).status_code == 200
    assert przydzial(leader_client, u.id, akt.id).status_code == 200
    assert logistat.ActivityAssignment.query.count() == 1


def test_zapis_blokuje_wiersz_zmiany(leader_client, queries):
    u = make_user('operator')
    akt = logistat.Activity.query.first()

    przydzial(leader_client, u.id, akt.id)

    zablokowane = [q for q in queries.matching('FROM shift')
                   if 'FOR UPDATE' in q.upper()]
    assert len(zablokowane) == 1, 'zapis przydzialu musi czytac zmiane z blokada'


def test_rownolegle_zapisy_nie_dubluja_przydzialu(flask_app):
    """Delete + insert z dwoch stanowisk naraz: bez blokady wiersza zmiany oba
    wstawialy swoj komplet i zmiana miala przydzial podwojnie."""
    u = make_user('operator')
    akt = logistat.Activity.query.first()
    lider = make_user('leader')
    logistat.get_or_create_shift(logistat.parse_date(DZIEN), 1)
    # Watki nie moga siegac do obiektow sesji glownego watku — tylko wartosci.
    user_id, activity_id, nazwa = u.id, akt.id, lider.username
    logistat.db.session.commit()
    wyniki = []

    def zapisz():
        with flask_app.app_context():
            c = flask_app.test_client()
            login(c, nazwa)
            wyniki.append(przydzial(c, user_id, activity_id).status_code)
            logistat.db.session.remove()

    watki = [threading.Thread(target=zapisz) for _ in range(4)]
    for w in watki:
        w.start()
    for w in watki:
        w.join(timeout=20)

    assert wyniki == [200] * 4
    assert logistat.ActivityAssignment.query.count() == 1
