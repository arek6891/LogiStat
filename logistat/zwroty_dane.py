"""Zwroty Paczek (kafelek Zwroty, od 2026-10-26) — dane tabeli.

Naglowki = dokladnie te z arkusza „Return_September_2026” operacji (nazwy,
pisownia i kolejnosc — tabela jest dalej przekazywana klientowi). Ekran i
eksport do Excela biora wiersze z JEDNEJ funkcji `wiersze_zwrotow()`, zeby nie
rozjechaly sie, gdy dojda zrodla danych.

Zrodla poszczegolnych kolumn ustalamy z operacja krok po kroku — do tego czasu
`wiersze_zwrotow()` zwraca pusta liste (bez zgadywanego modelu w bazie:
`migrate_columns()` umie tylko dokladac kolumny, nie zmieniac ich).

Invoice specification i Sorting Data (2026-10-26): wpisy reczne + cennik
miesieczny (admin); Sorting returns liczony z `wiersze_zwrotow()`.
"""
import calendar
from datetime import date

from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert

from logistat.czas import teraz_utc
from logistat.extensions import db
from logistat.faktura_zwrotow import (
    CZYNNOSCI_AUTO, CZYNNOSCI_FAKTURY, KLUCZ_POS, KLUCZE_FAKTURY, LICENCJA, WYSYLKA)
from logistat.models import CenaZwrotow, IloscMiesiacaZwrotow, LicencjaZwrotow, SortingDataWpis

NAGLOWKI_ZWROTOW = (
    'Paketnummer', 'Brand', 'Date', 'POS-Nummer', 'DPD', 'UPS', 'Retoure', 'Defekt',
    'Neuwarenueberschuss', 'Silber_in_Stück', 'Defektes_Silber_in_Stück',
    'Reduzierte_ware', 'Verpackungsvorschrift', 'Monat', 'Woche',
)


def wiersze_zwrotow(od, do, brand=None, paketnummer=None):
    """Wiersze tabeli z dni [od, do] (daty lokalne, wlacznie) — kazdy jako krotka
    wartosci w kolejnosci `NAGLOWKI_ZWROTOW`. `brand` = dokladna wartosc,
    `paketnummer` = fragment numeru. Na razie brak zrodla danych → []."""
    return []


def brandy_zwrotow():
    """Wartosci Brand do listy w filtrze (z danych). Na razie brak danych → []."""
    return []


# ── Invoice specification ────────────────────────────────────────────────────

def granice_miesiaca(rok, miesiac):
    """Pierwszy i ostatni dzien miesiaca (daty lokalne)."""
    return date(rok, miesiac, 1), date(rok, miesiac, calendar.monthrange(rok, miesiac)[1])


def liczba_sorting_returns(rok, miesiac):
    """Sorting returns = liczba wierszy raportu Zwroty Paczek w miesiacu (paczka =
    wiersz; powtorzony Paketnummer liczy sie znowu — tak liczy arkusz operacji)."""
    return len(wiersze_zwrotow(*granice_miesiaca(rok, miesiac)))


def ceny_miesiaca(rok, miesiac):
    """{czynnosc: cena EUR} ustawione przez admina; brak wpisu = brak ceny (nie 0)."""
    return {c.czynnosc: c.cena for c in CenaZwrotow.query.filter_by(rok=rok, miesiac=miesiac)}


def invoice_specification(rok, miesiac):
    """Wiersze raportu: ilosc (reczna albo z systemu), UoM, cena, Total charge.

    Bez ceny Total charge = None, a `brak_cen` wymienia czynnosci — faktura z
    cicha zerowa pozycja nie moze wyjsc do klienta."""
    reczne = {w.klucz: w.wartosc for w in IloscMiesiacaZwrotow.query.filter(
        IloscMiesiacaZwrotow.rok == rok, IloscMiesiacaZwrotow.miesiac == miesiac,
        IloscMiesiacaZwrotow.klucz.in_(KLUCZE_FAKTURY))}
    ceny = ceny_miesiaca(rok, miesiac)
    wiersze = []
    for klucz, nazwa, uom in CZYNNOSCI_FAKTURY:
        auto = klucz in CZYNNOSCI_AUTO
        ilosc = liczba_sorting_returns(rok, miesiac) if auto else reczne.get(klucz)
        cena = ceny.get(klucz)
        wiersze.append({
            'klucz': klucz, 'activity': nazwa, 'uom': uom, 'auto': auto,
            'ilosc': ilosc, 'cena': cena,
            'charge': None if cena is None else (ilosc or 0) * cena,
        })
    return {
        'rok': rok, 'miesiac': miesiac, 'wiersze': wiersze,
        'total': sum(w['charge'] for w in wiersze if w['charge'] is not None),
        'brak_cen': [w['activity'] for w in wiersze if w['cena'] is None],
    }


def _upsert(model, klucz, wartosci):
    """INSERT … ON CONFLICT DO UPDATE — dwoch liderow na tej samej komorce
    nie wywraca sie na kluczu glownym (autozapis z dwoch kart)."""
    stmt = insert(model.__table__).values(**klucz, **wartosci)
    db.session.execute(stmt.on_conflict_do_update(
        index_elements=list(klucz), set_=wartosci))


def zapisz_ilosc_miesiaca(rok, miesiac, klucz, wartosc, kto_id):
    """Reczna liczba miesiaca (czynnosc Invoice albo POS processed); None = puste."""
    _upsert(IloscMiesiacaZwrotow, {'rok': rok, 'miesiac': miesiac, 'klucz': klucz},
            {'wartosc': wartosc, 'zmienil_id': kto_id, 'zmieniono_at': teraz_utc()})
    db.session.commit()


def zapisz_ceny(rok, miesiac, ceny, kto_id):
    """Cennik miesiaca: {czynnosc: cena | None}; None usuwa cene (brak ceny)."""
    for czynnosc, cena in ceny.items():
        if cena is None:
            CenaZwrotow.query.filter_by(rok=rok, miesiac=miesiac, czynnosc=czynnosc).delete()
        else:
            _upsert(CenaZwrotow, {'rok': rok, 'miesiac': miesiac, 'czynnosc': czynnosc},
                    {'cena': cena, 'zmienil_id': kto_id, 'zmieniono_at': teraz_utc()})
    db.session.commit()


# ── Sorting Data ─────────────────────────────────────────────────────────────

def licencje_roku(rok):
    """Wiersze Sorting Data roku: aktywne ORAZ wylaczone, ktore maja dane w tym
    roku — wylaczenie licencji w grudniu nie moze zgubic jej stycznia–listopada."""
    z_danymi = db.session.query(SortingDataWpis.licencja_id).filter(SortingDataWpis.rok == rok)
    lista = LicencjaZwrotow.query.filter(or_(
        LicencjaZwrotow.aktywna.is_(True), LicencjaZwrotow.id.in_(z_danymi)))\
        .order_by(LicencjaZwrotow.kolejnosc, LicencjaZwrotow.id).all()
    return ([lic for lic in lista if lic.rodzaj == LICENCJA],
            [lic for lic in lista if lic.rodzaj == WYSYLKA])


def sorting_data(rok):
    """Caly rok: licencje i wysylki z Cartons/Pallets per miesiac, „Total boxes
    built” (suma licencji; puste = 0) i POS processed."""
    licencje, wysylki = licencje_roku(rok)
    wpisy = {(w.licencja_id, w.miesiac): w for w in SortingDataWpis.query.filter_by(rok=rok)}

    def wiersz(lic):
        mies = {}
        for m in range(1, 13):
            w = wpisy.get((lic.id, m))
            mies[m] = {'cartons': w.cartons if w else None, 'pallets': w.pallets if w else None}
        return {'id': lic.id, 'nazwa': lic.nazwa, 'aktywna': lic.aktywna, 'mies': mies}

    wiersze_lic = [wiersz(lic) for lic in licencje]
    suma = {m: {pole: sum(w['mies'][m][pole] or 0 for w in wiersze_lic)
                for pole in ('cartons', 'pallets')} for m in range(1, 13)}
    pos = {w.miesiac: w.wartosc for w in IloscMiesiacaZwrotow.query.filter_by(rok=rok, klucz=KLUCZ_POS)}
    return {'rok': rok, 'licencje': wiersze_lic, 'wysylki': [wiersz(lic) for lic in wysylki],
            'suma': suma, 'pos': {m: pos.get(m) for m in range(1, 13)}}


def zapisz_sorting(licencja_id, rok, miesiac, pole, wartosc, kto_id):
    """Jedna komorka Cartons albo Pallets; None = puste."""
    _upsert(SortingDataWpis, {'licencja_id': licencja_id, 'rok': rok, 'miesiac': miesiac},
            {pole: wartosc, 'zmienil_id': kto_id, 'zmieniono_at': teraz_utc()})
    db.session.commit()
