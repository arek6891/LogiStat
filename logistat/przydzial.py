"""Przydzielanie — dane z bazy: estymacja per czynnosc (srednia jednej osoby ze
wszystkich pracownikow, 30 dni; Post Processing ze skanow paczek) i wersja
przydzialu zmiany (wykrywanie dwoch liderow na jednej zmianie)."""
import hashlib
import json
from datetime import timedelta

from sqlalchemy import func

from logistat.extensions import db
from logistat.models import Activity, DailyStat, Shift
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
