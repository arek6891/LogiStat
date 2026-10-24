"""Przydzielanie — poprawki z przegladu 2026-10-24.

Zapis podmienia przydzial zmiany, ale tablica pokazuje tylko obecnych i tylko
aktywne czynnosci. Osoba przydzielona do czynnosci wylaczonej w trakcie zmiany
(albo bez obecnosci) nie miala karty — pierwsze przeciagniecie kogokolwiek
kasowalo jej przydzial i wiersze Wpisu ilosci. Teraz zapis rusza tylko osoby,
ktore klient wyslal, i obecnych przy aktywnych czynnosciach.
"""
from conftest import make_user

from logistat.extensions import db
from logistat.models import (
    Activity, ActivityAssignment, ShiftAttendance, get_or_create_shift)
from logistat.web.wspolne import parse_date

DZIEN = '2026-09-02'


def _zmiana():
    return get_or_create_shift(parse_date(DZIEN), 1)


def _obecny(user):
    db.session.add(ShiftAttendance(shift_id=_zmiana().id, user_id=user.id))
    db.session.commit()


def _zapisz(client, pary):
    wersja = client.get(f'/api/assignment/data?date={DZIEN}&shift_number=1').get_json()['wersja']
    return client.post('/api/assignment/save', json={
        'date': DZIEN, 'shift_number': 1, 'wersja': wersja,
        'assignments': [{'user_id': u, 'activity_id': a} for u, a in pary]})


def test_przydzial_do_wylaczonej_czynnosci_przetrwa_zapis(leader_client):
    a1, a2 = Activity.query.limit(2).all()
    x, y = make_user('operator', przeszkolony=True), make_user('operator', przeszkolony=True)
    _obecny(x)
    _obecny(y)
    assert _zapisz(leader_client, [(x.id, a1.id), (y.id, a2.id)]).status_code == 200
    a2.is_active = False
    db.session.commit()

    r = _zapisz(leader_client, [])  # tablica bez y (strefy a2 nie ma)

    assert r.status_code == 200
    zostalo = {(p.user_id, p.activity_id) for p in ActivityAssignment.query}
    assert zostalo == {(y.id, a2.id)}


def test_nieobecny_z_przydzialem_przetrwa_zapis(leader_client):
    a1 = Activity.query.first()
    x, y = make_user('operator', przeszkolony=True), make_user('operator', przeszkolony=True)
    _obecny(x)
    assert _zapisz(leader_client, [(x.id, a1.id), (y.id, a1.id)]).status_code == 200

    assert _zapisz(leader_client, []).status_code == 200

    assert {p.user_id for p in ActivityAssignment.query} == {y.id}


def test_przeciagniecie_z_wylaczonej_na_aktywna_przenosi(leader_client):
    a1, a2 = Activity.query.limit(2).all()
    y = make_user('operator', przeszkolony=True)
    _obecny(y)
    assert _zapisz(leader_client, [(y.id, a2.id)]).status_code == 200
    a2.is_active = False
    db.session.commit()

    assert _zapisz(leader_client, [(y.id, a1.id)]).status_code == 200

    assert {(p.user_id, p.activity_id) for p in ActivityAssignment.query} == {(y.id, a1.id)}


def test_tablica_dostaje_osoby_z_wylaczonych_czynnosci(leader_client):
    a1, a2 = Activity.query.limit(2).all()
    y = make_user('operator', przeszkolony=True)
    _obecny(y)
    _zapisz(leader_client, [(y.id, a2.id)])
    a2.is_active = False
    db.session.commit()

    d = leader_client.get(f'/api/assignment/data?date={DZIEN}&shift_number=1').get_json()

    assert d['w_wylaczonych'] == [{'user_id': y.id, 'czynnosc': a2.name}]


def test_sugestie_nie_biora_wpisow_z_pozniejszych_dni(leader_client):
    """Srednia z Wpisu ilosci dla dnia D: tylko dni <= D (bylo bez gornej granicy)."""
    from datetime import timedelta
    from logistat.models import DailyStat
    a1, a2 = Activity.query.filter(Activity.name != 'Post Processing').limit(2).all()
    x = make_user('operator', przeszkolony=True)
    _obecny(x)
    pozniej = get_or_create_shift(parse_date(DZIEN) + timedelta(days=5), 1)
    db.session.add(DailyStat(user_id=x.id, activity_id=a2.id, shift_id=pozniej.id, quantity=999))
    db.session.commit()

    import logistat.web.przydzial as wp
    zlapane = {}
    prawdziwe = wp.sugestie_przydzialu

    def podgladaj(**kw):
        zlapane.update(kw)
        return prawdziwe(**kw)
    wp.sugestie_przydzialu = podgladaj
    try:
        r = leader_client.get(f'/api/assignment/suggestions?date={DZIEN}&shift_number=1')
    finally:
        wp.sugestie_przydzialu = prawdziwe

    assert r.status_code == 200
    assert 999 not in zlapane['srednie'].values()
