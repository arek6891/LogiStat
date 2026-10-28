"""Dekoracje (kafelek Dzialu etykietowania, operacja 2026-10-28) — stale i czysta
logika akcji, bez Flaska i bazy.

Akcja (nazwa, data od–do) jest nadrzedna; na Gantcie widac akcje niezakonczone,
zakonczone („Zakończ akcję”, da sie przywrocic) sa w historii. Akcja ma indexy
(„+”) — index to szablon / zestaw displaya z wlasnymi stojakami, ilosciami i
zalozona produktywnoscia (sztuki na osobogodzine; godzin jeszcze nie liczymy).
Puste pole = NULL, nie 0 — suma z brakujacym skladnikiem jest „niepelna”.
"""
from datetime import date

# Listy z panelu admina (Supervisor → Listy Dekoracji).
TYP_STOJAKA = 'typ_stojaka'
MODEL_STOJAKA = 'model_stojaka'
RODZAJE_SLOWNIKA = {
    TYP_STOJAKA: 'Typ stojaka',
    MODEL_STOJAKA: 'Model stojaka',
}
SLOWNIK_DOMYSLNY = {
    TYP_STOJAKA: ('Twin', 'Solo'),
    MODEL_STOJAKA: ('Gondola',),
}
ZNACZNIK_SLOWNIKA = 'slownik_dekoracji_seeded'

NAZWA_MAX = 150
NAZWA_SLOWNIKA_MAX = 100
# Wiecej to raczej zeskanowany kod w polu liczby (jak ILOSC_WYGLADA_NA_KOD).
LICZBA_MAX = 100_000

# Pola indexu: (klucz, etykieta). Kolejnosc = kolejnosc na ekranie. RGD / DISPLAYS /
# Akcesoria = sztuki LACZNIE dla indexu (do potwierdzenia z operacja).
POLA_LICZB = (
    ('ilosc_stojakow', 'Ilość stojaków'),
    ('haki_na_stojak', 'Haków na stojak'),
    ('strony_na_stojak', 'Stron na stojak'),
    ('rgd', 'RGD (szt.)'),
    ('displays', 'DISPLAYS (szt.)'),
    ('akcesoria', 'Akcesoria (szt.)'),
    ('pos', 'Liczba POS'),
)
POLA_PRODUKTYWNOSCI = (
    ('prod_hakowania', 'Hakowanie'),
    ('prod_dekorowania', 'Dekorowanie'),
)
POLA_SLOWNIKA = (('typ_id', TYP_STOJAKA), ('model_id', MODEL_STOJAKA))
# Sumy akcji (podsumowanie nad indexami); haki = stojaki × haki na stojak.
POLA_SUM = ('ilosc_stojakow', 'haki', 'rgd', 'displays', 'akcesoria', 'pos')


def haki_razem(ilosc_stojakow, haki_na_stojak):
    """Haki potrzebne dla wszystkich stojakow indexu; None, gdy czegos brak."""
    if ilosc_stojakow is None or haki_na_stojak is None:
        return None
    return ilosc_stojakow * haki_na_stojak


def podsumowanie(indexy):
    """Sumy akcji z indexow (dict-y z polami POLA_LICZB). Kazda suma:
    {'suma': int, 'pelna': bool} — `pelna` False, gdy ktorys index ma puste pole
    (suma liczy wtedy tylko wpisane). Bez indexow: suma 0, pelna True."""
    wynik = {}
    for pole in POLA_SUM:
        wartosci = [haki_razem(i.get('ilosc_stojakow'), i.get('haki_na_stojak')) if pole == 'haki'
                    else i.get(pole) for i in indexy]
        wynik[pole] = {'suma': sum(w for w in wartosci if w is not None),
                       'pelna': all(w is not None for w in wartosci)}
    return wynik


def po_terminie(data_do, dzis):
    """Niezakonczona akcja po dacie konca — zostaje na Gantcie z ostrzezeniem."""
    return data_do < dzis


def data_z_tekstu(wartosc):
    """'YYYY-MM-DD' → date; None przy pustym / blednym (nigdy „dzis”)."""
    if not isinstance(wartosc, str) or not wartosc.strip():
        return None
    try:
        return date.fromisoformat(wartosc.strip())
    except ValueError:
        return None
