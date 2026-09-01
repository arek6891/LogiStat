"""Czasy paczek — blokada wlasciciela.

Paczka w trakcie nalezy do pracownika, ktory ja rozpoczal: inny startujacy
dostaje 409, inny konczacy 403. Paczka zakonczona jest zamknieta na oba.
"""
from datetime import date, datetime, timedelta

import app as logistat
from conftest import make_user

ZIEL = date(2026, 9, 10)


def make_carton(barcode='P1', stueckzahl=10):
    c = logistat.ImportedCarton(barcode=barcode, land='PL', stueckzahl=stueckzahl,
                                ziel_datum=ZIEL, uebergabe_nr='UB-1')
    logistat.db.session.add(c)
    logistat.db.session.commit()
    return c


def carton(barcode='P1'):
    return logistat.ImportedCarton.query.filter_by(barcode=barcode).first()


def start(client, emp, pkg='P1'):
    return client.post('/api/package-time/start',
                       json={'employee_barcode': emp, 'package_barcode': pkg})


def end(client, emp, pkg='P1'):
    return client.post('/api/package-time/end',
                       json={'employee_barcode': emp, 'package_barcode': pkg})


def test_start_i_koniec_przez_tego_samego_pracownika(leader_client):
    w = make_user('operator', barcode_id='W1')
    make_carton()

    assert start(leader_client, 'W1').status_code == 200
    c = carton()
    assert c.scan_start_at is not None and c.scan_start_by == w.id

    assert end(leader_client, 'W1').status_code == 200
    c = carton()
    assert c.scan_end_by == w.id
    assert c.processing_seconds() is not None and c.processing_seconds() >= 0


def test_powtorny_start_tego_samego_pracownika_nie_zmienia_czasu(leader_client):
    make_user('operator', barcode_id='W1')
    make_carton()
    start(leader_client, 'W1')
    pierwszy = carton().scan_start_at

    r = start(leader_client, 'W1')

    assert r.status_code == 200
    assert carton().scan_start_at == pierwszy, 'restart nie moze skasowac pomiaru'


def test_inny_pracownik_nie_podbierze_paczki_w_trakcie(leader_client):
    w1 = make_user('operator', barcode_id='W1')
    make_user('operator', barcode_id='W2')
    make_carton()
    start(leader_client, 'W1')

    r = start(leader_client, 'W2')

    assert r.status_code == 409
    assert carton().scan_start_by == w1.id


def test_inny_pracownik_nie_zakonczy_paczki(leader_client):
    make_user('operator', barcode_id='W1')
    make_user('operator', barcode_id='W2')
    make_carton()
    start(leader_client, 'W1')

    r = end(leader_client, 'W2')

    assert r.status_code == 403
    assert carton().scan_end_at is None


def test_koniec_bez_startu_daje_400(leader_client):
    make_user('operator', barcode_id='W1')
    make_carton()

    r = end(leader_client, 'W1')

    assert r.status_code == 400
    assert carton().scan_end_at is None


def test_zakonczona_paczka_jest_zamknieta(leader_client):
    make_user('operator', barcode_id='W1')
    make_carton()
    start(leader_client, 'W1')
    end(leader_client, 'W1')
    koniec = carton().scan_end_at

    assert start(leader_client, 'W1').status_code == 409, 'brak re-processingu'
    assert end(leader_client, 'W1').status_code == 409
    assert carton().scan_end_at == koniec


def test_nieznany_kod_pracownika_lub_paczki(leader_client):
    make_user('operator', barcode_id='W1')
    make_carton()

    assert start(leader_client, 'NIEISTNIEJE').status_code == 404
    assert start(leader_client, 'W1', pkg='BRAK').status_code == 404


def test_nieaktywny_pracownik_nie_skanuje(leader_client):
    w = make_user('operator', barcode_id='W1')
    w.is_active_user = False
    logistat.db.session.commit()
    make_carton()

    assert start(leader_client, 'W1').status_code == 404


def test_processing_seconds_liczy_roznice(flask_app):
    c = make_carton()
    c.scan_start_at = datetime(2026, 9, 1, 10, 0, 0)
    c.scan_end_at = datetime(2026, 9, 1, 10, 2, 30)
    logistat.db.session.commit()

    assert carton().processing_seconds() == 150


def test_processing_seconds_none_bez_pary(flask_app):
    c = make_carton()
    assert c.processing_seconds() is None
    c.scan_start_at = datetime.utcnow()
    logistat.db.session.commit()
    assert carton().processing_seconds() is None
