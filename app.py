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
from logistat.normy_dane import (  # noqa: F401 — re-eksport
    prace_osob, wydajnosc_pracownikow, MAKS_OTWARTEGO_SZKOLENIA, okresy_szkolen, cele_dzienne, zmiany_celu, zasiej_historie_celu, przeglad_zespolu, norma_pracownika, wykres_wydajnosci, podsumuj_paczki_pracownika)
from logistat.dashboard_dane import (  # noqa: F401 — re-eksport
    _agregaty_planu, _wiersz_planu, plan_dnia_pliku, plany_dni_pliku, zalegle_wg_daty_pliku)
from logistat.przydzial import (  # noqa: F401 — re-eksport
    CZYNNOSC_SKANOW_PACZEK, DNI_SREDNIEJ_PRZYDZIALU, GODZIN_ZMIANY, wersja_przydzialu, wydajnosc_czynnosci)
from logistat.paczki import (  # noqa: F401 — re-eksport
    parse_scan_categories)
from logistat.web.wspolne import (  # noqa: F401 — re-eksport
    process_import_rows, wymagana_data_pliku, acting_as_admin, leader_required, admin_required, json_body, parse_shift_number, parse_date, require_int, bezpieczny_next, blad_nieznanej_paczki)
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


from logistat.web.forecast import bp as bp_forecast  # noqa: E402
app.register_blueprint(bp_forecast)


from logistat.web.admin import bp as bp_admin  # noqa: E402
app.register_blueprint(bp_admin)


from logistat.web.auth import BEZ_WYMOGU_ZMIANY_HASLA, bp as bp_auth  # noqa: E402,F401
app.register_blueprint(bp_auth)


from logistat.web.imports import bp as bp_imports  # noqa: E402
app.register_blueprint(bp_imports)


from logistat.web.normy import bp as bp_normy  # noqa: E402
app.register_blueprint(bp_normy)


from logistat.web.dashboard import bp as bp_dashboard  # noqa: E402
app.register_blueprint(bp_dashboard)


from logistat.web.przydzial import bp as bp_przydzial  # noqa: E402
app.register_blueprint(bp_przydzial)


from logistat.web.rozliczenie import bp as bp_rozliczenie  # noqa: E402
app.register_blueprint(bp_rozliczenie)


from logistat.web.paczki import PACZKI_NA_STRONE, bp as bp_paczki  # noqa: E402,F401
app.register_blueprint(bp_paczki)


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


# ── Grupowa poprawa daty pliku ───────────────────────────────────────────────
#  Import = kartony jednej osoby z jednej minuty importu i jednej daty pliku
#  (process_import_rows daje calemu plikowi jedno `imported_at`). Klucz importu
#  w API: "<imported_by>|<minuta UTC ISO>|<data_pliku>".


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


# ══════════════════════════════════════════════════════════════════════════════
#  API: DAILY STATS (DATA ENTRY)
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
#  API: STATISTICS
# ══════════════════════════════════════════════════════════════════════════════


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


# ══════════════════════════════════════════════════════════════════════════════
#  PACKAGE SCAN TIMES & DOUBLE RATE
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/scan-paczki')
@leader_required
def scan_paczki():
    return render_template('scan_paczki.html')


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
