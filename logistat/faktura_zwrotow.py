"""Raporty zwrotow (kafelek Zwroty, 2026-10-26) — stale bez Flaska i bazy.

Uklad 1:1 z arkuszy operacji „Invoice specification” i „Sorting Data”
(raport dla klienta — angielskie nazwy zostaja, nie tlumaczyc).
"""

# Invoice specification: (klucz, Activity, UoM). Kolejnosc = wiersze raportu.
CZYNNOSCI_FAKTURY = (
    ('sorting_returns', 'Sorting returns', 'box'),
    ('palletizing', 'Palletizing sorted articles', 'box'),
    ('unloading', 'Unloading pallets', 'pallet'),
    ('weighing', 'Taking weight of pallets', 'pallet'),
    ('loading', 'Loading pallets', 'pallet'),
)
KLUCZE_FAKTURY = tuple(k for k, _, _ in CZYNNOSCI_FAKTURY)
# Liczone przez system: Sorting returns = liczba wierszy raportu Zwroty Paczek
# w miesiacu (jedna paczka = jeden wiersz; powtorzony Paketnummer liczy sie znowu).
CZYNNOSCI_AUTO = frozenset({'sorting_returns'})

# Sorting Data: dwie listy wierszy, edytowane przez admina (Ustawienia).
LICENCJA = 'licencja'   # wiersze nad „Total boxes built” (Cartons / Pallets)
WYSYLKA = 'wysylka'     # wiersze „… boxes shipped” pod nim
RODZAJE_LICENCJI = {LICENCJA: 'Licencje (boxes built)', WYSYLKA: 'Wysyłki (boxes shipped)'}
LICENCJE_DOMYSLNE = {
    LICENCJA: ('RECYKLING', '996 -', 'SILVER', 'C&A', 'DISNEY', 'New Balance', 'Marvel',
               'Peppa', 'Paw Patrol', 'SUN-OZON RETURN', 'Other licenses'),
    WYSYLKA: ('Recykling boxes shipped', 'Silver boxes shipped', 'Disney boxes shipped',
              'Marvel boxes shipped', 'Sun Ozon boxes shipped', 'New Bal/Rebbok shipped',
              'Other licenses'),
}
ZNACZNIK_LICENCJI = 'licencje_zwrotow_seeded'
NAZWA_LICENCJI_MAX = 100

# Pola Sorting Data: ilosci licencji / wysylek + jeden wiersz POS processed.
POLA_SORTING = ('cartons', 'pallets')
KLUCZ_POS = 'pos_processed'

MIESIACE_EN = ('January', 'February', 'March', 'April', 'May', 'June', 'July',
               'August', 'September', 'October', 'November', 'December')

# Wpisywane liczby: calkowite >= 0, ponizej tego (literowka / zeskanowany kod).
MAX_ILOSC_ZWROTOW = 10_000_000
