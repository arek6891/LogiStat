"""Dekoracje (kafelek Dzialu etykietowania, operacja 2026-10-28) — stale i czysta
logika akcji, bez Flaska i bazy.

Akcja (nazwa, data od–do) jest nadrzedna; na Gantcie widac akcje niezakonczone,
zakonczone („Zakończ akcję”, da sie przywrocic) sa w historii. Akcja ma indexy
(„+”) — index to szablon / zestaw displaya z wlasnymi stojakami, ilosciami i
zalozona produktywnoscia (sztuki na osobogodzine; godzin jeszcze nie liczymy).
Puste pole = NULL, nie 0 — suma z brakujacym skladnikiem jest „niepelna”.
"""
from datetime import date

from logistat.pdf_etykiet import miesci_sie
from logistat.przyjecie_zwrotu import pos_nummer

# Listy z panelu admina (Supervisor → Listy Dekoracji).
TYP_STOJAKA = 'typ_stojaka'
MODEL_STOJAKA = 'model_stojaka'
STREFA = 'strefa'       # strefy magazynu dla stocku stojakow — nazwa = kod na etykiecie
RODZAJE_SLOWNIKA = {
    TYP_STOJAKA: 'Typ stojaka',
    MODEL_STOJAKA: 'Model stojaka',
    STREFA: 'Strefy (stock stojaków)',
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


# ── Kamienie milowe akcji (operacja 2026-10-29) ─────────────────────────────
# Stala lista etapow — w bazie tylko klucz (zmiana nazwy nie przepisuje historii).
# Kazdy etap ma termin od–do wewnatrz dat akcji; „mało do końca” / „po terminie”
# liczy `stan_etapu()`. Potwierdzania etapow jeszcze nie ma (operacja ustali, co
# je potwierdza) — do tego czasu etap po terminie zostaje „po terminie”.
# (klucz, nazwa, podpowiedz, opcjonalny — tylko taki moze byc „nie dotyczy”)
ETAPY_AKCJI = (
    ('komponenty', 'Dostawa komponentów', 'Logistyk nakłada zadanie (później z WMS)', False),
    ('produkty', 'Dostawa produktów na stojak', '', False),
    ('opakowania', 'Dostawa materiałów opakowaniowych', '', False),
    ('picking', 'Picking', 'Tylko gdy produkty przyszły nieposortowane', True),
    ('assembly', 'Skręcanie displayów (Assembly)', 'Nadajemy nr nośnika i miejsce', False),
    ('hakowanie', 'Hakowanie', 'Haki na wieże displayów; nr nośnika i miejsce (opcjonalnie)', False),
    ('dekoracje', 'Dekoracje', 'Przed startem POS przypisany do nośnika; nr nośnika i miejsce (opcjonalnie)', False),
    ('pakowanie', 'Pakowanie i zabezpieczanie', '', False),
    ('wysylka', 'Wysyłka — załadunek', 'Skan nośnika przy załadunku; awizacje wprowadza Logistyka / Dispo', False),
)
KLUCZE_ETAPOW = tuple(k for k, *_ in ETAPY_AKCJI)
# „Mało do końca”: do konca terminu zostalo najwyzej tyle dni (0 = konczy sie dzis).
DNI_OSTRZEZENIA_ETAPU = 2

ETAP_BEZ_TERMINU = 'bez_terminu'
ETAP_NIE_DOTYCZY = 'nie_dotyczy'
ETAP_PLANOWANY = 'planowany'
ETAP_W_TOKU = 'w_toku'
ETAP_KONCZY_SIE = 'konczy_sie'
ETAP_PO_TERMINIE = 'po_terminie'
ETAPY_OSTRZEZENIA = (ETAP_KONCZY_SIE, ETAP_PO_TERMINIE)


def stan_etapu(od, do, dzis, nie_dotyczy=False):
    """Stan etapu wzgledem `dzis` (dzien lokalny serwera), koniec wlacznie:
    dzis == do → „kończy się”, dzis == do + 1 → „po terminie”. Bez dat = bez
    ostrzezenia."""
    if nie_dotyczy:
        return ETAP_NIE_DOTYCZY
    if od is None or do is None:
        return ETAP_BEZ_TERMINU
    if dzis > do:
        return ETAP_PO_TERMINIE
    if (do - dzis).days <= DNI_OSTRZEZENIA_ETAPU:
        return ETAP_KONCZY_SIE
    return ETAP_W_TOKU if dzis >= od else ETAP_PLANOWANY


def data_z_tekstu(wartosc):
    """'YYYY-MM-DD' → date; None przy pustym / blednym (nigdy „dzis”)."""
    if not isinstance(wartosc, str) or not wartosc.strip():
        return None
    try:
        return date.fromisoformat(wartosc.strip())
    except ValueError:
        return None


# ── Etykiety POS (operacja 2026-10-28) ──────────────────────────────────────
# Lista numerow POS (point of sale) z Excela → arkusz etykiet z kodem kreskowym
# (PDF, drukuje sie z przegladarki). Kolumna „Post Processing” (tak / nie / puste
# = nie ustalono) poprawiana eksportem do Excela i ponownym importem (klucz = numer).
# Ze stockiem stojakow i nosnikami jeszcze sie nie laczy (pozniejszy modul).
NAGLOWKI_NUMERU_POS = ('pos', 'nr pos', 'numer pos', 'pos nr', 'pos-nummer', 'pos nummer',
                       'pos_nummer', 'point of sale', 'point of sell')
NAGLOWKI_PP = ('post processing', 'post-processing', 'postprocessing', 'pp')
NAGLOWEK_EKSPORTU_POS = ('POS', 'Post Processing')
TAK_PP = ('tak', 't', 'yes', 'y', 'ja', 'j', 'x', '1', 'true')
NIE_PP = ('nie', 'n', 'no', 'nein', '0', 'false', '-')
KOPIE_MAX = 20
ETYKIET_MAX = 5000      # na jeden wydruk (~210 arkuszy)


def naglowek(wartosc):
    """Naglowek kolumny do porownan: male litery, pojedyncze spacje."""
    return ' '.join(str(wartosc).split()).lower() if wartosc is not None else ''


def flaga_pp(wartosc):
    """Komorka „Post Processing” → (True | False | None, poprawna). Puste = None
    (nie ustalono). Excel daje bool / liczbe / tekst."""
    if wartosc is None or (isinstance(wartosc, str) and not wartosc.strip()):
        return None, True
    if isinstance(wartosc, bool):
        return wartosc, True
    if isinstance(wartosc, (int, float)) and wartosc in (0, 1):
        return bool(wartosc), True
    tekst = naglowek(wartosc)
    if tekst in TAK_PP:
        return True, True
    if tekst in NIE_PP:
        return False, True
    return None, False


def _numer_z_komorki(wartosc):
    """Komorka numeru → tekst. Liczba z Excela przychodzi jako float — bez „.0”
    (wiodace zera traci juz Excel, dlatego eksport zapisuje numer jako tekst)."""
    if wartosc is None or isinstance(wartosc, bool):
        return ''
    if isinstance(wartosc, float) and wartosc.is_integer():
        return str(int(wartosc))
    return str(wartosc).strip()


def wiersze_pos(wiersze):
    """Arkusz listy POS (krotki komorek, pierwsza = naglowki) →
    (`pozycje` {numer: post_processing}, `ma_pp`, `bledy` [{wiersz, wartosc, powod}]).

    Kolumna numeru wymagana (ValueError), „Post Processing” opcjonalna — bez niej
    import nie rusza flag (`ma_pp` False). Puste wiersze pomija; numer powtorzony
    w pliku liczy sie raz (wygrywa ostatni wiersz)."""
    wiersze = iter(wiersze)
    naglowki = [naglowek(k) for k in next(wiersze, ())]
    kol_nr = next((i for i, n in enumerate(naglowki) if n in NAGLOWKI_NUMERU_POS), None)
    if kol_nr is None:
        raise ValueError('Brak kolumny „POS” w pierwszym wierszu pliku (nagłówek: POS, Nr POS albo POS-Nummer).')
    kol_pp = next((i for i, n in enumerate(naglowki) if n in NAGLOWKI_PP), None)
    pozycje, bledy = {}, []
    for nr, w in enumerate(wiersze, start=2):
        surowy = _numer_z_komorki(w[kol_nr] if kol_nr < len(w) else None)
        komorka_pp = w[kol_pp] if kol_pp is not None and kol_pp < len(w) else None
        if not surowy:
            if komorka_pp not in (None, ''):
                bledy.append({'wiersz': nr, 'wartosc': '', 'powod': 'brak numeru POS'})
            continue
        numer = pos_nummer(surowy)
        if numer is None:
            bledy.append({'wiersz': nr, 'wartosc': surowy[:60], 'powod': 'niedozwolone znaki albo za długi'})
            continue
        if not miesci_sie(numer):
            bledy.append({'wiersz': nr, 'wartosc': numer, 'powod': 'za długi na etykietę'})
            continue
        pp, poprawna = flaga_pp(komorka_pp)
        if not poprawna:
            bledy.append({'wiersz': nr, 'wartosc': numer,
                          'powod': f'Post Processing „{str(komorka_pp)[:20]}” — wpisz Tak, Nie albo zostaw puste'})
            continue
        pozycje[numer] = pp
    return pozycje, kol_pp is not None, bledy


# ── Stock gotowych stojakow (operacja 2026-10-28) ────────────────────────────
# Stojak = nosnik (numer z etykiety nosnika). Wiersz zaklada pierwszy skan nosnika
# na stanowisku (Operacje magazynowe → Skan stojaków), potem skan strefy; kazda
# zmiana strefy to ruch (kto, kiedy, skad, dokad). POS (tylko z listy Etykiet POS)
# i akcje przypisuje lider w tabeli stocku.
NOSNIK_MAX = 50


def kod_nosnika(wartosc):
    """Zeskanowany numer nosnika: bez bialych znakow, wielkie litery, drukowalne
    ASCII. None = bledny (pusty, za dlugi, inne znaki)."""
    if not isinstance(wartosc, str):
        return None
    kod = ''.join(wartosc.split()).upper()
    if not kod or len(kod) > NOSNIK_MAX or any(not 33 <= ord(z) <= 126 for z in kod):
        return None
    return kod


def kod_strefy(wartosc):
    """Nazwa strefy = kod na jej etykiecie (skanowany): regula numeru POS
    (A–Z, 0–9, - _ / .) i musi zmiescic sie na etykiecie. None = bledna."""
    kod = pos_nummer(wartosc)
    return kod if kod is not None and miesci_sie(kod) else None


# ── Dostawa produktow (operacja 2026-10-29) ─────────────────────────────────
# Akcja ma jeden typ dostawy — ustala go logistyk przy tworzeniu akcji (zmiana
# mozliwa, dopoki akcja nie ma zadnego wpisu dostawy). Wpisuje magazynier na
# stanowisku (Operacje magazynowe → Dekoracje → Dostawy):
# - kontenerowa: nr kontenera, potem wiersze artykul / kartony / PU (suma per
#   kontener i per artykul w akcji),
# - Beeline: skan kodu z numerem kartonu (ten sam karton w akcji drugi raz → 409).
# Lider poprawia (✕) i eksportuje do Excela na ekranie akcji.
DOSTAWA_KONTENER = 'kontener'
DOSTAWA_BEELINE = 'beeline'
TYPY_DOSTAWY = {
    DOSTAWA_BEELINE: 'Dostawa z Beeline',
    DOSTAWA_KONTENER: 'Dostawa kontenerowa',
}
NAGLOWEK_DOSTAW_KONTENER = ('Kontener', 'Artykuł', 'Kartony', 'PU', 'Wpisano', 'Kto')
NAGLOWEK_KONTENEROW = ('Kontener', 'Wierszy', 'Kartony', 'PU', 'Pierwszy wpis')
NAGLOWEK_ARTYKULOW = ('Artykuł', 'Kartony', 'PU')
NAGLOWEK_BEELINE = ('Nr kartonu', 'Zeskanowano', 'Kto')


def kod_dostawy(wartosc):
    """Nr kontenera / artykulu / kartonu Beeline: regula numeru nosnika (bez
    bialych znakow, wielkie litery) — „123 ” i „123” to ten sam artykul."""
    return kod_nosnika(wartosc)


def sumy_dostaw(wiersze):
    """Wiersze dostawy kontenerowej (dict-y: kontener, artykul, kartony, pu) →
    (per kontener, per artykul, razem). Kolejnosc kontenerow = pierwsze
    wystapienie, artykuly alfabetycznie."""
    kontenery, artykuly = {}, {}
    razem = {'wierszy': 0, 'kartony': 0, 'pu': 0}
    for w in wiersze:
        k = kontenery.setdefault(w['kontener'], {'kontener': w['kontener'], 'wierszy': 0, 'kartony': 0, 'pu': 0})
        a = artykuly.setdefault(w['artykul'], {'artykul': w['artykul'], 'kartony': 0, 'pu': 0})
        for s in (k, razem):
            s['wierszy'] += 1
        for s in (k, a, razem):
            s['kartony'] += w['kartony']
            s['pu'] += w['pu']
    return list(kontenery.values()), sorted(artykuly.values(), key=lambda a: a['artykul']), razem
