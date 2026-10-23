"""Przydzielanie — dane z bazy: estymacja per czynnosc (srednia jednej osoby ze
wszystkich pracownikow, 30 dni; Post Processing ze skanow paczek), grupy
P1/P2/P3 (ostatnie 20 dni pracy magazynu), ilosc do zrobienia z forecastu,
sugestie AI i wersja przydzialu zmiany (wykrywanie dwoch liderow na jednej zmianie)."""
import hashlib
import json
import math
from datetime import timedelta

from sqlalchemy import func

from logistat.czas import local_day_bounds, utc_to_local
from logistat.extensions import db
from logistat.models import (
    Activity, ActivityAssignment, DailyStat, Forecast, ImportedCarton, Shift)
from logistat.normy_dane import przeglad_zespolu

# Estymacja na tablicy Przydzielania (2026-10-13, operacje): ile zrobia osoby
# przydzielone do czynnosci = liczba osob × srednia NA OSOBE wszystkich
# pracownikow (nie tylko przydzielonych) z ostatnich 30 dni.
CZYNNOSC_SKANOW_PACZEK = 'Post Processing'   # ta czynnosc = skany paczek


DNI_SREDNIEJ_PRZYDZIALU = 30


GODZIN_ZMIANY = 7.5                          # 8 h minus 30 min przerwy


def wersja_przydzialu(przydzialy):
    """Odcisk przydzialu zmiany — do wykrycia, ze ktos inny zmienil go w miedzyczasie.

    Ekran zapisuje sie sam po kazdym przeciagnieciu, a zapis podmienia CALY
    przydzial zmiany. Dwoch liderow (albo dwa tablety) na tej samej zmianie
    nadpisywaloby sobie prace po cichu, wiec klient odsyla wersje, ktora
    wczytal, a zapis na nieaktualnej dostaje 409. Liczone z tresci, nie z
    czasu: bez nowej kolumny, a ten sam stan zawsze daje te sama wersje.
    """
    pary = sorted((a.user_id, a.activity_id) for a in przydzialy)
    return hashlib.sha1(json.dumps(pary).encode()).hexdigest()[:16]


def wydajnosc_czynnosci(dzien):
    """Srednia wydajnosc jednej osoby per czynnosc: {activity_id: {...}}.

    `Post Processing` bierze srednia zespolu szt./h ze skanow paczek — ta sama
    liczba co w Normach (`przeglad_zespolu()`), bez fragmentow szkolen. Pozostale
    czynnosci: srednia `DailyStat.quantity` na wpis (osoba × zmiana). Czynnosc
    bez danych nie ma klucza — ekran pokazuje „brak danych", nie zero.
    """
    od = dzien - timedelta(days=DNI_SREDNIEJ_PRZYDZIALU)
    wynik = {}

    for s in db.session.query(
        DailyStat.activity_id,
        func.avg(DailyStat.quantity).label('srednia'),
        func.count(DailyStat.id).label('wpisow')
    ).join(Shift).filter(
        Shift.date >= od, Shift.date <= dzien
    ).group_by(DailyStat.activity_id).all():
        na_zmiane = float(s.srednia or 0)
        wynik[s.activity_id] = {
            'szt_zmiana_os': round(na_zmiane, 1),
            'szt_h_os': round(na_zmiane / GODZIN_ZMIANY, 1),
            'zrodlo': 'wpis',
            'probek': s.wpisow,
        }

    skany = Activity.query.filter_by(name=CZYNNOSC_SKANOW_PACZEK).first()
    if skany:
        szt_h = przeglad_zespolu(od, dzien)['srednia_szt_h']
        if szt_h:
            wynik[skany.id] = {
                'szt_zmiana_os': round(szt_h * GODZIN_ZMIANY, 1),
                'szt_h_os': szt_h,
                'zrodlo': 'skany',
                'probek': None,
            }
    return wynik


# ── Grupy P1 / P2 / P3 (operacja 2026-10-23) ─────────────────────────────────
# Grupa = ocena z Norm (`przeglad_zespolu()`, ta sama definicja co kolory
# w Normach) za ostatnie DNI_GRUP dni pracy magazynu przed dniem zmiany:
# 🔴 slaba → P1, szara „w normie” → P2, 🟢 dobra → P3. Za malo danych (ponizej
# `min_packages_rank` albo bez czasu) → bez grupy. Liczone na biezaco, nic
# nie jest zapisywane — grupa zawsze zgadza sie z Normami za to okno.
DNI_GRUP = 20
GRUPA_Z_OCENY = {'slaba': 'P1', 'ok': 'P2', 'dobra': 'P3'}


def dni_pracy_magazynu(przed, ile=DNI_GRUP):
    """Ostatnie `ile` lokalnych dni z choc jedna zakonczona paczka, przed `przed`
    (dzien zmiany sie nie liczy — jest w toku). Rosnaco. Doby po Warszawie
    w Pythonie (nie `func.date()`); okno szukania rozszerzane, gdy za krotkie."""
    koniec, _ = local_day_bounds(przed)
    for wstecz in (45, 120, 400):
        start, _ = local_day_bounds(przed - timedelta(days=wstecz))
        dni = {utc_to_local(t).date() for (t,) in db.session.query(ImportedCarton.scan_end_at)
               .filter(ImportedCarton.scan_end_at >= start, ImportedCarton.scan_end_at < koniec)}
        if len(dni) >= ile:
            break
    return sorted(dni)[-ile:]


def grupy_wydajnosci(dzien):
    """{'grupy': {user_id: {'grupa', 'proc_sredniej'}}, 'okno': {...} | None}."""
    dni = dni_pracy_magazynu(dzien)
    if not dni:
        return {'grupy': {}, 'okno': None}
    p = przeglad_zespolu(dni[0], dni[-1])
    grupy = {}
    for r in p['pracownicy']:
        grupa = GRUPA_Z_OCENY.get(r['ocena'])
        if grupa:
            grupy[r['user_id']] = {'grupa': grupa, 'proc_sredniej': r['proc_sredniej']}
    return {'grupy': grupy,
            'okno': {'od': dni[0].isoformat(), 'do': dni[-1].isoformat(), 'dni': len(dni),
                     'progi': p['progi']}}


# ── Ilosc do zrobienia — Post Processing (operacja 2026-10-23) ───────────────

def do_zrobienia_dnia(dzien):
    """Sztuki na dzien zmiany (Loading date = dzien): Actual (suma Stückzahl
    z importu) albo, bez importu, Forecast. {'sztuk', 'zrodlo'} albo None."""
    actual = (db.session.query(func.sum(ImportedCarton.stueckzahl))
              .filter(ImportedCarton.data_pliku == dzien).scalar())
    if actual:
        return {'sztuk': int(actual), 'zrodlo': 'actual'}
    f = Forecast.query.filter_by(date=dzien).first()
    if f and f.quantity:
        return {'sztuk': int(f.quantity), 'zrodlo': 'forecast'}
    return None


def osob_pp_na_zmianie(dzien, shift_number):
    """Ile osob ma Post Processing na danej zmianie (zapisany przydzial)."""
    pp = Activity.query.filter_by(name=CZYNNOSC_SKANOW_PACZEK).first()
    if not pp:
        return 0
    return (db.session.query(func.count(ActivityAssignment.id))
            .join(Shift, Shift.id == ActivityAssignment.shift_id)
            .filter(Shift.date == dzien, Shift.shift_number == shift_number,
                    ActivityAssignment.activity_id == pp.id).scalar() or 0)


# ── Sugestie AI (od 2026-10-23: po grupach) ──────────────────────────────────
KOLEJNOSC_GRUP = {'P3': 0, 'P2': 1, None: 2, 'P1': 3}


def sugestie_przydzialu(obecni, czynnosci, szkolenia, grupy, srednie, wydajnosc,
                        do_zrobienia, osob_pp_druga):
    """Sugestie [{user_id, activity_id, grupa, powod}] — czysta logika, bez bazy.

    1. Post Processing: najpierw P3, potem P2, bez grupy, P1 (w grupie: wyzszy
       % sredniej pierwszy), tylko przeszkoleni — az estymacja obu zmian
       pokryje ilosc do zrobienia (druga zmiana liczona z jej zapisanego
       przydzialu). Bez forecastu / estymacji: do PP ida P3 i P2.
    2. Reszta osob: kazda pozostala czynnosc dostaje najpierw najlepsza osobe
       wg sredniej z Wpisu ilosci (30 dni), potem kazdy do czynnosci z najmniej
       osobami (w ktorych przeszkolony); kto ma tylko PP — do PP.
    `srednie` = {(user_id, activity_id): srednia}, `szkolenia` = {user_id: {activity_id}}.
    """
    przeszkolony = lambda uid, aid: aid in szkolenia.get(uid, ())   # noqa: E731
    pp = next((a for a in czynnosci if a.name == CZYNNOSC_SKANOW_PACZEK), None)
    grupa = lambda uid: (grupy.get(uid) or {}).get('grupa')         # noqa: E731
    kolejka = sorted(obecni, key=lambda uid: (
        KOLEJNOSC_GRUP[grupa(uid)], -((grupy.get(uid) or {}).get('proc_sredniej') or 0), uid))
    wynik, przydzieleni = [], set()

    def dodaj(uid, aid, powod):
        wynik.append({'user_id': uid, 'activity_id': aid, 'grupa': grupa(uid), 'powod': powod})
        przydzieleni.add(uid)

    if pp:
        na_osobe = (wydajnosc.get(pp.id) or {}).get('szt_zmiana_os')
        if do_zrobienia and na_osobe:
            brakuje = max(0.0, do_zrobienia['sztuk'] - osob_pp_druga * na_osobe)
            potrzeba = math.ceil(brakuje / na_osobe)
            chetni = [u for u in kolejka if przeszkolony(u, pp.id)]
        else:
            chetni = [u for u in kolejka if przeszkolony(u, pp.id) and grupa(u) in ('P3', 'P2')]
            potrzeba = len(chetni)
        for uid in chetni[:potrzeba]:
            dodaj(uid, pp.id, f'{grupa(uid) or "bez grupy"} → Post Processing')

    inne = [a for a in czynnosci if not pp or a.id != pp.id]
    for akt in inne:
        kandydaci = [u for u in kolejka if u not in przydzieleni and przeszkolony(u, akt.id)]
        if kandydaci:
            najlepszy = max(kandydaci, key=lambda u: srednie.get((u, akt.id), 0))
            dodaj(najlepszy, akt.id, 'najlepsza średnia z Wpisu ilości'
                  if srednie.get((najlepszy, akt.id)) else 'obsadzenie czynności')
    licznik = {a.id: 0 for a in czynnosci}
    for s_ in wynik:
        licznik[s_['activity_id']] += 1
    for uid in kolejka:
        if uid in przydzieleni:
            continue
        mozliwe = [a.id for a in inne if przeszkolony(uid, a.id)]
        if not mozliwe and pp and przeszkolony(uid, pp.id):
            mozliwe = [pp.id]
        if mozliwe:
            aid = min(mozliwe, key=lambda a: licznik[a])
            dodaj(uid, aid, 'najmniej obsadzona czynność')
            licznik[aid] += 1
    return wynik
