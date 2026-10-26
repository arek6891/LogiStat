"""Baza danych przy starcie: schemat (`create_all`), dokladanie kolumn do zyjacej
bazy (`migrate_columns`), jednorazowe migracje danych i seed — wszystko pod
`pg_advisory_lock` w `init_db()`. Wola to app.py przy imporcie (gunicorn), nie
`create_app()`."""
import logging
import os

from logistat.config import DEFAULT_ADMIN_PASSWORD
from logistat.extensions import db
from logistat.faktura_zwrotow import LICENCJE_DOMYSLNE, ZNACZNIK_LICENCJI
from logistat.models import (
    Activity, AppSetting, CountryMapping, GeneralStat, ImportedCarton, LicencjaZwrotow,
    USER_OPTION_DEFAULTS, User, UserOption, zaznacz_wszystkich_przeszkolonych)
from logistat.normy_dane import zasiej_historie_celu
from logistat.rozliczenie import _odsun_linie, przenies_linie, recompute_general_stat

log = logging.getLogger(__name__)


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
        log.info('[SEED] Domyslne czynnosci utworzone.')

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
            log.warning('[SEED] Konto admin z domyslnym haslem (%s) — zmiana wymuszona przy '
                        'pierwszym logowaniu; lepiej ustaw ADMIN_PASSWORD przed pierwszym startem.',
                        DEFAULT_ADMIN_PASSWORD)
        else:
            log.info('[SEED] Konto admin utworzone (haslo z ADMIN_PASSWORD).')

    # Tylko raz (znacznik w AppSetting): gdyby warunkiem byla pusta lista, admin,
    # ktory skasowal wszystkie pozycje, dostalby domyslne z powrotem po restarcie.
    if db.session.get(AppSetting, 'user_options_seeded') is None:
        for kind, nazwy in USER_OPTION_DEFAULTS.items():
            if UserOption.query.filter_by(kind=kind).count() == 0:
                for i, name in enumerate(nazwy):
                    db.session.add(UserOption(kind=kind, name=name, sort_order=i))
        db.session.add(AppSetting(key='user_options_seeded', value='1'))
        db.session.commit()
        log.info('[SEED] Domyslne listy uzytkownikow utworzone.')

    # Listy Sorting Data (2026-10-26) — raz, z arkusza operacji; jak wyzej znacznik,
    # zeby skasowane przez admina pozycje nie wracaly po restarcie.
    if db.session.get(AppSetting, ZNACZNIK_LICENCJI) is None:
        for rodzaj, nazwy in LICENCJE_DOMYSLNE.items():
            if LicencjaZwrotow.query.filter_by(rodzaj=rodzaj).count() == 0:
                for i, nazwa in enumerate(nazwy):
                    db.session.add(LicencjaZwrotow(rodzaj=rodzaj, nazwa=nazwa.strip(), kolejnosc=i))
        db.session.add(AppSetting(key=ZNACZNIK_LICENCJI, value='1'))
        db.session.commit()
        log.info('[SEED] Listy Sorting Data (licencje, wysylki) utworzone.')

    if CountryMapping.query.count() == 0:
        for country, innenauftrag in DEFAULT_COUNTRY_MAPPINGS:
            db.session.add(CountryMapping(country=country, innenauftrag=innenauftrag))
        db.session.commit()
        log.info('[SEED] Domyslne mapowanie krajow utworzone.')


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
    # Korekta godziny wejscia na osi czasu (2026-10-23).
    ("shift_attendance", "pierwotny_skan", "TIMESTAMP"),
    ("shift_attendance", "poprawione_przez", 'INTEGER REFERENCES "user"(id)'),
    ("shift_attendance", "poprawione_at", "TIMESTAMP"),
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
    log.info('[MIGRACJA] Data pliku: %d linii rozliczenia pod nowymi kluczami.', len(plan))


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
