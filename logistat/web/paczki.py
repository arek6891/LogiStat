"""Paczki (dane): lista z filtrami, dodanie i edycja reczna, korekta ilosci (tabela / stare okno),
potwierdzenie ❗, double rate, przepisanie, odblokowanie, zamkniecie zespolu."""
import math
from datetime import datetime

from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from logistat.czas import local_day_bounds, local_today, teraz_utc
from logistat.extensions import db
from logistat.import_paczek import _cell_to_date
from logistat.models import CountryMapping, ImportedCarton, UdzialPaczki, User, etykiety_kategorii
from logistat.paczki import (
    bledy_paczki, lista_osob, odswiez_roznice, otwarte_udzialy, parse_scan_categories, przelicz_ilosci_udzialow,
    zamknij_paczke_wielu_osob, zapisz_tabele_kartonu)
from logistat.rozliczenie import klucz_linii, recompute_general_stat
from logistat.tabela_ilosci import (
    TRYB_WZOR, TRYB_ZESPOL, normalizuj_tabele)
from logistat.web.wspolne import (
    json_body, leader_required, process_import_rows, wymagana_data_pliku)

bp = Blueprint('paczki', __name__)


PACZKI_NA_STRONE = 100


#  Po ktorym polu daty filtruje ekran /paczki (`date_typ`). Klucz -> (etykieta,
#  kolumna, czy to DateTime). Domyslnie `plik` (data pliku — glowna data pracy
#  od 2026-10). `data_pliku` i `ziel_datum` to db.Date i porownuja sie wprost;
#  pozostale trzy to naive-UTC DateTime, wiec granice doby musi liczyc
#  local_day_bounds() — inaczej „dzien" na tym ekranie znaczylby co innego niz
#  na dashboardzie i statystykach (patrz uwaga o strefach w CLAUDE.md).
PACZKI_POLA_DAT = {
    'plik':   ('Loading date',   ImportedCarton.data_pliku,    False),
    'ziel':   ('Ziel-Datum',     ImportedCarton.ziel_datum,    False),
    'import': ('Data importu',   ImportedCarton.imported_at,   True),
    'start':  ('Start paczki',   ImportedCarton.scan_start_at, True),
    'koniec': ('Koniec paczki',  ImportedCarton.scan_end_at,   True),
}


PACZKI_STATUSY = {
    'niezrobione':    'Niezrobione',
    'do_dokonczenia': 'Do dokończenia',
    'zrobione':       'Zrobione',
    'wszystkie':      'Wszystkie',
}


# Statusy bez wymaganego zakresu dat (malo paczek — nie wyciagna calej historii).
PACZKI_STATUSY_BEZ_DAT = ('niezrobione', 'do_dokonczenia')


class StroniceLista:
    """Minimalny odpowiednik `Pagination` Flask-SQLAlchemy dla listy w pamieci.

    Filtr „pokaz bledy" porownuje ilosci ze `scan_category_data` (JSON w kolumnie
    tekstowej) ze `stueckzahl`, czego nie da sie wyrazic w SQL — a JSONB jest
    zakazany (rozwala `json.loads` w akcesorach). Filtrujemy wiec w Pythonie i
    tniemy strony recznie, zachowujac API, ktorego uzywa szablon.
    """

    def __init__(self, items, page, per_page):
        self.total = len(items)
        self.per_page = per_page
        self.pages = max(1, math.ceil(self.total / per_page)) if self.total else 0
        self.page = min(max(1, page), self.pages) if self.pages else 1
        poczatek = (self.page - 1) * per_page
        self.items = items[poczatek:poczatek + per_page]

    @property
    def has_prev(self):
        return self.page > 1

    @property
    def has_next(self):
        return self.page < self.pages

    @property
    def prev_num(self):
        return self.page - 1

    @property
    def next_num(self):
        return self.page + 1


@bp.route('/paczki')
@leader_required
def paczki_view():
    date_from_str = request.args.get('date_from', '')
    date_to_str = request.args.get('date_to', '')
    date_typ = request.args.get('date_typ', 'plik')
    if date_typ not in PACZKI_POLA_DAT:
        date_typ = 'plik'
    barcode = request.args.get('barcode', '').strip()
    land = request.args.get('land', '').strip()
    osoba_id = request.args.get('osoba', type=int)
    tylko_double = request.args.get('double_rate') == '1'
    # Status: niezrobione (domyslnie) / zrobione (tylko zakonczone) / wszystkie.
    # Stary `pokaz_zrobione=1` DOKLADAL zrobione do niezrobionych, co przy
    # 1-5% zrobionych w dniu importu wygladalo jak „filtr nie dziala" —
    # zostaje jako alias „wszystkie" dla zapisanych zakladek.
    status = request.args.get('status', '')
    if status not in PACZKI_STATUSY:
        status = 'wszystkie' if request.args.get('pokaz_zrobione') == '1' else 'niezrobione'
    tylko_bledy = request.args.get('bledy') == '1'
    # ❗ niepotwierdzone — cel kafelka na Dashboardzie. Osobny filtr SQL, bo
    # `bledy=1` niesie tez stare reguly i „bez konca" z calej historii.
    do_potwierdzenia = request.args.get('do_potwierdzenia') == '1'
    page = request.args.get('page', 1, type=int)

    query = ImportedCarton.query

    def _dzien(wartosc):
        try:
            return datetime.strptime(wartosc, '%Y-%m-%d').date() if wartosc else None
        except ValueError:
            return None

    date_from = _dzien(date_from_str)
    date_to = _dzien(date_to_str)
    _, kolumna_daty, kolumna_jest_czasem = PACZKI_POLA_DAT[date_typ]

    if date_from:
        if kolumna_jest_czasem:
            query = query.filter(kolumna_daty >= local_day_bounds(date_from)[0])
        else:
            query = query.filter(kolumna_daty >= date_from)

    if date_to:
        # Gorna granica doby jest polotwarta (`<` na poczatek nastepnego dnia) —
        # `<=` wciagneloby paczki z pierwszych godzin kolejnego dnia lokalnego.
        # Dlatego ta galaz uzywa `<`, a kolumny db.Date (czysta data) `<=`.
        if kolumna_jest_czasem:
            query = query.filter(kolumna_daty < local_day_bounds(date_to)[1])
        else:
            query = query.filter(kolumna_daty <= date_to)

    if barcode:
        query = query.filter(ImportedCarton.barcode.ilike(f'%{barcode}%'))

    if land:
        query = query.filter(ImportedCarton.land.ilike(f'%{land}%'))

    if osoba_id:
        # Ta sama definicja „kto", co na ekranie skanu paczek: kto przejal,
        # kto rozpoczal, kto zakonczyl.
        query = query.filter(db.or_(
            ImportedCarton.processed_by == osoba_id,
            ImportedCarton.scan_start_by == osoba_id,
            ImportedCarton.scan_end_by == osoba_id,
            ImportedCarton.udzialy.any(UdzialPaczki.user_id == osoba_id),
        ))

    if tylko_double:
        query = query.filter(ImportedCarton.double_rate.is_(True))

    # „Pokaz zrobione" bez zakresu dat wyciagalo cala historie (tysiace paczek),
    # wiec zakres jest teraz wymagany. W formularzu pilnuje tego JS; ten warunek
    # lapie recznie sklejony URL i zakladke — zamiast bledu pokazujemy widok
    # domyslny z komunikatem (to strona Jinja, nie /api/, wiec abort() dalby
    # surowa strone bledu).
    brak_daty_dla_zrobionych = status not in PACZKI_STATUSY_BEZ_DAT and not (date_from or date_to)
    if brak_daty_dla_zrobionych:
        status = 'niezrobione'

    # Filtr po dacie konca skanu sam z siebie wybiera wylacznie paczki
    # zakonczone, wiec domyslne „tylko niezrobione" dawaloby zawsze pusta liste.
    # Zdejmujemy je z tego samego powodu, dla ktorego ignoruje je filtr bledow.
    filtr_po_koncu = bool(date_typ == 'koniec' and (date_from or date_to))
    if filtr_po_koncu and status == 'niezrobione':
        status = 'zrobione'

    # „Zrobiona" to paczka z zarejestrowanym koncem skanu (ta sama definicja,
    # co `finished` na /scan-package). Filtr bledow ignoruje status: blad ilosci
    # siedzi na zakonczonej paczce, a „bez konca" na niezakonczonej.
    if do_potwierdzenia:
        query = query.filter(ImportedCarton.roznica.is_(True),
                             ImportedCarton.roznica_potwierdzona_at.is_(None))
    elif not tylko_bledy:
        if status == 'niezrobione':
            query = query.filter(ImportedCarton.scan_end_at.is_(None))
        elif status == 'zrobione':
            query = query.filter(ImportedCarton.scan_end_at.isnot(None))
        elif status == 'do_dokonczenia':
            query = query.filter(ImportedCarton.scan_end_at.is_(None),
                                 ImportedCarton.scan_start_at.is_(None),
                                 ImportedCarton.udzialy.any())

    # Udzialy (i ich osoby) jednym zapytaniem — bledy_paczki() i komorka
    # „Pracownik" czytaja je per paczka.
    query = query.options(selectinload(ImportedCarton.udzialy).joinedload(UdzialPaczki.user),
                          joinedload(ImportedCarton.potwierdzajacy))
    query = query.order_by(ImportedCarton.imported_at.desc())

    if tylko_bledy:
        wszystkie = query.all()
        wszystkie = [c for c in wszystkie if bledy_paczki(c)]
        pagination = StroniceLista(wszystkie, page, PACZKI_NA_STRONE)
    else:
        pagination = query.paginate(page=page, per_page=PACZKI_NA_STRONE, error_out=False)

    users = User.query.filter_by(is_active_user=True).order_by(User.display_name).all()
    country_mappings = CountryMapping.query.order_by(CountryMapping.country).all()

    return render_template('paczki.html',
                           dzis=local_today().isoformat(),
                           pagination=pagination,
                           items=pagination.items,
                           date_from=date_from_str,
                           date_to=date_to_str,
                           date_typ=date_typ,
                           pola_dat=[(k, v[0]) for k, v in PACZKI_POLA_DAT.items()],
                           barcode=barcode,
                           land=land,
                           osoba_id=osoba_id,
                           tylko_double=tylko_double,
                           status=status,
                           statusy=PACZKI_STATUSY,
                           brak_daty_dla_zrobionych=brak_daty_dla_zrobionych,
                           filtr_po_koncu=filtr_po_koncu,
                           tylko_bledy=tylko_bledy,
                           do_potwierdzenia=do_potwierdzenia,
                           bledy_map={c.id: bledy_paczki(c) for c in pagination.items},
                           users=users,
                           country_mappings=country_mappings,
                           kategorie=list(etykiety_kategorii().items()))


@bp.route('/api/packages', methods=['POST'])
@leader_required
def api_package_create():
    """Manually add a single package (for packages missing from CSV imports).

    Runs through the SAME pipeline as CSV/Excel import (process_import_rows),
    so a manual package dedups, aggregates into GeneralStat and bills exactly
    like an imported one. Duplicate barcode → 409; missing required fields or
    bad values → 400.
    """
    data = json_body()
    barcode = (data.get('barcode') or '').strip()
    land = (data.get('land') or '').strip()
    kategorie = (data.get('kategorie') or '').strip()
    uebergabe_nr = (data.get('uebergabe_nr') or '').strip()
    ziel_datum_str = (data.get('ziel_datum') or '').strip()
    data_pliku_str = (data.get('data_pliku') or '').strip()
    double_rate = bool(data.get('double_rate'))

    # Required fields — must not be skipped, else the package can't bill.
    # Ziel-Datum jest od 2026-10 opcjonalna (kluczem linii jest data pliku).
    missing = []
    if not barcode:
        missing.append('Barcode')
    if not land:
        missing.append('Land')
    if not uebergabe_nr:
        missing.append('Übergabe Nr.')
    if not data_pliku_str:
        missing.append('Loading date')
    if missing:
        return jsonify({'error': 'Brakuje wymaganych pól: ' + ', '.join(missing)}), 400

    # Quantity — must be a positive integer
    try:
        stueckzahl = int(data.get('stueckzahl'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Stückzahl musi być liczbą całkowitą.'}), 400
    if stueckzahl <= 0:
        return jsonify({'error': 'Stückzahl musi być większe od zera.'}), 400

    # Dates — must parse
    data_pliku = wymagana_data_pliku(data_pliku_str)
    ziel_datum = _cell_to_date(ziel_datum_str) if ziel_datum_str else None
    if ziel_datum_str and ziel_datum is None:
        return jsonify({'error': 'Nieprawidłowy format daty Ziel-Datum.'}), 400

    # Duplicate barcode → 409 (pre-check; race handled by IntegrityError below)
    if ImportedCarton.query.filter_by(barcode=barcode).first():
        return jsonify({'error': f'Paczka o barcode "{barcode}" już istnieje.'}), 409

    row = {
        'barcode': barcode,
        'land': land,
        'stueckzahl': stueckzahl,
        'kategorie': kategorie,
        'ziel_datum': ziel_datum,
        'uebergabe_nr': uebergabe_nr,
        'double_rate': double_rate,
        'added_manually': True,
    }

    try:
        result = process_import_rows([row], data_pliku)
    except IntegrityError:
        # Concurrent add of the same barcode slipped past the pre-check
        db.session.rollback()
        return jsonify({'error': f'Paczka o barcode "{barcode}" już istnieje.'}), 409

    # Guard: a silent skip (imported=0) must not read as success
    if result.get('imported') != 1:
        return jsonify({'error': 'Nie udało się dodać paczki.'}), 409

    return jsonify({
        'message': f'Dodano paczkę {barcode}.',
        'stats_created': result.get('stats_created', 0),
        'stats_updated': result.get('stats_updated', 0),
    }), 201


@bp.route('/api/packages/<int:carton_id>', methods=['PUT'])
@leader_required
def api_package_update(carton_id):
    """Edit a manually-added package; recompute affected GeneralStat lines.

    Only `added_manually` packages are editable (imported ones are read-only →
    403). Changing a group field (uebergabe/land/data_pliku) moves the carton between
    GeneralStat groups — both the old and new lines are recomputed from carton
    sums so billing stays exact.
    """
    carton = db.get_or_404(ImportedCarton, carton_id)
    if not carton.added_manually:
        return jsonify({'error': 'Edytować można tylko paczki dodane ręcznie.'}), 403

    data = json_body()
    barcode = (data.get('barcode') or '').strip()
    land = (data.get('land') or '').strip()
    kategorie = (data.get('kategorie') or '').strip()
    uebergabe_nr = (data.get('uebergabe_nr') or '').strip()
    ziel_datum_str = (data.get('ziel_datum') or '').strip()
    data_pliku_str = (data.get('data_pliku') or '').strip()
    double_rate = bool(data.get('double_rate'))

    missing = []
    if not barcode:
        missing.append('Barcode')
    if not land:
        missing.append('Land')
    if not uebergabe_nr:
        missing.append('Übergabe Nr.')
    if not data_pliku_str:
        missing.append('Loading date')
    if missing:
        return jsonify({'error': 'Brakuje wymaganych pól: ' + ', '.join(missing)}), 400

    try:
        stueckzahl = int(data.get('stueckzahl'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Stückzahl musi być liczbą całkowitą.'}), 400
    if stueckzahl <= 0:
        return jsonify({'error': 'Stückzahl musi być większe od zera.'}), 400

    data_pliku = wymagana_data_pliku(data_pliku_str)
    ziel_datum = _cell_to_date(ziel_datum_str) if ziel_datum_str else None
    if ziel_datum_str and ziel_datum is None:
        return jsonify({'error': 'Nieprawidłowy format daty Ziel-Datum.'}), 400

    if barcode != carton.barcode and ImportedCarton.query.filter_by(barcode=barcode).first():
        return jsonify({'error': f'Paczka o barcode "{barcode}" już istnieje.'}), 409

    # Capture the OLD group before mutating, so we can recompute it after the move
    old_group = klucz_linii(carton)

    mapping = CountryMapping.query.filter_by(innenauftrag=land).first()
    carton.barcode = barcode
    carton.land = land
    carton.stueckzahl = stueckzahl
    carton.kategorie = kategorie
    carton.ziel_datum = ziel_datum
    carton.data_pliku = data_pliku
    carton.uebergabe_nr = uebergabe_nr
    carton.double_rate = double_rate
    carton.country_mapping_id = mapping.id if mapping else None
    carton.modified_at = teraz_utc()
    carton.modified_by = current_user.id

    new_group = klucz_linii(carton)
    # ❗ liczy sie wzgledem Stückzahl — po jej zmianie flaga musi sie odswiezyc.
    odswiez_roznice(carton)

    try:
        db.session.flush()  # push the carton UPDATE so recompute SUMs see new values / catch collision
        recompute_general_stat(*old_group, actor_id=current_user.id)
        if new_group != old_group:
            # Paczka z ilosciami ze skanu niesie je na nowa linie — bez from_scan
            # nowa linia powstawala 'manual' z pustymi kategoriami (przeglad 2026-10-24).
            recompute_general_stat(*new_group, actor_id=current_user.id,
                                   from_scan=bool(carton.get_scan_categories()))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': f'Paczka o barcode "{barcode}" już istnieje.'}), 409

    return jsonify({'message': f'Zapisano paczkę {barcode}.', 'carton': carton.to_dict()}), 200


@bp.route('/api/packages/<int:carton_id>/assign', methods=['PUT'])
@leader_required
def api_package_reassign(carton_id):
    carton = db.get_or_404(ImportedCarton, carton_id)
    data = json_body()
    user_id = data.get('user_id')
    if user_id is None:
        carton.processed_by = None
        carton.processed_at = None
    else:
        user = db.get_or_404(User, user_id)
        carton.processed_by = user.id
        carton.processed_at = teraz_utc()
    db.session.commit()
    return jsonify({'carton': carton.to_dict()}), 200


@bp.route('/api/packages/<int:carton_id>/double-rate', methods=['PUT'])
@leader_required
def api_package_double_rate(carton_id):
    carton = db.get_or_404(ImportedCarton, carton_id)
    data = json_body()
    carton.double_rate = bool(data.get('double_rate'))
    db.session.commit()
    return jsonify({'carton': carton.to_dict()}), 200


@bp.route('/api/packages/<int:carton_id>/zamknij-zespol', methods=['POST'])
@leader_required
def api_package_zamknij_zespol(carton_id):
    """Lider zamyka paczke zespolowa, gdy ktos nie wbil konca (poszedl do domu):
    pozostale otwarte udzialy koncza sie teraz, bez ilosci (i poza normami)."""
    carton = db.session.query(ImportedCarton).filter_by(id=carton_id).with_for_update().first()
    if not carton:
        abort(404)
    if carton.scan_end_at:
        return jsonify({'error': 'Paczka jest już zakończona.'}), 409
    otwarte = otwarte_udzialy(carton)
    if not otwarte:
        return jsonify({'error': 'Paczka nie ma otwartego zespołu — dla zwykłej paczki użyj „🔓 Odblokuj".'}), 400

    teraz = teraz_utc()
    for u in otwarte:
        u.end_at = teraz
        u.zamkniete_przez = current_user.id
    # Paczke „konczy" ostatnia osoba, ktora sama wbila koniec — a gdy nikt, ta, ktora zaczela.
    sami = [u for u in carton.udzialy if not u.zamkniete_przez]
    kto = max(sami, key=lambda u: u.end_at).user_id if sami else carton.scan_start_by
    zamknij_paczke_wielu_osob(carton, kto, teraz)
    carton.modified_at = teraz
    carton.modified_by = current_user.id
    przelicz_ilosci_udzialow(carton, current_user.id)
    db.session.commit()
    return jsonify({'message': f'Paczka {carton.barcode} zamknięta (bez ilości dla: {lista_osob(otwarte)}).',
                    'carton': carton.to_dict()}), 200


@bp.route('/api/packages/<int:carton_id>/categories', methods=['PUT'])
@leader_required
def api_package_categories_update(carton_id):
    """Korekta ilosci per kategoria — takze dla paczek z importu.

    Odkad ilosci ze skanu licza koszt, literowka pracownika jest bledem w
    rozliczeniu. `PUT /api/packages/<id>` edytuje tylko paczki dodane recznie,
    wiec bez tego wejscia pomylki na paczce z importu nie dalo sie naprawic.
    Zmieniamy WYLACZNIE ilosci — pola grupujace zostaja nietkniete.
    """
    carton = db.get_or_404(ImportedCarton, carton_id)
    data = json_body()

    kategorie, blad = parse_scan_categories(data.get('categories'))
    if blad:
        abort(400, blad)

    carton.set_scan_categories(kategorie)
    carton.modified_at = teraz_utc()
    carton.modified_by = current_user.id
    recompute_general_stat(*klucz_linii(carton),
                           actor_id=current_user.id, from_scan=True)
    db.session.commit()
    return jsonify(carton.to_dict()), 200


@bp.route('/api/packages/<int:carton_id>/tabela', methods=['PUT'])
@leader_required
def api_package_tabela_update(carton_id):
    """Lider poprawia tabele ilosci („✎ Ilosci" na /paczki).

    Paczka jednej osoby: cala tabela kartonu (tryb wzor). Paczka kilku osob:
    tabela jednej osoby (`udzial_id`, tryb zespol), karton = suma. Zapis
    lidera = potwierdzenie ❗ — sprawdzil i poprawil.
    """
    carton = (db.session.query(ImportedCarton).filter_by(id=carton_id)
              .with_for_update().first())
    if not carton:
        abort(404)
    data = json_body()
    udzial_id = data.get('udzial_id')
    if carton.udzialy:
        if carton.edytor_ilosci() != 'zespol':
            abort(400, 'Paczka sprzed tabeli ilości — popraw ją w starym oknie kategorii.')
        udzial = next((u for u in carton.udzialy if u.id == udzial_id), None)
        if not udzial:
            abort(400, 'Wybierz osobę, której ilości poprawiasz.')
        if not udzial.end_at:
            abort(409, 'Ta osoba jeszcze pracuje przy paczce — poczekaj na jej koniec.')
        tabela, blad = normalizuj_tabele(data.get('tabela'), TRYB_ZESPOL, carton.stueckzahl)
        if blad:
            abort(400, blad)
        udzial.set_tabela(tabela)
        # Zamkniety przez kogos innego = bez ilosci; od teraz ma ilosci lidera.
        udzial.zamkniete_przez = None
        przelicz_ilosci_udzialow(carton, current_user.id)
    else:
        if carton.edytor_ilosci() != 'tabela':
            abort(400, 'Paczka sprzed tabeli ilości — popraw ją w starym oknie kategorii.')
        tabela, blad = normalizuj_tabele(data.get('tabela'), TRYB_WZOR, carton.stueckzahl)
        if blad:
            abort(400, blad)
        zapisz_tabele_kartonu(carton, tabela, current_user.id)

    teraz = teraz_utc()
    carton.modified_at = teraz
    carton.modified_by = current_user.id
    if carton.roznica:
        carton.roznica_potwierdzona_at = teraz
        carton.roznica_potwierdzona_przez = current_user.id
    db.session.commit()
    return jsonify(carton.to_dict()), 200


@bp.route('/api/packages/<int:carton_id>/potwierdz-roznice', methods=['POST'])
@leader_required
def api_package_potwierdz_roznice(carton_id):
    """Lider potwierdza ❗ (rozmowa z pracownikiem / przeliczenie kartonu)."""
    carton = db.get_or_404(ImportedCarton, carton_id)
    if not carton.roznica:
        abort(400, 'Ta paczka nie ma różnicy do potwierdzenia.')
    if carton.roznica_potwierdzona_at:
        return jsonify(carton.to_dict()), 200
    carton.roznica_potwierdzona_at = teraz_utc()
    carton.roznica_potwierdzona_przez = current_user.id
    db.session.commit()
    return jsonify(carton.to_dict()), 200


@bp.route('/api/packages/<int:carton_id>/unlock-scan', methods=['POST'])
@leader_required
def api_package_unlock_scan(carton_id):
    """Zdejmij blokade z paczki rozpoczetej i nigdy nie zakonczonej.

    Paczka w trakcie nalezy do pracownika, ktory ja rozpoczal: inny dostanie 409
    przy starcie i 403 przy koncu. Gdy ten pracownik juz do niej nie wroci
    (koniec zmiany, pomylkowy skan), paczka zostaje zablokowana na zawsze —
    w bazie testowej wisialo tak 5 sztuk, najstarsza od tygodnia. Lider kasuje
    tu start, przez co paczka wraca do stanu „nierozpoczeta" i ktokolwiek moze
    ja zeskanowac od nowa. Paczki zakonczonej nie ruszamy.
    """
    carton = db.get_or_404(ImportedCarton, carton_id)

    if carton.scan_end_at:
        return jsonify({'error': 'Paczka jest zakończona — nie ma czego odblokowywać.'}), 409
    if not carton.scan_start_at:
        return jsonify({'error': 'Paczka nie jest rozpoczęta.'}), 400

    poprzedni = db.session.get(User, carton.scan_start_by) if carton.scan_start_by else None
    # Otwarte udzialy zespolu nie maja ilosci — znikaja razem ze startem.
    # Zamkniete (przekazane czesci) zostaja: paczka wraca do „do dokonczenia".
    for u in otwarte_udzialy(carton):
        carton.udzialy.remove(u)
    carton.scan_start_at = None
    carton.scan_start_by = None
    carton.modified_at = teraz_utc()
    carton.modified_by = current_user.id
    db.session.commit()

    kto = poprzedni.display_name if poprzedni else 'nieznany pracownik'
    return jsonify({
        'message': f'Paczka {carton.barcode} odblokowana (była u: {kto}).',
        'carton': carton.to_dict()
    }), 200
