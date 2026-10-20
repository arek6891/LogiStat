"""Import danych: CSV / Excel z Loading date, lista importow i grupowa poprawa Loading date."""
import csv
import io
from datetime import date, datetime, timedelta, timezone

import openpyxl
from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user
from sqlalchemy import and_, case, func, or_

from logistat.czas import LOCAL_TZ, iso_z, local_day_bounds, local_today, teraz_utc
from logistat.extensions import db
from logistat.import_paczek import detect_csv_encoding, normalize_header
from logistat.models import GeneralStat, ImportedCarton, User
from logistat.rozliczenie import (
    _ma_ilosci, _odsun_linie, klucz_linii, ma_reczne_ilosci, przenies_linie,
    recompute_general_stat)
from logistat.web.wspolne import (
    json_body, leader_required, parse_date, process_import_rows, require_int,
    wymagana_data_pliku)

bp = Blueprint('imports', __name__)

# ── Grupowa poprawa daty pliku ───────────────────────────────────────────────
#  Import = kartony jednej osoby z jednej minuty importu i jednej daty pliku
#  (process_import_rows daje calemu plikowi jedno `imported_at`). Klucz importu
#  w API: "<imported_by>|<minuta UTC ISO>|<data_pliku>".


MAX_IMPORTOW_NA_LISCIE = 300


def _minuta_importu():
    return func.date_trunc('minute', ImportedCarton.imported_at)


def _klucz_importu(osoba_id, minuta, data_pliku):
    return f"{osoba_id or 0}|{minuta.strftime('%Y-%m-%dT%H:%M')}|{data_pliku.isoformat() if data_pliku else ''}"


def _kartony_importow(klucze):
    """Kartony wskazanych importow. Zly klucz → 400 (nic nie zgadujemy)."""
    warunki = []
    for klucz in klucze:
        try:
            osoba, minuta, plik = str(klucz).split('|')
            osoba_id = int(osoba) or None
            minuta_dt = datetime.strptime(minuta, '%Y-%m-%dT%H:%M')
            plik_d = date.fromisoformat(plik) if plik else None
        except (ValueError, TypeError):
            abort(400, f'Nieprawidłowy import: {klucz}.')
        warunki.append(and_(
            ImportedCarton.imported_by.is_(None) if osoba_id is None
            else ImportedCarton.imported_by == osoba_id,
            ImportedCarton.imported_at >= minuta_dt,
            ImportedCarton.imported_at < minuta_dt + timedelta(minutes=1),
            ImportedCarton.data_pliku.is_(None) if plik_d is None
            else ImportedCarton.data_pliku == plik_d,
        ))
    if not warunki:
        return []
    return ImportedCarton.query.filter(or_(*warunki)).with_for_update().all()


@bp.route('/api/imports', methods=['GET'])
@leader_required
def api_imports():
    """Lista importow do grupowej poprawy daty pliku.

    Filtry (wszystkie opcjonalne): `data_pliku`, `dzien_importu` (dzien lokalny),
    `godz_od` / `godz_do` (HH:MM czasu polskiego, wlacznie), `osoba` (id).
    """
    q = db.session.query(
        ImportedCarton.imported_by,
        _minuta_importu().label('minuta'),
        ImportedCarton.data_pliku,
        func.count(ImportedCarton.id),
        func.coalesce(func.sum(ImportedCarton.stueckzahl), 0),
        func.count(ImportedCarton.scan_end_at),
        func.sum(case((ImportedCarton.added_manually.is_(True), 1), else_=0)),
    )
    if request.args.get('data_pliku'):
        q = q.filter(ImportedCarton.data_pliku == parse_date(request.args['data_pliku'], 'data_pliku'))
    if request.args.get('dzien_importu'):
        od, do = local_day_bounds(parse_date(request.args['dzien_importu'], 'dzien_importu'))
        q = q.filter(ImportedCarton.imported_at >= od, ImportedCarton.imported_at < do)
    if request.args.get('osoba'):
        q = q.filter(ImportedCarton.imported_by == require_int(request.args['osoba'], 'osoba'))

    def _godzina(nazwa):
        v = (request.args.get(nazwa) or '').strip()
        if not v:
            return None
        try:
            return datetime.strptime(v, '%H:%M').time()
        except ValueError:
            abort(400, f'Nieprawidłowa godzina w "{nazwa}" (oczekiwano HH:MM).')
    godz_od, godz_do = _godzina('godz_od'), _godzina('godz_do')

    wiersze = q.group_by(ImportedCarton.imported_by, 'minuta', ImportedCarton.data_pliku)\
               .order_by(db.desc('minuta')).all()
    osoby = {u.id: u for u in User.query.filter(
        User.id.in_({w[0] for w in wiersze if w[0]})).all()}
    importy = []
    for osoba_id, minuta, plik, paczek, sztuk, zrobionych, recznych in wiersze:
        if minuta is None:
            continue
        lokalnie = minuta.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)
        if godz_od and lokalnie.time() < godz_od:
            continue
        if godz_do and lokalnie.time() > godz_do:   # minuta importu, wiec „do 7:15" obejmuje 7:15
            continue
        u = osoby.get(osoba_id)
        importy.append({
            'klucz': _klucz_importu(osoba_id, minuta, plik),
            'osoba_id': osoba_id,
            'osoba': (u.display_name if u else '—'),
            'login': (u.username if u else None),
            'imported_at': iso_z(minuta),
            'data_pliku': plik.isoformat() if plik else None,
            'paczek': int(paczek), 'sztuk': int(sztuk or 0),
            'zrobionych': int(zrobionych or 0), 'recznych': int(recznych or 0),
        })
        if len(importy) >= MAX_IMPORTOW_NA_LISCIE:
            break
    importerzy = User.query.filter(User.id.in_(
        db.session.query(ImportedCarton.imported_by).distinct())).order_by(User.display_name).all()
    return jsonify({
        'importy': importy,
        'osoby': [{'id': u.id, 'nazwa': u.display_name, 'login': u.username} for u in importerzy],
        'ucieto': len(importy) >= MAX_IMPORTOW_NA_LISCIE,
    }), 200


@bp.route('/api/imports/zmien-date', methods=['POST'])
@leader_required
def api_imports_zmien_date():
    """Grupowa zmiana daty pliku dla wybranych importow.

    `{importy: [klucz, ...], nowa_data: 'YYYY-MM-DD', podglad: bool}`. Z
    `podglad: true` liczy skutki i NIC nie zapisuje — ekran pokazuje je przed
    potwierdzeniem. Data pliku jest kluczem linii rozliczenia, wiec zmiana
    przesuwa paczki miedzy liniami Statystyk ogolnych:
    - linia, ktorej przechodza WSZYSTKIE paczki, przechodzi razem z nimi
      (z recznymi ilosciami), laczac sie z linia, ktora juz stoi pod nowa data;
    - gdy przechodzi tylko czesc paczek linii z recznymi ilosciami → 409:
      nie da sie uczciwie podzielic recznie wpisanych liczb.
    """
    dane = json_body()
    klucze = dane.get('importy')
    if not isinstance(klucze, list) or not klucze:
        abort(400, 'Zaznacz co najmniej jeden import.')
    nowa = wymagana_data_pliku(dane.get('nowa_data'))
    podglad = bool(dane.get('podglad'))

    kartony = _kartony_importow(klucze)
    if not kartony:
        abort(404, 'Wybrane importy nie mają już paczek (ktoś je zmienił?). Odśwież listę.')
    do_zmiany = [c for c in kartony if c.data_pliku != nowa]
    ids = {c.id for c in do_zmiany}

    stare_klucze = {klucz_linii(c) for c in do_zmiany if c.uebergabe_nr and c.data_pliku}
    calkiem, konflikty = [], []
    for k in stare_klucze:
        linia = GeneralStat.query.filter_by(
            list_id=k[0], country_ledger=k[1], loading_date=k[2]).first()
        if linia is None:
            continue
        zostaje = ImportedCarton.query.filter(
            ImportedCarton.uebergabe_nr == k[0], ImportedCarton.land == k[1],
            ImportedCarton.data_pliku == k[2], ImportedCarton.id.notin_(ids)).count()
        if zostaje == 0:
            calkiem.append(linia)
        elif ma_reczne_ilosci(linia) or _ma_ilosci(linia.get_double_rate_category_data()):
            konflikty.append(f'{k[0]} · {k[1]} · {k[2].strftime("%d.%m.%Y")}')
    nowe_klucze = {(k[0], k[1], nowa) for k in stare_klucze}
    istniejace = sum(1 for k in nowe_klucze if GeneralStat.query.filter_by(
        list_id=k[0], country_ledger=k[1], loading_date=k[2]).first())

    # Laczenie linii recznej ze skanowa: przenies_linie() zostawilaby 'manual',
    # a skany przestalyby liczyc sie do rozliczenia — po cichu. Odmawiamy.
    laczone = {}
    for linia in calkiem:
        laczone.setdefault((linia.list_id, linia.country_ledger), []).append(linia)
    for (ub, land), linie in laczone.items():
        cel = GeneralStat.query.filter_by(list_id=ub, country_ledger=land, loading_date=nowa).first()
        grupa = linie + ([cel] if cel is not None and cel not in linie else [])
        if (any(ma_reczne_ilosci(x) for x in grupa)
                and any((x.category_source or 'manual') == 'scan' for x in grupa)):
            konflikty.append(f'{ub} · {land} · {nowa.strftime("%d.%m.%Y")} '
                             f'(łączenie ręcznych ilości z ilościami ze skanów)')

    skutki = {
        'paczek': len(do_zmiany),
        'juz_z_ta_data': len(kartony) - len(do_zmiany),
        'sztuk': sum(c.stueckzahl or 0 for c in do_zmiany),
        'zrobionych': sum(1 for c in do_zmiany if c.scan_end_at),
        'linii_przenoszonych': len(calkiem),
        'linii_dzielonych': len(stare_klucze) - len(calkiem),
        'linii_docelowych_istniejacych': istniejace,
        'konflikty': konflikty,
    }
    if konflikty:
        db.session.rollback()
        return jsonify({**skutki, 'error':
            'Część linii rozliczenia ma ręcznie wpisane ilości, a datę zmienia tylko '
            'część ich paczek — ręcznych liczb nie da się podzielić. Zaznacz wszystkie '
            'importy tych linii albo popraw ilości ręcznie: ' + '; '.join(konflikty[:10])}), 409
    if podglad or not do_zmiany:
        db.session.rollback()
        return jsonify({**skutki, 'podglad': True}), 200

    teraz = teraz_utc()
    for c in do_zmiany:
        c.data_pliku = nowa
        c.modified_at = teraz
        c.modified_by = current_user.id
    db.session.flush()

    _odsun_linie(calkiem)
    plan = {}
    for linia in calkiem:
        plan.setdefault((linia.list_id, linia.country_ledger, nowa), []).append(linia)
    for k in nowe_klucze:
        plan.setdefault(k, [])
    for k, linie in plan.items():
        ze_skanem = any(c.has_scan_categories() for c in do_zmiany
                        if (c.uebergabe_nr, c.land) == (k[0], k[1]))
        przenies_linie(linie, k, actor_id=current_user.id, from_scan=ze_skanem)
    # Stare klucze: linia czesciowo oprozniona przelicza sie z pozostalych paczek;
    # przeniesionej w calosci juz tam nie ma, a przy 0 sztuk nic nie powstaje.
    for k in stare_klucze:
        recompute_general_stat(*k, actor_id=current_user.id)
    db.session.commit()
    return jsonify({**skutki, 'message':
        f'Zmieniono Loading date {len(do_zmiany)} paczek na {nowa.strftime("%d.%m.%Y")}.'}), 200


@bp.route('/import-csv')
@leader_required
def import_csv_page():
    # Dzis LOKALNIE (Warszawa) — podpowiedz daty pliku w oknie importu; zegar
    # przegladarki moze stac w innej strefie albo sie spieszyc.
    return render_template('import_csv.html', dzis=local_today().isoformat())


@bp.route('/api/import-csv', methods=['POST'])
@leader_required
def api_import_csv():
    data_pliku = wymagana_data_pliku(request.form.get('data_pliku'))
    if 'file' not in request.files:
        return jsonify({'error': 'Brak pliku.'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'Brak nazwy pliku.'}), 400

    raw_bytes = file.read()
    encoding = detect_csv_encoding(raw_bytes)
    text = raw_bytes.decode(encoding)

    reader = csv.DictReader(io.StringIO(text), delimiter=';')

    # Normalize headers
    if reader.fieldnames:
        header_map = {h: normalize_header(h) for h in reader.fieldnames}
    else:
        return jsonify({'error': 'Plik CSV nie ma nag\u0142\u00f3wk\u00f3w.'}), 400

    rows = ({header_map.get(k, k): v for k, v in row.items()} for row in reader)
    return jsonify(process_import_rows(rows, data_pliku)), 200


@bp.route('/api/import/excel', methods=['POST'])
@leader_required
def api_import_excel():
    data_pliku = wymagana_data_pliku(request.form.get('data_pliku'))
    if 'file' not in request.files:
        return jsonify({'error': 'Brak pliku.'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'Brak nazwy pliku.'}), 400

    raw_bytes = file.read()
    try:
        wb = openpyxl.load_workbook(
            io.BytesIO(raw_bytes), data_only=True, read_only=True
        )
    except Exception as e:
        return jsonify({'error': f'Nie mo\u017cna odczyta\u0107 pliku Excel: {e}'}), 400

    ws = wb.active
    row_iter = ws.iter_rows(values_only=True)

    try:
        header_row = next(row_iter)
    except StopIteration:
        return jsonify({'error': 'Plik Excel jest pusty.'}), 400

    header_map = {}
    for idx, cell in enumerate(header_row):
        raw = str(cell) if cell is not None else ''
        header_map[idx] = normalize_header(raw)

    if not any(header_map.values()):
        return jsonify({'error': 'Plik Excel nie ma nag\u0142\u00f3wk\u00f3w.'}), 400

    def rows_gen():
        for values in row_iter:
            yield {header_map.get(idx, idx): val for idx, val in enumerate(values)}

    result = jsonify(process_import_rows(rows_gen(), data_pliku)), 200
    wb.close()
    return result
