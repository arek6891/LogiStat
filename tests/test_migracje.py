"""`migrate_columns()` — dokladanie kolumn do ZYJACEJ bazy.

`db.create_all()` tworzy brakujace TABELE, ale nigdy nie dokłada kolumny do
tabeli, ktora juz istnieje. Nowa kolumna musi wiec przyjsc z `migrate_columns()`,
inaczej po wdrozeniu kazde zapytanie dotykajace modelu konczy sie
`UndefinedColumn` — a zwykle testy tego nie widza, bo conftest stawia schemat
od zera przy kazdym tescie. Te testy symuluja stan produkcyjny: kasuja kolumne
i sprawdzaja, czy wraca.
"""
import pytest
from sqlalchemy import text

import app as logistat

KOLUMNY = [
    ('general_stat', 'category_source'),
    ('imported_carton', 'scan_category_data'),
]


def _kolumny(tabela):
    rows = logistat.db.session.execute(text(
        'SELECT column_name FROM information_schema.columns '
        'WHERE table_name = :t'), {'t': tabela}).fetchall()
    return {r[0] for r in rows}


@pytest.mark.parametrize('tabela,kolumna', KOLUMNY)
def test_migracja_przywraca_skasowana_kolumne(flask_app, tabela, kolumna):
    logistat.db.session.execute(text(f'ALTER TABLE {tabela} DROP COLUMN {kolumna}'))
    logistat.db.session.commit()
    assert kolumna not in _kolumny(tabela), 'przygotowanie testu zawiodlo'

    logistat.migrate_columns()

    assert kolumna in _kolumny(tabela)


def test_migracja_jest_idempotentna(flask_app):
    """Leci przy kazdym starcie kazdego workera — nie moze wybuchac."""
    logistat.migrate_columns()
    logistat.migrate_columns()

    for tabela, kolumna in KOLUMNY:
        assert kolumna in _kolumny(tabela)


def test_zapytanie_na_modelu_dziala_po_migracji(flask_app):
    """Sedno sprawy: brak kolumny = UndefinedColumn na kazdym zapytaniu."""
    logistat.db.session.execute(text(
        'ALTER TABLE general_stat DROP COLUMN category_source'))
    logistat.db.session.commit()
    logistat.db.session.rollback()

    logistat.migrate_columns()

    assert logistat.GeneralStat.query.count() == 0
