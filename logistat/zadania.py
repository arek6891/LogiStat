"""Zadania dodatkowe (operacja 2026-11-02) — czysta logika, bez Flaska i bazy.

Ekran zastepuje „Wpis ilosci”: lider wpisuje, ile czasu osoba spedzila na dziale
(od–do na suwaku) i jaka czynnosc dodatkowa robila (lista admina: sprzatanie,
5S…), z komentarzem; bez ilosci. Dzialy sa stala (operacja), czynnosci edytuje admin.
"""
from datetime import timedelta

from logistat.czas import local_day_bounds

# Klucz w bazie → nazwa na ekranie. Kolejnosc = kolejnosc na liscie.
DZIALY = {
    'post_process': 'Post-Process',
    'dekoracje': 'Dekoracje',
    'zwroty': 'Zwroty',
    'magazyn': 'Magazyn',
}
KOMENTARZ_MAX = 300
NAZWA_CZYNNOSCI_MAX = 100
# Zmiany nie maja godzin, a druga pracuje po polnocy: suwak obejmuje dzien zmiany
# od polnocy do GODZIN_PO_POLNOCY nastepnego dnia.
GODZIN_PO_POLNOCY = 6
MAX_GODZIN_ZADANIA = 16
MAX_DNI_EKSPORTU = 366

ZNACZNIK_CZYNNOSCI = 'czynnosci_dodatkowe_seeded'
CZYNNOSCI_DOMYSLNE = ('5S', 'Sprzątanie')


def okno_zmiany(dzien):
    """[poczatek, koniec) suwaka dla zmiany z dnia `dzien` (naive UTC)."""
    return local_day_bounds(dzien)[0], local_day_bounds(dzien + timedelta(days=1))[0] \
        + timedelta(hours=GODZIN_PO_POLNOCY)


def blad_zakresu(od, do, dzien):
    """Komunikat 400 albo None: od < do, najwyzej MAX_GODZIN_ZADANIA, w oknie zmiany."""
    if do <= od:
        return 'Koniec musi być po początku.'
    if do - od > timedelta(hours=MAX_GODZIN_ZADANIA):
        return f'Najwyżej {MAX_GODZIN_ZADANIA} h w jednym wierszu.'
    poczatek, koniec = okno_zmiany(dzien)
    if od < poczatek or do > koniec:
        return (f'Czas musi mieścić się w dniu zmiany (do {GODZIN_PO_POLNOCY}:00 '
                'następnego dnia).')
    return None


def godziny(od, do):
    return (do - od).total_seconds() / 3600
