"""Osoba szkolaca („Szkolacy", `User.is_trainer`) i kafelek „Szkolenie".

Decyzja operacji (2026-10-06): szkolenie to czas pracy — nie pomniejsza czasu
pracy jak przerwa / „Inne". W Normach paczki ZAKONCZONE W CZASIE szkolenia
licza sie jako dokladnie 100% celu z dnia paczki (czas skanowania × cel), tylko
one; reszta dnia idzie z prawdziwych sztuk, a samo szkolenie bez paczek niczego
nie dolicza. Paczki ze szkolenia nie wchodza do sredniej zespolu.
"""
from datetime import date, datetime, timedelta

import app as logistat
from conftest import make_user

DZIEN = date(2026, 9, 15)


def ustaw_cel(wartosc, od=logistat.POCZATEK_HISTORII_CELU):
    logistat.set_setting('target_szt_h', wartosc)
    logistat.db.session.merge(logistat.HistoriaCelu(dzien=od, wartosc=wartosc))
    logistat.db.session.commit()


def chwila(dzien, godz, minut=0):
    """Naive UTC lokalnej godziny `godz:minut` dnia `dzien`."""
    return logistat.local_day_bounds(dzien)[0] + timedelta(hours=godz, minutes=minut)


def szkolacy(nazwa='Trener', barcode=None):
    u = make_user('operator', username=nazwa.lower(), display_name=nazwa,
                  barcode_id=barcode)
    u.is_trainer = True
    logistat.db.session.commit()
    return u


def szkolenie(kto, dzien, od, do):
    shift = logistat.get_or_create_shift(dzien, 1)
    for typ, ts in (('training_start', od), ('training_end', do)):
        logistat.db.session.add(logistat.WorkerTimeEvent(
            user_id=kto.id, shift_id=shift.id, event_type=typ, timestamp=ts))
    logistat.db.session.commit()


_licznik = [0]


def paczka(kto, sztuk, start, koniec):
    _licznik[0] += 1
    logistat.db.session.add(logistat.ImportedCarton(
        barcode=f'SZK-{_licznik[0]}', land='PL', stueckzahl=sztuk,
        data_pliku=DZIEN, uebergabe_nr='UB-1',
        scan_start_at=start, scan_start_by=kto.id if start else None,
        scan_end_at=koniec, scan_end_by=kto.id))
    logistat.db.session.commit()


def paczki_po_kolei(kto, dzien, od_godz, ile, sztuk, minut):
    t = chwila(dzien, od_godz)
    for _ in range(ile):
        paczka(kto, sztuk, t, t + timedelta(minutes=minut))
        t += timedelta(minutes=minut)


def przeglad(client, od=DZIEN, do=DZIEN):
    r = client.get(f'/api/stats/overview?date_from={od}&date_to={do}')
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def wiersz(dane, nazwa):
    for r in dane['pracownicy'] + dane['za_malo_danych']:
        if r['display_name'] == nazwa:
            return r
    return None


# ── znacznik na koncie ───────────────────────────────────────────────────────

def test_admin_zaklada_szkolacego(admin_client):
    r = admin_client.post('/api/users', json={
        'username': 'ola', 'display_name': 'Ola', 'is_trainer': True})
    assert r.status_code == 201
    assert r.get_json()['is_trainer'] is True
    assert logistat.User.query.filter_by(username='ola').one().is_trainer


def test_domyslnie_nie_jest_szkolacym(admin_client):
    r = admin_client.post('/api/users', json={'username': 'ela', 'display_name': 'Ela'})
    assert r.get_json()['is_trainer'] is False


def test_lider_ustawia_znacznik_operatorowi(leader_client):
    op = make_user('operator')
    r = leader_client.put(f'/api/users/{op.id}', json={'is_trainer': True})
    assert r.status_code == 200 and r.get_json()['is_trainer'] is True


def test_lider_nie_ustawi_znacznika_liderowi(leader_client):
    inny = make_user('leader')
    r = leader_client.put(f'/api/users/{inny.id}', json={'is_trainer': True})
    assert r.status_code == 403
    logistat.db.session.refresh(inny)
    assert not inny.is_trainer


# ── kafelek „Szkolenie" ──────────────────────────────────────────────────────

def obecny(user, minut_temu=120):
    shift = logistat.get_or_create_shift(logistat.local_today(), 1)
    logistat.db.session.add(logistat.ShiftAttendance(
        shift_id=shift.id, user_id=user.id,
        scanned_at=datetime.utcnow() - timedelta(minutes=minut_temu)))
    logistat.db.session.commit()
    return shift


def skan(client, mode, barcode='T1'):
    return client.post('/api/time/scan', json={'barcode': barcode, 'mode': mode})


def test_szkolenie_tylko_dla_szkolacego(leader_client):
    obecny(make_user('operator', barcode_id='T1'))
    r = skan(leader_client, 'training')
    assert r.status_code == 403
    assert 'szkolącą' in r.get_json()['error']


def test_szkolacy_wchodzi_i_wychodzi_ze_szkolenia(leader_client):
    obecny(szkolacy(barcode='T1'))
    assert skan(leader_client, 'training').get_json()['event_type'] == 'training_start'
    assert skan(leader_client, 'training').get_json()['event_type'] == 'training_end'


def test_szkolenie_nie_naklada_sie_z_przerwa_ani_inne(leader_client):
    obecny(szkolacy(barcode='T1'))
    skan(leader_client, 'training')
    for tryb in ('break', 'other'):
        r = skan(leader_client, tryb)
        assert r.status_code == 409 and 'szkoleniu' in r.get_json()['error']
    skan(leader_client, 'training')                 # koniec szkolenia
    skan(leader_client, 'break')                    # przerwa
    r = skan(leader_client, 'training')
    assert r.status_code == 409 and 'przerwie' in r.get_json()['error']
    skan(leader_client, 'break')
    skan(leader_client, 'other')
    r = skan(leader_client, 'training')
    assert r.status_code == 409 and 'Inne' in r.get_json()['error']


def test_koniec_pracy_zamyka_szkolenie(leader_client):
    u = szkolacy(barcode='T1')
    shift = obecny(u)
    skan(leader_client, 'training')
    assert skan(leader_client, 'work_end').status_code == 200
    typy = [e.event_type for e in logistat.WorkerTimeEvent.query.filter_by(
        user_id=u.id, shift_id=shift.id).order_by(logistat.WorkerTimeEvent.id)]
    assert typy == ['training_start', 'training_end', 'work_end']


def test_szkolenie_nie_pomniejsza_czasu_pracy(flask_app):
    u = szkolacy()
    shift = logistat.get_or_create_shift(DZIEN, 1)
    wejscie = chwila(DZIEN, 6)
    szkolenie(u, DZIEN, chwila(DZIEN, 7), chwila(DZIEN, 9))
    logistat.db.session.add(logistat.WorkerTimeEvent(
        user_id=u.id, shift_id=shift.id, event_type='work_end', timestamp=chwila(DZIEN, 14)))
    logistat.db.session.commit()

    t = logistat._compute_worker_times(u.id, shift, wejscie)

    assert t['work_minutes'] == 8 * 60
    assert t['training_minutes'] == 120
    assert len(t['trainings']) == 1 and not t['on_training']


def test_reczne_szkolenie_tylko_dla_szkolacego(leader_client):
    op = make_user('operator')
    shift = logistat.get_or_create_shift(DZIEN, 1)
    r = leader_client.post('/api/worker-times/event', json={
        'user_id': op.id, 'shift_id': shift.id, 'event_type': 'training_start',
        'timestamp': chwila(DZIEN, 8).isoformat()})
    assert r.status_code == 400


# ── Normy: 100% celu dla paczek ze szkolenia ────────────────────────────────

def test_paczki_ze_szkolenia_daja_rowno_cel(leader_client):
    ustaw_cel(100)
    t = szkolacy()
    szkolenie(t, DZIEN, chwila(DZIEN, 8), chwila(DZIEN, 10))
    paczki_po_kolei(t, DZIEN, 8, ile=4, sztuk=5, minut=30)    # 10 szt./h naprawde

    r = wiersz(przeglad(leader_client), 'Trener')

    assert r['szt_h'] == 100
    assert r['proc_celu'] == 100 and r['ocena_celu'] == 'spelnia'
    assert r['paczek_szkolenia'] == 4
    assert r['sztuk'] == 20                    # prawdziwe sztuki zostaja


def test_tylko_paczki_w_czasie_szkolenia(leader_client):
    """Reszta dnia z prawdziwych sztuk: 1 h szkolenia (cel 100) + 1 h po 40 szt."""
    ustaw_cel(100)
    t = szkolacy()
    szkolenie(t, DZIEN, chwila(DZIEN, 8), chwila(DZIEN, 9))
    paczki_po_kolei(t, DZIEN, 8, ile=2, sztuk=5, minut=30)    # w szkoleniu
    paczki_po_kolei(t, DZIEN, 12, ile=2, sztuk=20, minut=30)  # po szkoleniu

    r = wiersz(przeglad(leader_client), 'Trener')

    assert r['paczek_szkolenia'] == 2
    assert r['szt_h'] == 70                    # (100 + 40) / 2 h


def test_samo_szkolenie_bez_paczek_nic_nie_dolicza(leader_client):
    ustaw_cel(100)
    t = szkolacy()
    szkolenie(t, DZIEN, chwila(DZIEN, 6), chwila(DZIEN, 14))
    paczki_po_kolei(t, DZIEN, 16, ile=3, sztuk=10, minut=30)  # po szkoleniu

    r = wiersz(przeglad(leader_client), 'Trener')

    assert r['paczek_szkolenia'] == 0
    assert r['szt_h'] == 20


def test_paczki_ze_szkolenia_nie_wchodza_do_sredniej(leader_client):
    ustaw_cel(100)
    a = make_user('operator', username='ala', display_name='Ala')
    paczki_po_kolei(a, DZIEN, 8, ile=4, sztuk=20, minut=30)   # 40 szt./h
    przed = przeglad(leader_client)['srednia_szt_h']

    t = szkolacy()
    szkolenie(t, DZIEN, chwila(DZIEN, 8), chwila(DZIEN, 10))
    paczki_po_kolei(t, DZIEN, 8, ile=4, sztuk=1, minut=30)

    assert przed == 40
    assert przeglad(leader_client)['srednia_szt_h'] == 40


def test_cel_z_dnia_paczki(leader_client):
    """Cel 100 do 15.09, od 16.09 cel 200 → po 1 h szkolenia w kazdym dniu = 150."""
    ustaw_cel(100)
    nastepny = DZIEN + timedelta(days=1)
    ustaw_cel(200, od=nastepny)
    t = szkolacy()
    for d in (DZIEN, nastepny):
        szkolenie(t, d, chwila(d, 8), chwila(d, 9))
        paczki_po_kolei(t, d, 8, ile=3, sztuk=1, minut=20)

    r = wiersz(przeglad(leader_client, DZIEN, nastepny), 'Trener')

    assert r['szt_h'] == 150


def test_dzien_bez_celu_liczy_prawdziwe_sztuki(leader_client):
    ustaw_cel(0)
    t = szkolacy()
    szkolenie(t, DZIEN, chwila(DZIEN, 8), chwila(DZIEN, 10))
    paczki_po_kolei(t, DZIEN, 8, ile=4, sztuk=5, minut=30)

    r = wiersz(przeglad(leader_client), 'Trener')

    assert r['paczek_szkolenia'] == 0
    assert r['szt_h'] == 10


def test_paczka_bez_startu_w_szkoleniu_nie_ma_czasu(leader_client):
    ustaw_cel(100)
    t = szkolacy()
    szkolenie(t, DZIEN, chwila(DZIEN, 8), chwila(DZIEN, 10))
    paczka(t, 50, None, chwila(DZIEN, 9))

    r = wiersz(przeglad(leader_client), 'Trener')

    assert r['szt_h'] is None


def test_ocena_osoby_i_wykres_zgadzaja_sie_z_przegladem(leader_client):
    ustaw_cel(100)
    t = szkolacy()
    szkolenie(t, DZIEN, chwila(DZIEN, 8), chwila(DZIEN, 10))
    paczki_po_kolei(t, DZIEN, 8, ile=4, sztuk=5, minut=30)

    wiersz_przegladu = wiersz(przeglad(leader_client), 'Trener')
    dane = leader_client.get(
        f'/api/stats/user/{t.id}?date_from={DZIEN}&date_to={DZIEN}').get_json()

    assert dane['norma']['wiersz'] == wiersz_przegladu
    assert dane['wykres_dzienny'][0]['szt_h'] == 100
    assert dane['wykres_dzienny'][0]['paczek_szkolenia'] == 4
    assert dane['wykres_dzienny'][0]['sztuk'] == 20
    assert dane['wykres_miesieczny'][0]['szt_h'] == 100


# ── historia celu ────────────────────────────────────────────────────────────

def test_zmiana_celu_nie_przelicza_starych_dni(leader_client):
    logistat.set_setting('target_szt_h', 80)
    logistat.db.session.commit()

    assert leader_client.put('/api/stats/target', json={'target_szt_h': 120}).status_code == 200

    cel = logistat.cele_dzienne()
    assert cel(DZIEN) == 80
    assert cel(logistat.local_today()) == 120


def test_dwa_zapisy_celu_jednego_dnia(leader_client):
    leader_client.put('/api/stats/target', json={'target_szt_h': 120})
    leader_client.put('/api/stats/target', json={'target_szt_h': 130})

    assert logistat.cele_dzienne()(logistat.local_today()) == 130
    assert logistat.HistoriaCelu.query.count() == 2   # zasiew + dzis
