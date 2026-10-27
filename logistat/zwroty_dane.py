"""Zwroty Paczek (kafelek Zwroty, od 2026-10-26) — dane tabeli.

Naglowki = te z arkusza „Return_September_2026” operacji (nazwy, pisownia
i kolejnosc — tabela idzie dalej do klienta). Kolumny kurierow (DPD, UPS, …)
ida z listy w Ustawieniach (2026-10-27): jedna kolumna na kuriera, 1 = ten
kurier, 0 = inny. Ekran i eksport do Excela biora wiersze z JEDNEJ funkcji
`wiersze_zwrotow()`, zrodlem jest Magazyn → Przyjęcie zwrotu (`ZwrotPaczki`).

Invoice specification i Sorting Data (2026-10-26): wpisy reczne + cennik
miesieczny (admin); Sorting returns = liczba przyjetych zwrotow w miesiacu.
"""
import calendar
from datetime import date

from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert

from logistat.czas import local_day_bounds, teraz_utc, utc_to_local
from logistat.extensions import db
from logistat.faktura_zwrotow import (
    CZYNNOSCI_AUTO, CZYNNOSCI_FAKTURY, KLUCZ_POS, KLUCZE_FAKTURY, LICENCJA, WYSYLKA)
from logistat.models import (
    AppSetting, CenaZwrotow, IloscMiesiacaZwrotow, LicencjaZwrotow, SortingDataWpis,
    ZwrotPaczki, set_setting)
from logistat.przyjecie_zwrotu import (
    BRAND, ETYKIETY_DOMYSLNE, KLUCZ_ETYKIETY, KURIER, LICZNIKI, RODZAJE_PRZYJECIA, monat, woche)

NAGLOWKI_PRZED_KURIERAMI = ('Paketnummer', 'Brand', 'Date', 'POS-Nummer')
NAGLOWKI_PO_KURIERACH = (
    'Retoure', 'Defekt', 'Neuwarenueberschuss', 'Silber_in_Stück', 'Defektes_Silber_in_Stück',
    'Reduzierte_ware', 'Verpackungsvorschrift', 'Monat', 'Woche',
)


def naglowki_zwrotow(kurierzy):
    """Naglowki raportu: stale kolumny arkusza + jedna kolumna na kuriera."""
    return NAGLOWKI_PRZED_KURIERAMI + tuple(kurierzy) + NAGLOWKI_PO_KURIERACH


def _granice(od, do):
    return local_day_bounds(od)[0], local_day_bounds(do)[1]


def opcje_przyjecia(rodzaj):
    """Aktywne nazwy listy (przyciski ekranu przyjecia) w kolejnosci z Ustawien."""
    return [n for (n,) in db.session.query(LicencjaZwrotow.nazwa)
            .filter(LicencjaZwrotow.rodzaj == rodzaj, LicencjaZwrotow.aktywna.is_(True))
            .order_by(LicencjaZwrotow.kolejnosc, LicencjaZwrotow.id)]


def kurierzy_raportu(od, do):
    """Kolumny kurierow: aktywni z listy (jej kolejnosc) ORAZ kazdy kurier,
    ktory jest w zwrotach z zakresu, a juz go na liscie nie ma (wylaczony,
    przemianowany) — inaczej jego paczki mialyby same zera."""
    kurierzy = opcje_przyjecia(KURIER)
    start, koniec = _granice(od, do)
    w_danych = sorted(k for (k,) in db.session.query(ZwrotPaczki.kurier).distinct().filter(
        ZwrotPaczki.przyjeto_at >= start, ZwrotPaczki.przyjeto_at < koniec))
    return kurierzy + [k for k in w_danych if k not in kurierzy]


class WierszZwrotu(tuple):
    """Krotka wartosci kolumn raportu (Excel / ekran iteruja po niej) plus `id`
    i `edycja` (surowe pola) dla poprawki lidera na ekranie."""
    id = None
    edycja = None


def wiersze_zwrotow(od, do, brand=None, paketnummer=None, kurierzy=None):
    """Wiersze tabeli z dni [od, do] (daty lokalne, wlacznie) — kazdy jako krotka
    wartosci w kolejnosci `naglowki_zwrotow(kurierzy)`. `brand` = dokladna
    wartosc, `paketnummer` = fragment numeru."""
    if kurierzy is None:
        kurierzy = kurierzy_raportu(od, do)
    start, koniec = _granice(od, do)
    q = ZwrotPaczki.query.filter(ZwrotPaczki.przyjeto_at >= start, ZwrotPaczki.przyjeto_at < koniec)
    if brand:
        q = q.filter(ZwrotPaczki.brand == brand)
    if paketnummer:
        q = q.filter(ZwrotPaczki.paketnummer.contains(paketnummer, autoescape=True))
    wiersze = []
    for z in q.order_by(ZwrotPaczki.przyjeto_at, ZwrotPaczki.id):
        dzien = utc_to_local(z.przyjeto_at).date()
        wiersz = WierszZwrotu((
            z.paketnummer, z.brand, dzien, z.pos_nummer,
            *(1 if z.kurier == k else 0 for k in kurierzy),
            *(getattr(z, pole) for pole, _, _, _ in LICZNIKI),
            z.verpackungsvorschrift, monat(dzien), woche(dzien),
        ))
        wiersz.id = z.id
        wiersz.edycja = {
            'id': z.id, 'paketnummer': z.paketnummer, 'brand': z.brand,
            'pos_nummer': z.pos_nummer, 'kurier': z.kurier,
            'verpackungsvorschrift': z.verpackungsvorschrift,
            **{pole: getattr(z, pole) for pole, _, _, _ in LICZNIKI},
        }
        wiersze.append(wiersz)
    return wiersze


def brandy_zwrotow():
    """Wartosci Brand do filtra: z listy w Ustawieniach i z przyjetych zwrotow."""
    lista = opcje_przyjecia(BRAND)
    w_danych = sorted(b for (b,) in db.session.query(ZwrotPaczki.brand).distinct())
    return lista + [b for b in w_danych if b not in lista]


# ── Przyjecie zwrotu (Magazyn) ───────────────────────────────────────────────

def etykiety_przyjecia():
    """Napisy ekranow przyjecia: nadpisane przez admina albo domyslne."""
    nadpisane = {
        row.key[len(KLUCZ_ETYKIETY):]: row.value
        for row in AppSetting.query.filter(AppSetting.key.like(KLUCZ_ETYKIETY + '%'))
        if (row.value or '').strip()
    }
    return {k: nadpisane.get(k) or domyslna for k, domyslna in ETYKIETY_DOMYSLNE.items()}


def zapisz_etykiety(etykiety):
    """{klucz: napis}; pusty albo rowny domyslnemu → wiersz usuniety (zmiana
    domyslnej w kodzie dziala tam, gdzie nikt nie nadpisal). Wartosci juz
    sprawdzone przez trase."""
    for klucz, napis in etykiety.items():
        if not napis or napis == ETYKIETY_DOMYSLNE[klucz]:
            row = db.session.get(AppSetting, KLUCZ_ETYKIETY + klucz)
            if row is not None:
                db.session.delete(row)
        else:
            set_setting(KLUCZ_ETYKIETY + klucz, napis)
    db.session.commit()


def listy_przyjecia():
    """Przyciski ekranow: {rodzaj: [nazwa, …]} — tylko aktywne pozycje."""
    return {r: opcje_przyjecia(r) for r in RODZAJE_PRZYJECIA}


def zapisz_zwrot(dane, token, kto_id, teraz):
    """Nowy wiersz zwrotu (dane juz sprawdzone). Ten sam `token` drugi raz
    (podwojne klikniecie, ponowienie) nie dodaje wiersza → (zwrot, False).
    `teraz` = ta sama chwila, dla ktorej sprawdzono obsade stanowiska."""
    stmt = insert(ZwrotPaczki.__table__).values(
        **dane, token=token, przyjal_id=kto_id, przyjeto_at=teraz)
    nowy_id = db.session.execute(
        stmt.on_conflict_do_nothing(index_elements=['token']).returning(ZwrotPaczki.id)).scalar()
    db.session.commit()
    if nowy_id is None:
        return ZwrotPaczki.query.filter_by(token=token).one(), False
    return db.session.get(ZwrotPaczki, nowy_id), True


# ── Invoice specification ────────────────────────────────────────────────────

def granice_miesiaca(rok, miesiac):
    """Pierwszy i ostatni dzien miesiaca (daty lokalne)."""
    return date(rok, miesiac, 1), date(rok, miesiac, calendar.monthrange(rok, miesiac)[1])


def liczba_sorting_returns(rok, miesiac):
    """Sorting returns = liczba wierszy raportu Zwroty Paczek w miesiacu (paczka =
    wiersz; powtorzony Paketnummer liczy sie znowu — tak liczy arkusz operacji)."""
    start, koniec = _granice(*granice_miesiaca(rok, miesiac))
    return ZwrotPaczki.query.filter(
        ZwrotPaczki.przyjeto_at >= start, ZwrotPaczki.przyjeto_at < koniec).count()


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
