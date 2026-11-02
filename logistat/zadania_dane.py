"""Zadania dodatkowe (2026-11-02) — odczyty z bazy dla ekranu, eksportu i listy admina.
Bez requestu; walidacja i zapis w logistat/web/zadania.py."""
from logistat.czas import iso_z
from logistat.extensions import db
from logistat.models import (
    CzynnoscDodatkowa, Shift, ShiftAttendance, User, ZadanieDodatkowe)
from logistat.zadania import DZIALY, godziny


def czynnosci_dodatkowe():
    return CzynnoscDodatkowa.query.order_by(CzynnoscDodatkowa.kolejnosc, CzynnoscDodatkowa.id).all()


def uzyte_czynnosci():
    """Id czynnosci z co najmniej jednym zadaniem (usuniecie → 409)."""
    return {c for (c,) in db.session.query(ZadanieDodatkowe.czynnosc_id).distinct()
            if c is not None}


def zadanie_dict(z):
    return {'id': z.id, 'user_id': z.user_id, 'dzial': z.dzial, 'od': iso_z(z.od),
            'do': iso_z(z.do), 'czynnosc_id': z.czynnosc_id, 'komentarz': z.komentarz or ''}


def stan_zmiany(shift):
    """Dane ekranu: wiersze zmiany, osoby do wyboru (aktywni operatorzy + kazdy z
    wierszem; `obecny` = zeskanowany na tej zmianie), dzialy i czynnosci (aktywne
    + wylaczone, ktore wiersze juz maja)."""
    wiersze = ZadanieDodatkowe.query.filter_by(shift_id=shift.id)\
        .order_by(ZadanieDodatkowe.od, ZadanieDodatkowe.id).all()
    w_wierszach = {z.user_id for z in wiersze}
    obecni = {u for (u,) in db.session.query(ShiftAttendance.user_id).filter_by(shift_id=shift.id)}
    osoby = User.query.filter(db.or_(
        db.and_(User.role == 'operator', User.is_active_user.is_(True)),
        User.id.in_(w_wierszach | obecni) if (w_wierszach | obecni) else db.false()))\
        .order_by(User.display_name).all()
    uzyte = {z.czynnosc_id for z in wiersze}
    return {
        'wiersze': [zadanie_dict(z) for z in wiersze],
        'osoby': [{'id': u.id, 'nazwa': u.display_name, 'obecny': u.id in obecni,
                   'aktywny': bool(u.is_active_user)} for u in osoby],
        'dzialy': [{'klucz': k, 'nazwa': n} for k, n in DZIALY.items()],
        'czynnosci': [{'id': c.id, 'nazwa': c.nazwa, 'aktywna': c.aktywna}
                      for c in czynnosci_dodatkowe() if c.aktywna or c.id in uzyte],
    }


def wiersze_eksportu(od, do):
    """Zadania zmian z dni [od, do] (data zmiany), po dacie, zmianie, osobie, godzinie."""
    zadania = ZadanieDodatkowe.query.join(Shift, ZadanieDodatkowe.shift_id == Shift.id)\
        .join(User, ZadanieDodatkowe.user_id == User.id)\
        .filter(Shift.date >= od, Shift.date <= do)\
        .order_by(Shift.date, Shift.shift_number, User.display_name, ZadanieDodatkowe.od).all()
    return [{
        'data': z.shift.date, 'zmiana': z.shift.shift_number, 'osoba': z.user.display_name,
        'dzial': DZIALY.get(z.dzial, z.dzial), 'od': z.od, 'do': z.do,
        'godziny': godziny(z.od, z.do), 'czynnosc': z.czynnosc.nazwa if z.czynnosc else '',
        'komentarz': z.komentarz or '', 'wpisal': z.wpisal.display_name if z.wpisal else '',
    } for z in zadania]
