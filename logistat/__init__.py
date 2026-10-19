"""LogiStat — pakiet z logika aplikacji (podzial app.py, 2026-10-16).

Moduly tu NIE importuja `app` ani Flaska: czysta logika, testowalna bez bazy.
`app.py` je importuje i re-eksportuje, wiec `import app as logistat` w testach
i `gunicorn app:app` dzialaja bez zmian. Plan dalszych krokow:
docs/ARCHITEKTURA.md („Przeglad architektury i plan podzialu app.py").
"""
