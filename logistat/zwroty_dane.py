"""Zwroty Paczek (kafelek Zwroty, od 2026-10-26) — dane tabeli.

Naglowki = dokladnie te z arkusza „Return_September_2026” operacji (nazwy,
pisownia i kolejnosc — tabela jest dalej przekazywana klientowi). Ekran i
eksport do Excela biora wiersze z JEDNEJ funkcji `wiersze_zwrotow()`, zeby nie
rozjechaly sie, gdy dojda zrodla danych.

Zrodla poszczegolnych kolumn ustalamy z operacja krok po kroku — do tego czasu
`wiersze_zwrotow()` zwraca pusta liste (bez zgadywanego modelu w bazie:
`migrate_columns()` umie tylko dokladac kolumny, nie zmieniac ich).
"""

NAGLOWKI_ZWROTOW = (
    'Paketnummer', 'Brand', 'Date', 'POS-Nummer', 'DPD', 'UPS', 'Retoure', 'Defekt',
    'Neuwarenueberschuss', 'Silber_in_Stück', 'Defektes_Silber_in_Stück',
    'Reduzierte_ware', 'Verpackungsvorschrift', 'Monat', 'Woche',
)


def wiersze_zwrotow(od, do, brand=None, paketnummer=None):
    """Wiersze tabeli z dni [od, do] (daty lokalne, wlacznie) — kazdy jako krotka
    wartosci w kolejnosci `NAGLOWKI_ZWROTOW`. `brand` = dokladna wartosc,
    `paketnummer` = fragment numeru. Na razie brak zrodla danych → []."""
    return []


def brandy_zwrotow():
    """Wartosci Brand do listy w filtrze (z danych). Na razie brak danych → []."""
    return []
