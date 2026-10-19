"""Dashboard — dane z bazy: plan pliku (wrzucone / zrobione / pozostalo / w toku
per Loading date), plany dni z zakresu, zalegle paczki. Wspolne agregaty
`_agregaty_planu` / `_wiersz_planu` = te same kolumny w kazdej zakladce."""
from sqlalchemy import and_, case, func, or_

from logistat.extensions import db
from logistat.models import ImportedCarton


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
