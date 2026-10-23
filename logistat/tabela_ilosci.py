"""Tabela ilosci na koniec paczki: walidacja, mapowanie na kolumny rozliczenia,
Nadwyzka/Brak, powody ❗. Czysta logika — liczy serwer.

Dwie wersje zapisanej tabeli (`ImportedCarton.tabela_ilosci`, `UdzialPaczki.tabela`):
- **wersja 2** (od 2026-10-23, `'wersja': 2`) — operator wpisuje wszystko wprost:
  per grupa Ilosc (pojedyncze) / Uszkodzone / Niesprocesowane, na paczke
  Podwojne / Potrojne / Flagi – Card Change; Nadwyzka i Brak liczy system
  z roznicy z Stückzahl. Ekran pisze tylko te wersje;
- **wersja 1** (2026-10-15…22, bez klucza `wersja`) — stary ksztalt (Brak /
  Nadwyzka wpisywane, „Pojedynczo" ze wzoru, dodatki). Tylko ODCZYT: paczki
  juz zapisane licza sie dalej starymi regulami (`_v1` ponizej), inaczej
  sprawdz_spojnosc.py zglosilby rozjazd, a rozliczenie zmieniloby sie wstecz.
"""
import json

from logistat.kategorie import liczba

# ── Wersja 2 (2026-10-23, operacja) ──────────────────────────────────────────
WERSJA_TABELI = 2
# Per grupa: Ilosc = sztuki oklejone pojedynczo, Uszkodzone, Niesprocesowane.
POLA_GRUPY_V2 = [('ilosc', 'Ilość (pojedyncze)'), ('uszkodzone', 'Uszkodzone'),
                 ('niesprocesowane', 'Niesprocesowane')]
# Na cala paczke (pod tabela): Podwojne / Potrojne ze wszystkich grup, Flagi.
POLA_PACZKI_V2 = [('karty', 'Flagi – Card Change'), ('podwojnie', 'Podwójne'),
                  ('potrojnie', 'Potrójne')]
BLAD_STARY_EKRAN = ('Ekran stanowiska jest nieaktualny (zmieniła się tabela ilości). '
                    'Odśwież stronę (F5) i wpisz ilości jeszcze raz — nic nie zapisano.')


# ── Wspolne obu wersjom ───────────────────────────────────────────────────────
# Grupy artykulowe = wiersze tabeli (stale, bez CRUD).
GRUPY_ARTYKULOWE = [
    ('bizuteria', 'Biżuteria'),
    ('akcesoria', 'Akcesoria'),
    ('okulary', 'Okulary'),
    ('tekstylia', 'Tekstylia'),
]
NAZWY_GRUP = dict(GRUPY_ARTYKULOWE)
# Biżuteria → Labelling one; pozostale grupy → wlasna kolumna (kazda ma swoja stawke).
GRUPA_GLOWNA = 'bizuteria'
KATEGORIA_GRUPY = {'akcesoria': 'accessoire', 'okulary': 'sunglasses', 'tekstylia': 'textile'}
# Paczka jednej osoby (`wzor`, nazwa z wersji 1) vs paczka kilku osob (`zespol`:
# kazdy wpisuje swoja czesc, karton = suma). W wersji 2 formularz jest ten sam,
# tryb decyduje o zapisie (karton / udzial) i o 409 `zmiana_trybu`.
TRYB_WZOR = 'wzor'
TRYB_ZESPOL = 'zespol'
# LOGIKA_KLEJENIA.xlsx: pierwsza etykieta = 1, kazda kolejna = 0,5.
MNOZNIK_PODWOJNIE = 1.5
MNOZNIK_POTROJNIE = 2
# Liczba od tej wartosci to prawie na pewno zeskanowany kod, nie ilosc sztuk
# (ta sama granica co WYGLADA_NA_KOD w static/js/tabela_ilosci.js).
ILOSC_WYGLADA_NA_KOD = 100000

# ── Wersja 1 (2026-10-15…22) — tylko odczyt zapisanych tabel ─────────────────
# Wiersze = grupy, kolumny Brak / Nadwyzka / Uszkodzone / Podwojnie / Potrojnie
# wpisywane, „Pojedynczo" ze wzoru (Ilosc biżuterii = Stückzahl − reszta grup),
# pod spodem dodatki. Decyzje operacji: docs/ARCHITEKTURA.md.
POLA_GRUPY = ['ilosc', 'brak', 'nadwyzka', 'uszkodzone', 'podwojnie', 'potrojnie', 'pojedynczo']
DODATKI_TABELI = [
    ('sortowanie_inne', 'Sortowanie inne'),
    ('karta_uszkodzona', 'Podmiana karty uszkodzonej'),
    ('karta_algorytm', 'Podmiana karty ze względu na algorytm'),
    ('worki', 'Etykietowanie worków'),
]


def _pusta_grupa():
    return {pole: 0 for pole in POLA_GRUPY}


def jest_v2(tabela):
    return bool(tabela) and tabela.get('wersja') == WERSJA_TABELI


def normalizuj_tabele(surowe, tryb, stueckzahl):
    """Waliduje tabele z ekranu (wersja 2). Zwraca (tabela, blad).

    Operator wpisuje wszystko wprost (oba tryby tak samo), serwer tylko
    sprawdza liczby. Ksztalt bez `wersja: 2` = karta stanowiska otwarta przed
    wdrozeniem (stara tabela) → blad, nic nie zapisane: odczytana jako nowa
    dalaby prawie same zera i ciche rozliczenie.
    """
    if not isinstance(surowe, dict):
        return None, 'Nieprawidłowy format tabeli ilości.'
    if surowe.get('wersja') != WERSJA_TABELI:
        return None, BLAD_STARY_EKRAN
    grupy_we = surowe.get('grupy') or {}
    if not isinstance(grupy_we, dict):
        return None, 'Nieprawidłowy format tabeli ilości.'

    def wartosc(slownik, pole, opis):
        v = slownik.get(pole)
        if v in (None, ''):
            return 0, None
        try:
            n = int(v)
        except (TypeError, ValueError):
            return None, f'{opis}: wpisz liczbę całkowitą.'
        if n < 0:
            return None, f'{opis}: ilość nie może być ujemna.'
        if n >= ILOSC_WYGLADA_NA_KOD:
            return None, f'{opis}: {n} wygląda na zeskanowany kod, nie liczbę sztuk.'
        return n, None

    tabela = {'wersja': WERSJA_TABELI, 'tryb': tryb, 'grupy': {}}
    for g, nazwa in GRUPY_ARTYKULOWE:
        we = grupy_we.get(g) or {}
        if not isinstance(we, dict):
            return None, 'Nieprawidłowy format tabeli ilości.'
        wiersz = {}
        for pole, opis in POLA_GRUPY_V2:
            n, blad = wartosc(we, pole, f'{nazwa} – {opis}')
            if blad:
                return None, blad
            wiersz[pole] = n
        tabela['grupy'][g] = wiersz
    for pole, opis in POLA_PACZKI_V2:
        n, blad = wartosc(surowe, pole, opis)
        if blad:
            return None, blad
        tabela[pole] = n
    # Pusta tabela przechodzi: paczka bez zadnej sztuki = cala ilosc jako Brak
    # (❗ dla lidera). Przypadkowy Enter na nietknietej tabeli zatrzymuje ekran
    # (static/js/tabela_ilosci.js) — tam widac, czy pole puste, czy wpisane „0”.
    return tabela, None


def nadwyzka_brak(tabela, stueckzahl):
    """(nadwyzka, brak) kartonu: wpisane sztuki vs Stückzahl z pliku (wersja 2)."""
    roznica = sztuki_tabeli(tabela) - int(stueckzahl or 0)
    return max(roznica, 0), max(-roznica, 0)


def na_wersje_2(tabela):
    """Dowolna zapisana tabela → wersja 2 (okno lidera dla starej paczki,
    paczka zespolu z udzialami w obu wersjach). Wersja 1: Ilosc = jej
    „Pojedynczo”, Podwojne/Potrojne = suma grup, Flagi = obie podmiany kart,
    „Sortowanie inne” → Niesprocesowane biżuterii (obie szly do Sorting).
    Worki i Brak/Nadwyzka nie maja odpowiednika (Nadwyzka/Brak liczy system)."""
    if not tabela or jest_v2(tabela):
        return tabela
    grupy = tabela.get('grupy') or {}
    dod = tabela.get('dodatki') or {}
    wynik = {'wersja': WERSJA_TABELI, 'tryb': tabela.get('tryb') or TRYB_WZOR, 'grupy': {},
             'podwojnie': 0, 'potrojnie': 0,
             'karty': (dod.get('karta_uszkodzona') or 0) + (dod.get('karta_algorytm') or 0)}
    for g, _ in GRUPY_ARTYKULOWE:
        w = grupy.get(g) or {}
        wynik['grupy'][g] = {'ilosc': w.get('pojedynczo', 0) or 0,
                             'uszkodzone': w.get('uszkodzone', 0) or 0,
                             'niesprocesowane': 0}
        wynik['podwojnie'] += w.get('podwojnie', 0) or 0
        wynik['potrojnie'] += w.get('potrojnie', 0) or 0
    wynik['grupy'][GRUPA_GLOWNA]['niesprocesowane'] = dod.get('sortowanie_inne') or 0
    return wynik


# Dymek „ⓘ" przy kolumnie w Statystykach ogolnych: skad sie bierze ilosc.
# Musi sie zgadzac z kategorie_z_tabeli() — zmiana tam = zmiana tu.
ZRODLO_KATEGORII = {
    'labelling_on': 'Biżuteria → „Ilość (pojedyncze)”. Paczki 15–22.10.2026: biżuteria „Pojedynczo”.',
    'labelling_tvl': '„Podwójne” (wszystkie grupy) × 1,5. Pierwsza etykieta liczy się jako 1, każda kolejna jako 0,5 (2 sztuki = 3). Paczki 15–22.10.2026: tylko biżuteria.',
    'labelling_try': '„Potrójne” (wszystkie grupy) × 2. Pierwsza etykieta liczy się jako 1, każda kolejna jako 0,5 (3 sztuki = 6). Paczki 15–22.10.2026: tylko biżuteria.',
    'textile': 'Tekstylia → „Ilość (pojedyncze)”. Paczki 15–22.10.2026: wszystkie sztuki grupy bez uszkodzonych (z podwójnymi i potrójnymi).',
    'accessoire': 'Akcesoria → „Ilość (pojedyncze)”. Paczki 15–22.10.2026: wszystkie sztuki grupy bez uszkodzonych (z podwójnymi i potrójnymi).',
    'sunglasses': 'Okulary → „Ilość (pojedyncze)”. Jedna stawka za oklejanie i czynności poboczne. Paczki 15–22.10.2026: wszystkie sztuki grupy bez uszkodzonych.',
    'card_facture': '„Flagi – Card Change”. Liczba kart. Paczki 15–22.10.2026: podmiana karty uszkodzonej + ze względu na algorytm.',
    'labelling_polybag': 'Nie z tabeli ilości (pole usunięte 23.10.2026). Paczki 15–22.10.2026: „Etykietowanie worków”, liczba worków.',
    'sorting': '„Uszkodzone” + „Niesprocesowane” ze wszystkich grup. Paczki 15–22.10.2026: uszkodzone + „Sortowanie inne”.',
}


def kategorie_z_tabeli(tabela):
    """Tabela → kolumny rozliczenia {kategoria: ilosc} (bez zer).

    Wersja 2: Ilosc kazdej grupy do jej kolumny (biżuteria → Labelling one),
    Podwojne ×1,5 → twice, Potrojne ×2 → triple (wszystkie grupy razem),
    Sorting = Uszkodzone + Niesprocesowane, Card facture = Flagi.
    """
    if not tabela:
        return {}
    if not jest_v2(tabela):
        return _kategorie_v1(tabela)
    grupy = tabela.get('grupy') or {}

    def suma(p):
        return sum((grupy.get(g) or {}).get(p, 0) or 0 for g, _ in GRUPY_ARTYKULOWE)

    wynik = {
        'labelling_on': (grupy.get(GRUPA_GLOWNA) or {}).get('ilosc', 0) or 0,
        'labelling_tvl': (tabela.get('podwojnie') or 0) * MNOZNIK_PODWOJNIE,
        'labelling_try': (tabela.get('potrojnie') or 0) * MNOZNIK_POTROJNIE,
        'sorting': suma('uszkodzone') + suma('niesprocesowane'),
        'card_facture': tabela.get('karty') or 0,
    }
    for g, kat in KATEGORIA_GRUPY.items():
        wynik[kat] = (grupy.get(g) or {}).get('ilosc', 0) or 0
    return {k: liczba(v) for k, v in wynik.items() if v}


def _kategorie_v1(tabela):
    """Wersja 1 (paczki 15–22.10.2026) — bez zmian wzgledem tamtego wdrozenia.

    Labelling one/twice/triple = TYLKO biżuteria (twice ×1,5, triple ×2);
    pozostale grupy = wszystkie ich sztuki bez uszkodzonych, kazda do swojej
    kolumny; Sorting = uszkodzone ze wszystkich grup + sortowanie inne.
    """
    grupy = tabela.get('grupy') or {}
    dod = tabela.get('dodatki') or {}

    def pole(g, p):
        return (grupy.get(g) or {}).get(p, 0) or 0

    wynik = {
        'labelling_on': pole(GRUPA_GLOWNA, 'pojedynczo'),
        'labelling_tvl': pole(GRUPA_GLOWNA, 'podwojnie') * MNOZNIK_PODWOJNIE,
        'labelling_try': pole(GRUPA_GLOWNA, 'potrojnie') * MNOZNIK_POTROJNIE,
        'sorting': sum(pole(g, 'uszkodzone') for g, _ in GRUPY_ARTYKULOWE)
                   + (dod.get('sortowanie_inne') or 0),
        'card_facture': (dod.get('karta_uszkodzona') or 0) + (dod.get('karta_algorytm') or 0),
        'labelling_polybag': dod.get('worki') or 0,
    }
    for g, kat in KATEGORIA_GRUPY.items():
        wynik[kat] = pole(g, 'pojedynczo') + pole(g, 'podwojnie') + pole(g, 'potrojnie')
    return {k: liczba(v) for k, v in wynik.items() if v}


def sztuki_tabeli(tabela):
    """Sztuki wpisane w tabeli — JEDNA definicja: Nadwyzka/Brak, ❗ zespolu
    i Normy osoby w paczce kilku osob.

    Wersja 2: Ilosc + Uszkodzone + Niesprocesowane ze wszystkich grup
    + Podwojne + Potrojne (sztuki, bez ×1,5/×2). Flagi to karty, nie sztuki.
    Wersja 1: Pojedynczo + Podwojnie + Potrojnie + Uszkodzone (bez zmian).
    """
    if not tabela:
        return 0
    if jest_v2(tabela):
        return (sum(sum((w.get(p, 0) or 0) for p, _ in POLA_GRUPY_V2)
                    for w in (tabela.get('grupy') or {}).values())
                + (tabela.get('podwojnie') or 0) + (tabela.get('potrojnie') or 0))
    return sum((w.get('pojedynczo', 0) or 0) + (w.get('podwojnie', 0) or 0)
               + (w.get('potrojnie', 0) or 0) + (w.get('uszkodzone', 0) or 0)
               for w in (tabela.get('grupy') or {}).values())


def suma_tabel(tabele):
    """Tabele kilku osob → jedna tabela kartonu (tryb zespol), pole po polu.

    Gdy choc jedna jest w wersji 2, wszystkie ida przez na_wersje_2() i wynik
    jest w wersji 2 (paczka zaczeta przed wdrozeniem, dokonczona po nim).
    Same wersje 1 — stara suma bez zmian."""
    if any(jest_v2(t) for t in tabele):
        wynik = {'wersja': WERSJA_TABELI, 'tryb': TRYB_ZESPOL,
                 'grupy': {g: {p: 0 for p, _ in POLA_GRUPY_V2} for g, _ in GRUPY_ARTYKULOWE},
                 **{p: 0 for p, _ in POLA_PACZKI_V2}}
        for t in map(na_wersje_2, tabele):
            for g, w in (t.get('grupy') or {}).items():
                if g in wynik['grupy']:
                    for p, _ in POLA_GRUPY_V2:
                        wynik['grupy'][g][p] += w.get(p, 0) or 0
            for p, _ in POLA_PACZKI_V2:
                wynik[p] += t.get(p, 0) or 0
        return wynik
    wynik = {'tryb': TRYB_ZESPOL,
             'grupy': {g: _pusta_grupa() for g, _ in GRUPY_ARTYKULOWE},
             'dodatki': {p: 0 for p, _ in DODATKI_TABELI}}
    for t in tabele:
        for g, w in (t.get('grupy') or {}).items():
            if g in wynik['grupy']:
                for p in POLA_GRUPY:
                    wynik['grupy'][g][p] += w.get(p, 0) or 0
        for p, v in (t.get('dodatki') or {}).items():
            if p in wynik['dodatki']:
                wynik['dodatki'][p] += v or 0
    return wynik


def roznice_tabeli(tabela, stueckzahl, osob=1):
    """Powody wykrzyknika ❗ (lider potwierdza). Pusta lista = brak roznicy.

    Bez progow procentowych (operacja, 2026-10-15): kazdy Brak, Nadwyzka
    i Uszkodzone; przy paczce kilku osob — suma wpisanych sztuk ≠ Stückzahl.
    Wersja 2: Brak/Nadwyzka z sumy (sztuki_tabeli vs Stückzahl), oba tryby.
    """
    if not tabela:
        return []
    powody = []
    grupy = tabela.get('grupy') or {}
    if jest_v2(tabela):
        # Wersja 2: Nadwyzka/Brak z sumy wpisanych sztuk + kazde Uszkodzone.
        sztuk, w_paczce = sztuki_tabeli(tabela), int(stueckzahl or 0)
        nadwyzka, brak = nadwyzka_brak(tabela, stueckzahl)
        kto = f'{osob} os. wpisało razem' if tabela.get('tryb') == TRYB_ZESPOL else 'wpisano'
        if nadwyzka:
            powody.append(f'Nadwyżka {nadwyzka} szt. ({kto} {sztuk} przy {w_paczce} w paczce)')
        if brak:
            powody.append(f'Brak {brak} szt. ({kto} {sztuk} przy {w_paczce} w paczce)')
        for g, nazwa in GRUPY_ARTYKULOWE:
            n = (grupy.get(g) or {}).get('uszkodzone')
            if n:
                powody.append(f'{nazwa}: uszkodzone {n}')
        return powody
    if tabela.get('tryb') == TRYB_ZESPOL:
        sztuk = sztuki_tabeli(tabela)
        w_paczce = int(stueckzahl or 0)
        if sztuk != w_paczce:
            powody.append(f'{osob} os. wpisało razem {sztuk} szt. przy {w_paczce} w paczce')
        pola = [('uszkodzone', 'uszkodzone')]
    else:
        pola = [('brak', 'brak'), ('nadwyzka', 'nadwyżka'), ('uszkodzone', 'uszkodzone')]
    for g, nazwa in GRUPY_ARTYKULOWE:
        w = grupy.get(g) or {}
        czesci = [f'{opis} {w.get(p)}' for p, opis in pola if w.get(p)]
        if czesci:
            powody.append(f'{nazwa}: ' + ', '.join(czesci))
    return powody


def wczytaj_json_dict(tekst):
    try:
        dane = json.loads(tekst) if tekst else None
    except (json.JSONDecodeError, TypeError):
        return None
    return dane if isinstance(dane, dict) else None
