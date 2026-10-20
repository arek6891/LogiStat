"""Modele bazy danych podzielone wedlug obszarow (2026-10-16, krok 3).

Kazdy model importuje `db` z `logistat.extensions`. Ten plik zbiera wszystkie,
zeby `db.create_all()` widzial komplet tabel niezaleznie od tego, ktory modul
zaimportowano pierwszy; app.py importuje stad.
"""
from logistat.models.ustawienia import (  # noqa: F401
    AppSetting,
    SETTING_DEFAULTS,
    get_setting,
    get_setting_int,
    set_setting,
)
from logistat.models.uzytkownicy import (  # noqa: F401
    User,
    USER_OPTION_KINDS,
    USER_OPTION_DEFAULTS,
    UserOption,
    user_options_by_kind,
    ROLES,
    PRIVILEGED_ROLES,
    active_admin_count,
    ProbaLogowania,
)
from logistat.models.zmiany import (  # noqa: F401
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
)
from logistat.models.rozliczenie import (  # noqa: F401
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
)
from logistat.models.paczki import (  # noqa: F401
    ImportedCarton,
    UDZIAL_PRZEKAZANA,
    UDZIAL_ZESPOL,
    UdzialPaczki,
)
from logistat.models.czas_pracy import (  # noqa: F401
    WorkerTimeEvent,
    EVENT_TYPES,
    TRYBY_CZASU,
    TRYBY_SKANU,
    KOMUNIKATY_TRWANIA,
    HistoriaCelu,
    historia_celu_lista,
    POCZATEK_HISTORII_CELU,
)
