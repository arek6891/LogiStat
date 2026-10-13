"""Szkolenia z czynnosci (2026-10-13, operacje): do czynnosci mozna przydzielic
tylko osobe przeszkolona. Szkolenia zaznacza lider w Uzytkownikach; nowa osoba
i nowa czynnosc startuja bez szkolen. Wszystkich istniejacych w dniu wdrozenia
zaznacza raz `zaznacz_wszystkich_przeszkolonych()`. Zapisany przydzial zostaje,
choc szkolenie potem odznaczono — blokada dotyczy tylko NOWYCH przydzialow.
"""
import app as logistat
from conftest import make_user

DZIEN = '2026-09-01'


def zapisz(client, *pary):
    return client.post('/api/assignment/save', json={
        'date': DZIEN, 'shift_number': 1,
        'assignments': [{'user_id': u.id, 'activity_id': a.id} for u, a in pary]})


def przeszkol(user, *czynnosci):
    for a in czynnosci:
        logistat.db.session.add(logistat.SzkolenieCzynnosci(user_id=user.id, activity_id=a.id))
    logistat.db.session.commit()


def czynnosci(n=2):
    return logistat.Activity.query.order_by(logistat.Activity.sort_order).limit(n).all()


def obecny(user):
    zmiana = logistat.get_or_create_shift(logistat.parse_date(DZIEN), 1)
    logistat.db.session.add(logistat.ShiftAttendance(shift_id=zmiana.id, user_id=user.id))
    logistat.db.session.commit()


def test_bez_szkolenia_nie_mozna_przydzielic(leader_client):
    u = make_user('operator', display_name='Nowa')
    a, = czynnosci(1)

    r = zapisz(leader_client, (u, a))

    assert r.status_code == 400
    d = r.get_json()
    assert d['brak_szkolenia'] == [{'user_id': u.id, 'activity_id': a.id,
                                    'osoba': 'Nowa', 'czynnosc': a.name}]
    assert 'Brak szkolenia' in d['error'] and 'Nowa' in d['error']
    assert logistat.ActivityAssignment.query.count() == 0


def test_odrzucony_zapis_nie_kasuje_dotychczasowego_przydzialu(leader_client):
    ok = make_user('operator')
    nowa = make_user('operator')
    a, = czynnosci(1)
    przeszkol(ok, a)
    assert zapisz(leader_client, (ok, a)).status_code == 200

    assert zapisz(leader_client, (ok, a), (nowa, a)).status_code == 400

    assert [(x.user_id, x.activity_id) for x in logistat.ActivityAssignment.query] == [(ok.id, a.id)]


def test_przeszkolony_przydziela_sie(leader_client):
    u = make_user('operator')
    a, = czynnosci(1)
    przeszkol(u, a)

    assert zapisz(leader_client, (u, a)).status_code == 200
    assert logistat.ActivityAssignment.query.count() == 1


def test_szkolenie_z_innej_czynnosci_nie_wystarcza(leader_client):
    u = make_user('operator')
    a1, a2 = czynnosci(2)
    przeszkol(u, a1)

    assert zapisz(leader_client, (u, a2)).status_code == 400


def test_odznaczone_szkolenie_nie_zdejmuje_zapisanego_przydzialu(leader_client):
    """Odznaczenie nie moze blokowac zapisu calej zmiany — stary przydzial zostaje,
    ale przeniesienie z powrotem po zdjeciu juz nie przejdzie."""
    u, inna = make_user('operator'), make_user('operator')
    a1, a2 = czynnosci(2)
    przeszkol(u, a1)
    przeszkol(inna, a2)
    assert zapisz(leader_client, (u, a1)).status_code == 200
    logistat.SzkolenieCzynnosci.query.filter_by(user_id=u.id).delete()
    logistat.db.session.commit()

    assert zapisz(leader_client, (u, a1), (inna, a2)).status_code == 200
    assert zapisz(leader_client, (inna, a2)).status_code == 200      # u zdjeta
    assert zapisz(leader_client, (u, a1)).status_code == 400         # i nie wraca


def test_dane_tablicy_niosa_szkolenia(leader_client):
    u = make_user('operator')
    a1, a2 = czynnosci(2)
    przeszkol(u, a1, a2)
    obecny(u)

    d = leader_client.get(f'/api/assignment/data?date={DZIEN}&shift_number=1').get_json()

    assert d['szkolenia'] == {str(u.id): sorted([a1.id, a2.id])}


def test_sugestie_tylko_do_przeszkolonych(leader_client):
    u = make_user('operator')
    nikt = make_user('operator')
    a1, a2 = czynnosci(2)
    przeszkol(u, a2)
    obecny(u)
    obecny(nikt)

    s = leader_client.get(f'/api/assignment/suggestions?date={DZIEN}&shift_number=1') \
        .get_json()['suggestions']

    assert [(x['user_id'], x['activity_id']) for x in s] == [(u.id, a2.id)]


def test_sugestie_przechodza_zapis(leader_client):
    for _ in range(3):
        u = make_user('operator', przeszkolony=True)
        obecny(u)
    s = leader_client.get(f'/api/assignment/suggestions?date={DZIEN}&shift_number=1') \
        .get_json()['suggestions']

    r = leader_client.post('/api/assignment/save', json={
        'date': DZIEN, 'shift_number': 1, 'assignments': s})

    assert r.status_code == 200


# ── Uzytkownicy: zaznaczanie szkolen ─────────────────────────────────────────

def szkolenia(user):
    return {w.activity_id for w in logistat.SzkolenieCzynnosci.query.filter_by(user_id=user.id)}


def test_lider_zaznacza_szkolenia_operatora(leader_client):
    u = make_user('operator')
    a1, a2 = czynnosci(2)

    r = leader_client.put(f'/api/users/{u.id}', json={'czynnosci': [a1.id, a2.id]})
    assert r.status_code == 200
    assert szkolenia(u) == {a1.id, a2.id}

    leader_client.put(f'/api/users/{u.id}', json={'czynnosci': [a2.id]})
    assert szkolenia(u) == {a2.id}


def test_bez_pola_czynnosci_szkolenia_zostaja(leader_client):
    u = make_user('operator')
    a, = czynnosci(1)
    przeszkol(u, a)

    leader_client.put(f'/api/users/{u.id}', json={'display_name': 'Nowe imie'})

    assert szkolenia(u) == {a.id}


def test_nowy_uzytkownik_ze_szkoleniami(leader_client):
    a, = czynnosci(1)
    r = leader_client.post('/api/users', json={
        'username': 'nowy', 'display_name': 'Nowy', 'czynnosci': [a.id]})

    assert r.status_code == 201
    assert szkolenia(logistat.db.session.get(logistat.User, r.get_json()['id'])) == {a.id}


def test_nowy_uzytkownik_domyslnie_bez_szkolen(leader_client):
    r = leader_client.post('/api/users', json={'username': 'nowy', 'display_name': 'Nowy'})

    assert szkolenia(logistat.db.session.get(logistat.User, r.get_json()['id'])) == set()


def test_nieznana_czynnosc_400(leader_client):
    u = make_user('operator')

    assert leader_client.put(f'/api/users/{u.id}', json={'czynnosci': [999999]}).status_code == 400
    assert leader_client.put(f'/api/users/{u.id}', json={'czynnosci': 'x'}).status_code == 400


def test_szkolenie_z_wylaczonej_czynnosci_zostaje(leader_client):
    """Ekran pokazuje tylko aktywne czynnosci — zapis nie moze kasowac reszty."""
    u = make_user('operator')
    a1, a2 = czynnosci(2)
    przeszkol(u, a1, a2)
    a2.is_active = False
    logistat.db.session.commit()

    leader_client.put(f'/api/users/{u.id}', json={'czynnosci': []})

    assert szkolenia(u) == {a2.id}


def test_lider_nie_zmieni_szkolen_admina(leader_client):
    admin = make_user('admin')
    a, = czynnosci(1)

    r = leader_client.put(f'/api/users/{admin.id}', json={'czynnosci': [a.id]})

    assert r.status_code == 403
    assert szkolenia(admin) == set()


def test_strona_uzytkownikow_ma_checkboxy_czynnosci(leader_client):
    u = make_user('operator', przeszkolony=True)
    html = leader_client.get('/admin/users').get_data(as_text=True)

    assert 'class="czynnosc-szkolenie"' in html
    n = logistat.Activity.query.filter_by(is_active=True).count()
    assert f'✅ Szkolenia {n}/{n}' in html
    assert u.display_name in html


def test_tablica_ma_okno_braku_szkolenia(leader_client):
    html = leader_client.get('/assignment').get_data(as_text=True)

    assert 'id="brakSzkoleniaModal"' in html
    assert 'moznaPrzydzielic' in html


# ── Jednorazowe zaznaczenie istniejacych ─────────────────────────────────────

def test_migracja_zaznacza_wszystkich_raz(flask_app):
    u = make_user('operator')
    wszystkie = {a.id for a in logistat.Activity.query}

    logistat.zaznacz_wszystkich_przeszkolonych()

    assert szkolenia(u) == wszystkie
    po = make_user('operator')
    logistat.SzkolenieCzynnosci.query.filter_by(user_id=u.id).delete()
    logistat.db.session.commit()
    logistat.zaznacz_wszystkich_przeszkolonych()           # znacznik — drugi raz nic
    assert szkolenia(u) == set()
    assert szkolenia(po) == set(), 'kto przyszedl po wdrozeniu, startuje bez szkolen'
