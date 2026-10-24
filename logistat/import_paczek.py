"""Import paczek z CSV / Excel: naglowki, konwersja komorek, agregacja do linii.
Autor importu przychodzi parametrem (actor_id) — modul nie wie o zalogowanym uzytkowniku."""
import json
from datetime import date, datetime

from logistat.czas import teraz_utc
from logistat.extensions import db
from logistat.models import CountryMapping, GeneralStat, ImportedCarton, empty_category_data
from logistat.rozliczenie import klucz_linii, recompute_general_stat

# Wiersze importu przetwarzamy partiami: dedup barcode'ow idzie jednym
# zapytaniem `IN (...)` na partie, a nie jednym na wiersz. Rozmiar ograniczony,
# zeby duzy plik nie wchodzil caly do pamieci.
IMPORT_CHUNK = 500


def _partiami(iterable, rozmiar):
    """Dziel iterowalne (moze byc generator) na listy po `rozmiar` elementow."""
    partia = []
    for element in iterable:
        partia.append(element)
        if len(partia) >= rozmiar:
            yield partia
            partia = []
    if partia:
        yield partia


def detect_csv_encoding(raw_bytes):
    """Try UTF-8 first, then Latin-1."""
    for enc in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']:
        try:
            raw_bytes.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return 'latin-1'


def normalize_header(h):
    """Normalize CSV header to handle encoding issues."""
    h = h.strip().lower()
    replacements = {
        'st\u00fcckzahl': 'stueckzahl',
        'st\u00fcckel': 'stueckzahl',
        'stã¼ckzahl': 'stueckzahl',
        'stã¼ckel': 'stueckzahl',
        '\u00fcbergabe nr.': 'uebergabe_nr',
        '\u00fcbergabe nr': 'uebergabe_nr',
        'ãœbergabe nr.': 'uebergabe_nr',
        'ãœbergabe nr': 'uebergabe_nr',
        'ziel-datum': 'ziel_datum',
        'land': 'land',
        'barcode': 'barcode',
        'kategorie': 'kategorie',
    }
    for key, val in replacements.items():
        if key in h:
            return val
    return h


def _cell_to_barcode(val):
    """Coerce a cell value to a barcode string.

    Excel stores numeric-looking barcodes as float64 \u2014 a whole number is
    rendered without the trailing '.0' (str(123.0) -> '123'), and leading
    zeros are already lost at the source. CSV always hands us strings.
    """
    if val is None:
        return ''
    if isinstance(val, bool):
        return ''
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        return str(int(val)) if val.is_integer() else str(val)
    return str(val).strip()


def _cell_to_int(val):
    """Coerce a cell value to an int quantity (0 on failure)."""
    if val is None:
        return 0
    if isinstance(val, bool):
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    try:
        return int(float(str(val).strip().replace(',', '')))
    except (ValueError, TypeError):
        return 0


def _cell_to_date(val):
    """Coerce a cell value to a date (None on failure).

    openpyxl returns datetime/date for date cells; CSV returns strings.
    """
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    for fmt in ('%d.%m.%Y', '%Y-%m-%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _cell_to_str(val):
    """Coerce a cell value to a trimmed string ('' for None)."""
    if val is None:
        return ''
    return str(val).strip()


def importuj_wiersze(rows, data_pliku, actor_id):
    """Shared import pipeline for CSV and Excel.

    `rows` is an iterable of dicts keyed by NORMALIZED header names
    (barcode, land, stueckzahl, kategorie, ziel_datum, uebergabe_nr).
    Values may be raw strings (CSV) or native types (Excel) \u2014 all field
    coercion is type-aware. Creates ImportedCarton records (deduped by
    barcode) and upserts aggregated GeneralStat rows. Returns the result
    dict for the API response.

    `data_pliku` (wymagana) dostaje kazdy karton i jest kluczem linii.
    `imported_at` jest jeden na caly import: lista importow przy grupowej
    poprawie daty grupuje po (osoba, minuta), a plik wczytywany kilkadziesiat
    sekund nie moze sie rozpasc na dwa "importy".
    """
    teraz = teraz_utc()
    imported = 0
    skipped = 0
    skipped_barcodes = []
    aggregation = {}  # key: (list_id, land, date_str) -> sum of stueckzahl

    # Mapowania krajow to kilkadziesiat rekordow — jeden odczyt zamiast SELECT-a
    # na kazdy wiersz pliku.
    mapowania = {m.innenauftrag: m for m in CountryMapping.query.all()}
    # Barcode'y widziane w TYM imporcie — lapie duplikaty wewnatrz pliku bez
    # polegania na autoflushu.
    widziane = set()

    for partia in _partiami(rows, IMPORT_CHUNK):
        parsed = []
        for row in partia:
            barcode = _cell_to_barcode(row.get('barcode'))
            if not barcode:
                continue
            parsed.append((barcode, row))

        # Jedno zapytanie na partie zamiast jednego na wiersz.
        istniejace = set()
        if parsed:
            kandydaci = [b for b, _ in parsed]
            istniejace = {
                b for (b,) in db.session.query(ImportedCarton.barcode)
                .filter(ImportedCarton.barcode.in_(kandydaci)).all()
            }

        for barcode, row in parsed:
            if barcode in istniejace or barcode in widziane:
                skipped += 1
                skipped_barcodes.append(barcode)
                continue
            widziane.add(barcode)

            land = _cell_to_str(row.get('land'))
            kategorie = _cell_to_str(row.get('kategorie'))
            uebergabe_nr = _cell_to_str(row.get('uebergabe_nr'))
            stueckzahl = _cell_to_int(row.get('stueckzahl'))
            ziel_datum = _cell_to_date(row.get('ziel_datum'))

            mapping = mapowania.get(land)

            carton = ImportedCarton(
                barcode=barcode,
                land=land,
                stueckzahl=stueckzahl,
                kategorie=kategorie,
                ziel_datum=ziel_datum,
                uebergabe_nr=uebergabe_nr,
                country_mapping_id=mapping.id if mapping else None,
                double_rate=bool(row.get('double_rate')),
                added_manually=bool(row.get('added_manually')),
                imported_by=actor_id,
                imported_at=teraz,
                data_pliku=data_pliku,
            )
            db.session.add(carton)
            imported += 1

            # Aggregate for GeneralStat — klucz_linii(): (UB, land, data_pliku).
            # Ziel-Datum nie jest juz wymagana (decyzja 2026-10: paczki bez niej
            # tez sie rozliczaja).
            if uebergabe_nr:
                agg_key = klucz_linii(carton)
                if agg_key not in aggregation:
                    aggregation[agg_key] = {
                        'stueckzahl': 0,
                        'country': mapping.country if mapping else None,
                        'date': data_pliku
                    }
                aggregation[agg_key]['stueckzahl'] += stueckzahl

    # Create/update GeneralStat entries
    stats_created = 0
    stats_updated = 0
    db.session.flush()
    for (list_id, land_val, _data), agg in aggregation.items():
        # Blokada wiersza linii: drugi import tej samej linii czeka, a jego SUM
        # (nowe zapytanie po blokadzie) widzi juz kartony pierwszego.
        existing = GeneralStat.query.filter_by(
            list_id=list_id,
            country_ledger=land_val,
            loading_date=agg['date']
        ).with_for_update().first()

        if existing:
            # Z sumy, nie przyrostowo (przeglad 2026-10-24): `+=` przenosilo
            # kazdy wczesniejszy rozjazd i gubilo sie przy dwoch importach naraz.
            recompute_general_stat(list_id, land_val, agg['date'], actor_id=actor_id)
            stats_updated += 1
        else:
            stat = GeneralStat(
                loading_date=agg['date'],
                week_number=agg['date'].isocalendar()[1],
                list_id=list_id,
                country_of_destination=agg['country'],
                country_ledger=land_val,
                amounts=agg['stueckzahl'],
                category_data=json.dumps(empty_category_data())
            )
            db.session.add(stat)
            stats_created += 1

    db.session.commit()

    return {
        'message': f'Zaimportowano {imported} karton\u00f3w.',
        'imported': imported,
        'skipped': skipped,
        'skipped_barcodes': skipped_barcodes[:50],
        'stats_created': stats_created,
        'stats_updated': stats_updated
    }
