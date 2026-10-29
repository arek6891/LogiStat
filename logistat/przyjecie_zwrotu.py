"""Przyjecie zwrotu (kafelek Magazyn, belka Zwroty, operacja 2026-10-27) — stale
i czysta logika, bez Flaska i bazy.

Pracownik magazynu przechodzi ekran po ekranie (kazdy z „Wstecz”); jeden
zapis = jeden wiersz raportu Zwroty Paczek. Naglowki raportu zostaja niemieckie
(arkusz klienta), ale pracownik ich nie widzi — na ekranach sa etykiety
z Ustawien (`etykieta_zwrotu:<klucz>`, pusta = domyslna ponizej).
"""
import re
from datetime import date, timedelta

from logistat.okresy import zlacz_okresy

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
# Domyslne z probki arkusza operacji (Return_September_2026) + TOSH (operacja
# 2026-10-29) — lista sie zmienia, admin ja edytuje w Ustawieniach.
LISTY_DOMYSLNE = {
    BRAND: ('ACC', 'SIX', 'NK', 'ITS', 'TOSH'),
    KURIER: ('DPD', 'UPS', 'Other'),
    OPAKOWANIE: ('Yes', 'VKM'),
}
ZNACZNIK_LIST = 'listy_przyjecia_zwrotow_seeded'
ZNACZNIK_TOSH = 'brand_tosh_dodany'   # dopisanie TOSH do baz zasianych przed 2026-10-29

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
    'retoure': 'Ilość paczek',
    'defekt': 'Uszkodzone',
    'neuwarenueberschuss': 'Nadwyżka nowego towaru',
    'silber': 'Srebro (szt.)',
    'defektes_silber': 'Uszkodzone srebro (szt.)',
    'reduzierte_ware': 'Towar przeceniony',
    'verpackungsvorschrift': 'Sposób pakowania',
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
    """Kolumna Woche: tydzien i rok daty przyjecia — „36-2026”. Jak Excel
    WEEKNUM(data; 2), nie ISO (operacja 2026-10-29): tydzien z 1 stycznia to
    zawsze 1, kolejne od poniedzialku, rok = rok kalendarzowy daty.
    31.12.2026 → „53-2026”, 01.01.2027 → „1-2027”, pon. 04.01.2027 → „2-2027”."""
    pierwszy = date(dzien.year, 1, 1)
    poczatek = pierwszy - timedelta(days=pierwszy.weekday())
    return f'{(dzien - poczatek).days // 7 + 1}-{dzien.year}'


def pos_nummer(wartosc):
    """POS-Nummer z ekranu: duze litery, bez spacji. None = bledny."""
    if not isinstance(wartosc, str):
        return None
    pos = ''.join(wartosc.split()).upper()
    if not pos or len(pos) > POS_MAX or not WZOR_POS.match(pos):
        return None
    return pos


# ── Przydzial osob do stanowisk zwrotow (operacja 2026-10-27) ────────────────
# Lider przydziela osoby z czynnosci „Zwroty” (Przydzielanie, po NAZWIE — zmiana
# nazwy czynnosci odcina ten ekran) do stanowisk = kont roli `stanowisko`, albo jako
# Support przy stanowisku (2026-10-29: bez paczek i statystyk, „pod wynik stolu”). Osoba liczy sie od chwili przydzialu do przeniesienia / zdjecia,
# skanu „Koniec pracy” albo MAX_GODZIN_PRZYDZIALU (zmiany nie maja godzin).
CZYNNOSC_ZWROTOW = 'Zwroty'
SUPPORT = 'support'
MAX_GODZIN_PRZYDZIALU = 12
# Ta sama paczka drugi raz na stanowisku (operacja 2026-10-29): odmowa. Paczka
# z kilku czesci (1/2, 2/2) dopisuje lider w Zwrotach Paczek.
KOMUNIKAT_JUZ_PRZYJETA = ('Paczka {numer} była już przyjęta {kiedy} ({gdzie}). Nie skanuj jej '
                          'ponownie. Jeśli to kolejna część przesyłki (np. 2/2), zgłoś to '
                          'liderowi — dopisze ją w Zwrotach Paczek.')
KOMUNIKAT_BRAK_OBSADY = ('Nie przydzielono nikogo do stanowiska! Skontaktuj się z liderem, '
                         'aby przydzielił stanowisko do zwrotów.')


def efektywne_okresy(wiersze, konce_pracy):
    """Okresy przydzialu, ktore naprawde licza sie do statystyk.

    `wiersze`: [(user_id, stanowisko_id | None, support, od, do | None)] (naive UTC),
    `konce_pracy`: {user_id: [czas work_end, …]}. Koniec okresu = najwczesniejsze
    z: `do`, pierwszy „Koniec pracy” po `od`, `od` + MAX_GODZIN_PRZYDZIALU. Okres
    jeszcze trwajacy siega w przyszlosc — godziny do statystyk przycina wolajacy
    (do „teraz”). Zwraca [(user_id, stanowisko_id, support, start, koniec)]."""
    wynik = []
    for user_id, stanowisko_id, support, od, do in wiersze:
        konce = [od + timedelta(hours=MAX_GODZIN_PRZYDZIALU)]
        if do is not None:
            konce.append(do)
        koniec_pracy = min((k for k in konce_pracy.get(user_id, ()) if k > od), default=None)
        if koniec_pracy is not None:
            konce.append(koniec_pracy)
        koniec = min(konce)
        if koniec > od:
            wynik.append((user_id, stanowisko_id, support, od, koniec))
    return wynik


def przerwy_osob(zdarzenia, teraz):
    """Przerwy i „Inne” z Czasu pracy jako zlaczone okresy {user_id: [(start, koniec)]}
    — odejmowane od godzin na stanowisku (czas netto, jak w Post-Processingu;
    szkolenie to praca, nie odejmuje sie). `zdarzenia`: [(user_id, shift_id, typ,
    czas)] posortowane po czasie. Pary w obrebie (osoba, zmiana) jak
    `_compute_worker_times` — niezamknieta przerwa z poniedzialku nie moze zjesc
    wtorku. Otwarty okres konczy „Koniec pracy” tej zmiany albo `teraz`."""
    otwarte, okresy = {}, {}
    for user_id, shift_id, typ, kiedy in zdarzenia:
        moje = otwarte.setdefault((user_id, shift_id), {})
        if typ in ('break_start', 'other_start'):
            moje.setdefault(typ[:-6], kiedy)
        elif typ in ('break_end', 'other_end'):
            start = moje.pop(typ[:-4], None)
            if start is not None:
                okresy.setdefault(user_id, []).append((start, kiedy))
        elif typ == 'work_end':
            for start in moje.values():
                okresy.setdefault(user_id, []).append((start, kiedy))
            moje.clear()
    for (user_id, _), moje in otwarte.items():
        for start in moje.values():
            okresy.setdefault(user_id, []).append((start, teraz))
    return {u: zlacz_okresy(o) for u, o in okresy.items()}


def kto_na_stanowisku(okresy, stanowisko_id, chwila):
    """Osoby (posortowane id) na stanowisku w danej chwili — z `efektywne_okresy()`.
    Jedyna definicja: blokada przyjecia zwrotu i dashboard licza tak samo.
    Okres [start, koniec) — przy przeniesieniu o 10:00 paczka z 10:00 idzie na nowe miejsce."""
    return sorted({u for u, s, sup, start, koniec in okresy
                   if not sup and s == stanowisko_id and start <= chwila < koniec})
