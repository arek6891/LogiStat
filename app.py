"""Punkt wejscia LogiStat: `gunicorn app:app` (Dockerfile) i `python app.py` (dev).

Cala aplikacja jest w pakiecie `logistat/` (uklad: logistat/__init__.py). Tu:
1. `app = create_app()` — konfiguracja, obsluga bledow, blueprinty;
2. `init_db()` przy imporcie — schemat, migracje, seed pod advisory lockiem
   (kazdy worker gunicorna importuje ten plik); `LOGISTAT_BEZ_INIT=1` pomija
   (narzedzia tylko do odczytu, scripts/sprawdz_spojnosc.py);
3. re-eksport nazw z pakietu — testy uzywaja `import app as logistat` i
   `logistat.X` (przepinanie ~700 testow na nowe importy to osobna praca).
"""
import os
from datetime import datetime  # noqa: F401 — testy uzywaja logistat.datetime


# Re-eksport dla testow (`logistat.X`) — patrz docstring.
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
from logistat import create_app
from logistat.baza import (  # noqa: F401 — re-eksport
    DEFAULT_ACTIVITIES, DEFAULT_COUNTRY_MAPPINGS, seed_data, MIGRACJE_KOLUMN, migrate_columns, ZNACZNIK_MIGRACJI_DATY_PLIKU, migruj_date_pliku, init_db)
from logistat.web.auth import BEZ_WYMOGU_ZMIANY_HASLA  # noqa: F401
from logistat.web.czas_pracy import stan_czasu_dzis  # noqa: F401
from logistat.web.paczki import PACZKI_NA_STRONE  # noqa: F401
from logistat.aplikacja import load_user  # noqa: F401

app = create_app()

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
