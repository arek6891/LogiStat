"""Przyjecie zwrotu (kafelek Magazyn, belka Zwroty, operacja 2026-10-27) — stale
i czysta logika, bez Flaska i bazy.

Pracownik magazynu przechodzi ekran po ekranie (kazdy z „Wstecz”); jeden
zapis = jeden wiersz raportu Zwroty Paczek. Naglowki raportu zostaja niemieckie
(arkusz klienta), ale pracownik ich nie widzi — na ekranach sa etykiety
z Ustawien (`etykieta_zwrotu:<klucz>`, pusta = domyslna ponizej).
"""
import re

# Listy z przyciskami (Ustawienia → Przyjęcie zwrotu). Ta sama tabela co listy
# Sorting Data (`licencja_zwrotow.rodzaj`), osobne rodzaje.
BRAND = 'brand'
KURIER = 'kurier'
OPAKOWANIE = 'opakowanie'   # Verpackungsvorschrift
RODZAJE_PRZYJECIA = {
    BRAND: 'Brand',
    KURIER: 'Kurierzy',
    OPAKOWANIE: 'Verpackungsvorschrift',
}
# Domyslne z probki arkusza operacji (Return_September_2026) — admin poprawia.
LISTY_DOMYSLNE = {
    BRAND: ('ACC', 'SIX', 'NK', 'ITS'),
    KURIER: ('DPD', 'UPS', 'Other'),
    OPAKOWANIE: ('Yes', 'VKM'),
}
ZNACZNIK_LIST = 'listy_przyjecia_zwrotow_seeded'

# Ekrany z liczba: (klucz = kolumna modelu, naglowek raportu, minimum, domyslna).
# Retoure nie moze byc 0 ani puste (operacja) — paczka to co najmniej jeden zwrot.
LICZNIKI = (
    ('retoure', 'Retoure', 1, 1),
    ('defekt', 'Defekt', 0, 0),
    ('neuwarenueberschuss', 'Neuwarenueberschuss', 0, 0),
    ('silber', 'Silber_in_Stück', 0, 0),
    ('defektes_silber', 'Defektes_Silber_in_Stück', 0, 0),
    ('reduzierte_ware', 'Reduzierte_ware', 0, 0),
)
# Wiecej to raczej zeskanowany kod w polu liczby niz realna ilosc w paczce.
MAX_LICZNIK = 100_000

# POS-Nummer: zawsze duze litery; przycisk „brak numeru” wpisuje to, co stoi
# w arkuszu operacji przy paczkach bez POS.
BRAK_POS = 'NO'
WZOR_POS = re.compile(r'^[A-Z0-9][A-Z0-9\-_/.]*$')
POS_MAX = 50
PAKETNUMMER_MAX = 100
NAZWA_LISTY_MAX = 100
TOKEN_MAX = 64

# Etykiety ekranow (klucz → domyslna). Kolejnosc = kolejnosc ekranow.
ETYKIETY_DOMYSLNE = {
    'paketnummer': 'Zeskanuj numer paczki',
    'brand': 'Wybierz brand',
    'pos_nummer': 'Numer POS',
    'brak_pos': 'Brak numeru POS',
    'kurier': 'Wybierz kuriera',
    'retoure': 'Ilość zwrotów',
    'defekt': 'Uszkodzone',
    'neuwarenueberschuss': 'Nadwyżka nowego towaru',
    'silber': 'Srebro (szt.)',
    'defektes_silber': 'Uszkodzone srebro (szt.)',
    'reduzierte_ware': 'Towar przeceniony',
    'verpackungsvorschrift': 'Instrukcja pakowania',
}
# Co admin widzi obok etykiety — z jaka kolumna raportu sie wiaze.
KOLUMNA_ETYKIETY = {
    'paketnummer': 'Paketnummer', 'brand': 'Brand', 'pos_nummer': 'POS-Nummer',
    'brak_pos': 'POS-Nummer (przycisk „brak”)', 'kurier': 'DPD / UPS / … (kurierzy)',
    **{k: n for k, n, _, _ in LICZNIKI},
    'verpackungsvorschrift': 'Verpackungsvorschrift',
}
KLUCZ_ETYKIETY = 'etykieta_zwrotu:'
ETYKIETA_MAX = 80

MIESIACE_PL = ('styczeń', 'luty', 'marzec', 'kwiecień', 'maj', 'czerwiec', 'lipiec',
               'sierpień', 'wrzesień', 'październik', 'listopad', 'grudzień')


def monat(dzien):
    """Kolumna Monat: polski miesiac i rok daty przyjecia — „wrzesień-2026”."""
    return f'{MIESIACE_PL[dzien.month - 1]}-{dzien.year}'


def woche(dzien):
    """Kolumna Woche: tydzien i rok daty przyjecia — „36-2026”. Tydzien ISO
    (poniedzialek–niedziela) i rok tego tygodnia: 31.12.2026 → „53-2026”,
    01.01.2027 tez „53-2026” (ten sam tydzien)."""
    rok, tydzien, _ = dzien.isocalendar()
    return f'{tydzien}-{rok}'


def pos_nummer(wartosc):
    """POS-Nummer z ekranu: duze litery, bez spacji. None = bledny."""
    if not isinstance(wartosc, str):
        return None
    pos = ''.join(wartosc.split()).upper()
    if not pos or len(pos) > POS_MAX or not WZOR_POS.match(pos):
        return None
    return pos
