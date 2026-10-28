"""Kafelki po zalogowaniu (operacja 2026-10-24, grupy 2026-10-28): na ekranie
startowym trzy kafelki-GRUPY — Operacje magazynowe / Dzial etykietowania /
Supervisor; Dzial etykietowania po kliknieciu pokazuje swoje kafelki
(Post-Process, Dekoracje, Zwroty). Grupa to tylko ekran wyboru — dostep, menu
i `session['obszar']` dzialaja dalej na kafelkach (obszarach) ponizej.

Kazdy endpoint nalezy do jednego lub kilku obszarow (kafelkow), albo do
`WSPOLNE` (logowanie, profil, ekran kafelkow). Rola decyduje, ktore kafelki
widac i do czego jest dostep (ekran spoza kafelkow roli → brak dostepu);
wybrany kafelek (`session['obszar']`) wybiera tylko MENU — ekran innego
kafelka roli otwiera sie i przelacza menu (wersja lagodna, 2026-10-24).
`tests/test_obszary.py` pilnuje, ze kazda trasa jest przypisana — nowa trasa
bez wpisu tutaj = czerwony test.

Czysta logika — bez Flaska i bazy (import z `aplikacja.py` i `web/`).
"""

MAGAZYN = 'magazyn'
POST_PROCESS = 'post_process'
DISPLAYS = 'displays'
ZWROTY = 'zwroty'
USTAWIENIA = 'ustawienia'

# Kolejnosc = kolejnosc kafelkow. `start` = pierwszy ekran po wyborze kafelka.
OBSZARY = {
    MAGAZYN: {
        'nazwa': 'Operacje magazynowe', 'ikona': '👷', 'start': 'stanowisko.scan_paczki',
        'opis': 'Stanowiska: skaner zmian, czas pracy, czasy paczek, inspektor paczek, przyjęcie zwrotu',
    },
    POST_PROCESS: {
        'nazwa': 'Post-Process', 'ikona': '📦', 'start': 'dashboard.dashboard',
        'opis': 'Lider: dashboard, przydzielanie, normy, paczki, import, statystyki, użytkownicy',
    },
    # Do 2026-10-28 „Akcje - Displays”; od 2026-10-28 akcje na wykresie Gantta.
    DISPLAYS: {
        'nazwa': 'Dekoracje', 'ikona': '💍', 'start': 'displays.displays',
        'opis': 'Akcje na wykresie Gantta, indexy displayi, historia akcji',
    },
    ZWROTY: {
        'nazwa': 'Zwroty', 'ikona': '↩️', 'start': 'zwroty.zwroty_paczek',
        'opis': 'Zwroty Paczek, dashboard i przydział zwrotów, Invoice specification, Sorting Data',
    },
    USTAWIENIA: {
        'nazwa': 'Supervisor', 'ikona': '🛡️', 'start': 'admin.admin_panel',
        'opis': 'Wszystkie ustawienia: czynności, stawki, kraje, nazwy kategorii, progi, zwroty',
    },
}

# Kafelki na ekranie startowym (operacja 2026-10-28). Grupa z jednym kafelkiem
# roli prowadzi od razu do niego; z kilkoma — pokazuje je (`/start?grupa=…`).
# Kolejnosc = kolejnosc na ekranie; kazdy obszar w dokladnie jednej grupie.
GRUPY = {
    'magazynowe': {
        'nazwa': 'Operacje magazynowe', 'ikona': '🏭', 'obszary': (MAGAZYN,),
        'opis': 'Wszystkie moduły magazynu: skaner zmian, czas pracy, czasy paczek, przyjęcie zwrotu',
    },
    'etykietowanie': {
        'nazwa': 'Dział etykietowania', 'ikona': '🏷️', 'obszary': (POST_PROCESS, DISPLAYS, ZWROTY),
        'opis': 'Post-Process, Dekoracje, Zwroty',
    },
    'supervisor': {
        'nazwa': 'Supervisor', 'ikona': '🛡️', 'obszary': (USTAWIENIA,),
        'opis': 'Wszystkie ustawienia',
    },
}

# Rola → kafelki. Operator (skanowany na zmianie) nie loguje sie wcale.
ROLE_OBSZARY = {
    'stanowisko': (MAGAZYN,),
    'leader': (MAGAZYN, POST_PROCESS, DISPLAYS, ZWROTY),
    'admin': (MAGAZYN, POST_PROCESS, DISPLAYS, ZWROTY, USTAWIENIA),
}

# Dostepne zawsze po zalogowaniu (i przed wyborem kafelka).
WSPOLNE = frozenset({
    'static', 'auth.favicon', 'auth.index', 'auth.login', 'auth.logout', 'auth.profile',
    'auth.kafelki', 'auth.wybierz_obszar',
})

_ENDPOINTY = {
    MAGAZYN: {
        # Skaner zmian
        'stanowisko.scanner', 'stanowisko.api_scan', 'stanowisko.api_unscan',
        'stanowisko.api_shift_attendances',
        # Czas pracy (przerwy, Inne, koniec pracy, szkolenia)
        'czas_pracy.time_tracking', 'czas_pracy.api_time_scan',
        'czas_pracy.api_training_aktywne', 'czas_pracy.api_training_trener',
        'czas_pracy.api_training_szkolony', 'czas_pracy.api_training_koniec',
        # Czasy paczek
        'stanowisko.scan_paczki', 'stanowisko.api_employee_lookup',
        'stanowisko.api_package_time_start', 'stanowisko.api_package_time_end',
        'stanowisko.api_package_time_przekaz', 'stanowisko.api_package_time_dolacz',
        # Paczki inspektor
        'stanowisko.scan_package', 'stanowisko.api_package_lookup',
        # Przyjecie zwrotu (2026-10-27) — wiersze raportu Zwroty Paczek
        'zwroty.przyjecie_zwrotu', 'zwroty.api_przyjecie_zwrotu',
        # Dekoracje: skan stojakow nosnik → strefa (2026-10-28)
        'displays.skan_stojakow', 'displays.api_nosnik', 'displays.api_skan',
    },
    POST_PROCESS: {
        'dashboard.dashboard', 'dashboard.api_dashboard', 'dashboard.api_dashboard_plik',
        'dashboard.api_dashboard_zalegle', 'dashboard.api_dashboard_loading_dates',
        'dashboard.api_dashboard_shifts',
        'forecast.forecast_page', 'forecast.api_forecast_chart_data',
        'forecast.api_forecast_save', 'forecast.api_forecast_export',
        'przydzial.assignment', 'przydzial.api_assignment_data', 'przydzial.api_assignment_save',
        'przydzial.api_assignment_suggestions', 'przydzial.data_entry',
        'przydzial.api_daily_stats_get', 'przydzial.api_daily_stats_save',
        'przydzial.api_daily_stat_update',
        'normy.stats', 'normy.api_stats_overview', 'normy.api_stats_user',
        'normy.api_stats_target_update',
        'paczki.paczki_view', 'paczki.api_package_create', 'paczki.api_package_update',
        'paczki.api_package_double_rate', 'paczki.api_package_reassign',
        'paczki.api_package_categories_update', 'paczki.api_package_tabela_update',
        'paczki.api_package_potwierdz_roznice', 'paczki.api_package_unlock_scan',
        'paczki.api_package_zamknij_zespol',
        'czas_pracy.worker_times', 'czas_pracy.api_worker_times',
        'czas_pracy.api_time_event_create', 'czas_pracy.api_time_event_update',
        'czas_pracy.api_time_event_delete', 'czas_pracy.api_wejscie_update',
        'imports.import_csv_page', 'imports.api_import_csv', 'imports.api_import_excel',
        'imports.api_imports', 'imports.api_imports_zmien_date',
        'rozliczenie.general_stats_page', 'rozliczenie.general_stats_export',
        'rozliczenie.api_general_stats', 'rozliczenie.api_general_stat_update',
        'rozliczenie.api_general_stat_use_scan',
        # Uzytkownicy (w menu Lidera) + listy, ktore ich okno czyta
        'admin.admin_users', 'admin.api_users', 'admin.api_user_create',
        'admin.api_user_update', 'admin.api_user_delete',
        'admin.api_user_options', 'admin.api_activities',
        # Przydzielanie → kolumna „Zwroty” → stanowiska (2026-10-27; tez w kafelku Zwroty)
        'zwroty.przydzial_zwrotow', 'zwroty.api_przydzial_zwrotow',
        'zwroty.api_przydzial_zwrotow_zapisz',
    },
    DISPLAYS: {
        # Akcje na Gantcie, ekran akcji z indexami, historia (2026-10-28)
        'displays.displays', 'displays.historia', 'displays.akcja',
        'displays.api_akcja_dodaj', 'displays.api_akcja_zmien', 'displays.api_akcja_status',
        'displays.api_index_dodaj', 'displays.api_index_zmien', 'displays.api_index_usun',
        # Etykiety POS: lista z Excela → PDF z kodami (2026-10-28)
        'displays.pos', 'displays.api_pos_import', 'displays.api_pos_usun',
        'displays.pos_etykiety', 'displays.pos_export',
        # Stock stojakow: tabela, POS / akcja / strefa, historia ruchow (2026-10-28)
        'displays.stock', 'displays.api_stojak_zmien', 'displays.api_stojak_usun',
        'displays.api_stojak_ruchy',
    },
    ZWROTY: {
        'zwroty.zwroty', 'zwroty.zwroty_paczek', 'zwroty.zwroty_paczek_export',
        # Invoice specification i Sorting Data (2026-10-26)
        'zwroty.invoice_specification_view', 'zwroty.invoice_specification_export',
        'zwroty.api_invoice_ilosc',
        'zwroty.sorting_data_view', 'zwroty.sorting_data_export', 'zwroty.api_sorting_data',
        # Przydzial osob do stanowisk zwrotow i dashboard (2026-10-27)
        'zwroty.przydzial_zwrotow', 'zwroty.api_przydzial_zwrotow',
        'zwroty.api_przydzial_zwrotow_zapisz', 'zwroty.dashboard_zwrotow_view',
        # Poprawka / usuniecie przyjetego zwrotu z ekranu Zwroty Paczek
        'zwroty.api_zwrot_popraw', 'zwroty.api_zwrot_usun',
    },
    USTAWIENIA: {
        'admin.admin_panel', 'admin.admin_activities', 'admin.admin_country_mapping',
        'admin.admin_user_options', 'admin.admin_category_labels', 'admin.admin_settings',
        'admin.admin_cost_mapping',
        # Zwroty (2026-10-26): listy Sorting Data i cennik Invoice specification
        'zwroty.admin_licencje', 'zwroty.api_licencja_dodaj', 'zwroty.api_licencja_zmien',
        'zwroty.api_licencja_usun', 'zwroty.admin_cennik', 'zwroty.api_cennik',
        'zwroty.api_cennik_zapisz',
        'zwroty.admin_przyjecie', 'zwroty.api_etykiety_przyjecia',
        'admin.api_activities', 'admin.api_activity_create', 'admin.api_activity_update',
        'admin.api_activity_delete', 'admin.api_activities_reorder',
        'admin.api_country_mappings', 'admin.api_country_mapping_create',
        'admin.api_country_mapping_update', 'admin.api_country_mapping_delete',
        'admin.api_user_options', 'admin.api_user_option_create',
        'admin.api_user_option_update', 'admin.api_user_option_delete',
        'admin.api_category_labels_update', 'admin.api_settings_update',
        'admin.api_cost_mapping_get', 'admin.api_cost_mapping_save',
        # Dekoracje (2026-10-28): typy i modele stojakow
        'displays.admin_slownik', 'displays.api_slownik_dodaj', 'displays.api_slownik_zmien',
        'displays.api_slownik_usun', 'displays.strefy_etykiety',
    },
}


def obszary_endpointu(endpoint):
    """Kafelki, w ktorych endpoint jest dostepny (pusty zbior = nieprzypisany)."""
    return {o for o, eps in _ENDPOINTY.items() if endpoint in eps}


def obszary_roli(rola):
    """Kafelki roli w kolejnosci wyswietlania; brak roli z logowaniem → ()."""
    return ROLE_OBSZARY.get(rola, ())


def grupy_roli(rola):
    """Grupy widoczne dla roli: [(klucz, grupa, obszary roli w tej grupie)] —
    tylko grupy z co najmniej jednym kafelkiem roli."""
    role = obszary_roli(rola)
    wynik = []
    for klucz, g in GRUPY.items():
        obszary = tuple(o for o in g['obszary'] if o in role)
        if obszary:
            wynik.append((klucz, g, obszary))
    return wynik


def grupa_obszaru(obszar):
    """Klucz grupy, do ktorej nalezy kafelek (None = nieznany)."""
    return next((k for k, g in GRUPY.items() if obszar in g['obszary']), None)


def wszystkie_przypisane():
    return set().union(*_ENDPOINTY.values()) | WSPOLNE
