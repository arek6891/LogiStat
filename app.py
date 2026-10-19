import os
from datetime import datetime  # noqa: F401 — testy uzywaja logistat.datetime

from flask import Flask, jsonify, request, url_for
from werkzeug.exceptions import HTTPException

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
from logistat.config import (
    DEV_SECRET_KEY, DEFAULT_MAX_UPLOAD_MB, DEFAULT_ADMIN_PASSWORD, resolve_secret_key,
    resolve_database_url)
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
from logistat.czas_pracy_dane import (  # noqa: F401 — re-eksport
    _compute_worker_times, otwarci_szkoleni)
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


from logistat.web.czas_pracy import stan_czasu_dzis, bp as bp_czas_pracy  # noqa: E402,F401
app.register_blueprint(bp_czas_pracy)


from logistat.web.stanowisko import bp as bp_stanowisko  # noqa: E402
app.register_blueprint(bp_stanowisko)


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


# ── Grupowa poprawa daty pliku ───────────────────────────────────────────────
#  Import = kartony jednej osoby z jednej minuty importu i jednej daty pliku
#  (process_import_rows daje calemu plikowi jedno `imported_at`). Klucz importu
#  w API: "<imported_by>|<minuta UTC ISO>|<data_pliku>".


# ══════════════════════════════════════════════════════════════════════════════
#  API: BARCODE SCANNING
# ══════════════════════════════════════════════════════════════════════════════


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


# ══════════════════════════════════════════════════════════════════════════════
#  PACKAGE SCAN TIMES & DOUBLE RATE
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
#  TIME TRACKING
# ══════════════════════════════════════════════════════════════════════════════


# ── Szkolenie: szkolacy + osoby szkolone ─────────────────────────────────────
#
# Zakladka „🎓 Szkolenie" w Czasie pracy (decyzja operacji 2026-10-08):
# 1. skan szkolacego — NIC nie zapisuje, tylko sprawdza i pokazuje stan,
# 2. skan osob szkolonych — pierwsza zaczyna szkolenie (szkolacy i ona w tej
#    samej chwili), kolejne dopisuja sie takze w trakcie,
# 3. „Zakończ szkolenie" — koniec dla szkolacego i wszystkich szkolonych naraz.
# Szkolenie bez ani jednej osoby szkolonej nie istnieje — inaczej sam skan
# dawalby szkolacemu 100% celu.


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
