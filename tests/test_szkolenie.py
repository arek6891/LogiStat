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


# ── zakladka „Szkolenie": szkolacy + osoby szkolone ─────────────────────────

def obecny(user, minut_temu=120):
    shift = logistat.get_or_create_shift(logistat.local_today(), 1)
    logistat.db.session.add(logistat.ShiftAttendance(
        shift_id=shift.id, user_id=user.id,
        scanned_at=datetime.utcnow() - timedelta(minutes=minut_temu)))
    logistat.db.session.commit()
    return shift


def skan(client, mode, barcode='T1'):
    return client.post('/api/time/scan', json={'barcode': barcode, 'mode': mode})


def wybierz_trenera(client, barcode='T1'):
    return client.post('/api/time/training/trener', json={'barcode': barcode})


def dopisz(client, trener, barcode):
    return client.post('/api/time/training/szkolony',
                       json={'trener_id': trener.id, 'barcode': barcode})


def zakoncz(client, trener):
    return client.post('/api/time/training/koniec', json={'trener_id': trener.id})


def zdarzenia(user):
    return [(e.event_type, e.timestamp, e.training_lead_id)
            for e in logistat.WorkerTimeEvent.query.filter_by(user_id=user.id)
            .order_by(logistat.WorkerTimeEvent.id)]


def ekipa():
    """Szkolacy T1 + dwie osoby do szkolenia (S1, S2), wszyscy obecni dzis."""
    t = szkolacy(barcode='T1')
    s1 = make_user('operator', username='s1', display_name='Szkolona1', barcode_id='S1')
    s2 = make_user('operator', username='s2', display_name='Szkolona2', barcode_id='S2')
    for u in (t, s1, s2):
        obecny(u)
    return t, s1, s2


def test_szkolenia_nie_prowadzi_osoba_bez_znacznika(leader_client):
    obecny(make_user('operator', barcode_id='T1'))
    r = wybierz_trenera(leader_client)
    assert r.status_code == 403
    assert 'szkolącą' in r.get_json()['error']


def test_zwykly_skan_nie_zaczyna_szkolenia(leader_client):
    """Wymog min. 1 szkolonego — stary przelacznik by go omijal."""
    obecny(szkolacy(barcode='T1'))
    assert skan(leader_client, 'training').status_code == 400
    assert skan(leader_client, 'trainee').status_code == 400


def test_sam_skan_szkolacego_niczego_nie_zapisuje(leader_client):
    t, _, _ = ekipa()
    r = wybierz_trenera(leader_client)
    assert r.status_code == 200
    assert r.get_json()['trwa'] is False and r.get_json()['szkoleni'] == []
    assert zdarzenia(t) == []


def test_pierwszy_szkolony_zaczyna_szkolenie_w_tej_samej_chwili(leader_client):
    t, s1, _ = ekipa()
    r = dopisz(leader_client, t, 'S1')

    assert r.status_code == 200
    dane = r.get_json()
    assert dane['trwa'] is True
    assert [u['display_name'] for u in dane['szkoleni']] == ['Szkolona1']
    (typ_t, ts_t, _), = zdarzenia(t)
    (typ_s, ts_s, lead), = zdarzenia(s1)
    assert (typ_t, typ_s) == ('training_start', 'trainee_start')
    assert ts_t == ts_s and lead == t.id


def test_szkolonego_mozna_dopisac_w_trakcie(leader_client):
    t, s1, s2 = ekipa()
    dopisz(leader_client, t, 'S1')
    r = dopisz(leader_client, t, 'S2')

    assert r.status_code == 200
    assert len(r.get_json()['szkoleni']) == 2
    assert [z[0] for z in zdarzenia(t)] == ['training_start']   # bez drugiego startu
    assert wybierz_trenera(leader_client).get_json()['trwa'] is True


def test_koniec_szkolenia_konczy_wszystkich_naraz(leader_client):
    t, s1, s2 = ekipa()
    dopisz(leader_client, t, 'S1')
    dopisz(leader_client, t, 'S2')

    r = zakoncz(leader_client, t)

    assert r.status_code == 200
    konce = [zdarzenia(u)[-1] for u in (t, s1, s2)]
    assert [k[0] for k in konce] == ['training_end', 'trainee_end', 'trainee_end']
    assert len({k[1] for k in konce}) == 1
    assert zakoncz(leader_client, t).status_code == 409


def test_koniec_pracy_szkolacego_konczy_szkolonych(leader_client):
    t, s1, _ = ekipa()
    dopisz(leader_client, t, 'S1')

    assert skan(leader_client, 'work_end').status_code == 200

    assert [z[0] for z in zdarzenia(t)] == ['training_start', 'training_end', 'work_end']
    assert [z[0] for z in zdarzenia(s1)] == ['trainee_start', 'trainee_end']


def test_koniec_pracy_szkolonego_zamyka_tylko_jego(leader_client):
    t, s1, s2 = ekipa()
    dopisz(leader_client, t, 'S1')
    dopisz(leader_client, t, 'S2')

    skan(leader_client, 'work_end', barcode='S1')

    assert [z[0] for z in zdarzenia(s1)] == ['trainee_start', 'trainee_end', 'work_end']
    assert [u['display_name'] for u in wybierz_trenera(leader_client).get_json()['szkoleni']] \
        == ['Szkolona2']


def test_dwa_szkolenia_naraz_koncza_sie_osobno(leader_client):
    t, s1, _ = ekipa()
    t2 = szkolacy('Trener2', barcode='T2')
    obecny(t2)
    s3 = make_user('operator', username='s3', barcode_id='S3')
    obecny(s3)
    dopisz(leader_client, t, 'S1')
    dopisz(leader_client, t2, 'S3')

    zakoncz(leader_client, t)

    assert zdarzenia(s1)[-1][0] == 'trainee_end'
    assert zdarzenia(s3)[-1][0] == 'trainee_start'


def test_szkolony_nie_wyjdzie_na_przerwe(leader_client):
    t, _, _ = ekipa()
    dopisz(leader_client, t, 'S1')
    r = skan(leader_client, 'break', barcode='S1')
    assert r.status_code == 409 and 'szkolona' in r.get_json()['error']


def test_szkolacy_nie_wyjdzie_na_przerwe_w_trakcie(leader_client):
    t, _, _ = ekipa()
    dopisz(leader_client, t, 'S1')
    r = skan(leader_client, 'break')
    assert r.status_code == 409 and 'szkolenie' in r.get_json()['error']


def test_bledy_przy_dopisywaniu(leader_client):
    t, s1, s2 = ekipa()
    nieobecny = make_user('operator', barcode_id='N1')
    skan(leader_client, 'break', barcode='S2')                 # S2 na przerwie

    assert dopisz(leader_client, t, 'XX').status_code == 404
    assert dopisz(leader_client, t, 'T1').status_code == 400   # kod szkolacego
    assert dopisz(leader_client, t, 'N1').status_code == 400   # nie ma go na zmianie
    r = dopisz(leader_client, t, 'S2')
    assert r.status_code == 409 and 'przerwie' in r.get_json()['error']
    assert zdarzenia(t) == []                                   # nic nie zaczeto
    dopisz(leader_client, t, 'S1')
    r = dopisz(leader_client, t, 'S1')
    assert r.status_code == 409 and 'już jest na tym szkoleniu' in r.get_json()['error']
    assert nieobecny.id


def test_szkolacy_na_przerwie_nie_zacznie(leader_client):
    t, _, _ = ekipa()
    skan(leader_client, 'break')
    assert wybierz_trenera(leader_client).status_code == 409
    assert dopisz(leader_client, t, 'S1').status_code == 409


def test_aktywne_szkolenia(leader_client):
    t, _, _ = ekipa()
    assert leader_client.get('/api/time/training/aktywne').get_json()['szkolenia'] == []
    dopisz(leader_client, t, 'S1')
    dane = leader_client.get('/api/time/training/aktywne').get_json()['szkolenia']
    assert [d['trener']['id'] for d in dane] == [t.id]
    assert [u['display_name'] for u in dane[0]['szkoleni']] == ['Szkolona1']


def test_czas_szkolonego_nie_pomniejsza_pracy(leader_client):
    t, s1, _ = ekipa()
    dopisz(leader_client, t, 'S1')
    shift = logistat.get_or_create_shift(logistat.local_today(), 1)
    wejscie = logistat.ShiftAttendance.query.filter_by(user_id=s1.id).one().scanned_at

    w = logistat._compute_worker_times(s1.id, shift, wejscie)

    assert w['on_trainee'] and w['work_minutes'] >= 119
    assert len(w['trainee_periods']) == 1


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


def test_paczka_zaczeta_przed_szkoleniem_zalicza_tylko_czas_w_szkoleniu(leader_client):
    """Paczka 8:05–10:05 (120 szt., 60 szt./h), szkolenie od 10:00: 5 minut celu
    (100 szt./h), reszta z prawdziwych sztuk — nie 2 h po 100."""
    ustaw_cel(100)
    t = szkolacy()
    szkolenie(t, DZIEN, chwila(DZIEN, 10), chwila(DZIEN, 12))
    paczka(t, 120, chwila(DZIEN, 8, 5), chwila(DZIEN, 10, 5))

    dane = przeglad(leader_client)
    r = wiersz(dane, 'Trener')

    assert r['paczek_szkolenia'] == 1
    assert r['szt_h'] == 61.7                  # (115 + 100 * 5/60) / 2 h
    assert r['godzin_szkolenia'] == round(5 / 60, 2)
    assert dane['srednia_szt_h'] == 60         # tylko czesc poza szkoleniem


def test_paczka_w_szkoleniu_rownolegle_z_inna_nie_liczy_czasu_dwa_razy(leader_client):
    """Mianownik to jedna suma zlaczonych okresow wszystkich paczek."""
    ustaw_cel(100)
    t = szkolacy()
    szkolenie(t, DZIEN, chwila(DZIEN, 8), chwila(DZIEN, 9))
    paczka(t, 10, chwila(DZIEN, 8), chwila(DZIEN, 9))
    paczka(t, 10, chwila(DZIEN, 8), chwila(DZIEN, 9))

    r = wiersz(przeglad(leader_client), 'Trener')

    assert r['godzin'] == 1.0
    assert r['szt_h'] == 100                   # cel, nie 2 × cel


# ── Normy: osoba szkolona wypada z oceny w czasie szkolenia ─────────────────

def jako_szkolony(kto, trener, dzien, od, do):
    shift = logistat.get_or_create_shift(dzien, 1)
    for typ, ts in (('trainee_start', od), ('trainee_end', do)):
        logistat.db.session.add(logistat.WorkerTimeEvent(
            user_id=kto.id, shift_id=shift.id, event_type=typ, timestamp=ts,
            training_lead_id=trener.id))
    logistat.db.session.commit()


def test_paczki_szkolonego_z_czasu_szkolenia_wypadaja(leader_client):
    t = szkolacy()
    s = make_user('operator', username='nowa', display_name='Nowa')
    jako_szkolony(s, t, DZIEN, chwila(DZIEN, 8), chwila(DZIEN, 10))
    paczki_po_kolei(s, DZIEN, 8, ile=4, sztuk=1, minut=30)    # w szkoleniu, 2 szt./h
    paczki_po_kolei(s, DZIEN, 12, ile=3, sztuk=20, minut=20)  # po szkoleniu, 60 szt./h

    dane = przeglad(leader_client)
    r = wiersz(dane, 'Nowa')

    assert r['paczek'] == 7 and r['paczek_jako_szkolony'] == 4
    assert r['paczek_do_oceny'] == 3
    assert r['szt_h'] == 60
    assert dane['srednia_szt_h'] == 60
    assert r in dane['pracownicy']


def test_szkolony_wypada_takze_bez_celu(flask_app):
    """Wylaczenie szkolonego nie zalezy od celu (cel 0 nie wylacza wylaczenia)."""
    ustaw_cel(0)
    t = szkolacy()
    s = make_user('operator', username='nowa', display_name='Nowa')
    jako_szkolony(s, t, DZIEN, chwila(DZIEN, 8), chwila(DZIEN, 10))
    paczki_po_kolei(s, DZIEN, 8, ile=4, sztuk=1, minut=30)

    r = logistat.przeglad_zespolu(DZIEN, DZIEN)

    assert r['srednia_szt_h'] is None
    assert wiersz(r, 'Nowa')['szt_h'] is None


def test_paczka_szkolonego_przecieta_szkoleniem_liczy_sie_czesciowo(leader_client):
    """Paczka 9:00–11:00 (120 szt.), szkolenie do 10:00 → zostaje 1 h i 60 szt."""
    t = szkolacy()
    s = make_user('operator', username='nowa', display_name='Nowa')
    jako_szkolony(s, t, DZIEN, chwila(DZIEN, 8), chwila(DZIEN, 10))
    paczka(s, 120, chwila(DZIEN, 9), chwila(DZIEN, 11))

    r = wiersz(przeglad(leader_client), 'Nowa')

    assert r['godzin'] == 1.0 and r['szt_h'] == 60
    assert r['godzin_jako_szkolony'] == 1.0


def test_paczka_szkolonego_bez_startu_wypada(leader_client):
    t = szkolacy()
    s = make_user('operator', username='nowa', display_name='Nowa')
    jako_szkolony(s, t, DZIEN, chwila(DZIEN, 8), chwila(DZIEN, 10))
    paczka(s, 50, None, chwila(DZIEN, 9))

    r = wiersz(przeglad(leader_client), 'Nowa')

    assert r['paczek_do_oceny'] == 0 and r['paczek_jako_szkolony'] == 1


def test_szkolony_bez_innych_paczek_dostaje_wlasny_powod(leader_client):
    t = szkolacy()
    s = make_user('operator', username='nowa', display_name='Nowa')
    jako_szkolony(s, t, DZIEN, chwila(DZIEN, 8), chwila(DZIEN, 12))
    paczki_po_kolei(s, DZIEN, 8, ile=4, sztuk=10, minut=30)

    dane = leader_client.get(
        f'/api/stats/user/{s.id}?date_from={DZIEN}&date_to={DZIEN}').get_json()

    assert dane['norma']['powod_braku_oceny'] == 'szkolony'
    assert dane['norma']['wiersz'] == wiersz(przeglad(leader_client), 'Nowa')
    assert dane['wykres_dzienny'][0]['szt_h'] is None
    assert dane['wykres_dzienny'][0]['paczek_jako_szkolony'] == 4
    # Podsumowanie paczek to nie norma — liczy prawdziwe paczki.
    assert dane['paczki_podsumowanie']['paczek'] == 4


def test_szkolacy_dalej_dostaje_100_procent_przy_szkolonym(leader_client):
    """Ten sam przeplyw ze skanera: szkolacy zaliczony, szkolony wylaczony."""
    ustaw_cel(100)
    t, s1, _ = ekipa()
    dopisz(leader_client, t, 'S1')
    teraz = datetime.utcnow()
    paczka(t, 1, teraz - timedelta(seconds=1), teraz)
    zakoncz(leader_client, t)
    dzis = logistat.local_today()

    dane = przeglad(leader_client, dzis, dzis)

    assert wiersz(dane, 'Trener')['paczek_szkolenia'] == 1


def test_dwie_stacje_naraz_daja_jeden_start_szkolenia(flask_app, leader, monkeypatch):
    """Pierwszy szkolony z dwoch stacji jednoczesnie: bez blokady wiersza
    szkolacego oba zadania widzialy „szkolenie nie trwa" i pisaly dwa starty."""
    import threading
    import time
    from conftest import login

    t, _, _ = ekipa()
    nazwa_lidera = leader.username
    oryginal = logistat.stan_czasu_dzis

    def wolno(user):
        wynik = oryginal(user)
        time.sleep(0.3)
        return wynik

    monkeypatch.setattr(logistat, 'stan_czasu_dzis', wolno)
    wyniki = []

    def zadanie(kod):
        with flask_app.app_context():
            k = flask_app.test_client()
            login(k, nazwa_lidera)
            wyniki.append(dopisz(k, t, kod).status_code)
            logistat.db.session.remove()

    watki = [threading.Thread(target=zadanie, args=(kod,)) for kod in ('S1', 'S2')]
    for w in watki:
        w.start()
    for w in watki:
        w.join(timeout=15)

    assert wyniki == [200, 200]
    assert [z[0] for z in zdarzenia(t)] == ['training_start']
