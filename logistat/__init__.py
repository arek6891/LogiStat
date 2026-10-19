"""LogiStat — pakiet aplikacji.

Uklad i kierunek zaleznosci (pilnuja tests/test_logistat_moduly.py i test_trasy.py):
    web/ (blueprinty, warstwa HTTP) → uslugi (rozliczenie, paczki, normy_dane, …)
    → models/ → extensions (db, login_manager);  czysta logika: czas, kategorie,
    tabela_ilosci, okresy, normy — bez Flaska i bazy.
Aplikacje buduje `create_app()` (logistat/aplikacja.py) — bez dotykania bazy;
schemat, migracje i seed robi `logistat.baza.init_db()`. Punkt wejscia
`gunicorn app:app` (app.py). Historia podzialu: docs/ARCHITEKTURA.md.

Ten plik celowo nic nie importuje: import czystego modulu (np. `logistat.czas`)
laduje najpierw pakiet, a nie moze przy tym ciagnac Flaska.
"""


def create_app():
    """Aplikacja Flask — patrz `logistat.aplikacja.create_app`."""
    from logistat.aplikacja import create_app as _create_app
    return _create_app()
