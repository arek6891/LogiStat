import os
import csv
import io
import json
import calendar
import hashlib
import math
from types import SimpleNamespace
from bisect import bisect_right
from datetime import datetime, date, timedelta, timezone

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, session, abort, make_response
)
from werkzeug.exceptions import HTTPException
from flask_login import login_user, login_required, logout_user, current_user
from sqlalchemy import func, and_, or_, case
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

import openpyxl

# Czysta logika w pakiecie logistat/ (podzial app.py, 2026-10-16). Nazwy
# re-eksportowane tutaj: reszta app.py i testy (`logistat.X`) bez zmian.
from logistat.czas import LOCAL_TZ, iso_z, local_day_bounds, local_today, utc_to_local
from logistat.kategorie import (
    STAT_CATEGORIES, STAT_CATEGORY_LABELS, STAT_CATEGORY_LABELS_PL, TOTAL_AMOUNT_BEZ,
    liczba, total_amount_wiersza)
from logistat.tabela_ilosci import (
    DODATKI_TABELI, GRUPA_GLOWNA, GRUPY_ARTYKULOWE, ILOSC_WYGLADA_NA_KOD,
    KATEGORIA_GRUPY, MNOZNIK_PODWOJNIE, MNOZNIK_POTROJNIE, NAZWY_GRUP, POLA_GRUPY,
    TRYB_WZOR, TRYB_ZESPOL, WPISYWANE_WZOR, WPISYWANE_ZESPOL, ZRODLO_KATEGORII,
    kategorie_z_tabeli, normalizuj_tabele, roznice_tabeli, suma_tabel, sztuki_tabeli,
    wczytaj_json_dict)
from logistat.okresy import suma_zlaczonych_okresow
from logistat.normy import policz_wydajnosc
from logistat.config import DEV_SECRET_KEY, DEFAULT_MAX_UPLOAD_MB, DEFAULT_ADMIN_PASSWORD, resolve_secret_key, resolve_database_url
from logistat.extensions import db, login_manager
from logistat.models import (  # noqa: F401 — re-eksport dla testow i reszty app.py
    AppSetting,
    SETTING_DEFAULTS,
    get_setting,
    get_setting_int,
    set_setting,
    User,
    USER_OPTION_KINDS,
    USER_OPTION_DEFAULTS,
    UserOption,
    user_options_by_kind,
    ROLES,
    PRIVILEGED_ROLES,
    active_admin_count,
    Activity,
    Shift,
    ShiftAttendance,
    ActivityAssignment,
    SzkolenieCzynnosci,
    szkolenia_czynnosci,
    ZNACZNIK_SZKOLEN_CZYNNOSCI,
    zaznacz_wszystkich_przeszkolonych,
    DailyStat,
    get_or_create_shift,
    CountryMapping,
    KLUCZ_NAZWY_PL,
    NAZWA_PL_MAX,
    nazwy_kategorii_pl,
    etykieta_kategorii,
    etykiety_kategorii,
    empty_category_data,
    Forecast,
    GeneralStat,
    CostMapping,
    rates_for,
    ImportedCarton,
    UDZIAL_PRZEKAZANA,
    UDZIAL_ZESPOL,
    UdzialPaczki,
    WorkerTimeEvent,
    EVENT_TYPES,
    TRYBY_CZASU,
    TRYBY_SKANU,
    KOMUNIKATY_TRWANIA,
    HistoriaCelu,
    historia_celu_lista,
    POCZATEK_HISTORII_CELU,
)
from logistat.web.wspolne import (  # noqa: F401 — re-eksport
    acting_as_admin, leader_required, admin_required, json_body, parse_shift_number, parse_date, require_int, bezpieczny_next, blad_nieznanej_paczki)
from logistat.rozliczenie import (  # noqa: F401 — re-eksport
    _ma_ilosci, _odsun_linie, _suma_kategorii, double_rate_amount_map, klucz_linii,
    ma_reczne_ilosci, przenies_linie, recompute_general_stat, scan_category_totals,
    scan_coverage_map)
from logistat.paczki import (  # noqa: F401 — re-eksport
    TOLERANCJA_ILOSCI, bledy_paczki, lista_osob, odswiez_roznice, otwarte_udzialy,
    przelicz_ilosci_udzialow, zamknij_paczke_wielu_osob, zapisz_tabele_kartonu)
from logistat.import_paczek import (  # noqa: F401 — re-eksport
    IMPORT_CHUNK, _cell_to_barcode, _cell_to_date, _cell_to_int, _cell_to_str, _partiami,
    detect_csv_encoding, importuj_wiersze, normalize_header)
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

app = Flask(__name__)
app.config['SECRET_KEY'] = resolve_secret_key()
# Aplikacja chodzi WYLACZNIE na Postgresie — brak DATABASE_URL to blad
# konfiguracji, nie powod do cichego fallbacku na plik obok kodu.
app.config['SQLALCHEMY_DATABASE_URI'] = resolve_database_url()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Sprawdz polaczenie przed uzyciem: po restarcie kontenera bazy workery trzymaja
# martwe polaczenia z puli i pierwsze zadanie na kazdym zwracalo 500
# ("server closed the connection unexpectedly").
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}
app.config['MAX_CONTENT_LENGTH'] = int(
    os.environ.get('MAX_UPLOAD_MB', DEFAULT_MAX_UPLOAD_MB)) * 1024 * 1024
# SameSite=Lax: przegladarka nie dosle ciasteczka przy POST z obcej strony.
# Endpointy JSON byly chronione ubocznie (wymagaja Content-Type: application/json,
# co wymusza preflight), ale /api/import-csv jest multipart, czyli bylo osiagalne
# CSRF-em. Secure wlaczamy zmienna, bo do .31 wchodzi sie tez po HTTP z LAN-u.
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE') == '1'

db.init_app(app)


@app.errorhandler(HTTPException)
def _blad_http(e):
    """Na /api/ zwracaj JSON — front wszedzie czyta `data.error`.

    Domyslnie Flask oddaje strone HTML, wiec `await r.json()` w JS wybuchalo i
    uzytkownik widzial "Blad polaczenia" zamiast tresci bledu.
    """
    if request.path.startswith('/api/'):
        return jsonify({'error': e.description}), e.code
    return e


@app.errorhandler(413)
def _upload_za_duzy(e):
    """Domyslna odpowiedz 413 to HTML — front na /import-csv czyta JSON."""
    limit_mb = app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)
    komunikat = f'Plik jest za duzy (limit {limit_mb} MB).'
    if request.path.startswith('/api/'):
        return jsonify({'error': komunikat}), 413
    return komunikat, 413


login_manager.init_app(app)
login_manager.login_view = 'auth.login'

@app.context_processor
def _static_version():
    """`static_v('style.css')` dokleja mtime pliku jako ?v=.

    Dotad w base.html siedzialo recznie wpisane ?v=6 — trzeba bylo pamietac o
    bumpie przy kazdej zmianie CSS, inaczej przegladarka trzymala stary plik.
    """
    def static_v(filename):
        url = url_for('static', filename=filename)
        try:
            mtime = int(os.path.getmtime(os.path.join(app.static_folder, filename)))
        except OSError:
            return url
        return f'{url}?v={mtime}'

    return {'static_v': static_v}


@app.template_filter('localdt')
def localdt_filter(dt, fmt='%d.%m.%Y %H:%M'):
    """Jinja filter: render a naive-UTC datetime in Europe/Warsaw (DST-correct)."""
    if not dt:
        return '—'
    return utc_to_local(dt).strftime(fmt)

# ── Walidacja danych z zadania dla modeli (400 przy zlej wartosci) ──────────
# Zostaja w warstwie HTTP: uzywaja abort() i current_user, modele w
# logistat/models/ nie wiedza nic o zadaniu.


def process_import_rows(rows, data_pliku):
    """Import w imieniu zalogowanego uzytkownika — `importuj_wiersze()` z
    `logistat.import_paczek` dostaje autora jawnie (modul nie zna current_user)."""
    return importuj_wiersze(rows, data_pliku, current_user.id)


from logistat.web.forecast import bp as bp_forecast  # noqa: E402
app.register_blueprint(bp_forecast)


from logistat.web.admin import bp as bp_admin  # noqa: E402
app.register_blueprint(bp_admin)


from logistat.web.auth import BEZ_WYMOGU_ZMIANY_HASLA, bp as bp_auth  # noqa: E402,F401
app.register_blueprint(bp_auth)


@login_manager.user_loader
def load_user(user_id):
    """Zwraca None dla konta nieaktywnego, wiec dezaktywacja wyrzuca tez z
    trwajacej sesji (nie tylko blokuje kolejne logowanie)."""
    try:
        user = db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None
    if user is None or not user.is_active_user:
        return None
    return user


# ══════════════════════════════════════════════════════════════════════════════
#  HELPER: get or create shift
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE ROUTES
# ══════════════════════════════════════════════════════════════════════════════


@app.route('/scanner/<int:shift_number>')
@leader_required
def scanner(shift_number):
    if shift_number not in (1, 2):
        shift_number = 1
    today = local_today()
    shift = get_or_create_shift(today, shift_number)
    attendances = ShiftAttendance.query.filter_by(shift_id=shift.id)\
        .order_by(ShiftAttendance.scanned_at.desc()).all()
    return render_template('scanner.html',
                           shift_number=shift_number,
                           shift=shift,
                           attendances=attendances,
                           today=today)


@app.route('/assignment')
@leader_required
def assignment():
    activities = Activity.query.filter_by(is_active=True)\
        .order_by(Activity.sort_order).all()
    return render_template('assignment.html', activities=activities)


@app.route('/data-entry')
@leader_required
def data_entry():
    activities = Activity.query.filter_by(is_active=True)\
        .order_by(Activity.sort_order).all()
    return render_template('data_entry.html', activities=activities)


@app.route('/stats')
@leader_required
def stats():
    users = User.query.filter_by(is_active_user=True)\
        .order_by(User.display_name).all()
    activities = Activity.query.filter_by(is_active=True)\
        .order_by(Activity.sort_order).all()
    return render_template('stats.html', users=users, activities=activities,
                           cel_szt_h=get_setting_int('target_szt_h', 0),
                           historia_celu=historia_celu_lista())


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


@app.route('/api/imports', methods=['GET'])
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


@app.route('/api/imports/zmien-date', methods=['POST'])
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

    teraz = datetime.utcnow()
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


@app.route('/import-csv')
@leader_required
def import_csv_page():
    # Dzis LOKALNIE (Warszawa) — podpowiedz daty pliku w oknie importu; zegar
    # przegladarki moze stac w innej strefie albo sie spieszyc.
    return render_template('import_csv.html', dzis=local_today().isoformat())

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


@app.route('/paczki')
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
                           kategorie=list(etykiety_kategorii().items()),
                           grupy=GRUPY_ARTYKULOWE,
                           dodatki=DODATKI_TABELI)


@app.route('/general-stats/export')
@leader_required
def general_stats_export():
    # Lider dostaje ten sam plik bez kolumn kosztow — stawki widzi tylko admin.
    koszty = acting_as_admin()

    date_from_str = request.args.get('date_from', '')
    date_to_str = request.args.get('date_to', '')

    query = GeneralStat.query
    if date_from_str:
        try:
            query = query.filter(GeneralStat.loading_date >= datetime.strptime(date_from_str, '%Y-%m-%d').date())
        except ValueError:
            pass
    if date_to_str:
        try:
            query = query.filter(GeneralStat.loading_date <= datetime.strptime(date_to_str, '%Y-%m-%d').date())
        except ValueError:
            pass
    stats = query.order_by(GeneralStat.loading_date.asc()).all()

    dr_amounts = double_rate_amount_map()

    cost_mappings = CostMapping.query.all() if koszty else []
    rates_by_ym = {(cm.year, cm.month): cm.get_rates_data() for cm in cost_mappings}
    kol_na_kat = 2 if koszty else 1

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Statystyki ogólne'

    # Styles
    header_font = Font(bold=True, color='FFFFFF', size=10)
    header_fill_main = PatternFill('solid', fgColor='3B4A6B')
    header_fill_cat  = PatternFill('solid', fgColor='4F46E5')
    header_fill_dr   = PatternFill('solid', fgColor='C2410C')
    header_fill_tot  = PatternFill('solid', fgColor='166534')
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    thin = Border(
        left=Side(style='thin', color='555555'),
        right=Side(style='thin', color='555555'),
        top=Side(style='thin', color='555555'),
        bottom=Side(style='thin', color='555555'),
    )
    dr_fill_row = PatternFill('solid', fgColor='FFF3E0')

    # Row 1: main headers
    base_headers = ['Loading date', 'Double Rate', 'Week', 'List-ID',
                    'Country of destination', 'Country ledger', 'Amounts', 'Total Amount']
    cat_cols_start = len(base_headers) + 1

    for ci, h in enumerate(base_headers, 1):
        cell = ws.cell(row=1, column=ci, value=h)
        cell.font = header_font
        cell.fill = header_fill_dr if h == 'Double Rate' else header_fill_main
        cell.alignment = center
        cell.border = thin
        ws.merge_cells(start_row=1, start_column=ci, end_row=2, end_column=ci)

    for i, cat in enumerate(STAT_CATEGORIES):
        col = cat_cols_start + i * kol_na_kat
        label = STAT_CATEGORY_LABELS[cat]
        c = ws.cell(row=1, column=col, value=label)
        c.font = header_font
        c.fill = header_fill_cat
        c.alignment = center
        c.border = thin
        if kol_na_kat > 1:
            ws.merge_cells(start_row=1, start_column=col, end_row=1, end_column=col + 1)

    total_col = cat_cols_start + len(STAT_CATEGORIES) * kol_na_kat
    if koszty:
        tc = ws.cell(row=1, column=total_col, value='Total cost (EUR)')
        tc.font = header_font
        tc.fill = header_fill_tot
        tc.alignment = center
        tc.border = thin
        ws.merge_cells(start_row=1, start_column=total_col, end_row=2, end_column=total_col)

    # Row 2: sub-headers for categories
    for i, cat in enumerate(STAT_CATEGORIES):
        col = cat_cols_start + i * kol_na_kat
        for offset, sub in enumerate(['Amount', 'Cost (EUR)'][:kol_na_kat]):
            c = ws.cell(row=2, column=col + offset, value=sub)
            c.font = Font(bold=True, color='FFFFFF', size=9)
            c.fill = header_fill_cat
            c.alignment = center
            c.border = thin

    ws.row_dimensions[1].height = 28
    ws.row_dimensions[2].height = 18

    def write_data_row(ri, s, cd, dr_label, row_fill, amounts_val):
        """Write one data row (normal or yellow double-rate) at Excel row ri."""
        ym = (s.loading_date.year, s.loading_date.month)
        rates = rates_by_ym.get(ym, {})

        # Total Amount: wszystko poza twice/triple, w obu wierszach (TOTAL_AMOUNT_BEZ).
        total_amount = total_amount_wiersza(cd)
        total_cost = sum(cd.get(cat, {}).get('amount', 0) * rates.get(cat, 0.0)
                         for cat in STAT_CATEGORIES)

        row_data = [
            s.loading_date.strftime('%d.%m.%Y'),
            dr_label,
            s.week_number,
            s.list_id,
            s.country_of_destination or '',
            s.country_ledger,
            amounts_val,
            total_amount,
        ]

        for ci, val in enumerate(row_data, 1):
            c = ws.cell(row=ri, column=ci, value=val)
            c.border = thin
            c.alignment = Alignment(horizontal='center' if ci in (1, 2, 3, 7, 8) else 'left')
            if row_fill:
                c.fill = row_fill
            if ci == 2 and dr_label:
                c.font = Font(bold=True, color='C2410C')

        for i, cat in enumerate(STAT_CATEGORIES):
            col = cat_cols_start + i * kol_na_kat
            amt = cd.get(cat, {}).get('amount', 0)
            cost = amt * rates.get(cat, 0.0)
            for offset, val in enumerate([amt, round(cost, 2)][:kol_na_kat]):
                c = ws.cell(row=ri, column=col + offset, value=val)
                c.border = thin
                c.alignment = Alignment(horizontal='right')
                if row_fill:
                    c.fill = row_fill

        if not koszty:
            return
        tc = ws.cell(row=ri, column=total_col, value=round(total_cost, 2))
        tc.border = thin
        tc.alignment = Alignment(horizontal='right')
        tc.font = Font(bold=True)
        if row_fill:
            tc.fill = row_fill

    # Data rows — normal row, then a yellow double-rate row when the line has
    # double-rate packages. The doubling is emergent: the same packages are
    # billed once in the normal row and again (×1) in the yellow row.
    ri = 3
    for s in stats:
        write_data_row(ri, s, s.get_category_data(), '', None, s.amounts)
        ri += 1

        dr_amount = dr_amounts.get((s.list_id, s.country_ledger, s.loading_date), 0)
        if dr_amount > 0:
            write_data_row(ri, s, s.get_double_rate_category_data(),
                           'DOUBLE RATE', dr_fill_row, dr_amount)
            ri += 1

    # Column widths
    col_widths = [12, 10, 6, 14, 22, 18, 9, 12]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    for i in range(len(STAT_CATEGORIES) * kol_na_kat):
        ws.column_dimensions[openpyxl.utils.get_column_letter(cat_cols_start + i)].width = 9
    if koszty:
        ws.column_dimensions[openpyxl.utils.get_column_letter(total_col)].width = 14

    ws.freeze_panes = 'A3'

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    fname = f"statystyki_{date_from_str or 'all'}_{date_to_str or 'all'}.xlsx"
    response = make_response(output.read())
    response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    response.headers['Content-Disposition'] = f'attachment; filename="{fname}"'
    return response


@app.route('/general-stats')
@leader_required
def general_stats_page():
    # Lider: podglad bez kosztow i bez edycji (API zapisu zostaje @admin_required).
    # Stawek nie wysylamy mu nawet do JS — bylyby w zrodle strony.
    admin = acting_as_admin()
    # If parameters not provided, use first and last day of current month
    today = local_today()
    default_from = today.replace(day=1).strftime('%Y-%m-%d')
    # Calculate last day of month
    last_day = calendar.monthrange(today.year, today.month)[1]
    default_to = today.replace(day=last_day).strftime('%Y-%m-%d')

    date_from_str = request.args.get('date_from', default_from)
    date_to_str = request.args.get('date_to', default_to)
    
    query = GeneralStat.query
    
    date_from = None
    date_to = None
    
    if date_from_str:
        try:
            date_from = datetime.strptime(date_from_str, '%Y-%m-%d').date()
            query = query.filter(GeneralStat.loading_date >= date_from)
        except ValueError:
            pass
            
    if date_to_str:
        try:
            date_to = datetime.strptime(date_to_str, '%Y-%m-%d').date()
            query = query.filter(GeneralStat.loading_date <= date_to)
        except ValueError:
            pass

    stats = query.order_by(GeneralStat.loading_date.desc()).all()

    # Ilość double-rate (suma Stückzahl paczek oznaczonych) per linia → żółty wiersz
    dr_amounts = double_rate_amount_map()
    pokrycie = scan_coverage_map()
    for s in stats:
        s.dr_amount = dr_amounts.get((s.list_id, s.country_ledger, s.loading_date), 0)
        # Linia zasilana skanami czyta w trakcie zmiany mniej niz finalnie —
        # licznik pokrycia pilnuje, by nikt nie wzial jej za gotowa.
        s.scanned_cartons, s.total_cartons = pokrycie.get(
            (s.list_id, s.country_ledger, s.loading_date), (0, 0))

    # Przekazanie do szablonu wszystkich mapowań kosztów aby JS miał do nich dostęp przy edycji
    cost_mappings = CostMapping.query.all() if admin else []
    rates_by_ym = {f"{cm.year}-{cm.month:02d}": cm.get_rates_data() for cm in cost_mappings}

    return render_template('general_stats.html',
                           stats=stats,
                           category_labels=STAT_CATEGORY_LABELS,
                           category_labels_pl=nazwy_kategorii_pl(),
                           total_amount_bez=list(TOTAL_AMOUNT_BEZ),
                           zrodlo_kategorii=ZRODLO_KATEGORII,
                           categories=STAT_CATEGORIES,
                           date_from=date_from_str,
                           date_to=date_to_str,
                           rates_by_ym=rates_by_ym,
                           pokaz_koszty=admin,
                           edycja=admin)


# ══════════════════════════════════════════════════════════════════════════════
#  API: BARCODE SCANNING
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/scan', methods=['POST'])
@leader_required
def api_scan():
    data = json_body()
    barcode = str(data.get('barcode') or '').strip()
    shift_number = parse_shift_number(data.get('shift_number', 1))
    shift_date = parse_date(data.get('date'))

    if not barcode:
        return jsonify({'error': 'Brak kodu kreskowego.'}), 400

    # Look up user by barcode
    user = User.query.filter_by(barcode_id=barcode, is_active_user=True).first()
    if not user:
        return jsonify({
            'error': 'Nieznany kod kreskowy! Dodaj użytkownika w panelu.'
        }), 404

    # Get or create shift
    shift = get_or_create_shift(shift_date, shift_number)

    # Check if already scanned
    existing = ShiftAttendance.query.filter_by(
        shift_id=shift.id, user_id=user.id
    ).first()
    if existing:
        return jsonify({
            'warning': f'{user.display_name} już zarejestrowany/a na zmianę {shift_number}.',
            'user': user.to_dict(),
            'already_scanned': True
        }), 200

    # Register attendance
    attendance = ShiftAttendance(shift_id=shift.id, user_id=user.id)
    db.session.add(attendance)
    db.session.commit()

    return jsonify({
        'message': f'{user.display_name} zarejestrowany/a na zmianę {shift_number}.',
        'user': user.to_dict(),
        'attendance': attendance.to_dict()
    }), 201


@app.route('/api/scan/<int:attendance_id>', methods=['DELETE'])
@leader_required
def api_unscan(attendance_id):
    attendance = db.get_or_404(ShiftAttendance, attendance_id)
    db.session.delete(attendance)
    db.session.commit()
    return jsonify({'message': 'Usunięto rejestrację.'}), 200


@app.route('/api/shift/attendances', methods=['GET'])
@leader_required
def api_shift_attendances():
    shift_date = request.args.get('date', local_today().isoformat())
    shift_number = parse_shift_number(request.args.get('shift_number', 1))
    shift = Shift.query.filter_by(
        date=parse_date(shift_date),
        shift_number=shift_number
    ).first()
    if not shift:
        return jsonify({'attendances': [], 'shift': None}), 200
    attendances = ShiftAttendance.query.filter_by(shift_id=shift.id)\
        .options(joinedload(ShiftAttendance.user))\
        .order_by(ShiftAttendance.scanned_at.desc()).all()
    return jsonify({
        'attendances': [a.to_dict() for a in attendances],
        'shift': shift.to_dict()
    }), 200


# ══════════════════════════════════════════════════════════════════════════════
#  API: ASSIGNMENT (DRAG & DROP)
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/assignment/data', methods=['GET'])
@leader_required
def api_assignment_data():
    """Get all assignment data for a given date and shift."""
    shift_date = request.args.get('date', local_today().isoformat())
    shift_number = parse_shift_number(request.args.get('shift_number', 1))

    shift = Shift.query.filter_by(
        date=parse_date(shift_date),
        shift_number=shift_number
    ).first()

    activities = Activity.query.filter_by(is_active=True)\
        .order_by(Activity.sort_order).all()

    if not shift:
        return jsonify({
            'shift': None,
            'attendees': [],
            'assignments': [],
            'activities': [a.to_dict() for a in activities],
            'wydajnosc': wydajnosc_czynnosci(parse_date(shift_date)),
            'szkolenia': {},
            'wersja': wersja_przydzialu([])
        }), 200

    # joinedload: to_dict() kazdego wiersza siega po user/activity — bez tego
    # lista robila SELECT na kazdego pracownika i kazda czynnosc osobno.
    attendances = ShiftAttendance.query.filter_by(shift_id=shift.id)\
        .options(joinedload(ShiftAttendance.user)).all()
    assignments = ActivityAssignment.query.filter_by(shift_id=shift.id)\
        .options(joinedload(ActivityAssignment.user),
                 joinedload(ActivityAssignment.activity)).all()

    # Build set of already-assigned user IDs
    assigned_user_ids = {a.user_id for a in assignments}

    return jsonify({
        'wydajnosc': wydajnosc_czynnosci(shift.date),
        'shift': shift.to_dict(),
        'attendees': [a.user.to_dict() for a in attendances],
        'assignments': [a.to_dict() for a in assignments],
        'activities': [a.to_dict() for a in activities],
        'unassigned': [a.user.to_dict() for a in attendances
                       if a.user_id not in assigned_user_ids],
        # {user_id: [activity_id…]} — tablica nie pozwala upuscic osoby na
        # czynnosc bez szkolenia (serwer i tak to sprawdza przy zapisie).
        'szkolenia': {str(u): sorted(a) for u, a in szkolenia_czynnosci(
            {a.user_id for a in attendances} | assigned_user_ids).items()},
        'wersja': wersja_przydzialu(assignments)
    }), 200


@app.route('/api/assignment/suggestions', methods=['GET'])
@leader_required
def api_assignment_suggestions():
    """Generate AI-based assignment suggestions based on user statistics."""
    shift_date = request.args.get('date', local_today().isoformat())
    shift_number = parse_shift_number(request.args.get('shift_number', 1))

    shift = Shift.query.filter_by(
        date=parse_date(shift_date),
        shift_number=shift_number
    ).first()
    if not shift:
        return jsonify({'suggestions': []}), 200

    attendances = ShiftAttendance.query.filter_by(shift_id=shift.id).all()
    attendee_ids = [a.user_id for a in attendances]
    if not attendee_ids:
        return jsonify({'suggestions': []}), 200

    activities = Activity.query.filter_by(is_active=True)\
        .order_by(Activity.sort_order).all()

    # Calculate average quantity per user per activity (last 30 days)
    thirty_days_ago = parse_date(shift_date) - timedelta(days=30)
    stats = db.session.query(
        DailyStat.user_id,
        DailyStat.activity_id,
        func.avg(DailyStat.quantity).label('avg_qty'),
        func.count(DailyStat.id).label('days_worked')
    ).join(Shift).filter(
        DailyStat.user_id.in_(attendee_ids),
        Shift.date >= thirty_days_ago
    ).group_by(DailyStat.user_id, DailyStat.activity_id).all()

    # Sugestie tylko tam, gdzie osoba jest przeszkolona — zapis i tak by je odrzucil.
    szkolenia = szkolenia_czynnosci(attendee_ids)

    def przeszkolony(uid, aid):
        return aid in szkolenia.get(uid, ())

    # Build performance map: {(user_id, activity_id): avg_qty}
    perf = {}
    for s in stats:
        perf[(s.user_id, s.activity_id)] = float(s.avg_qty)

    # Greedy assignment: for each activity, pick the best unassigned user
    suggestions = []
    assigned = set()

    # Sort activities by fewest qualified workers first
    activity_scores = []
    for act in activities:
        qualified = sum(1 for uid in attendee_ids
                       if perf.get((uid, act.id), 0) > 0)
        activity_scores.append((qualified, act))
    activity_scores.sort(key=lambda x: x[0])

    for _, act in activity_scores:
        # Rank available users by performance for this activity
        candidates = []
        for uid in attendee_ids:
            if uid not in assigned and przeszkolony(uid, act.id):
                avg = perf.get((uid, act.id), 0)
                candidates.append((avg, uid))
        candidates.sort(reverse=True)

        if candidates:
            best_avg, best_uid = candidates[0]
            suggestions.append({
                'user_id': best_uid,
                'activity_id': act.id,
                'avg_quantity': best_avg
            })
            assigned.add(best_uid)

    # Assign remaining unassigned users to activities with fewest people
    activity_counts = {act.id: 0 for act in activities}
    for s in suggestions:
        activity_counts[s['activity_id']] = activity_counts.get(s['activity_id'], 0) + 1

    for uid in attendee_ids:
        mozliwe = [a for a in activity_counts if przeszkolony(uid, a)]
        if uid not in assigned and mozliwe:
            # Find activity with fewest assigned people (z tych, w ktorych przeszkolony)
            min_act_id = min(mozliwe, key=activity_counts.get)
            suggestions.append({
                'user_id': uid,
                'activity_id': min_act_id,
                'avg_quantity': 0
            })
            activity_counts[min_act_id] += 1
            assigned.add(uid)

    return jsonify({'suggestions': suggestions}), 200


# Estymacja na tablicy Przydzielania (2026-10-13, operacje): ile zrobia osoby
# przydzielone do czynnosci = liczba osob × srednia NA OSOBE wszystkich
# pracownikow (nie tylko przydzielonych) z ostatnich 30 dni.
CZYNNOSC_SKANOW_PACZEK = 'Post Processing'   # ta czynnosc = skany paczek
GODZIN_ZMIANY = 7.5                          # 8 h minus 30 min przerwy
DNI_SREDNIEJ_PRZYDZIALU = 30


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


@app.route('/api/assignment/save', methods=['POST'])
@leader_required
def api_assignment_save():
    """Save drag & drop assignments."""
    data = json_body()
    shift_number = parse_shift_number(data.get('shift_number', 1))
    assignments = data.get('assignments') or []
    if not isinstance(assignments, list):
        return jsonify({'error': 'Pole "assignments" musi być listą.'}), 400

    shift = get_or_create_shift(parse_date(data.get('date')), shift_number)
    # Blokada wiersza zmiany serializuje zapisy tej zmiany: bez niej dwa
    # rownolegle delete+insert (autozapis z dwoch stanowisk) wstawialy oba
    # komplety, a sprawdzenie wersji ponizej nie byloby atomowe.
    shift = Shift.query.filter_by(id=shift.id).with_for_update().one()

    # Sprawdz FK przed czyszczeniem, zeby bledne cialo nie wyczyscilo przydzialu
    # i nie zostawilo zmiany pustej.
    znani = {u.id for u in User.query.with_entities(User.id).all()}
    czynnosci = {a.id for a in Activity.query.with_entities(Activity.id).all()}
    nowe = []
    for a in assignments:
        if not isinstance(a, dict):
            return jsonify({'error': 'Każde przydzielenie musi być obiektem.'}), 400
        user_id = require_int(a.get('user_id'), 'user_id')
        activity_id = require_int(a.get('activity_id'), 'activity_id')
        if user_id not in znani:
            return jsonify({'error': f'Nieznany pracownik (id {user_id}).'}), 400
        if activity_id not in czynnosci:
            return jsonify({'error': f'Nieznana czynność (id {activity_id}).'}), 400
        nowe.append((user_id, activity_id, bool(a.get('is_suggestion', False))))

    # Brak `wersja` w ciele = stary klient / API — zapis bez sprawdzania.
    oczekiwana = data.get('wersja')
    if oczekiwana is not None:
        teraz = wersja_przydzialu(
            ActivityAssignment.query.filter_by(shift_id=shift.id).all())
        if oczekiwana != teraz:
            db.session.rollback()
            return jsonify({
                'error': 'Ktoś inny zmienił przydział tej zmiany w międzyczasie. '
                         'Wczytaj aktualny stan i przeciągnij jeszcze raz.',
                'konflikt': True,
                'wersja': teraz,
            }), 409

    # Szkolenia (2026-10-13): NOWY przydzial tylko do czynnosci, w ktorej osoba
    # jest przeszkolona. Juz zapisany zostaje, choc szkolenie odznaczono —
    # inaczej odznaczenie zablokowaloby zapis calej zmiany.
    juz_sa = {(a.user_id, a.activity_id) for a in
              ActivityAssignment.query.filter_by(shift_id=shift.id)}
    do_sprawdzenia = {(u, a) for u, a, _ in nowe if (u, a) not in juz_sa}
    if do_sprawdzenia:
        szkolenia = szkolenia_czynnosci({u for u, _ in do_sprawdzenia})
        brak = sorted((u, a) for u, a in do_sprawdzenia if a not in szkolenia.get(u, ()))
        if brak:
            db.session.rollback()
            osoby = {u.id: u.display_name for u in User.query.filter(
                User.id.in_({u for u, _ in brak}))}
            nazwy = {a.id: a.name for a in Activity.query.filter(
                Activity.id.in_({a for _, a in brak}))}
            lista = [{'user_id': u, 'activity_id': a, 'osoba': osoby.get(u, f'#{u}'),
                      'czynnosc': nazwy.get(a, f'#{a}')} for u, a in brak]
            return jsonify({
                'error': 'Brak szkolenia: ' + '; '.join(
                    f"{x['osoba']} — {x['czynnosc']}" for x in lista)
                    + '. Szkolenia zaznacza się w Użytkownikach.',
                'brak_szkolenia': lista,
            }), 400

    # Clear existing assignments for this shift
    ActivityAssignment.query.filter_by(shift_id=shift.id).delete()

    for user_id, activity_id, is_suggestion in nowe:
        db.session.add(ActivityAssignment(
            shift_id=shift.id,
            user_id=user_id,
            activity_id=activity_id,
            is_suggestion=is_suggestion,
            assigned_by=current_user.id
        ))

    db.session.commit()
    return jsonify({
        'message': 'Przydzielenie zapisane.',
        'wersja': wersja_przydzialu(
            ActivityAssignment.query.filter_by(shift_id=shift.id).all()),
    }), 200


# ══════════════════════════════════════════════════════════════════════════════
#  API: DAILY STATS (DATA ENTRY)
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/daily-stats', methods=['GET'])
@leader_required
def api_daily_stats_get():
    """Get stats for a given date and shift."""
    shift_date = request.args.get('date', local_today().isoformat())
    shift_number = parse_shift_number(request.args.get('shift_number', 1))

    shift = Shift.query.filter_by(
        date=parse_date(shift_date),
        shift_number=shift_number
    ).first()
    if not shift:
        return jsonify({'stats': [], 'shift': None}), 200

    # Get assignments for this shift
    assignments = ActivityAssignment.query.filter_by(shift_id=shift.id)\
        .options(joinedload(ActivityAssignment.user),
                 joinedload(ActivityAssignment.activity)).all()
    stats = DailyStat.query.filter_by(shift_id=shift.id)\
        .options(joinedload(DailyStat.user), joinedload(DailyStat.activity)).all()

    return jsonify({
        'shift': shift.to_dict(),
        'assignments': [a.to_dict() for a in assignments],
        'stats': [s.to_dict() for s in stats]
    }), 200


@app.route('/api/daily-stats', methods=['POST'])
@leader_required
def api_daily_stats_save():
    """Save or update daily statistics."""
    data = json_body()
    shift_number = parse_shift_number(data.get('shift_number', 1))
    entries = data.get('entries') or []
    if not isinstance(entries, list):
        return jsonify({'error': 'Pole "entries" musi być listą.'}), 400

    shift = get_or_create_shift(parse_date(data.get('date')), shift_number)

    for entry in entries:
        if not isinstance(entry, dict):
            return jsonify({'error': 'Każdy wpis musi być obiektem.'}), 400
        user_id = require_int(entry.get('user_id'), 'user_id')
        activity_id = require_int(entry.get('activity_id'), 'activity_id')
        quantity = require_int(entry.get('quantity', 0) or 0, 'quantity')

        existing = DailyStat.query.filter_by(
            shift_id=shift.id,
            user_id=user_id,
            activity_id=activity_id
        ).first()

        if existing:
            existing.quantity = quantity
            existing.note = entry.get('note', '')
            existing.modified_by = current_user.id
            existing.modified_at = datetime.utcnow()
        else:
            db.session.add(DailyStat(
                shift_id=shift.id,
                user_id=user_id,
                activity_id=activity_id,
                quantity=quantity,
                note=entry.get('note', ''),
                entered_by=current_user.id
            ))

    db.session.commit()
    return jsonify({'message': 'Statystyki zapisane.'}), 200


@app.route('/api/daily-stats/<int:stat_id>', methods=['PUT'])
@leader_required
def api_daily_stat_update(stat_id):
    """Update a single daily stat (mistake correction)."""
    stat = db.get_or_404(DailyStat, stat_id)
    data = json_body()

    stat.quantity = data.get('quantity', stat.quantity)
    stat.note = data.get('note', stat.note)
    stat.modified_by = current_user.id
    stat.modified_at = datetime.utcnow()

    db.session.commit()
    return jsonify({'message': 'Zaktualizowano.', 'stat': stat.to_dict()}), 200


# ══════════════════════════════════════════════════════════════════════════════
#  API: STATISTICS
# ══════════════════════════════════════════════════════════════════════════════

def prace_osob(date_from=None, date_to=None, user_ids=None):
    """Zakonczona praca kazdej osoby przy paczkach: `{uid: [(start, koniec, sztuk)]}`.

    JEDYNA definicja „kto ile zrobil" — Normy, wykresy, Dashboard (per
    pracownik, per zmiana). Dwa zrodla:
    - paczka jednej osoby (bez `udzial_paczki`): kto zakonczyl, start–koniec,
      sztuk = Stückzahl — jak zawsze;
    - paczka wielu osob (przekazana / zespol): kazdy swoj udzial — jego czas
      i jego WPISANE ilosci (decyzja operacji 2026-10-13; od 2026-10-15 z tabeli:
      Pojedynczo + Podwojnie + Potrojnie + Uszkodzone — UdzialPaczki.sztuki()),
      liczony po koncu
      udzialu, takze gdy paczke dokonczy ktos inny pozniej. Udzial zamkniety
      przez kogos innego (bez ilosci) pomijamy — nie ma czego liczyc.
    Zakres po DOBIE LOKALNEJ konca, polotwarty.
    """
    ma_udzialy = db.session.query(UdzialPaczki.id).filter(
        UdzialPaczki.carton_id == ImportedCarton.id).exists()
    q = db.session.query(
        ImportedCarton.scan_end_by,
        ImportedCarton.scan_start_at,
        ImportedCarton.scan_end_at,
        ImportedCarton.stueckzahl,
    ).filter(
        ImportedCarton.scan_end_at.isnot(None),
        ImportedCarton.scan_end_by.isnot(None),
        ~ma_udzialy,
    )
    uq = UdzialPaczki.query.filter(
        UdzialPaczki.end_at.isnot(None),
        UdzialPaczki.zamkniete_przez.is_(None),
    )
    # `scan_end_at` / `end_at` to naive UTC — granice doby jak wszedzie indziej.
    if date_from:
        q = q.filter(ImportedCarton.scan_end_at >= local_day_bounds(date_from)[0])
        uq = uq.filter(UdzialPaczki.end_at >= local_day_bounds(date_from)[0])
    if date_to:
        q = q.filter(ImportedCarton.scan_end_at < local_day_bounds(date_to)[1])
        uq = uq.filter(UdzialPaczki.end_at < local_day_bounds(date_to)[1])
    if user_ids is not None:
        q = q.filter(ImportedCarton.scan_end_by.in_(list(user_ids)))
        uq = uq.filter(UdzialPaczki.user_id.in_(list(user_ids)))

    per_osoba = {}
    for uid, start, koniec, sztuk in q.all():
        per_osoba.setdefault(uid, []).append((start, koniec, sztuk or 0))
    for u in uq.all():
        per_osoba.setdefault(u.user_id, []).append((u.start_at, u.end_at, u.sztuki()))
    return per_osoba


def wydajnosc_pracownikow(date_from=None, date_to=None):
    """Zakonczone paczki kazdego pracownika: `{uid: [(start, koniec, sztuk)]}`.

    Dlaczego z paczek, a nie z `DailyStat`: wpis ilosci jest uzupelniany
    sporadycznie (na `.31` to kilka wierszy), a skan paczek leci przy kazdej
    sztuce — to jedyne zrodlo, ktore realnie pokrywa zespol.

    Liczenie (szt./h, szkolenia) robi `policz_wydajnosc()` — tu tylko dane
    z `prace_osob()`. `start` bywa None (paczka zamknieta bez skanu „Start").
    """
    return prace_osob(date_from, date_to)


# Szkolenie bez „konca" (zapomniany skan, brak „Koniec pracy") liczymy do teraz,
# ale najwyzej tyle — inaczej jedno zapomniane wejscie sprzed tygodnia robiloby
# „szkoleniowymi" wszystkie paczki tej osoby az do dzis.
MAKS_OTWARTEGO_SZKOLENIA = timedelta(hours=12)


def okresy_szkolen(user_ids, date_from=None, date_to=None, najwczesniej=None):
    """`(prowadzone, jako_szkolony)` — dwa `{uid: [(start, koniec)]}` (naive UTC).

    `prowadzone` = szkolenia, ktore osoba prowadzila (`training_*`),
    `jako_szkolony` = czas, w ktorym sama byla szkolona (`trainee_*`). Jedno
    zapytanie na oba rodzaje. Pary start/koniec skladamy w obrebie (osoba,
    zmiana), tak samo jak `_compute_worker_times()`. Margines doby przy
    granicach zakresu: paczka zakonczona tuz po polnocy moze lezec w szkoleniu
    zaczetym wieczorem. `najwczesniej` = najwczesniejszy start paczki w
    zakresie (naive UTC): paczka zaczeta dni przed `date_from` liczy sie cala,
    gdy zahaczyla o szkolenie — bez tego wynik zalezal od wybranego zakresu.
    """
    if not user_ids:
        return {}, {}
    q = WorkerTimeEvent.query.filter(
        WorkerTimeEvent.user_id.in_(list(user_ids)),
        WorkerTimeEvent.event_type.in_(
            ('training_start', 'training_end', 'trainee_start', 'trainee_end')))
    margines = timedelta(days=1)
    if date_from:
        od = local_day_bounds(date_from)[0]
        if najwczesniej and najwczesniej < od:
            od = najwczesniej
        q = q.filter(WorkerTimeEvent.timestamp >= od - margines)
    if date_to:
        q = q.filter(WorkerTimeEvent.timestamp < local_day_bounds(date_to)[1] + margines)

    otwarte = {}
    wynik = {'training': {}, 'trainee': {}}
    for e in q.order_by(WorkerTimeEvent.timestamp, WorkerTimeEvent.id):
        rodzaj, _, koncowka = e.event_type.rpartition('_')
        klucz = (rodzaj, e.user_id, e.shift_id)
        if koncowka == 'start':
            otwarte[klucz] = e.timestamp
        elif klucz in otwarte:
            wynik[rodzaj].setdefault(e.user_id, []).append((otwarte.pop(klucz), e.timestamp))
    teraz = datetime.utcnow()
    for (rodzaj, uid, _), start in otwarte.items():
        wynik[rodzaj].setdefault(uid, []).append(
            (start, min(teraz, start + MAKS_OTWARTEGO_SZKOLENIA)))
    return wynik['training'], wynik['trainee']


def cele_dzienne():
    """Funkcja `dzien -> cel szt./h obowiazujacy tego dnia` (0 = nie ustawiono).

    Z `HistoriaCelu`; dzien sprzed pierwszego wpisu (historia jeszcze nie
    zasiana) dostaje biezaca wartosc ustawienia.
    """
    wiersze = HistoriaCelu.query.order_by(HistoriaCelu.dzien).all()
    dni = [w.dzien for w in wiersze]
    wartosci = [w.wartosc for w in wiersze]
    biezacy = get_setting_int('target_szt_h', 0)

    def cel(dzien):
        i = bisect_right(dni, dzien)
        return wartosci[i - 1] if i else biezacy
    return cel


def zmiany_celu(date_from=None, date_to=None):
    """Cele obowiazujace w zakresie dni: `[{'od': iso|None, 'wartosc'}]`, rosnaco.

    Pierwszy element to cel obowiazujacy juz na poczatku zakresu (`od` = jego
    prawdziwy dzien wpisu; `None` = zasiew „od zawsze"). Wartosc 0 = brak celu.
    """
    wiersze = HistoriaCelu.query.order_by(HistoriaCelu.dzien).all()
    wynik = []
    for w in wiersze:
        if date_to and w.dzien > date_to:
            break
        wpis = {'od': None if w.dzien == POCZATEK_HISTORII_CELU else w.dzien.isoformat(),
                'wartosc': w.wartosc}
        if date_from and w.dzien <= date_from:
            wynik = [wpis]             # obowiazywal juz na poczatku zakresu
        else:
            wynik.append(wpis)
    if not wynik:
        wynik = [{'od': None, 'wartosc': get_setting_int('target_szt_h', 0)}]
    return wynik


def zasiej_historie_celu():
    """Pusta `HistoriaCelu` → jeden wiersz z biezacym celem od `POCZATEK_HISTORII_CELU`.

    Bez tego pierwsza zmiana celu po wdrozeniu przeliczylaby wstecz wszystkie
    wczesniejsze szkolenia (dzien bez wpisu bralby biezacy cel). Bez commitu.
    """
    if HistoriaCelu.query.first() is None:
        db.session.add(HistoriaCelu(dzien=POCZATEK_HISTORII_CELU,
                                    wartosc=get_setting_int('target_szt_h', 0)))


@app.route('/api/stats/target', methods=['PUT'])
@leader_required
def api_stats_target_update():
    """Docelowa wydajnosc (szt./h) wpisywana przez lidera na ekranie Statystyk.

    Celowo `@leader_required`, mimo ze reszta `AppSetting` idzie przez
    admin-only `PUT /api/settings`: cel jest **wylacznie informacyjny** —
    koloruje kolumne i nie dotyka ani rozliczen, ani zadnej blokady. Lider
    prowadzi zmiane, wiec to on ustala poprzeczke. Endpoint przyjmuje ten jeden
    klucz i nic wiecej, zeby nie otwierac liderowi calych ustawien.
    """
    data = json_body()
    try:
        wartosc = int(data.get('target_szt_h'))
    except (TypeError, ValueError):
        abort(400, 'Docelowa wydajność musi być liczbą całkowitą.')
    if wartosc < 0:
        abort(400, 'Docelowa wydajność nie może być ujemna.')

    # Historia celu: szkolenie liczy sie celem z dnia paczki, wiec stare dni
    # musza zachowac stary cel. Najpierw (raz) zapisujemy dotychczasowa wartosc
    # jako obowiazujaca „od zawsze", potem nowa od dzis.
    zasiej_historie_celu()
    dzis = db.session.get(HistoriaCelu, local_today())
    if dzis is None:
        dzis = HistoriaCelu(dzien=local_today(), wartosc=wartosc)
        db.session.add(dzis)
    else:
        dzis.wartosc = wartosc         # ostatni zapis danego dnia wygrywa
    dzis.zmienil_id = current_user.id
    dzis.zmieniono_at = datetime.utcnow()
    set_setting('target_szt_h', wartosc)
    db.session.commit()
    return jsonify({
        'message': 'Zapisano cel.' if wartosc else 'Cel wyłączony.',
        'target_szt_h': wartosc,
        'historia': historia_celu_lista(),
    }), 200


@app.route('/api/stats/overview', methods=['GET'])
@leader_required
def api_stats_overview():
    date_from = parse_date(request.args.get('date_from'), 'date_from') \
        if request.args.get('date_from') else None
    date_to = parse_date(request.args.get('date_to'), 'date_to') \
        if request.args.get('date_to') else None
    return jsonify(przeglad_zespolu(date_from, date_to)), 200


def przeglad_zespolu(date_from, date_to):
    """Przeglad calego zespolu: kto wyrabia najlepiej, kto odstaje.

    Jedyna definicja oceny — korzysta z niej i zakladka „Przeglad ogolny",
    i karta oceny w widoku per pracownik (`norma_pracownika()`), zeby ta sama
    osoba w tym samym okresie nigdy nie dostala dwoch roznych wynikow.

    Odniesieniem jest **srednia zespolu** z wybranego okresu, liczona jako
    wszystkie sztuki / wszystkie godziny skanowania (decyzja z 2026-09-28,
    wczesniej mediana). Wchodza WSZYSCY ze zmierzonym czasem, takze osoby
    ponizej `min_packages_rank` — ale kazda wazy tyle, ile przepracowala, wiec
    konto z dwiema blyskawicznymi paczkami (26 038 szt./h na .31) nie wypacza
    wyniku, jak zrobilaby to zwykla srednia z wynikow osob (2 570 zamiast 292).
    Prog paczek nadal decyduje tylko o tym, kto jest w rankingu i dostaje ocene.

    Paczki zahaczajace o szkolenie (osoba szkolaca) licza sie jej cale jako
    100% celu i nie wchodza do sredniej — patrz `policz_wydajnosc()`.
    """
    prog_dobry = get_setting_int('norm_good_pct', 110)
    prog_slaby = get_setting_int('norm_weak_pct', 90)
    min_paczek = get_setting_int('min_packages_rank', 3)

    dane = wydajnosc_pracownikow(date_from, date_to)
    szkolenia, szkoleni = okresy_szkolen(
        dane.keys(), date_from, date_to,
        najwczesniej=min((p[0] for ps in dane.values() for p in ps if p[0]), default=None))
    # Cel z dnia pracy (2026-10-13): kazdy liczony celem, ktory obowiazywal,
    # gdy skanowal — zmiana celu nie przelicza starych dni.
    cel_dnia = cele_dzienne()
    # joinedload: rodzaj pracownika i nazwa zmiany ida do kazdego wiersza.
    uzytkownicy = {u.id: u for u in User.query.options(
        joinedload(User.worker_type), joinedload(User.shift_group)).filter(
        User.id.in_(dane.keys())).all()} if dane else {}

    wiersze = []
    suma_sztuk_z_czasem = 0
    suma_godzin_z_czasem = 0.0
    sekundy_z_celem = 0.0
    cel_x_sekundy = 0.0
    for uid, paczki in dane.items():
        user = uzytkownicy.get(uid)
        if not user:
            continue                   # konto skasowane twardo — pomijamy
        w = policz_wydajnosc(paczki, szkolenia.get(uid, ()), cel_dnia,
                             szkoleni.get(uid, ()))
        if w['sekundy_do_sredniej'] > 0:
            # Paczki bez zmierzonego czasu nie wchodza do sredniej — sztuki
            # bez godzin zawyzylyby ja. Paczki ze szkolenia tez nie (sa
            # z definicji rowno w celu).
            suma_sztuk_z_czasem += w['sztuk_do_sredniej']
            suma_godzin_z_czasem += w['sekundy_do_sredniej'] / 3600.0
        sekundy_z_celem += w['sekundy_z_celem']
        cel_x_sekundy += w['cel_x_sekundy']
        wiersze.append({
            'user_id': uid,
            'display_name': user.display_name,
            'is_active_user': user.is_active_user,
            'worker_type': user.worker_type.name if user.worker_type else None,
            'shift_group': user.shift_group.name if user.shift_group else None,
            'paczek': w['paczek'],
            'sztuk': w['sztuk'],
            'godzin': round(w['sekundy'] / 3600.0, 2),
            'szt_h': w['szt_h'],
            # Paczki zrobione w czasie szkolenia (liczone jako 100% celu dnia).
            'paczek_szkolenia': w['paczek_szkolenia'],
            'godzin_szkolenia': round(w['sekundy_szkolenia'] / 3600.0, 2),
            # Paczki zrobione jako osoba szkolona — wypadaja z oceny.
            'paczek_jako_szkolony': w['paczek_jako_szkolony'],
            'godzin_jako_szkolony': round(w['sekundy_jako_szkolony'] / 3600.0, 2),
            'paczek_do_oceny': w['paczek_do_oceny'],
            # Cel tej osoby: srednia celow z dni, w ktore skanowala (wazona godzinami).
            'cel_szt_h': w['cel_szt_h'],
        })

    # Do rankingu wchodzi tylko ten, kto ma dosc paczek i zmierzony czas.
    # Reszta ladu je w osobnym koszyku — ukrycie jej sugerowaloby, ze nie
    # pracowala, a to nieprawda: po prostu nie ma z czego liczyc sredniej.
    def kwalifikuje(r):
        return r['paczek_do_oceny'] >= min_paczek and r['szt_h'] is not None

    ranking = [r for r in wiersze if kwalifikuje(r)]
    za_malo = [r for r in wiersze if not kwalifikuje(r)]

    srednia = (suma_sztuk_z_czasem / suma_godzin_z_czasem
               if suma_godzin_z_czasem > 0 else None)

    for r in ranking:
        if srednia and srednia > 0:
            proc = round(r['szt_h'] / srednia * 100)
            r['proc_sredniej'] = proc
            r['ocena'] = ('dobra' if proc >= prog_dobry
                          else 'slaba' if proc <= prog_slaby else 'ok')
        else:
            r['proc_sredniej'] = None
            r['ocena'] = None
        # Cel jest poprzeczka do przeskoczenia, wiec ocena jest dwustanowa:
        # 100% = spelnia. NIE uzywamy tu pasm norm_good/norm_weak — te opisuja
        # odchylenie od sredniej zespolu, a lider, ktory wpisal liczbe jako
        # wymagany poziom, przeczytalby „rowno w celu = tylko ok" jako blad.
        if r['cel_szt_h']:
            proc_celu = round(r['szt_h'] / r['cel_szt_h'] * 100)
            r['proc_celu'] = proc_celu
            r['ocena_celu'] = 'spelnia' if proc_celu >= 100 else 'ponizej'
        else:
            r['proc_celu'] = None
            r['ocena_celu'] = None
    for r in za_malo:
        r['proc_sredniej'] = None
        r['ocena'] = None
        r['proc_celu'] = None
        r['ocena_celu'] = None

    ranking.sort(key=lambda r: r['szt_h'], reverse=True)
    za_malo.sort(key=lambda r: r['display_name'])

    # Cel zespolu w okresie: wazony godzinami wszystkich; bez godzin — cel
    # z ostatniego dnia zakresu (zeby kolumna celu nie znikala na pustym dniu).
    zmiany = zmiany_celu(date_from, date_to)
    if sekundy_z_celem > 0:
        cel = round(cel_x_sekundy / sekundy_z_celem, 1)
    else:
        cel = cel_dnia(date_to or local_today()) or None

    return {
        'date_from': date_from.isoformat() if date_from else None,
        'date_to': date_to.isoformat() if date_to else None,
        'srednia_szt_h': round(srednia, 1) if srednia else None,
        'cel_szt_h': cel,
        # Cele obowiazujace w zakresie, rosnaco — >1 = cel zmienial sie po drodze.
        'cele_w_okresie': zmiany,
        'progi': {'dobry': prog_dobry, 'slaby': prog_slaby, 'min_paczek': min_paczek},
        # Bez celu albo bez nikogo w rankingu nie ma czego zliczac — `None`,
        # nie 0. „0 / 0" czytaloby sie jak „nikt nie spelnia" albo, gorzej,
        # jak komplet (0 z 0 to przeciez wszyscy).
        'spelnia_cel': (sum(1 for r in ranking if r['ocena_celu'] == 'spelnia')
                        if cel and ranking else None),
        'pracownicy': ranking,
        'za_malo_danych': za_malo,
        'podsumowanie': {
            'osob': len(wiersze),
            'w_rankingu': len(ranking),
            'paczek': sum(r['paczek'] for r in wiersze),
            'sztuk': sum(r['sztuk'] for r in wiersze),
            'godzin': round(sum(r['godzin'] for r in wiersze), 2),
        },
    }


def norma_pracownika(user_id, date_from, date_to):
    """Ocena jednej osoby na tle zespolu — wiersz wyjety z `przeglad_zespolu()`.

    Nie liczymy niczego drugi raz: srednia, progi i cel sa te same co w
    przegladzie, wiec % sredniej i ocena zgadzaja sie z rankingiem co do joty.
    """
    p = przeglad_zespolu(date_from, date_to)
    wynik = {
        'srednia_szt_h': p['srednia_szt_h'],
        'cel_szt_h': p['cel_szt_h'],
        'progi': p['progi'],
        'w_rankingu': len(p['pracownicy']),
        'miejsce': None,
        'powod_braku_oceny': None,
        'wiersz': None,
    }
    for i, r in enumerate(p['pracownicy']):
        if r['user_id'] == user_id:
            wynik['miejsce'] = i + 1
            wynik['wiersz'] = r
            # Cel tej osoby — z dni, w ktore pracowala (% celu liczony wlasnie nim).
            if r['cel_szt_h'] is not None:
                wynik['cel_szt_h'] = r['cel_szt_h']
            return wynik
    for r in p['za_malo_danych']:
        if r['user_id'] == user_id:
            wynik['wiersz'] = r
            if r['cel_szt_h'] is not None:
                wynik['cel_szt_h'] = r['cel_szt_h']
            wynik['powod_braku_oceny'] = (
                'szkolony' if r['paczek_do_oceny'] == 0 and r['paczek_jako_szkolony']
                else 'brak_czasu' if r['szt_h'] is None
                else 'za_malo_paczek')
            return wynik
    wynik['powod_braku_oceny'] = 'brak_paczek'
    return wynik


def wykres_wydajnosci(paczki_per_klucz, szkolenia=(), cel_dnia=None, jako_szkolony=()):
    """`{klucz: [(start, koniec, sztuk)]}` → lista punktow wykresu, rosnaco.

    Liczy `policz_wydajnosc()` — ta sama miara co w przegladzie, lacznie
    z paczkami ze szkolenia (100% celu dnia). Slupki (`sztuk`) to prawdziwe
    sztuki. Bez zmierzonego czasu `szt_h` = None, nie 0: zero wygladaloby na
    fatalny dzien, a to po prostu brak skanu „Start".
    """
    punkty = []
    for klucz in sorted(paczki_per_klucz):
        w = policz_wydajnosc(paczki_per_klucz[klucz], szkolenia, cel_dnia, jako_szkolony)
        punkty.append({
            'okres': klucz,
            'paczek': w['paczek'],
            'sztuk': w['sztuk'],
            'godzin': round(w['sekundy'] / 3600.0, 2),
            'szt_h': w['szt_h'],
            'paczek_szkolenia': w['paczek_szkolenia'],
            'paczek_jako_szkolony': w['paczek_jako_szkolony'],
            # Cel z dni tego punktu; dzien bez zmierzonego czasu — cel tego dnia.
            'cel': (w['cel_szt_h'] if w['cel_szt_h'] is not None
                    else (cel_dnia(date.fromisoformat(klucz)) or None)
                    if cel_dnia and len(klucz) == 10 else None),
        })
    return punkty


def podsumuj_paczki_pracownika(per_day):
    """Srednie paczek i sztuk jednej osoby z `{'YYYY-MM-DD': {'cnt', 'pcs'}}`.

    Mianownikiem sa dni i miesiace, w ktorych osoba FAKTYCZNIE zakonczyla
    choc jedna paczke — nie dni kalendarzowe zakresu. Inaczej urlop albo
    weekend zanizalyby srednia, a lider czyta ja jako „ile robi, kiedy jest".
    Srednia miesieczna liczy miesiace z praca w wybranym okresie, wiec przy
    zakresie „30 dni" przecinajacym dwa miesiace dzieli przez 2.
    """
    paczek = sum(a['cnt'] for a in per_day.values())
    sztuk = sum(a['pcs'] for a in per_day.values())
    dni = len(per_day)
    miesiecy = len({d[:7] for d in per_day})

    def srednio(ile, przez):
        return round(ile / przez, 1) if przez else None

    return {
        'paczek': paczek,
        'sztuk': sztuk,
        'dni_pracy': dni,
        'miesiecy_pracy': miesiecy,
        'srednio_dziennie': {'paczek': srednio(paczek, dni), 'sztuk': srednio(sztuk, dni)},
        'srednio_miesiecznie': {'paczek': srednio(paczek, miesiecy),
                                'sztuk': srednio(sztuk, miesiecy)},
    }


@app.route('/api/stats/user/<int:user_id>', methods=['GET'])
@leader_required
def api_stats_user(user_id):
    """Get per-user statistics, grouped by day and month."""
    user = db.get_or_404(User, user_id)
    activity_id = request.args.get('activity_id', type=int)
    date_from = parse_date(request.args.get('date_from'), 'date_from') \
        if request.args.get('date_from') else None
    date_to = parse_date(request.args.get('date_to'), 'date_to') \
        if request.args.get('date_to') else None

    query = db.session.query(
        DailyStat, Shift
    ).join(Shift).filter(DailyStat.user_id == user_id)

    if activity_id:
        query = query.filter(DailyStat.activity_id == activity_id)
    if date_from:
        query = query.filter(Shift.date >= date_from)
    if date_to:
        query = query.filter(Shift.date <= date_to)

    results = query.order_by(Shift.date.desc()).all()

    daily_stats = []
    monthly_agg = {}

    for stat, shift in results:
        daily_stats.append({
            'date': shift.date.isoformat(),
            'shift_number': shift.shift_number,
            'activity': stat.activity.name,
            'activity_id': stat.activity_id,
            'quantity': stat.quantity,
            'note': stat.note,
            'entered_by': stat.entered_by_user.display_name if stat.entered_by_user else None,
            'modified_by': stat.modified_by_user.display_name if stat.modified_by_user else None,
            'modified_at': iso_z(stat.modified_at),
            'stat_id': stat.id
        })

        month_key = shift.date.strftime('%Y-%m')
        act_name = stat.activity.name
        key = (month_key, act_name)
        if key not in monthly_agg:
            monthly_agg[key] = {'total': 0, 'days': 0}
        monthly_agg[key]['total'] += stat.quantity
        monthly_agg[key]['days'] += 1

    # Zakonczone paczki pracownika w okresie, po DOBIE LOKALNEJ, tak samo jak
    # dashboard. `func.date()` cielo po dacie UTC, wiec paczka zakonczona po
    # lokalnej polnocy trafiala na inny dzien tutaj niz na dashboardzie.
    # Konwersja jest w Pythonie: `local_day_bounds()` jest jedyna definicja doby
    # w calej aplikacji, a zakres jest maly (paczki jednej osoby w okresie).
    praca = prace_osob(date_from, date_to, user_ids=[user_id]).get(user_id, [])

    per_day = {}
    paczki_dnia = {}
    paczki_miesiaca = {}
    for scan_start_at, scan_end_at, stueckzahl in praca:
        d = utc_to_local(scan_end_at).date().isoformat()
        agg = per_day.setdefault(d, {'cnt': 0, 'pcs': 0})
        agg['cnt'] += 1
        agg['pcs'] += stueckzahl or 0
        paczka = (scan_start_at, scan_end_at, stueckzahl or 0)
        paczki_dnia.setdefault(d, []).append(paczka)
        paczki_miesiaca.setdefault(d[:7], []).append(paczka)
    szkolenia, szkoleni = okresy_szkolen(
        [user_id], date_from, date_to,
        najwczesniej=min((p[0] for p in praca if p[0]), default=None))
    szkolenia = szkolenia.get(user_id, ())
    szkoleni = szkoleni.get(user_id, ())
    cel_dnia = cele_dzienne()

    paczki_podsumowanie = podsumuj_paczki_pracownika(per_day)

    # Paczki jako syntetyczne pozycje tabel — tylko w widoku "Wszystkie"
    if not activity_id:
        PKG_METRICS = [('📦 Paczki', lambda cnt, pcs: cnt),
                       ('📦 Paczki (szt.)', lambda cnt, pcs: pcs)]
        for d, agg in per_day.items():
            cnt, pcs = agg['cnt'], agg['pcs']
            for label, metric in PKG_METRICS:
                qty = int(metric(cnt, pcs))
                daily_stats.append({
                    'date': d,
                    'shift_number': None,
                    'activity': label,
                    'activity_id': None,
                    'quantity': qty,
                    'note': '',
                    'entered_by': 'auto (skan paczek)',
                    'modified_by': None,
                    'modified_at': None,
                    'stat_id': None,
                    'is_package': True,
                })
                month_key = d[:7]  # 'YYYY-MM'
                key = (month_key, label)
                if key not in monthly_agg:
                    monthly_agg[key] = {'total': 0, 'days': 0}
                monthly_agg[key]['total'] += qty
                monthly_agg[key]['days'] += 1

    # Wspólne sortowanie malejąco po dacie (paczki wymieszane z czynnościami)
    daily_stats.sort(key=lambda x: x['date'], reverse=True)

    monthly_stats = [
        {
            'month': k[0],
            'activity': k[1],
            'total_quantity': v['total'],
            'days_worked': v['days'],
            'avg_per_day': round(v['total'] / v['days'], 1) if v['days'] > 0 else 0
        }
        for k, v in sorted(monthly_agg.items(), reverse=True)
    ]

    return jsonify({
        'user': user.to_dict(),
        'daily': daily_stats,
        'monthly': monthly_stats,
        'paczki_podsumowanie': paczki_podsumowanie,
        # Ocena i wykresy ida z paczek, wiec — jak podsumowanie — nie zaleza
        # od filtra czynnosci.
        'norma': norma_pracownika(user_id, date_from, date_to),
        'wykres_dzienny': wykres_wydajnosci(paczki_dnia, szkolenia, cel_dnia, szkoleni),
        'wykres_miesieczny': wykres_wydajnosci(paczki_miesiaca, szkolenia, cel_dnia, szkoleni),
    }), 200


# ══════════════════════════════════════════════════════════════════════════════
#  API: ADMIN — ACTIVITIES
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
#  API: ADMIN — USERS
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
#  API: ADMIN — LISTY NA KONCIE UZYTKOWNIKA (rodzaj pracownika, nazwa zmiany)
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
#  API: ADMIN — COUNTRY MAPPINGS
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
#  API: CSV IMPORT + GENERAL STATS
# ══════════════════════════════════════════════════════════════════════════════


def wymagana_data_pliku(wartosc):
    """Data pliku z requestu — WYMAGANA. Nie przez parse_date(): ta dla pustej
    wartosci zwraca dzis, a cichy domysl to dokladnie blad, przed ktorym
    chroni okno z data przy imporcie."""
    tekst = str(wartosc or '').strip()
    if not tekst:
        abort(400, 'Podaj Loading date (dzień, którego dotyczy plik).')
    try:
        return date.fromisoformat(tekst)
    except ValueError:
        abort(400, 'Nieprawidłowa Loading date (oczekiwano YYYY-MM-DD).')


@app.route('/api/import-csv', methods=['POST'])
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


@app.route('/api/import/excel', methods=['POST'])
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


@app.route('/api/general-stats', methods=['GET'])
@admin_required
def api_general_stats():
    """Lista linii rozliczeniowych. Opcjonalne `date_from` / `date_to`
    (YYYY-MM-DD) — bez nich zwraca wszystko, jak dotad."""
    query = GeneralStat.query
    for param, warunek in (('date_from', GeneralStat.loading_date.__ge__),
                           ('date_to', GeneralStat.loading_date.__le__)):
        wartosc = request.args.get(param, '')
        if wartosc:
            try:
                query = query.filter(warunek(date.fromisoformat(wartosc)))
            except ValueError:
                return jsonify({'error': f'Nieprawidłowa data w {param}.'}), 400
    stats = query.order_by(GeneralStat.loading_date.desc()).all()
    # Pokrycie liczymy raz dla calej listy (jedno zapytanie), nie per wiersz.
    pokrycie = scan_coverage_map()
    wynik = []
    for s in stats:
        d = s.to_dict()
        zesk, wsz = pokrycie.get((s.list_id, s.country_ledger, s.loading_date), (0, 0))
        d['scanned_cartons'] = zesk
        d['total_cartons'] = wsz
        wynik.append(d)
    return jsonify(wynik), 200


@app.route('/api/general-stats/<int:stat_id>', methods=['PUT'])
@admin_required
def api_general_stat_update(stat_id):
    stat = db.get_or_404(GeneralStat, stat_id)
    data = json_body()

    if 'category_data' in data:
        if (stat.category_source or 'manual') == 'scan':
            abort(400, 'Kategorie tej linii pochodzą ze skanów paczek — '
                       'popraw ilości przy paczce (Paczki → ✎ Ilości).')
        stat.set_category_data(data['category_data'])
    if 'double_rate_category_data' in data:
        stat.set_double_rate_category_data(data['double_rate_category_data'])
    stat.updated_at = datetime.utcnow()
    stat.updated_by = current_user.id

    db.session.commit()
    return jsonify(stat.to_dict()), 200


@app.route('/api/general-stats/<int:stat_id>/use-scan', methods=['POST'])
@admin_required
def api_general_stat_use_scan(stat_id):
    """Swiadome przelaczenie linii z ilosci recznych na sume skanow.

    Linia z recznymi ilosciami nie przelacza sie sama (patrz recompute_general_stat),
    zeby pierwszy zeskanowany karton nie zastapil calego rozliczenia. Tu admin
    potwierdza zamiane — po niej `category_data` jest suma skanow tej grupy.
    """
    stat = db.get_or_404(GeneralStat, stat_id)
    stat.category_source = 'scan'
    stat.set_category_data(
        scan_category_totals(stat.list_id, stat.country_ledger, stat.loading_date))
    stat.updated_at = datetime.utcnow()
    stat.updated_by = current_user.id
    db.session.commit()
    return jsonify(stat.to_dict()), 200


@app.route('/dashboard')
@leader_required
def dashboard():
    return render_template('dashboard.html')


@app.route('/api/dashboard')
@leader_required
def api_dashboard():
    today = local_today()
    today_start, today_end = local_day_bounds(today)

    # Paczki — ogólne (przetworzona = ZAKOŃCZONA, scan_end)
    total_cartons = ImportedCarton.query.count()
    done_cartons = ImportedCarton.query.filter(ImportedCarton.scan_end_at.isnot(None)).count()
    remaining_cartons = total_cartons - done_cartons
    # Te same paczki co `remaining_cartons`, liczone w sztukach — lider planuje
    # obsade po ilosci towaru, a paczki potrafia miec od 1 do kilkuset sztuk.
    remaining_pieces = db.session.query(func.sum(ImportedCarton.stueckzahl))\
        .filter(ImportedCarton.scan_end_at.is_(None)).scalar() or 0

    # ❗ Paczki z roznica w tabeli ilosci, ktorej lider jeszcze nie potwierdzil
    # (wszystkie dni — zalegle potwierdzenie nie znika o polnocy).
    do_potwierdzenia = ImportedCarton.query.filter(
        ImportedCarton.roznica.is_(True),
        ImportedCarton.roznica_potwierdzona_at.is_(None)).count()

    # Paczki zakończone dziś
    dzis = and_(ImportedCarton.scan_end_at >= today_start,
                ImportedCarton.scan_end_at < today_end)
    done_today = ImportedCarton.query.filter(dzis).count()
    pieces_today = db.session.query(func.sum(ImportedCarton.stueckzahl))\
        .filter(dzis).scalar() or 0

    # Breakdown per pracownik — dziś. Paczka wielu osob liczy sie kazdej z nich
    # (jej udzial i jej wpisane ilosci) — `prace_osob()`.
    praca_dzis = prace_osob(today, today)
    nazwy = {u.id: u.display_name for u in User.query.filter(
        User.id.in_(list(praca_dzis))).all()} if praca_dzis else {}
    workers_today = sorted((
        {'user_id': uid, 'name': nazwy.get(uid, '?'),
         'packages': len(p), 'pieces': int(sum(x[2] for x in p))}
        for uid, p in praca_dzis.items()
    ), key=lambda w: w['packages'], reverse=True)

    # Obecni na zmianach dziś
    shift1 = Shift.query.filter_by(date=today, shift_number=1).first()
    shift2 = Shift.query.filter_by(date=today, shift_number=2).first()
    present_ids = set()
    if shift1:
        present_ids |= {a.user_id for a in ShiftAttendance.query.filter_by(shift_id=shift1.id).all()}
    if shift2:
        present_ids |= {a.user_id for a in ShiftAttendance.query.filter_by(shift_id=shift2.id).all()}

    # DailyStat dziś — per czynność (sumy)
    daily_rows = db.session.query(
        DailyStat.activity_id,
        func.sum(DailyStat.quantity).label('total_qty'),
    ).join(Shift).filter(Shift.date == today).group_by(DailyStat.activity_id).all()

    act_map = {a.id: a.name for a in Activity.query.all()}
    activities_today = [
        {'activity': act_map.get(r.activity_id, '?'), 'total_qty': int(r.total_qty or 0)}
        for r in sorted(daily_rows, key=lambda r: r.total_qty or 0, reverse=True)
    ]

    # Per pracownik na zmianie — paczki + DailyStat
    pkg_by_user = {w['user_id']: {'packages': w['packages'], 'pieces': w['pieces']}
                   for w in workers_today}

    daily_per_user = db.session.query(
        DailyStat.user_id,
        DailyStat.activity_id,
        func.sum(DailyStat.quantity).label('qty'),
    ).join(Shift).filter(Shift.date == today).group_by(DailyStat.user_id, DailyStat.activity_id).all()

    stat_by_user = {}
    for r in daily_per_user:
        stat_by_user.setdefault(r.user_id, []).append(
            {'activity': act_map.get(r.activity_id, '?'), 'qty': int(r.qty or 0)}
        )

    # Widoczni: obecni na zmianie LUB ci, którzy dziś zakończyli paczki (nic nie chowamy)
    relevant_ids = present_ids | set(pkg_by_user.keys())
    present_users = User.query.filter(User.id.in_(relevant_ids)).order_by(User.display_name).all() \
        if relevant_ids else []

    per_worker = []
    for u in present_users:
        pkg = pkg_by_user.get(u.id, {'packages': 0, 'pieces': 0})
        per_worker.append({
            'id': u.id,
            'name': u.display_name,
            'packages_today': pkg['packages'],
            'pieces_today': pkg['pieces'],
            'activities': sorted(stat_by_user.get(u.id, []), key=lambda x: x['qty'], reverse=True),
        })

    progress_pct = round(done_cartons / total_cartons * 100, 1) if total_cartons else 0

    return jsonify({
        'total_cartons': total_cartons,
        'done_cartons': done_cartons,
        'remaining_cartons': remaining_cartons,
        'remaining_pieces': int(remaining_pieces),
        'done_today': done_today,
        'pieces_today': int(pieces_today),
        'do_potwierdzenia': do_potwierdzenia,
        'progress_pct': progress_pct,
        'present_count': len(present_ids),
        'workers_today': workers_today,
        'activities_today': activities_today,
        'per_worker': per_worker,
        # Plan dnia dla dzisiejszego pliku i zalegle (niezrobione) per data pliku.
        'plik_dzis': plan_dnia_pliku(today),
        'zalegle': zalegle_wg_daty_pliku(),
        'as_of': datetime.now(LOCAL_TZ).strftime('%H:%M:%S'),
    })


def _agregaty_planu():
    """Kolumny planu pliku: paczek, sztuk, zrobione, zrobione szt., w toku.
    Jedna definicja dla jednego dnia (Dzis / Wybrany dzien) i zakresu (Per Loading date)."""
    zrobiona = ImportedCarton.scan_end_at.isnot(None)
    # W toku = ktos przy niej pracuje albo czeka na dokonczenie po poprzedniej osobie.
    w_toku = and_(ImportedCarton.scan_end_at.is_(None),
                  or_(ImportedCarton.scan_start_at.isnot(None), ImportedCarton.udzialy.any()))
    return (
        func.count(ImportedCarton.id),
        func.coalesce(func.sum(ImportedCarton.stueckzahl), 0),
        func.count(ImportedCarton.scan_end_at),
        func.coalesce(func.sum(case((zrobiona, ImportedCarton.stueckzahl), else_=0)), 0),
        func.coalesce(func.sum(case((w_toku, 1), else_=0)), 0),
    )


def _wiersz_planu(dzien, wartosci):
    paczek, sztuk, zrob, zrob_szt, toku = (int(x or 0) for x in wartosci)
    return {
        'data_pliku': dzien.isoformat(),
        'paczek': paczek, 'sztuk': sztuk,
        'zrobione': zrob, 'zrobione_sztuk': zrob_szt,
        'w_toku': toku,
        'pozostalo': paczek - zrob, 'pozostalo_sztuk': sztuk - zrob_szt,
        'procent': round(zrob / paczek * 100, 1) if paczek else 0,
    }


def plan_dnia_pliku(dzien):
    """Paczki z plikow danego dnia (data pliku): wrzucone / zrobione / w toku /
    pozostalo, w paczkach i sztukach.

    „Zrobione" = karton tego pliku z `scan_end_at` — niezaleznie od tego, KIEDY
    go skonczono. To co innego niz „zakonczone dzis" (po czasie skanu): plik z
    poniedzialku konczony we wtorek liczy sie do poniedzialku.
    """
    w = db.session.query(*_agregaty_planu()).filter(ImportedCarton.data_pliku == dzien).one()
    return _wiersz_planu(dzien, w)


MAX_DNI_ZAKRESU_DASHBOARDU = 366


def plany_dni_pliku(od, do):
    """Plan pliku (jak `plan_dnia_pliku`) dla kazdej daty pliku z [od, do] —
    zakladka „Per Loading date". Tylko dni, w ktorych cos wrzucono; najnowsze
    najpierw. `suma` = te same pola dla calego zakresu."""
    wiersze = db.session.query(ImportedCarton.data_pliku, *_agregaty_planu())\
        .filter(ImportedCarton.data_pliku >= od, ImportedCarton.data_pliku <= do)\
        .group_by(ImportedCarton.data_pliku)\
        .order_by(ImportedCarton.data_pliku.desc()).all()
    dni = [_wiersz_planu(w[0], w[1:]) for w in wiersze]
    pola = ('paczek', 'sztuk', 'zrobione', 'zrobione_sztuk', 'w_toku')
    suma = _wiersz_planu(od, [sum(d[p] for d in dni) for p in pola])
    del suma['data_pliku']
    return {'date_from': od.isoformat(), 'date_to': do.isoformat(), 'dni': dni, 'suma': suma}


def zalegle_wg_daty_pliku(od=None, do=None):
    """Wszystkie niezrobione paczki (scan_end_at IS NULL) per data pliku,
    najstarsze najpierw — Podsumowanie Dashboardu. `od`/`do` (opcjonalne)
    zawezaja do dat pliku z zakresu; przy filtrze paczki bez daty pliku odpadaja."""
    q = db.session.query(
        ImportedCarton.data_pliku,
        func.count(ImportedCarton.id),
        func.coalesce(func.sum(ImportedCarton.stueckzahl), 0),
        func.coalesce(func.sum(case((ImportedCarton.scan_start_at.isnot(None), 1), else_=0)), 0),
    ).filter(ImportedCarton.scan_end_at.is_(None))
    if od:
        q = q.filter(ImportedCarton.data_pliku >= od)
    if do:
        q = q.filter(ImportedCarton.data_pliku <= do)
    wiersze = q.group_by(ImportedCarton.data_pliku)\
               .order_by(ImportedCarton.data_pliku.asc().nullsfirst()).all()
    dni = [{'data_pliku': d.isoformat() if d else None, 'paczek': int(n), 'sztuk': int(szt or 0),
            'w_toku': int(t or 0)} for d, n, szt, t in wiersze]
    return {'paczek': sum(x['paczek'] for x in dni), 'sztuk': sum(x['sztuk'] for x in dni), 'dni': dni}


@app.route('/api/dashboard/plik')
@leader_required
def api_dashboard_plik():
    """Plan dnia dla wybranej daty pliku (`?date=`, domyslnie dzis)."""
    return jsonify(plan_dnia_pliku(parse_date(request.args.get('date'))))


@app.route('/api/dashboard/zalegle')
@leader_required
def api_dashboard_zalegle():
    """Podsumowanie (niezrobione per data pliku) z opcjonalnym zakresem
    `date_from` / `date_to` po dacie pliku. Puste = wszystkie dni."""
    od_s, do_s = request.args.get('date_from', ''), request.args.get('date_to', '')
    od = parse_date(od_s, 'date_from') if od_s else None
    do = parse_date(do_s, 'date_to') if do_s else None
    if od and do and od > do:
        abort(400, 'Data „od" jest późniejsza niż „do".')
    return jsonify(zalegle_wg_daty_pliku(od, do))


@app.route('/api/dashboard/loading-dates')
@leader_required
def api_dashboard_loading_dates():
    """Zakladka „Per Loading date": plan pliku per data pliku z zakresu.
    Bez dat — biezacy miesiac do dzis."""
    dzis = local_today()
    od_s, do_s = request.args.get('date_from', ''), request.args.get('date_to', '')
    od = parse_date(od_s, 'date_from') if od_s else dzis.replace(day=1)
    do = parse_date(do_s, 'date_to') if do_s else dzis
    if od > do:
        abort(400, 'Data „od" jest późniejsza niż „do".')
    if (do - od).days >= MAX_DNI_ZAKRESU_DASHBOARDU:
        abort(400, f'Zakres może mieć najwyżej {MAX_DNI_ZAKRESU_DASHBOARDU} dni.')
    return jsonify(plany_dni_pliku(od, do))


@app.route('/api/dashboard/shifts')
@leader_required
def api_dashboard_shifts():
    """Per-shift daily breakdown for a chosen date.

    DailyStat is already shift-tagged (shift_id) → aggregated directly.
    Packages (ImportedCarton) have no shift, so they are attributed by
    ATTENDANCE: a package finished by a worker counts toward the single shift
    that worker was scanned into that day. Workers with no attendance (or in
    both shifts → ambiguous) land in the 'unattributed' bucket so nothing is
    silently dropped and totals stay exact (each package counted once).
    """
    date_str = request.args.get('date', '')
    try:
        target = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else local_today()
    except ValueError:
        target = local_today()

    act_map = {a.id: a.name for a in Activity.query.all()}
    user_map = {u.id: u.display_name for u in User.query.all()}

    # Shifts that day + attendance (user_id -> set of shift_numbers attended)
    shifts = {s.shift_number: s for s in Shift.query.filter_by(date=target).all()}
    user_shifts = {}
    for snum, sh in shifts.items():
        for a in ShiftAttendance.query.filter_by(shift_id=sh.id).all():
            user_shifts.setdefault(a.user_id, set()).add(snum)

    # Praca tego dnia per osoba (`prace_osob()`): paczka jednej osoby raz,
    # paczka wielu osob — udzial kazdej z nich, wiec kazda trafia do swojej zmiany.
    pkg_rows = [SimpleNamespace(user_id=uid, packages=len(p), pieces=sum(x[2] for x in p))
                for uid, p in prace_osob(target, target).items()]

    per_shift_pkg = {1: {'packages': 0, 'pieces': 0}, 2: {'packages': 0, 'pieces': 0}}
    unattributed = {'packages': 0, 'pieces': 0, 'workers': []}

    for r in pkg_rows:
        attended = user_shifts.get(r.user_id, set())
        pkgs, pcs = int(r.packages), int(r.pieces or 0)
        if len(attended) == 1:
            snum = next(iter(attended))
            per_shift_pkg[snum]['packages'] += pkgs
            per_shift_pkg[snum]['pieces'] += pcs
        else:
            unattributed['packages'] += pkgs
            unattributed['pieces'] += pcs
            unattributed['workers'].append({
                'user_id': r.user_id,
                'name': user_map.get(r.user_id, '?'),
                'packages': pkgs, 'pieces': pcs,
                'reason': 'brak obecności' if not attended else 'obie zmiany',
            })

    # DailyStat per shift + activity (direct via shift_id)
    ds_rows = db.session.query(
        Shift.shift_number,
        DailyStat.activity_id,
        func.sum(DailyStat.quantity).label('qty'),
    ).join(Shift, DailyStat.shift_id == Shift.id)\
     .filter(Shift.date == target)\
     .group_by(Shift.shift_number, DailyStat.activity_id).all()

    per_shift_acts = {1: [], 2: []}
    for r in ds_rows:
        per_shift_acts.setdefault(r.shift_number, []).append(
            {'activity': act_map.get(r.activity_id, '?'), 'qty': int(r.qty or 0)}
        )

    result_shifts = []
    for snum in (1, 2):
        sh = shifts.get(snum)
        present = ShiftAttendance.query.filter_by(shift_id=sh.id).count() if sh else 0
        result_shifts.append({
            'shift_number': snum,
            'exists': sh is not None,
            'present_count': present,
            'packages': per_shift_pkg[snum]['packages'],
            'pieces': per_shift_pkg[snum]['pieces'],
            'activities': sorted(per_shift_acts.get(snum, []), key=lambda x: x['qty'], reverse=True),
        })

    return jsonify({
        'date': target.isoformat(),
        'shifts': result_shifts,
        'unattributed': unattributed,
    })


@app.route('/scan-package')
@leader_required
def scan_package():
    return render_template('scan_package.html')


@app.route('/api/employee-lookup', methods=['GET'])
@leader_required
def api_employee_lookup():
    """Krok 1 na /scan-paczki — sprawdza kod pracownika ZANIM pojdzie dalej.

    Wczesniej zly kod wychodzil dopiero przy zapisie konca, juz po wpisaniu
    ilosci — formularz sie czyscil, ilosci przepadaly, a paczka zostawala
    otwarta (dwie takie wisza od 14.09).
    """
    barcode = (request.args.get('barcode') or '').strip()
    if not barcode:
        return jsonify({'error': 'Brak kodu pracownika.'}), 400

    user = User.query.filter_by(barcode_id=barcode, is_active_user=True).first()
    if not user:
        if ImportedCarton.query.filter_by(barcode=barcode).first():
            return jsonify({'error': 'To jest kod paczki, nie pracownika — '
                                     'najpierw zeskanuj identyfikator.'}), 400
        return jsonify({'error': 'Nieznany kod pracownika.'}), 404
    return jsonify({'user': {'id': user.id, 'display_name': user.display_name}}), 200


@app.route('/api/package-lookup', methods=['GET'])
@leader_required
def api_package_lookup():
    """Read-only lookup: sprawdza status paczki (przeskanowana / kto / zakończona) + dane."""
    barcode = (request.args.get('barcode') or '').strip()
    if not barcode:
        return jsonify({'error': 'Brak kodu paczki.'}), 400

    carton = ImportedCarton.query.filter_by(barcode=barcode).first()
    if not carton:
        return blad_nieznanej_paczki(
            barcode, 'Nieznany kod paczki. Upewnij się, że paczka została zaimportowana.')

    d = carton.to_dict()
    # Derived status: przeskanowana = przypisana LUB rozpoczęto pomiar czasu
    # Przekazana do dokonczenia nie ma startu, ale ktos juz przy niej pracowal.
    d['scanned'] = bool(carton.processed_by) or bool(carton.scan_start_at) or bool(carton.udzialy)
    d['scanned_by'] = (d.get('processed_by_name') or d.get('scan_start_by_name')
                       or (d['udzialy'][0]['user_name'] if d['udzialy'] else None))
    d['finished'] = bool(carton.scan_end_at)
    return jsonify({'carton': d}), 200


@app.route('/api/packages', methods=['POST'])
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


@app.route('/api/packages/<int:carton_id>', methods=['PUT'])
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
    carton.modified_at = datetime.utcnow()
    carton.modified_by = current_user.id

    new_group = klucz_linii(carton)

    try:
        db.session.flush()  # push the carton UPDATE so recompute SUMs see new values / catch collision
        recompute_general_stat(*old_group, actor_id=current_user.id)
        if new_group != old_group:
            recompute_general_stat(*new_group, actor_id=current_user.id)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': f'Paczka o barcode "{barcode}" już istnieje.'}), 409

    return jsonify({'message': f'Zapisano paczkę {barcode}.', 'carton': carton.to_dict()}), 200


@app.route('/api/packages/<int:carton_id>/assign', methods=['PUT'])
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
        carton.processed_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'carton': carton.to_dict()}), 200


@app.route('/api/packages/<int:carton_id>/double-rate', methods=['PUT'])
@leader_required
def api_package_double_rate(carton_id):
    carton = db.get_or_404(ImportedCarton, carton_id)
    data = json_body()
    carton.double_rate = bool(data.get('double_rate'))
    db.session.commit()
    return jsonify({'carton': carton.to_dict()}), 200


# ══════════════════════════════════════════════════════════════════════════════
#  PACKAGE SCAN TIMES & DOUBLE RATE
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/scan-paczki')
@leader_required
def scan_paczki():
    return render_template('scan_paczki.html')


def parse_scan_categories(surowe):
    """Waliduje ilosci per kategoria. Zwraca (dict, komunikat_bledu).

    Suma NIE jest porownywana ze `stueckzahl` — rozbieznosc miedzy deklaracja
    a zawartoscia paczki jest normalna i nie moze blokowac pracy.
    """
    if surowe is None:
        return {}, None
    if not isinstance(surowe, dict):
        return None, 'Nieprawidłowy format ilości.'
    wynik = {}
    for kat, wartosc in surowe.items():
        if kat not in STAT_CATEGORIES:
            return None, f'Nieznana kategoria: {kat}.'
        try:
            ile = int(wartosc)
        except (TypeError, ValueError):
            return None, f'Ilość dla „{etykieta_kategorii(kat)}" musi być liczbą.'
        if ile < 0:
            return None, f'Ilość dla „{etykieta_kategorii(kat)}" nie może być ujemna.'
        if ile:
            wynik[kat] = ile
    return wynik, None


def tabela_z_body(data, carton, oczekiwany_tryb):
    """(tabela, odpowiedz_bledu) z `tabela` + `tryb` w body stanowiska.

    Tryb wybiera ekran przy otwarciu panelu (z `tryb_tabeli` paczki). Gdy
    w miedzyczasie ktos dolaczyl, tabela ma inny ksztalt — 409, panel od nowa.
    """
    if data.get('tryb') != oczekiwany_tryb:
        return None, (jsonify({
            'error': 'Przy paczce zmienił się skład osób (ktoś dołączył albo przekazał paczkę). '
                     'Zeskanuj paczkę jeszcze raz i wpisz ilości od nowa.',
            'zmiana_trybu': True}), 409)
    tabela, blad = normalizuj_tabele(data.get('tabela'), oczekiwany_tryb, carton.stueckzahl)
    if blad:
        return None, (jsonify({'error': blad}), 400)
    return tabela, None


def pracownik_i_paczka_z_body():
    """Wspolne wejscie stanowiska: (user, carton zablokowany FOR UPDATE) albo odpowiedz bledu."""
    data = json_body()
    employee_barcode = (data.get('employee_barcode') or '').strip()
    package_barcode = (data.get('package_barcode') or '').strip()
    if not employee_barcode:
        return data, None, None, (jsonify({'error': 'Brak kodu pracownika.'}), 400)
    if not package_barcode:
        return data, None, None, (jsonify({'error': 'Brak kodu paczki.'}), 400)
    user = User.query.filter_by(barcode_id=employee_barcode, is_active_user=True).first()
    if not user:
        return data, None, None, (jsonify({'error': 'Nieznany kod pracownika.'}), 404)
    carton = (ImportedCarton.query.filter_by(barcode=package_barcode)
              .with_for_update().first())
    if not carton:
        return data, user, None, blad_nieznanej_paczki(package_barcode)
    return data, user, carton, None


def blad_wlasciciela(carton):
    starter = db.session.get(User, carton.scan_start_by) if carton.scan_start_by else None
    return jsonify({
        'error': f'Paczkę rozpoczął {starter.display_name if starter else "inny pracownik"} — tylko on może ją zakończyć.'
    }), 403


@app.route('/api/package-time/przekaz', methods=['POST'])
@leader_required
def api_package_time_przekaz():
    """„Paczka do dokonczenia": koniec zmiany — pracownik wpisuje, co przerobil,
    a paczka NIE jest zamykana. Start zostaje zdjety, wiec nastepna osoba wbija
    zwykly Start i konczy paczke standardowo (2026-10-13)."""
    data, user, carton, blad = pracownik_i_paczka_z_body()
    if blad:
        return blad
    if carton.scan_end_at:
        return jsonify({'error': 'Paczka jest już zakończona.'}), 409
    if not carton.scan_start_at:
        return jsonify({'error': 'Paczka nie jest rozpoczęta — nie ma czego przekazać.'}), 400

    otwarte = otwarte_udzialy(carton)
    moj = next((u for u in otwarte if u.user_id == user.id), None)
    if otwarte:
        if not moj:
            return jsonify({'error': f'Nie pracujesz przy tej paczce (pracują: {lista_osob(otwarte)}).'}), 403
        inni = [u for u in otwarte if u is not moj]
        if inni:
            return jsonify({'error': f'Przy paczce pracują jeszcze: {lista_osob(inni)}. Wbij zwykły '
                                     '„Koniec paczki" — zamknie tylko Twój udział, paczkę dokończy zespół.'}), 409
    elif carton.scan_start_by != user.id:
        return blad_wlasciciela(carton)

    tabela = None
    if 'tabela' in data:
        tabela, blad = tabela_z_body(data, carton, TRYB_ZESPOL)
        if blad:
            return blad
    else:
        # Stary formularz kategorii — karta stanowiska otwarta przed wdrozeniem.
        kategorie, blad = parse_scan_categories(data.get('categories'))
        if blad:
            return jsonify({'error': blad}), 400

    teraz = datetime.utcnow()
    if not moj:
        moj = UdzialPaczki(carton=carton, user_id=user.id, rodzaj=UDZIAL_PRZEKAZANA,
                           start_at=carton.scan_start_at)
        db.session.add(moj)
    moj.end_at = teraz
    if tabela:
        moj.set_tabela(tabela)
    else:
        moj.set_ilosci(kategorie)
    carton.scan_start_at = None
    carton.scan_start_by = None
    przelicz_ilosci_udzialow(carton, user.id)
    db.session.commit()

    return jsonify({
        'message': f'Paczka {carton.barcode} czeka na dokończenie — wpisano {moj.sztuki()} szt. '
                   'Następna osoba wbija zwykły „Start paczki".',
        'carton': carton.to_dict()
    }), 200


@app.route('/api/package-time/dolacz', methods=['POST'])
@leader_required
def api_package_time_dolacz():
    """„Pakowanie zespolowe": druga/trzecia osoba dolacza do paczki juz
    rozpoczetej. Koniec wbija kazdy sam (zakladka Koniec) ze swoimi iloscami."""
    data, user, carton, blad = pracownik_i_paczka_z_body()
    if blad:
        return blad
    if carton.scan_end_at:
        return jsonify({'error': 'Paczka jest już zakończona.'}), 409
    if not carton.scan_start_at:
        return jsonify({'error': 'Paczka nie jest rozpoczęta — pierwsza osoba wbija „Start paczki".'}), 400

    otwarte = otwarte_udzialy(carton)
    if any(u.user_id == user.id for u in otwarte) or (not otwarte and carton.scan_start_by == user.id):
        return jsonify({'message': f'Już pracujesz przy paczce {carton.barcode}.',
                        'carton': carton.to_dict()}), 200

    teraz = datetime.utcnow()
    # Pierwsze dolaczenie: osoba, ktora zaczela, tez dostaje udzial — od swojego
    # startu. Tylko jesli nie ma JUZ wiersza z tego startu: gdy zaczynajaca
    # skonczyla swoja czesc (wiersz zamkniety), drugi wiersz od tego samego
    # startu bylby otwartym udzialem osoby, ktora poszla do domu.
    if carton.scan_start_by and not any(
            u.user_id == carton.scan_start_by and u.start_at == carton.scan_start_at
            for u in carton.udzialy):
        db.session.add(UdzialPaczki(carton=carton, user_id=carton.scan_start_by,
                                    rodzaj=UDZIAL_ZESPOL, start_at=carton.scan_start_at))
    db.session.add(UdzialPaczki(carton=carton, user_id=user.id, rodzaj=UDZIAL_ZESPOL, start_at=teraz))
    db.session.commit()

    return jsonify({
        'message': f'Dołączono do paczki {carton.barcode} — pracują: {lista_osob(otwarte_udzialy(carton))}. '
                   'Koniec każdy wbija sam w zakładce „Koniec paczki".',
        'carton': carton.to_dict()
    }), 200


def koniec_udzialu(carton, user, kategorie, zamknij_wszystkich, tabela=None):
    """Koniec paczki wielu osob: zamyka udzial tej osoby; paczka konczy sie,
    gdy nie zostal nikt otwarty (albo „zamknij dla wszystkich")."""
    otwarte = otwarte_udzialy(carton)
    moj = next((u for u in otwarte if u.user_id == user.id), None)
    if otwarte and not moj:
        return jsonify({'error': f'Nie pracujesz przy tej paczce (pracują: {lista_osob(otwarte)}).'}), 403
    if not otwarte:
        # Po przekazaniu: osoba, ktora wbila Start, nie ma jeszcze wiersza.
        if carton.scan_start_by != user.id:
            return blad_wlasciciela(carton)
        moj = UdzialPaczki(carton=carton, user_id=user.id, rodzaj=UDZIAL_PRZEKAZANA,
                           start_at=carton.scan_start_at)
        db.session.add(moj)

    teraz = datetime.utcnow()
    moj.end_at = teraz
    if tabela:
        moj.set_tabela(tabela)
    else:
        moj.set_ilosci(kategorie)
    if zamknij_wszystkich:
        for u in otwarte_udzialy(carton):
            u.end_at = teraz
            u.zamkniete_przez = user.id
    pozostali = otwarte_udzialy(carton)
    if not pozostali:
        zamknij_paczke_wielu_osob(carton, user.id, teraz)
    przelicz_ilosci_udzialow(carton, user.id)
    db.session.commit()

    if pozostali:
        msg = (f'Zakończono Twój udział ({moj.sztuki()} szt.). Przy paczce pracują jeszcze: '
               f'{lista_osob(pozostali)} — paczka zamknie się po ich końcu.')
    else:
        secs = carton.processing_seconds() or 0
        msg = f'Koniec zarejestrowany — paczka zamknięta, czas procesowania: {secs // 60}m {secs % 60}s.'
    return jsonify({'message': msg, 'zamknieta': not pozostali, 'carton': carton.to_dict()}), 200


@app.route('/api/packages/<int:carton_id>/zamknij-zespol', methods=['POST'])
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

    teraz = datetime.utcnow()
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


@app.route('/api/package-time/start', methods=['POST'])
@leader_required
def api_package_time_start():
    data = json_body()
    employee_barcode = (data.get('employee_barcode') or '').strip()
    package_barcode = (data.get('package_barcode') or '').strip()

    if not employee_barcode:
        return jsonify({'error': 'Brak kodu pracownika.'}), 400
    if not package_barcode:
        return jsonify({'error': 'Brak kodu paczki.'}), 400

    user = User.query.filter_by(barcode_id=employee_barcode, is_active_user=True).first()
    if not user:
        return jsonify({'error': 'Nieznany kod pracownika.'}), 404

    # FOR UPDATE: sprawdzenie stanu i zapis musza byc atomowe. Bez blokady dwa
    # rownolegle zadania (podwojny Enter, dwa stanowiska) oba przechodzily
    # kontrole — na .31 15.09 ta sama paczka dostala dwa „koniec" z 200.
    carton = (ImportedCarton.query.filter_by(barcode=package_barcode)
              .with_for_update().first())
    if not carton:
        return blad_nieznanej_paczki(package_barcode)

    # Paczka już zakończona — nie można jej rozpocząć ponownie
    if carton.scan_end_at:
        return jsonify({'error': 'Paczka jest już zakończona — nie można jej rozpocząć ponownie.'}), 409

    # Paczka w trakcie (start bez końca) — tylko pracownik, który zaczął, nią zarządza
    if carton.scan_start_at:
        if carton.scan_start_by == user.id:
            return jsonify({
                'message': f'Paczka {package_barcode} już rozpoczęta przez Ciebie — start bez zmian.',
                'carton': carton.to_dict()
            }), 200
        if any(u.user_id == user.id for u in otwarte_udzialy(carton)):
            return jsonify({
                'message': f'Pracujesz już przy paczce {package_barcode} (zespół) — start bez zmian.',
                'carton': carton.to_dict()
            }), 200
        starter = db.session.get(User, carton.scan_start_by) if carton.scan_start_by else None
        return jsonify({
            'error': f'Paczka już rozpoczęta przez {starter.display_name if starter else "innego pracownika"}. '
                     'Nie można jej podebrać — żeby pracować razem, użyj zakładki „Pakowanie zespołowe".'
        }), 409

    # Świeży start (paczka nierozpoczęta albo czekajaca na dokonczenie)
    dokonczenie = carton.do_dokonczenia()
    carton.scan_start_at = datetime.utcnow()
    carton.scan_start_by = user.id
    db.session.commit()

    po_kim = ''
    if dokonczenie:
        po_kim = f' Dokończenie po: {lista_osob(carton.udzialy)} (wpisano {sum(u.sztuki() for u in carton.udzialy)} szt.).'
    return jsonify({
        'message': f'Start zarejestrowany dla paczki {package_barcode} — {user.display_name}.{po_kim}',
        'carton': carton.to_dict()
    }), 200


@app.route('/api/package-time/end', methods=['POST'])
@leader_required
def api_package_time_end():
    data = json_body()
    employee_barcode = (data.get('employee_barcode') or '').strip()
    package_barcode = (data.get('package_barcode') or '').strip()

    if not employee_barcode:
        return jsonify({'error': 'Brak kodu pracownika.'}), 400
    if not package_barcode:
        return jsonify({'error': 'Brak kodu paczki.'}), 400

    user = User.query.filter_by(barcode_id=employee_barcode, is_active_user=True).first()
    if not user:
        return jsonify({'error': 'Nieznany kod pracownika.'}), 404

    # FOR UPDATE — patrz api_package_time_start.
    carton = (ImportedCarton.query.filter_by(barcode=package_barcode)
              .with_for_update().first())
    if not carton:
        return blad_nieznanej_paczki(package_barcode)

    if not carton.scan_start_at:
        return jsonify({'error': 'Brak zarejestrowanego startu dla tej paczki.'}), 400

    if carton.scan_end_at:
        return jsonify({'error': 'Paczka jest już zakończona.'}), 409

    if carton.udzialy:
        if 'tabela' in data:
            tabela, blad = tabela_z_body(data, carton, TRYB_ZESPOL)
            if blad:
                return blad
            return koniec_udzialu(carton, user, None, bool(data.get('zamknij_wszystkich')),
                                  tabela=tabela)
        kategorie, blad = parse_scan_categories(data.get('categories'))
        if blad:
            return jsonify({'error': blad}), 400
        return koniec_udzialu(carton, user, kategorie, bool(data.get('zamknij_wszystkich')))

    # Tylko pracownik, który rozpoczął paczkę, może ją zakończyć
    if carton.scan_start_by and carton.scan_start_by != user.id:
        starter = db.session.get(User, carton.scan_start_by)
        return jsonify({
            'error': f'Paczkę rozpoczął {starter.display_name if starter else "inny pracownik"} — tylko on może ją zakończyć.'
        }), 403

    tabela = None
    if 'tabela' in data:
        tabela, blad = tabela_z_body(data, carton, TRYB_WZOR)
        if blad:
            return blad
    else:
        # Stary formularz kategorii (karta otwarta przed wdrozeniem tabeli).
        kategorie, blad = parse_scan_categories(data.get('categories'))
        if blad:
            return jsonify({'error': blad}), 400

    carton.scan_end_at = datetime.utcnow()
    carton.scan_end_by = user.id
    if tabela:
        zapisz_tabele_kartonu(carton, tabela, user.id)
    elif kategorie:
        carton.set_scan_categories(kategorie)
        # Ilosci ze skanu staja sie zrodlem rozliczenia tej linii.
        recompute_general_stat(*klucz_linii(carton),
                               actor_id=user.id, from_scan=True)
    db.session.commit()

    secs = carton.processing_seconds()
    mins, s = divmod(secs, 60)
    time_str = f'{mins}m {s}s'

    return jsonify({
        'message': f'Koniec zarejestrowany — czas procesowania: {time_str}.',
        'carton': carton.to_dict()
    }), 200


@app.route('/api/packages/<int:carton_id>/categories', methods=['PUT'])
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
    carton.modified_at = datetime.utcnow()
    carton.modified_by = current_user.id
    recompute_general_stat(*klucz_linii(carton),
                           actor_id=current_user.id, from_scan=True)
    db.session.commit()
    return jsonify(carton.to_dict()), 200


@app.route('/api/packages/<int:carton_id>/tabela', methods=['PUT'])
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

    teraz = datetime.utcnow()
    carton.modified_at = teraz
    carton.modified_by = current_user.id
    if carton.roznica:
        carton.roznica_potwierdzona_at = teraz
        carton.roznica_potwierdzona_przez = current_user.id
    db.session.commit()
    return jsonify(carton.to_dict()), 200


@app.route('/api/packages/<int:carton_id>/potwierdz-roznice', methods=['POST'])
@leader_required
def api_package_potwierdz_roznice(carton_id):
    """Lider potwierdza ❗ (rozmowa z pracownikiem / przeliczenie kartonu)."""
    carton = db.get_or_404(ImportedCarton, carton_id)
    if not carton.roznica:
        abort(400, 'Ta paczka nie ma różnicy do potwierdzenia.')
    if carton.roznica_potwierdzona_at:
        return jsonify(carton.to_dict()), 200
    carton.roznica_potwierdzona_at = datetime.utcnow()
    carton.roznica_potwierdzona_przez = current_user.id
    db.session.commit()
    return jsonify(carton.to_dict()), 200


@app.route('/api/packages/<int:carton_id>/unlock-scan', methods=['POST'])
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
    carton.modified_at = datetime.utcnow()
    carton.modified_by = current_user.id
    db.session.commit()

    kto = poprzedni.display_name if poprzedni else 'nieznany pracownik'
    return jsonify({
        'message': f'Paczka {carton.barcode} odblokowana (była u: {kto}).',
        'carton': carton.to_dict()
    }), 200


# ══════════════════════════════════════════════════════════════════════════════
#  TIME TRACKING
# ══════════════════════════════════════════════════════════════════════════════

def _compute_worker_times(uid, shift, attendance_time):
    """Return break/work summary for one worker-shift pair."""
    events = WorkerTimeEvent.query.filter_by(
        user_id=uid, shift_id=shift.id
    ).order_by(WorkerTimeEvent.timestamp).all()

    break_secs = 0
    other_secs = 0
    training_secs = 0
    trainee_secs = 0
    open_break = None
    open_other = None
    open_training = None
    open_trainee = None
    work_end_ts = None
    breaks = []
    others = []
    trainings = []
    trainee_periods = []
    okresy = []          # (start, koniec) wszystkich zamknietych przerw i „Innych"

    for e in events:
        if e.event_type == 'break_start':
            open_break = e.timestamp
        elif e.event_type == 'break_end' and open_break:
            secs = (e.timestamp - open_break).total_seconds()
            breaks.append({'start': iso_z(open_break), 'end': iso_z(e.timestamp),
                           'minutes': int(secs / 60)})
            break_secs += secs
            okresy.append((open_break, e.timestamp))
            open_break = None
        elif e.event_type == 'other_start':
            open_other = e.timestamp
        elif e.event_type == 'other_end' and open_other:
            secs = (e.timestamp - open_other).total_seconds()
            others.append({'start': iso_z(open_other), 'end': iso_z(e.timestamp),
                           'minutes': int(secs / 60)})
            other_secs += secs
            okresy.append((open_other, e.timestamp))
            open_other = None
        elif e.event_type == 'training_start':
            open_training = e.timestamp
        elif e.event_type == 'training_end' and open_training:
            # Szkolenie to praca — NIE trafia do `okresy`, wiec nie pomniejsza
            # czasu pracy; raportujemy je tylko osobno.
            secs = (e.timestamp - open_training).total_seconds()
            trainings.append({'start': iso_z(open_training), 'end': iso_z(e.timestamp),
                              'minutes': int(secs / 60)})
            training_secs += secs
            open_training = None
        elif e.event_type == 'trainee_start':
            open_trainee = e.timestamp
        elif e.event_type == 'trainee_end' and open_trainee:
            # Bycie szkolonym to tez praca — nie pomniejsza czasu pracy.
            secs = (e.timestamp - open_trainee).total_seconds()
            trainee_periods.append({'start': iso_z(open_trainee), 'end': iso_z(e.timestamp),
                                    'minutes': int(secs / 60)})
            trainee_secs += secs
            open_trainee = None
        elif e.event_type == 'work_end':
            work_end_ts = e.timestamp

    if open_break:
        breaks.append({'start': iso_z(open_break), 'end': None, 'minutes': None})
    if open_other:
        others.append({'start': iso_z(open_other), 'end': None, 'minutes': None})
    if open_training:
        trainings.append({'start': iso_z(open_training), 'end': None, 'minutes': None})
    if open_trainee:
        trainee_periods.append({'start': iso_z(open_trainee), 'end': None, 'minutes': None})

    end_ref = work_end_ts or datetime.utcnow()
    # „Inne" (np. wyjscie do HR) pomniejsza czas pracy tak samo jak przerwa,
    # ale jest raportowane osobno — przerwa i „Inne" to rozne rzeczy dla operacji.
    #
    # Odejmujemy SUME ZLACZONYCH okresow, nie sume dlugosci: skan pilnuje, zeby
    # przerwa i „Inne" sie nie nakladaly, ale reczna korekta na /worker-times
    # (POST/PUT zdarzenia) moze stworzyc nachodzace okresy. Sumowanie dlugosci
    # odjeloby wtedy te same minuty dwa razy i czas pracy wyszedlby za niski.
    work_secs = max(0, (end_ref - attendance_time).total_seconds()
                    - suma_zlaczonych_okresow(okresy))

    return {
        'work_end':      iso_z(work_end_ts),
        'break_minutes': int(break_secs / 60),
        'other_minutes': int(other_secs / 60),
        'training_minutes': int(training_secs / 60),
        'trainee_minutes': int(trainee_secs / 60),
        'work_minutes':  int(work_secs / 60),
        'breaks':        breaks,
        'others':        others,
        'trainings':     trainings,
        'trainee_periods': trainee_periods,
        'on_break':      open_break is not None,
        'on_other':      open_other is not None,
        'on_training':   open_training is not None,
        'on_trainee':    open_trainee is not None,
        'work_ended':    work_end_ts is not None,
        'events':        [e.to_dict() for e in events],
    }


@app.route('/time-tracking')
@leader_required
def time_tracking():
    return render_template('time_tracking.html')


@app.route('/worker-times')
@leader_required
def worker_times():
    return render_template('worker_times.html',
                           break_threshold=get_setting_int('break_threshold_minutes', 30),
                           max_work=get_setting_int('max_work_minutes', 660),
                           min_break=get_setting_int('min_break_minutes', 15))


def stan_czasu_dzis(user):
    """Dzisiejsza zmiana osoby i jej zdarzenia czasu — albo abort().

    Zwraca `{'shift', 'events', 'work_ended', 'trwajace'}`; `trwajace` to
    otwarte stany z `TRYBY_CZASU` (wiecej `*_start` niz `*_end`, bez flagi na User).
    """
    attendance = ShiftAttendance.query.join(Shift).filter(
        ShiftAttendance.user_id == user.id,
        Shift.date == local_today()
    ).order_by(ShiftAttendance.scanned_at.desc()).first()
    if not attendance:
        abort(400, f'{user.display_name} nie jest zeskanowany/a na zmianę dziś.')

    shift = attendance.shift
    events = WorkerTimeEvent.query.filter_by(
        user_id=user.id, shift_id=shift.id
    ).order_by(WorkerTimeEvent.timestamp, WorkerTimeEvent.id).all()

    def otwarte(prefix):
        return (sum(1 for e in events if e.event_type == f'{prefix}_start')
                > sum(1 for e in events if e.event_type == f'{prefix}_end'))

    return {
        'shift': shift,
        'events': events,
        'work_ended': any(e.event_type == 'work_end' for e in events),
        'trwajace': [m for m in TRYBY_CZASU if otwarte(m)],
    }


def otwarci_szkoleni(trener_id):
    """`[(user, shift_id)]` osob szkolonych z otwartym szkoleniem u `trener_id`."""
    od = datetime.utcnow() - timedelta(days=2)     # szkolenie nie trwa dluzej
    pary = {(e.user_id, e.shift_id) for e in WorkerTimeEvent.query.filter(
        WorkerTimeEvent.training_lead_id == trener_id,
        WorkerTimeEvent.event_type == 'trainee_start',
        WorkerTimeEvent.timestamp >= od)}
    wynik = []
    for uid, shift_id in sorted(pary):
        typy = [e.event_type for e in WorkerTimeEvent.query.filter(
            WorkerTimeEvent.user_id == uid, WorkerTimeEvent.shift_id == shift_id,
            WorkerTimeEvent.event_type.in_(('trainee_start', 'trainee_end')))]
        if typy.count('trainee_start') > typy.count('trainee_end'):
            wynik.append((db.session.get(User, uid), shift_id))
    return wynik


def zakoncz_szkolenie(trener, shift, now, notatka=None):
    """Koniec szkolenia `trener` + wszystkich jego szkolonych, ten sam `now`.

    Jedyna droga zamykania szkolenia ze skanera (przycisk „Zakończ szkolenie"
    i „Koniec pracy" szkolacego) — szkoleni koncza razem ze szkolacym.
    Bez commitu.
    """
    kto = current_user.id if notatka else None
    db.session.add(WorkerTimeEvent(
        user_id=trener.id, shift_id=shift.id, event_type='training_end',
        timestamp=now, recorded_by=kto, is_manual=False, note=notatka))
    for szkolony, shift_id in otwarci_szkoleni(trener.id):
        db.session.add(WorkerTimeEvent(
            user_id=szkolony.id, shift_id=shift_id, event_type='trainee_end',
            timestamp=now, recorded_by=current_user.id, is_manual=False,
            training_lead_id=trener.id,
            note=f'Koniec szkolenia prowadzonego przez {trener.display_name}'))


@app.route('/api/time/scan', methods=['POST'])
@leader_required
def api_time_scan():
    data = json_body()
    barcode = (data.get('barcode') or '').strip()
    mode    = data.get('mode', 'break')   # 'break' | 'other' | 'work_end'

    if not barcode:
        return jsonify({'error': 'Brak kodu.'}), 400

    user = User.query.filter_by(barcode_id=barcode, is_active_user=True).first()
    if not user:
        return jsonify({'error': 'Nieznany kod pracownika.'}), 404

    if mode not in TRYBY_SKANU and mode != 'work_end':
        # Szkolenie ma wlasny przeplyw (szkolacy + min. 1 szkolony) — zwykly
        # przelacznik ominalby ten wymog.
        return jsonify({'error': 'Nieprawidłowy tryb skanowania.'}), 400

    stan = stan_czasu_dzis(user)
    shift, trwajace = stan['shift'], stan['trwajace']
    now = datetime.utcnow()

    if mode == 'work_end':
        if stan['work_ended']:
            return jsonify({'error': f'{user.display_name} już zakończył/a pracę na tej zmianie.'}), 409

        # Niedomkniete przerwa/„Inne"/szkolenie zamykamy sami — inaczej
        # wisialyby otwarte i zjadaly czas pracy az do konca swiata.
        for prefix, opis in (('break', 'przerwy'), ('other', '„Innego"'),
                             ('trainee', 'szkolenia (szkolony)')):
            if prefix in trwajace:
                db.session.add(WorkerTimeEvent(
                    user_id=user.id, shift_id=shift.id, event_type=f'{prefix}_end',
                    timestamp=now, recorded_by=current_user.id, is_manual=False,
                    note=f'Auto-zamknięcie {opis} przy końcu pracy'
                ))
        if 'training' in trwajace:
            # Szkolacy konczy prace → koncza tez jego szkoleni.
            zakoncz_szkolenie(user, shift, now, 'Auto-zamknięcie szkolenia przy końcu pracy')

        db.session.add(WorkerTimeEvent(
            user_id=user.id, shift_id=shift.id, event_type='work_end',
            timestamp=now, recorded_by=None, is_manual=False
        ))
        db.session.commit()
        return jsonify({'message': f'{user.display_name} — koniec pracy zarejestrowany.',
                        'event_type': 'work_end', 'user': user.to_dict()}), 200

    if stan['work_ended']:
        return jsonify({'error': f'{user.display_name} już zakończył/a pracę.'}), 409

    trwa = mode in trwajace
    # Przerwa, „Inne" i szkolenie nie moga trwac jednoczesnie — przerwa
    # i „Inne" odjelyby ten sam czas dwa razy, a paczka z przerwy liczylaby
    # sie jako szkolenie.
    if not trwa and trwajace:
        return jsonify({'error': f'{user.display_name} {KOMUNIKATY_TRWANIA[trwajace[0]]}'}), 409

    event_type = f'{mode}_end' if trwa else f'{mode}_start'

    db.session.add(WorkerTimeEvent(
        user_id=user.id, shift_id=shift.id, event_type=event_type,
        timestamp=now, recorded_by=None, is_manual=False
    ))
    db.session.commit()

    etykiety = {
        'break_start': 'poszedł/poszła na przerwę ☕',
        'break_end':   'wrócił/wróciła z przerwy ✅',
        'other_start': 'wyszedł/wyszła — Inne 🚪',
        'other_end':   'wrócił/wróciła (Inne) ✅',
    }
    return jsonify({'message': f'{user.display_name} — {etykiety[event_type]}',
                    'event_type': event_type, 'user': user.to_dict()}), 200


# ── Szkolenie: szkolacy + osoby szkolone ─────────────────────────────────────
#
# Zakladka „🎓 Szkolenie" w Czasie pracy (decyzja operacji 2026-10-08):
# 1. skan szkolacego — NIC nie zapisuje, tylko sprawdza i pokazuje stan,
# 2. skan osob szkolonych — pierwsza zaczyna szkolenie (szkolacy i ona w tej
#    samej chwili), kolejne dopisuja sie takze w trakcie,
# 3. „Zakończ szkolenie" — koniec dla szkolacego i wszystkich szkolonych naraz.
# Szkolenie bez ani jednej osoby szkolonej nie istnieje — inaczej sam skan
# dawalby szkolacemu 100% celu.

def _trener_z_zadania(data):
    """Szkolacy z `trener_id` albo `barcode` — po sprawdzeniu znacznika."""
    if data.get('trener_id') not in (None, ''):
        trener = db.session.get(User, require_int(data.get('trener_id'), 'trener_id'))
    else:
        barcode = (data.get('barcode') or '').strip()
        if not barcode:
            abort(400, 'Brak kodu.')
        trener = User.query.filter_by(barcode_id=barcode).first()
    if trener is None or not trener.is_active_user:
        abort(404, 'Nieznany kod pracownika.')
    if not trener.is_trainer:
        abort(403, f'{trener.display_name} nie jest osobą szkolącą — szkolenie prowadzą '
                   'tylko osoby ze znacznikiem „Szkolący".')
    return trener


def opis_szkolenia(trener, stan=None):
    """Stan szkolenia dla ekranu: czy trwa, od kiedy i kto jest szkolony."""
    stan = stan or stan_czasu_dzis(trener)
    trwa = 'training' in stan['trwajace']
    od = None
    if trwa:
        od = [e.timestamp for e in stan['events'] if e.event_type == 'training_start'][-1]
    return {
        'trener': {'id': trener.id, 'display_name': trener.display_name,
                   'barcode_id': trener.barcode_id},
        'trwa': trwa,
        'od': iso_z(od),
        'szkoleni': ([{'id': u.id, 'display_name': u.display_name}
                      for u, _ in otwarci_szkoleni(trener.id)] if trwa else []),
    }


@app.route('/api/time/training/aktywne', methods=['GET'])
@leader_required
def api_training_aktywne():
    """Trwajace dzis szkolenia — druga stacja moze przejac dowolne z nich."""
    starty = WorkerTimeEvent.query.join(Shift).filter(
        Shift.date == local_today(),
        WorkerTimeEvent.event_type.in_(('training_start', 'training_end'))).all()
    licznik = {}
    for e in starty:
        licznik[e.user_id] = licznik.get(e.user_id, 0) + (
            1 if e.event_type == 'training_start' else -1)
    wynik = []
    for uid in sorted(u for u, n in licznik.items() if n > 0):
        trener = db.session.get(User, uid)
        stan = stan_czasu_dzis(trener)
        if 'training' in stan['trwajace']:
            wynik.append(opis_szkolenia(trener, stan))
    return jsonify({'szkolenia': wynik}), 200


@app.route('/api/time/training/trener', methods=['POST'])
@leader_required
def api_training_trener():
    """Krok 1: skan szkolacego. Niczego nie zapisuje."""
    trener = _trener_z_zadania(json_body())
    stan = stan_czasu_dzis(trener)
    if stan['work_ended']:
        abort(409, f'{trener.display_name} już zakończył/a pracę.')
    inne = [m for m in stan['trwajace'] if m != 'training']
    if inne:
        abort(409, f'{trener.display_name} {KOMUNIKATY_TRWANIA[inne[0]]}')
    return jsonify(opis_szkolenia(trener, stan)), 200


@app.route('/api/time/training/szkolony', methods=['POST'])
@leader_required
def api_training_szkolony():
    """Krok 2: skan osoby szkolonej. Pierwsza zaczyna szkolenie."""
    data = json_body()
    trener = _trener_z_zadania({'trener_id': data.get('trener_id')})
    # Blokada wiersza szkolacego: podwojny Enter / dwie stacje przy pierwszym
    # szkolonym dalyby dwa `training_start`.
    db.session.query(User).filter_by(id=trener.id).with_for_update().one()

    barcode = (data.get('barcode') or '').strip()
    if not barcode:
        abort(400, 'Brak kodu.')
    szkolony = User.query.filter_by(barcode_id=barcode, is_active_user=True).first()
    if szkolony is None:
        abort(404, 'Nieznany kod pracownika.')
    if szkolony.id == trener.id:
        abort(400, f'To kod osoby szkolącej ({trener.display_name}) — zeskanuj osobę szkoloną. '
                   'Szkolenie kończy przycisk „Zakończ szkolenie".')

    stan_trenera = stan_czasu_dzis(trener)
    if stan_trenera['work_ended']:
        abort(409, f'{trener.display_name} już zakończył/a pracę.')
    inne = [m for m in stan_trenera['trwajace'] if m != 'training']
    if inne:
        abort(409, f'{trener.display_name} {KOMUNIKATY_TRWANIA[inne[0]]}')

    stan = stan_czasu_dzis(szkolony)
    if stan['work_ended']:
        abort(409, f'{szkolony.display_name} już zakończył/a pracę.')
    if stan['trwajace']:
        if 'trainee' in stan['trwajace'] and any(
                u.id == szkolony.id for u, _ in otwarci_szkoleni(trener.id)):
            abort(409, f'{szkolony.display_name} już jest na tym szkoleniu.')
        abort(409, f'{szkolony.display_name} {KOMUNIKATY_TRWANIA[stan["trwajace"][0]]}')

    now = datetime.utcnow()
    rozpoczete = 'training' not in stan_trenera['trwajace']
    if rozpoczete:
        db.session.add(WorkerTimeEvent(
            user_id=trener.id, shift_id=stan_trenera['shift'].id,
            event_type='training_start', timestamp=now, is_manual=False))
    db.session.add(WorkerTimeEvent(
        user_id=szkolony.id, shift_id=stan['shift'].id, event_type='trainee_start',
        timestamp=now, is_manual=False, training_lead_id=trener.id))
    db.session.commit()

    wynik = opis_szkolenia(trener)
    wynik['message'] = (f'Szkolenie rozpoczęte — {trener.display_name} szkoli '
                        f'{szkolony.display_name} 🎓' if rozpoczete else
                        f'{szkolony.display_name} dołączył/a do szkolenia 🎓')
    return jsonify(wynik), 200


@app.route('/api/time/training/koniec', methods=['POST'])
@leader_required
def api_training_koniec():
    """Krok 3: koniec szkolenia — szkolacy i wszyscy szkoleni naraz.

    Szkolacy bez znacznika (zdjetego w trakcie) tez moze zakonczyc — inaczej
    jego szkolenie wisialoby otwarte."""
    data = json_body()
    trener = db.get_or_404(User, require_int(data.get('trener_id'), 'trener_id'))
    db.session.query(User).filter_by(id=trener.id).with_for_update().one()
    stan = stan_czasu_dzis(trener)
    if 'training' not in stan['trwajace']:
        abort(409, f'{trener.display_name} nie prowadzi teraz szkolenia.')
    szkoleni = [u.display_name for u, _ in otwarci_szkoleni(trener.id)]
    zakoncz_szkolenie(trener, stan['shift'], datetime.utcnow())
    db.session.commit()
    return jsonify({
        'message': f'Szkolenie zakończone — {trener.display_name}'
                   + (f' i {len(szkoleni)} os. szkolonych' if szkoleni else '') + ' ✅',
        'szkoleni': szkoleni,
    }), 200


@app.route('/api/worker-times')
@leader_required
def api_worker_times():
    date_str = request.args.get('date', local_today().isoformat())
    try:
        query_date = date.fromisoformat(date_str)
    except ValueError:
        query_date = local_today()

    shifts = Shift.query.filter_by(date=query_date).all()
    if not shifts:
        return jsonify({'workers': [], 'date': date_str}), 200

    shift_ids = [s.id for s in shifts]
    attendances = ShiftAttendance.query.filter(
        ShiftAttendance.shift_id.in_(shift_ids)
    ).options(joinedload(ShiftAttendance.user),
              joinedload(ShiftAttendance.shift)).all()

    # One entry per user — earliest attendance_in
    by_user = {}
    for att in attendances:
        uid = att.user_id
        if uid not in by_user or att.scanned_at < by_user[uid].scanned_at:
            by_user[uid] = att

    result = []
    for uid, att in by_user.items():
        summary = _compute_worker_times(uid, att.shift, att.scanned_at)
        summary.update({
            'user_id':      uid,
            'user_name':    att.user.display_name,
            'shift_id':     att.shift_id,
            'shift_number': att.shift.shift_number,
            'shift_in':     iso_z(att.scanned_at),
        })
        result.append(summary)

    result.sort(key=lambda x: x['user_name'])
    return jsonify({'workers': result, 'date': date_str}), 200


@app.route('/api/worker-times/event', methods=['POST'])
@leader_required
def api_time_event_create():
    data = json_body()
    user_id    = data.get('user_id')
    shift_id   = data.get('shift_id')
    event_type = data.get('event_type')
    ts_str     = data.get('timestamp', '')
    note       = (data.get('note') or '').strip()

    if not all([user_id, shift_id, event_type, ts_str]):
        return jsonify({'error': 'Brakuje wymaganych pól.'}), 400
    if event_type not in EVENT_TYPES:
        return jsonify({'error': 'Nieprawidłowy typ zdarzenia.'}), 400
    try:
        ts = datetime.fromisoformat(str(ts_str))
    except (TypeError, ValueError):
        return jsonify({'error': 'Nieprawidłowy format czasu.'}), 400

    # Bez tego bledne id konczylo sie naruszeniem klucza obcego i 500-ka
    # (na Postgresie transakcja padala w commicie).
    user_id = require_int(user_id, 'user_id')
    shift_id = require_int(shift_id, 'shift_id')
    pracownik = db.session.get(User, user_id)
    if pracownik is None:
        return jsonify({'error': f'Nieznany pracownik (id {user_id}).'}), 400
    if event_type == 'training_start' and not pracownik.is_trainer:
        return jsonify({'error': f'{pracownik.display_name} nie jest osobą szkolącą.'}), 400
    if db.session.get(Shift, shift_id) is None:
        return jsonify({'error': f'Nieznana zmiana (id {shift_id}).'}), 400

    event = WorkerTimeEvent(
        user_id=user_id, shift_id=shift_id, event_type=event_type,
        timestamp=ts, recorded_by=current_user.id, is_manual=True, note=note
    )
    db.session.add(event)
    db.session.commit()
    return jsonify(event.to_dict()), 201


@app.route('/api/worker-times/event/<int:event_id>', methods=['PUT'])
@leader_required
def api_time_event_update(event_id):
    event = db.get_or_404(WorkerTimeEvent, event_id)
    data  = json_body()
    if 'event_type' in data:
        if data['event_type'] not in EVENT_TYPES:
            return jsonify({'error': 'Nieprawidłowy typ.'}), 400
        if (data['event_type'] == 'training_start'
                and not db.session.get(User, event.user_id).is_trainer):
            return jsonify({'error': 'Ta osoba nie jest osobą szkolącą.'}), 400
        event.event_type = data['event_type']
    if 'timestamp' in data:
        try:
            event.timestamp = datetime.fromisoformat(data['timestamp'])
        except ValueError:
            return jsonify({'error': 'Nieprawidłowy format czasu.'}), 400
    if 'note' in data:
        event.note = data['note']
    event.recorded_by = current_user.id
    event.is_manual   = True
    db.session.commit()
    return jsonify(event.to_dict()), 200


@app.route('/api/worker-times/event/<int:event_id>', methods=['DELETE'])
@leader_required
def api_time_event_delete(event_id):
    event = db.get_or_404(WorkerTimeEvent, event_id)
    db.session.delete(event)
    db.session.commit()
    return jsonify({'message': 'Usunięto.'}), 200


# ══════════════════════════════════════════════════════════════════════════════
#  FORECAST
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
#  SEED DATA
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_ACTIVITIES = [
    'Post Processing',
    'Zwroty',
    'Organic Decoration',
    'Rollout Decoration',
    'Expansion',
    'Textile-Picking',
    'Order-VAS',
    'Carton Labeling',
    'Orders',
]


DEFAULT_COUNTRY_MAPPINGS = [
    ('Schweiz', '91000741810'),
    ('Italien', '91000741812'),
    ('Rumänien', '91000741814'),
    ('Vereinigtes Königreich', '91000741816'),
    ('Frankreich', '91000741817'),
    ('Croatia', '91000741820'),
    ('Spanien Kanaren', 'ES01'),
    ('Spanien', 'ES01'),
    ('Portugal', '91000741824'),
    ('Elfenbeinküste', '91000741828'),
    ('Deutschland', 'Orsay DE'),
    ('Kongo', 'IAM RCB'),
    ('Senegal', 'IAM SN'),
    ('Deutschland AMAZON', 'DE AMAZON'),
    ('EDEKA', 'EDK1'),
    ('Netherlands', 'NL01'),
    ('Northern Ireland', 'IRL'),
    ('ES', 'ES01'),
    ('IT', '91000741812'),
    ('CH', '91000741810'),
    ('Slowakei', 'SLO'),
    ('Tschechien', 'TSC'),
    ('PL', 'PL'),
    ('HU', 'HU'),
    ('BE', 'BE'),
    ('PT', 'PT'),
    ('AT', 'AT'),
    ('Deutschland C&A', 'DE'),
    ('SI', 'SI'),
]


def seed_data():
    """Seed default activities, admin user and country mappings on first run."""
    if Activity.query.count() == 0:
        for i, name in enumerate(DEFAULT_ACTIVITIES):
            db.session.add(Activity(name=name, sort_order=i))
        db.session.commit()
        print("[SEED] Default activities created.")

    if User.query.filter_by(role='admin').count() == 0:
        haslo = os.environ.get('ADMIN_PASSWORD', '').strip() or DEFAULT_ADMIN_PASSWORD
        admin = User(
            username='admin',
            display_name='Administrator',
            role='admin'
        )
        admin.set_password(haslo)
        db.session.add(admin)
        db.session.commit()
        if haslo == DEFAULT_ADMIN_PASSWORD:
            print("[SEED] Admin user created (login: admin / password: "
                  f"{DEFAULT_ADMIN_PASSWORD})")
            print("[SEED] !!! ZMIEN TO HASLO PRZY PIERWSZYM LOGOWANIU (/profile) "
                  "albo ustaw ADMIN_PASSWORD przed pierwszym startem.")
        else:
            print("[SEED] Admin user created (login: admin / haslo z ADMIN_PASSWORD)")

    # Tylko raz (znacznik w AppSetting): gdyby warunkiem byla pusta lista, admin,
    # ktory skasowal wszystkie pozycje, dostalby domyslne z powrotem po restarcie.
    if db.session.get(AppSetting, 'user_options_seeded') is None:
        for kind, nazwy in USER_OPTION_DEFAULTS.items():
            if UserOption.query.filter_by(kind=kind).count() == 0:
                for i, name in enumerate(nazwy):
                    db.session.add(UserOption(kind=kind, name=name, sort_order=i))
        db.session.add(AppSetting(key='user_options_seeded', value='1'))
        db.session.commit()
        print("[SEED] Default user options created.")

    if CountryMapping.query.count() == 0:
        for country, innenauftrag in DEFAULT_COUNTRY_MAPPINGS:
            db.session.add(CountryMapping(country=country, innenauftrag=innenauftrag))
        db.session.commit()
        print("[SEED] Default country mappings created.")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

# (tabela, kolumna, definicja) — dokladane przez migrate_columns() do zyjacej
# bazy. Kazda nowa kolumna modelu MUSI tu trafic (+ tests/test_migracje.py).
MIGRACJE_KOLUMN = [
    ("imported_carton", "scan_category_data", "TEXT DEFAULT '{}'"),
    ("general_stat",    "category_source",    "VARCHAR(10) DEFAULT 'manual'"),
    # "user" to slowo zastrzezone — bez cudzyslowu ALTER pada skladniowo,
    # a do 2026-10-16 try/except w migrate_columns() polykal ten blad.
    ('"user"', "worker_type_id", "INTEGER REFERENCES user_option(id)"),
    ('"user"', "shift_group_id", "INTEGER REFERENCES user_option(id)"),
    ("imported_carton", "data_pliku",         "DATE"),
    ('"user"', "is_trainer", "BOOLEAN NOT NULL DEFAULT FALSE"),
    # "user" w REFERENCES tez musi byc w cudzyslowie.
    ("worker_time_event", "training_lead_id", 'INTEGER REFERENCES "user"(id)'),
    ("historia_celu", "zmienil_id", 'INTEGER REFERENCES "user"(id)'),
    ("historia_celu", "zmieniono_at", "TIMESTAMP"),
    # Tabela ilosci na koniec paczki (2026-10-15).
    ("imported_carton", "tabela_ilosci", "TEXT"),
    ("imported_carton", "roznica", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("imported_carton", "roznica_potwierdzona_at", "TIMESTAMP"),
    ("imported_carton", "roznica_potwierdzona_przez", 'INTEGER REFERENCES "user"(id)'),
    ("udzial_paczki", "tabela", "TEXT"),
]


def migrate_columns():
    """Add missing columns to existing tables without dropping data.

    `create_all()` dokłada tylko brakujace TABELE, nigdy kolumn do istniejacej
    tabeli — wiec nowa kolumna na dzialajacym Postgresie musi przyjsc stad,
    inaczej kazde zapytanie dotykajace modelu konczy sie `UndefinedColumn`.
    Testy same z siebie tego nie zlapia: conftest robi drop_all() + create_all(),
    czyli schema jest tam zawsze swieza — blad istnieje wylacznie na bazie,
    ktora juz zyje. Stad `test_migracji_kolumn`, ktory kasuje kolumne i sprawdza,
    czy wraca.

    `ADD COLUMN IF NOT EXISTS` czyni to idempotentnym, wiec blad tutaj to
    zawsze prawdziwy blad (literowka w typie, FK do nieistniejacej tabeli,
    `user` bez cudzyslowu). Do 2026-10-16 except go polykal i aplikacja
    wstawala bez kolumny — `UndefinedColumn` wychodzil dopiero na pierwszym
    zapytaniu. Teraz start pada od razu, z nazwa kolumny.
    """
    with db.engine.connect() as conn:

        for table, column, col_def in MIGRACJE_KOLUMN:
            try:
                conn.execute(db.text(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_def}"))
                conn.commit()
            except Exception as e:
                conn.rollback()
                raise RuntimeError(
                    f'migrate_columns: nie udalo sie dodac {table}.{column} ({col_def}): {e}') from e

        indexes = [
            "CREATE INDEX IF NOT EXISTS ix_carton_ziel_datum   ON imported_carton (ziel_datum)",
            "CREATE INDEX IF NOT EXISTS ix_carton_data_pliku   ON imported_carton (data_pliku)",
            "CREATE INDEX IF NOT EXISTS ix_carton_uebergabe_nr ON imported_carton (uebergabe_nr)",
            "CREATE INDEX IF NOT EXISTS ix_carton_processed_by ON imported_carton (processed_by)",
            "CREATE INDEX IF NOT EXISTS ix_carton_land         ON imported_carton (land)",
            "CREATE INDEX IF NOT EXISTS ix_carton_imported_at  ON imported_carton (imported_at)",
            "CREATE INDEX IF NOT EXISTS ix_gstat_loading_date  ON general_stat    (loading_date)",
            "CREATE INDEX IF NOT EXISTS ix_gstat_list_id       ON general_stat    (list_id)",
            "CREATE INDEX IF NOT EXISTS ix_wte_user_shift      ON worker_time_event (user_id, shift_id)",
            "CREATE INDEX IF NOT EXISTS ix_wte_shift_id        ON worker_time_event (shift_id)",
        ]
        for sql in indexes:
            try:
                conn.execute(db.text(sql))
                conn.commit()
            except Exception as e:
                conn.rollback()
                raise RuntimeError(f'migrate_columns: indeks nie powstal ({sql.split(" ON ")[0]}): {e}') from e


ZNACZNIK_MIGRACJI_DATY_PLIKU = 'migracja_data_pliku'


def migruj_date_pliku():
    """Jednorazowo (znacznik w AppSetting): data pliku dla starych kartonow
    i przeklucz linii rozliczenia z Ziel-Datum na date pliku.

    1. Karton bez daty pliku dostaje lokalny (Europe/Warsaw) dzien importu,
       a bez `imported_at` — swoja Ziel-Datum. W SQL-u, z `at time zone`:
       data UTC przesunelaby nocne importy na zly dzien.
    2. Kazda linia idzie pod klucz_linii() swoich kartonow. Linie trafiajace
       pod ten sam klucz sa laczone (przenies_linie). Linia, ktorej kartony
       rozjechaly sie na kilka dni, oddaje reczne ilosci dniowi z najwieksza
       liczba sztuk — pozostale dni dostaja linie przeliczone z kartonow.
    3. Klucze, ktorych dotad nie bylo (np. kartony bez Ziel-Datum, ktore
       wczesniej sie nie rozliczaly — decyzja 2026-10: maja sie rozliczac),
       dostaja nowe linie.
    Bieg w init_db() pod pg_advisory_lock — jeden worker, jedna transakcja.
    """
    if db.session.get(AppSetting, ZNACZNIK_MIGRACJI_DATY_PLIKU) is not None:
        return
    db.session.execute(db.text("""
        UPDATE imported_carton
           SET data_pliku = COALESCE(
                 (imported_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Warsaw')::date,
                 ziel_datum)
         WHERE data_pliku IS NULL
    """))
    db.session.flush()

    # stary klucz (UB, land, ziel) -> {nowy klucz: sztuki}
    stare = {}
    for ub, land, ziel, plik, szt in db.session.query(
            ImportedCarton.uebergabe_nr, ImportedCarton.land, ImportedCarton.ziel_datum,
            ImportedCarton.data_pliku, ImportedCarton.stueckzahl):
        if ub and ziel and plik:
            cel = stare.setdefault((ub, land, ziel), {})
            cel[(ub, land, plik)] = cel.get((ub, land, plik), 0) + (szt or 0)

    plan = {}          # nowy klucz -> [linie]
    for linia in GeneralStat.query.all():
        cele = stare.get((linia.list_id, linia.country_ledger, linia.loading_date))
        if not cele:
            continue   # linia bez kartonow (np. reczna) zostaje, gdzie byla
        glowny = max(cele, key=lambda k: cele[k])
        plan.setdefault(glowny, []).append(linia)
        for k in cele:
            plan.setdefault(k, [])

    _odsun_linie([x for linie in plan.values() for x in linie])
    for klucz, linie in plan.items():
        przenies_linie(linie, klucz)

    # Klucze kartonow, ktore nie mialy linii (np. bez Ziel-Datum).
    for klucz in db.session.query(ImportedCarton.uebergabe_nr, ImportedCarton.land,
                                  ImportedCarton.data_pliku).distinct():
        if klucz[0] and klucz[2] and tuple(klucz) not in plan:
            recompute_general_stat(*klucz)

    db.session.add(AppSetting(key=ZNACZNIK_MIGRACJI_DATY_PLIKU, value='1'))
    db.session.commit()
    print(f'[MIGRACJA] Data pliku: {len(plan)} linii rozliczenia pod nowymi kluczami.')


def init_db():
    """Create the schema, patch columns and seed — safe to run from every worker.

    Gunicorn imports this module once per worker, so on a fresh Postgres all
    workers race inside create_all() and the loser dies with a UniqueViolation on
    pg_class ("worker failed to boot"). A Postgres advisory lock serializes them:
    the winner does the DDL, the rest wait and then find nothing left to do
    (create_all and seed_data are both no-ops on an initialized database).
    """
    lock_id = 5001  # dowolna stala — byle ta sama we wszystkich workerach
    with db.engine.connect() as conn:
        conn.execute(db.text('SELECT pg_advisory_lock(:id)'), {'id': lock_id})
        conn.commit()
        try:
            db.create_all()
            migrate_columns()
            migruj_date_pliku()
            seed_data()
            zasiej_historie_celu()
            zaznacz_wszystkich_przeszkolonych()
            db.session.commit()
        finally:
            conn.execute(db.text('SELECT pg_advisory_unlock(:id)'), {'id': lock_id})
            conn.commit()


# LOGISTAT_BEZ_INIT=1: import bez DDL, migracji i seeda — dla narzedzi tylko
# do odczytu (scripts/sprawdz_spojnosc.py). Aplikacja i testy zawsze z init_db().
if os.environ.get('LOGISTAT_BEZ_INIT') != '1':
    with app.app_context():
        init_db()

if __name__ == '__main__':
    # Debugger Werkzeuga pozwala wykonac dowolny kod, wiec domyslnie sluchamy
    # tylko na loopbacku. Dostep z LAN-u w dev: HOST=0.0.0.0 python app.py
    # (produkcja i tak chodzi na gunicornie z Dockerfile, nie tedy).
    app.run(
        debug=os.environ.get('FLASK_DEBUG', '1') == '1',
        host=os.environ.get('HOST', '127.0.0.1'),
        port=int(os.environ.get('PORT', 5001)),
    )
