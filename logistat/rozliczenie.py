"""Rozliczenie: linie Statystyk ogolnych liczone Z SUMY paczek (nigdy przyrostowo),
klucz linii, pokrycie skanami, przenoszenie linii przy zmianie Loading date."""
import json
from datetime import date, datetime, timedelta

from sqlalchemy import and_, case, func

from logistat.extensions import db
from logistat.kategorie import STAT_CATEGORIES, liczba
from logistat.models import CountryMapping, GeneralStat, ImportedCarton, empty_category_data


def _ma_ilosci(dane):
    return any(isinstance(v, dict) and v.get('amount') for v in (dane or {}).values())


def klucz_linii(carton):
    """Klucz linii rozliczenia (GeneralStat) dla kartonu:
    (uebergabe_nr, land, data_pliku) == (list_id, country_ledger, loading_date).

    JEDYNA definicja — kazde miejsce, ktore przelicza albo szuka linii kartonu,
    idzie przez nia. Od 2026-10 kluczem jest data pliku, nie Ziel-Datum.
    """
    return (carton.uebergabe_nr, carton.land, carton.data_pliku)


def double_rate_amount_map():
    """Sum of Stückzahl of double-rate cartons, keyed by
    (uebergabe_nr, land, data_pliku) == (list_id, country_ledger, loading_date) — klucz_linii()."""
    rows = db.session.query(
        ImportedCarton.uebergabe_nr,
        ImportedCarton.land,
        ImportedCarton.data_pliku,
        func.coalesce(func.sum(ImportedCarton.stueckzahl), 0),
    ).filter(ImportedCarton.double_rate.is_(True)).group_by(
        ImportedCarton.uebergabe_nr,
        ImportedCarton.land,
        ImportedCarton.data_pliku,
    ).all()
    return {(u, l, d): int(s or 0) for u, l, d, s in rows}


def scan_category_totals(uebergabe_nr, land, data_pliku):
    """Suma ilosci per kategoria ze skanow paczek w danej grupie rozliczeniowej.

    Kategorie siedza w kolumnie Text jako JSON (patrz `category_data`), wiec
    sumujemy w Pythonie. Zwraca ksztalt `category_data`, czyli
    {kategoria: {'amount': N, 'cost': 0.0}} — koszt liczy sie w locie w to_dict().
    """
    kartony = ImportedCarton.query.filter(
        ImportedCarton.uebergabe_nr == uebergabe_nr,
        ImportedCarton.land == land,
        ImportedCarton.data_pliku == data_pliku,
    ).all()
    suma = {kat: 0 for kat in STAT_CATEGORIES}
    for karton in kartony:
        for kat, ile in karton.get_scan_categories().items():
            suma[kat] = suma.get(kat, 0) + (ile or 0)
    return {kat: {'amount': liczba(suma.get(kat, 0)), 'cost': 0.0} for kat in STAT_CATEGORIES}


def ma_reczne_ilosci(stat):
    """Czy linia ma juz wpisane recznie niezerowe ilosci per kategoria."""
    if (stat.category_source or 'manual') != 'manual':
        return False
    return any(d.get('amount', 0) for d in stat.get_category_data().values()
               if isinstance(d, dict))


def scan_coverage_map():
    """Pokrycie skanami per grupa: {(uebergabe, land, data_pliku): (zeskanowane, wszystkie)}.

    Linia zasilana skanami czyta w trakcie zmiany mniej niz finalnie — bez tego
    licznika latwo wyeksportowac polowicznie zeskanowana linie jako gotowa.
    """
    # Agregujemy w bazie (GROUP BY), nie w Pythonie — inaczej ekran rozliczen
    # ciagnalby cala tabele kartonow przy kazdym otwarciu.
    # Tylko paczki ZAKONCZONE: czesc przekazana do dokonczenia ma juz ilosci,
    # ale paczka nie jest skonczona — nie moze wygladac na „zeskanowana".
    ma_skan = case(
        (and_(ImportedCarton.scan_end_at.isnot(None),
              ImportedCarton.scan_category_data.isnot(None),
              ImportedCarton.scan_category_data.notin_(('{}', '', 'null'))), 1),
        else_=0)
    rows = db.session.query(
        ImportedCarton.uebergabe_nr,
        ImportedCarton.land,
        ImportedCarton.data_pliku,
        func.count(ImportedCarton.id),
        func.coalesce(func.sum(ma_skan), 0),
    ).group_by(
        ImportedCarton.uebergabe_nr,
        ImportedCarton.land,
        ImportedCarton.data_pliku,
    ).all()
    return {(u, l, d): (int(zesk or 0), int(wsz or 0)) for u, l, d, wsz, zesk in rows}


def recompute_general_stat(uebergabe_nr, land, data_pliku, actor_id=None, from_scan=False):
    """Recompute a GeneralStat line's `amounts` from the SUM of its cartons.

    Argumenty to klucz_linii(): (uebergabe_nr, land, data_pliku) — wolajacy
    podaje `*klucz_linii(carton)`, nigdy wlasnej trojki.

    `amounts` is a pure carton aggregate (only written by process_import_rows),
    so recomputing from SUM(stueckzahl) over the group is exact — it avoids
    delta drift and stays correct when manual and imported cartons share a
    line. Groups without uebergabe_nr or data_pliku never aggregate, so nothing
    to recompute. If the group emptied to 0, the GeneralStat row is kept at
    amounts=0 (preserves any entered category_data).
    """
    if not (uebergabe_nr and data_pliku):
        return
    total = db.session.query(
        func.coalesce(func.sum(ImportedCarton.stueckzahl), 0)
    ).filter(
        ImportedCarton.uebergabe_nr == uebergabe_nr,
        ImportedCarton.land == land,
        ImportedCarton.data_pliku == data_pliku,
    ).scalar() or 0

    existing = GeneralStat.query.filter_by(
        list_id=uebergabe_nr,
        country_ledger=land,
        loading_date=data_pliku,
    ).first()

    if existing:
        existing.amounts = total
        # Skan ilosci przelacza linie na zrodlo 'scan' — swiadomie, nie przy okazji
        # importu. Linie 'manual' (sprzed skanowania) NIGDY nie sa nadpisywane,
        # inaczej przeliczenie wyzerowaloby recznie wpisane rozliczenia.
        #
        # Wyjatek od przelaczenia: linia, w ktorej ktos juz wpisal ilosci recznie.
        # Pierwszy skan zastapilby np. 120 sztuk szescioma i nikt by tego nie
        # zauwazyl. Ilosci ze skanu i tak zapisuja sie na kartonie (nic nie ginie),
        # a linie przelacza dopiero admin — POST /api/general-stats/<id>/use-scan.
        if from_scan and not ma_reczne_ilosci(existing):
            existing.category_source = 'scan'
        if existing.category_source == 'scan':
            existing.set_category_data(
                scan_category_totals(uebergabe_nr, land, data_pliku))
        existing.updated_at = datetime.utcnow()
        if actor_id:
            existing.updated_by = actor_id
    elif total > 0:
        mapping = CountryMapping.query.filter_by(innenauftrag=land).first()
        stat = GeneralStat(
            loading_date=data_pliku,
            week_number=data_pliku.isocalendar()[1],
            list_id=uebergabe_nr,
            country_of_destination=mapping.country if mapping else None,
            country_ledger=land,
            amounts=total,
            category_source='scan' if from_scan else 'manual',
            category_data=json.dumps(
                scan_category_totals(uebergabe_nr, land, data_pliku)
                if from_scan else empty_category_data()),
        )
        db.session.add(stat)


def _suma_kategorii(*slowniki):
    """Suma ilosci per kategoria kilku `category_data` (ksztalt {kat: {'amount': N}})."""
    suma = {kat: 0 for kat in STAT_CATEGORIES}
    for dane in slowniki:
        for kat, wartosc in (dane or {}).items():
            if kat in suma and isinstance(wartosc, dict):
                suma[kat] += int(wartosc.get('amount', 0) or 0)
    return {kat: {'amount': n, 'cost': 0.0} for kat, n in suma.items()}


def przenies_linie(zrodla, klucz, actor_id=None, from_scan=False):
    """Zlacz linie `zrodla` (GeneralStat) w jedna linie pod kluczem `klucz`
    (uebergabe_nr, land, data_pliku) i przelicz ja z kartonow.

    Uzywane przez jednorazowa migracje i grupowa zmiane daty pliku, zeby obie
    trzymaly sie tych samych regul:
    - linia, ktora juz stoi pod `klucz`, przezywa; inaczej pierwsza ze zrodel;
    - reczne `category_data` (linie 'manual') i `double_rate_category_data` sa
      SUMOWANE — to jedyne dane linii, ktorych nie da sie odtworzyc z kartonow;
    - `amounts` i ilosci ze skanow liczy od nowa recompute_general_stat();
    - linia ze zrodlem 'scan' zostaje 'scan', chyba ze ktores zrodlo ma reczne
      ilosci (wtedy 'manual' z suma — skany i tak leza na kartonach).
    Wolajacy musi wczesniej odsunac zrodla z ich starych kluczy (patrz
    _odsun_linie), bo unikalny (list_id, country_ledger, loading_date) nie
    pozwala przesunac linii na miejsce, ktore jeszcze zajmuje inna.
    """
    ub, land, data = klucz
    docelowa = GeneralStat.query.filter_by(
        list_id=ub, country_ledger=land, loading_date=data).first()
    wszystkie = list({id(x): x for x in ([docelowa] if docelowa else []) + list(zrodla)}.values())
    if not wszystkie:
        recompute_general_stat(ub, land, data, actor_id=actor_id, from_scan=from_scan)
        return
    zostaje = docelowa or wszystkie[0]
    reczne = [x for x in wszystkie if (x.category_source or 'manual') == 'manual'
              and _ma_ilosci(x.get_category_data())]
    skanowe = any((x.category_source or 'manual') == 'scan' for x in wszystkie)
    zostaje.set_double_rate_category_data(
        _suma_kategorii(*(x.get_double_rate_category_data() for x in wszystkie)))
    if reczne:
        zostaje.category_source = 'manual'
        zostaje.set_category_data(_suma_kategorii(*(x.get_category_data() for x in reczne)))
    elif skanowe:
        zostaje.category_source = 'scan'
    if not zostaje.country_of_destination:
        zostaje.country_of_destination = next(
            (x.country_of_destination for x in wszystkie if x.country_of_destination), None)
    for x in wszystkie:
        if x is not zostaje:
            db.session.delete(x)
    db.session.flush()
    zostaje.loading_date = data
    zostaje.week_number = data.isocalendar()[1]
    db.session.flush()
    recompute_general_stat(ub, land, data, actor_id=actor_id,
                           from_scan=from_scan and not reczne)


def _odsun_linie(linie):
    """Przestaw linie na tymczasowe, unikalne daty (1900-01-01 + id), zeby
    zwolnic ich klucze przed przesunieciem — inaczej linia A wchodzaca na dzien
    linii B, ktora sama dopiero sie przesuwa, lamie unikalny indeks."""
    for x in linie:
        x.loading_date = date(1900, 1, 1) + timedelta(days=x.id)
    db.session.flush()
