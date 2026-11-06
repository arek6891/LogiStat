"""Kafelki po zalogowaniu (operacja 2026-10-24, grupy 2026-10-28): na ekranie
startowym trzy kafelki-GRUPY — Operacje magazynowe / Dzial etykietowania /
Supervisor; grupa po kliknieciu pokazuje swoje kafelki — Operacje magazynowe
(od 2026-11-06, po procesach: Zmiany, Post-processing, Zwroty, Dekoracje),
Dzial etykietowania (od 2026-11-02: Przydzielanie, Pracownicy, Post-Process,
Dekoracje, Zwroty, Zadania dodatkowe). Grupa to tylko ekran wyboru — dostep, menu
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

# Operacje magazynowe — ekrany stanowisk, po procesach (operacja 2026-11-06;
# do tego dnia jeden kafelek `magazyn`).
MAGAZYN_ZMIANY = 'magazyn_zmiany'
MAGAZYN_PP = 'magazyn_pp'
MAGAZYN_ZWROTY = 'magazyn_zwroty'
MAGAZYN_DEKORACJE = 'magazyn_dekoracje'
MAGAZYN = (MAGAZYN_ZMIANY, MAGAZYN_PP, MAGAZYN_ZWROTY, MAGAZYN_DEKORACJE)
PRZYDZIELANIE = 'przydzielanie'
PRACOWNICY = 'pracownicy'
POST_PROCESS = 'post_process'
DISPLAYS = 'displays'
ZWROTY = 'zwroty'
ZADANIA = 'zadania'
USTAWIENIA = 'ustawienia'

# Kolejnosc = kolejnosc kafelkow. `start` = pierwszy ekran po wyborze kafelka
# (`start_args` = jego argumenty adresu).
OBSZARY = {
    MAGAZYN_ZMIANY: {
        'nazwa': 'Zmiany', 'ikona': '🔁', 'start': 'stanowisko.scanner',
        'start_args': {'shift_number': 1},
        'opis': 'Skaner zmian, czas pracy',
    },
    MAGAZYN_PP: {
        'nazwa': 'Post-processing', 'ikona': '👷', 'start': 'stanowisko.scan_paczki',
        'opis': 'Czasy paczek, paczki inspektor',
    },
    MAGAZYN_ZWROTY: {
        'nazwa': 'Zwroty', 'ikona': '📥', 'start': 'zwroty.przyjecie_zwrotu',
        'opis': 'Przyjęcie zwrotu',
    },
    MAGAZYN_DEKORACJE: {
        'nazwa': 'Dekoracje', 'ikona': '💍', 'start': 'displays.dostawy_stanowisko',
        'opis': 'Dostawy, skan stojaków',
    },
    # Operacja 2026-11-02: Przydzielanie i Pracownicy wyjete z menu Post-Process.
    PRZYDZIELANIE: {
        'nazwa': 'Przydzielanie', 'ikona': '📋', 'start': 'przydzial.assignment',
        'opis': 'Przydział ludzi do czynności na zmianie, stanowiska zwrotów',
    },
    PRACOWNICY: {
        'nazwa': 'Pracownicy', 'ikona': '👥', 'start': 'admin.admin_users',
        'opis': 'Lista pracowników, normy per proces, czasy pracowników',
    },
    POST_PROCESS: {
        'nazwa': 'Post-Process', 'ikona': '📦', 'start': 'dashboard.dashboard',
        'opis': 'Lider: dashboard, forecast, normy, paczki, import, statystyki',
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
    # Operacja 2026-11-02: zastepuje „Wpis ilosci” — czas na dziale + czynnosc dodatkowa.
    ZADANIA: {
        'nazwa': 'Zadania dodatkowe', 'ikona': '🧹', 'start': 'zadania.zadania_dodatkowe',
        'opis': 'Czas pracowników w działach i czynności dodatkowe (sprzątanie, 5S…), eksport do Excela',
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
        'nazwa': 'Operacje magazynowe', 'ikona': '🏭', 'obszary': MAGAZYN,
        'opis': 'Zmiany, Post-processing, Zwroty, Dekoracje',
    },
    'etykietowanie': {
        'nazwa': 'Dział etykietowania', 'ikona': '🏷️',
        'obszary': (PRZYDZIELANIE, PRACOWNICY, POST_PROCESS, DISPLAYS, ZWROTY, ZADANIA),
        'opis': 'Przydzielanie, Pracownicy, Post-Process, Dekoracje, Zwroty, Zadania dodatkowe',
    },
    'supervisor': {
        'nazwa': 'Supervisor', 'ikona': '🛡️', 'obszary': (USTAWIENIA,),
        'opis': 'Wszystkie ustawienia',
    },
}

# Rola → kafelki. Operator (skanowany na zmianie) nie loguje sie wcale.
ROLE_OBSZARY = {
    'stanowisko': MAGAZYN,
    'leader': (*MAGAZYN, PRZYDZIELANIE, PRACOWNICY, POST_PROCESS, DISPLAYS, ZWROTY, ZADANIA),
    'admin': (*MAGAZYN, PRZYDZIELANIE, PRACOWNICY, POST_PROCESS, DISPLAYS, ZWROTY, ZADANIA, USTAWIENIA),
}

# Dostepne zawsze po zalogowaniu (i przed wyborem kafelka).
WSPOLNE = frozenset({
    'static', 'auth.favicon', 'auth.index', 'auth.login', 'auth.logout', 'auth.profile',
    'auth.kafelki', 'auth.wybierz_obszar',
})

_ENDPOINTY = {
    MAGAZYN_ZMIANY: {
        # Skaner zmian
        'stanowisko.scanner', 'stanowisko.api_scan', 'stanowisko.api_unscan',
        'stanowisko.api_shift_attendances',
        # Czas pracy (przerwy, Inne, koniec pracy, szkolenia)
        'czas_pracy.time_tracking', 'czas_pracy.api_time_scan',
        'czas_pracy.api_training_aktywne', 'czas_pracy.api_training_trener',
        'czas_pracy.api_training_szkolony', 'czas_pracy.api_training_koniec',
    },
    MAGAZYN_PP: {
        # Czasy paczek
        'stanowisko.scan_paczki', 'stanowisko.api_employee_lookup',
        'stanowisko.api_package_time_start', 'stanowisko.api_package_time_end',
        'stanowisko.api_package_time_przekaz', 'stanowisko.api_package_time_dolacz',
        # Paczki inspektor
        'stanowisko.scan_package', 'stanowisko.api_package_lookup',
    },
    MAGAZYN_ZWROTY: {
        # Przyjecie zwrotu (2026-10-27) — wiersze raportu Zwroty Paczek
        'zwroty.przyjecie_zwrotu', 'zwroty.api_przyjecie_zwrotu', 'zwroty.api_przyjecie_sprawdz',
    },
    MAGAZYN_DEKORACJE: {
        # Dekoracje: skan stojakow nosnik → strefa (2026-10-28)
        'displays.skan_stojakow', 'displays.api_nosnik', 'displays.api_skan',
        # Dekoracje: dostawa produktow — kontener / Beeline (2026-10-29)
        'displays.dostawy_stanowisko', 'displays.api_kontener', 'displays.api_kontener_wiersz',
        'displays.api_beeline',
    },
    POST_PROCESS: {
        'dashboard.dashboard', 'dashboard.api_dashboard', 'dashboard.api_dashboard_plik',
        'dashboard.api_dashboard_zalegle', 'dashboard.api_dashboard_loading_dates',
        'dashboard.api_dashboard_shifts',
        'forecast.forecast_page', 'forecast.api_forecast_chart_data',
        'forecast.api_forecast_save', 'forecast.api_forecast_export',
        # Stary Wpis ilosci: PUT poprawia wpis z karty pracownika w Normach.
        'przydzial.api_daily_stats_get', 'przydzial.api_daily_stats_save',
        'przydzial.api_daily_stat_update',
        'normy.stats', 'normy.api_stats_overview', 'normy.api_stats_user',
        'normy.api_stats_target_update',
        'paczki.paczki_view', 'paczki.api_package_create', 'paczki.api_package_update',
        'paczki.api_package_double_rate', 'paczki.api_package_reassign',
        'paczki.api_package_categories_update', 'paczki.api_package_tabela_update',
        'paczki.api_package_potwierdz_roznice', 'paczki.api_package_unlock_scan',
        'paczki.api_package_zamknij_zespol',
        'imports.import_csv_page', 'imports.api_import_csv', 'imports.api_import_excel',
        'imports.api_imports', 'imports.api_imports_zmien_date',
        'rozliczenie.general_stats_page', 'rozliczenie.general_stats_export',
        'rozliczenie.api_general_stats', 'rozliczenie.api_general_stat_update',
        'rozliczenie.api_general_stat_use_scan',
    },
    PRZYDZIELANIE: {
        'przydzial.assignment', 'przydzial.api_assignment_data', 'przydzial.api_assignment_save',
        'przydzial.api_assignment_suggestions',
        # Przydzielanie → kolumna „Zwroty” → stanowiska (2026-10-27; tez w kafelku Zwroty)
        'zwroty.przydzial_zwrotow', 'zwroty.api_przydzial_zwrotow',
        'zwroty.api_przydzial_zwrotow_zapisz',
    },
    PRACOWNICY: {
        # Lista pracownikow (dawniej „Uzytkownicy” w Post-Process) + listy, ktore jej okno czyta
        'admin.admin_users', 'admin.api_users', 'admin.api_user_create',
        'admin.api_user_update', 'admin.api_user_delete',
        'admin.api_user_options', 'admin.api_activities',
        'czas_pracy.worker_times', 'czas_pracy.api_worker_times',
        'czas_pracy.api_time_event_create', 'czas_pracy.api_time_event_update',
        'czas_pracy.api_time_event_delete', 'czas_pracy.api_wejscie_update',
    },
    ZADANIA: {
        # Zadania dodatkowe (2026-11-02); stary adres Wpisu ilosci przekierowuje tutaj
        'zadania.zadania_dodatkowe', 'zadania.zadania_export', 'zadania.api_zadania',
        'zadania.api_zadanie_dodaj', 'zadania.api_zadanie_zmien', 'zadania.api_zadanie_usun',
        'zadania.stary_wpis_ilosci',
    },
    DISPLAYS: {
        # Akcje na Gantcie, ekran akcji z indexami, historia (2026-10-28)
        'displays.displays', 'displays.historia', 'displays.akcja',
        'displays.api_akcja_dodaj', 'displays.api_akcja_zmien', 'displays.api_akcja_status',
        'displays.api_etap_zmien',
        'displays.api_akcja_typ_dostawy', 'displays.api_dostawy', 'displays.api_pozycja_dostawy_usun',
        'displays.api_karton_beeline_usun', 'displays.dostawy_export',
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
        'zwroty.api_zwrot_popraw', 'zwroty.api_zwrot_czesc', 'zwroty.api_zwrot_usun',
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
        # Zadania dodatkowe (2026-11-02): lista czynnosci dodatkowych
        'zadania.admin_czynnosci', 'zadania.api_czynnosc_dodaj', 'zadania.api_czynnosc_zmien',
        'zadania.api_czynnosc_usun',
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
