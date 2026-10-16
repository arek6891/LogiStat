"""Tabela ilosci na koniec paczki: walidacja, wzor „Pojedynczo",
mapowanie na kolumny rozliczenia, powody ❗. Czysta logika — liczy serwer."""
import json

from logistat.kategorie import liczba

# ── Tabela ilosci na koniec paczki (Post Processing, 2026-10-15) ──────────────
# Operator wpisuje tabele: wiersze = grupy artykulowe, kolumny = Brak /
# Nadwyzka / Uszkodzone / Podwojnie / Potrojnie; „Pojedynczo" liczy system.
# Pelna tabela zostaje na kartonie (tabela_ilosci), a do rozliczenia idzie
# z niej `scan_category_data` — reszta toru (scan_category_totals,
# recompute_general_stat) bez zmian. Decyzje operacji: docs/ARCHITEKTURA.md.
GRUPY_ARTYKULOWE = [
    ('bizuteria', 'Biżuteria'),
    ('akcesoria', 'Akcesoria'),
    ('okulary', 'Okulary'),
    ('tekstylia', 'Tekstylia'),
]
NAZWY_GRUP = dict(GRUPY_ARTYKULOWE)
# Plik importu ma jedna ilosc na karton, bez podzialu na grupy: cala idzie do
# Biżuterii, operator wpisuje ile jest pozostalych grup, system odejmuje.
GRUPA_GLOWNA = 'bizuteria'
# Grupy poza biżuteria → kolumna rozliczenia (kazda ma swoja stawke).
KATEGORIA_GRUPY = {'akcesoria': 'accessoire', 'okulary': 'sunglasses', 'tekstylia': 'textile'}
POLA_GRUPY = ['ilosc', 'brak', 'nadwyzka', 'uszkodzone', 'podwojnie', 'potrojnie', 'pojedynczo']
# Co operator wpisuje: przy paczce jednej osoby „Pojedynczo" wynika ze wzoru,
# przy paczce kilku osob kazdy wpisuje wprost swoje sztuki (Brak i Nadwyzka
# wychodza dopiero z porownania sumy wszystkich z iloscia w pliku).
TRYB_WZOR = 'wzor'
TRYB_ZESPOL = 'zespol'
WPISYWANE_WZOR = ['brak', 'nadwyzka', 'uszkodzone', 'podwojnie', 'potrojnie']
WPISYWANE_ZESPOL = ['pojedynczo', 'podwojnie', 'potrojnie', 'uszkodzone']
DODATKI_TABELI = [
    ('sortowanie_inne', 'Sortowanie inne'),
    ('karta_uszkodzona', 'Podmiana karty uszkodzonej'),
    ('karta_algorytm', 'Podmiana karty ze względu na algorytm'),
    ('worki', 'Etykietowanie worków'),
]
# LOGIKA_KLEJENIA.xlsx: pierwsza etykieta = 1, kazda kolejna = 0,5.
MNOZNIK_PODWOJNIE = 1.5
MNOZNIK_POTROJNIE = 2
# Liczba od tej wartosci to prawie na pewno zeskanowany kod, nie ilosc sztuk
# (ta sama granica co ILOSC_WYGLADA_NA_KOD w scan_paczki.html).
ILOSC_WYGLADA_NA_KOD = 100000


def _pusta_grupa():
    return {pole: 0 for pole in POLA_GRUPY}


def normalizuj_tabele(surowe, tryb, stueckzahl):
    """Waliduje tabele z ekranu i liczy pola systemowe. Zwraca (tabela, blad).

    Liczy ZAWSZE serwer — wynik nie zalezy od przegladarki. Tryb `wzor`:
    Ilosc biżuterii = Stückzahl − pozostale grupy, Pojedynczo = Ilosc − Brak
    + Nadwyzka − Uszkodzone − Podwojnie − Potrojnie; ujemne → blad z nazwa
    wiersza. Tryb `zespol`: wpisane wprost, Ilosc = suma sztuk osoby.
    """
    if not isinstance(surowe, dict):
        return None, 'Nieprawidłowy format tabeli ilości.'
    grupy_we = surowe.get('grupy') or {}
    dodatki_we = surowe.get('dodatki') or {}
    if not isinstance(grupy_we, dict) or not isinstance(dodatki_we, dict):
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

    wpisywane = WPISYWANE_WZOR if tryb == TRYB_WZOR else WPISYWANE_ZESPOL
    grupy = {}
    for g, nazwa in GRUPY_ARTYKULOWE:
        we = grupy_we.get(g) or {}
        if not isinstance(we, dict):
            return None, 'Nieprawidłowy format tabeli ilości.'
        wiersz = _pusta_grupa()
        pola = list(wpisywane)
        if tryb == TRYB_WZOR and g != GRUPA_GLOWNA:
            pola.append('ilosc')
        for pole in pola:
            n, blad = wartosc(we, pole, nazwa)
            if blad:
                return None, blad
            wiersz[pole] = n
        grupy[g] = wiersz

    if tryb == TRYB_WZOR:
        pozostale = sum(grupy[g]['ilosc'] for g in grupy if g != GRUPA_GLOWNA)
        w_paczce = int(stueckzahl or 0)
        if pozostale > w_paczce:
            return None, (f'Akcesoria, okulary i tekstylia razem ({pozostale} szt.) to więcej niż '
                          f'w paczce ({w_paczce} szt.). Popraw kolumnę „Ilość” — sztuki ponad '
                          'plik wpisz jako „Nadwyżka”.')
        grupy[GRUPA_GLOWNA]['ilosc'] = w_paczce - pozostale
        for g, nazwa in GRUPY_ARTYKULOWE:
            w = grupy[g]
            w['pojedynczo'] = (w['ilosc'] - w['brak'] + w['nadwyzka'] - w['uszkodzone']
                               - w['podwojnie'] - w['potrojnie'])
            if w['pojedynczo'] < 0:
                return None, (f'{nazwa}: „Pojedynczo” wychodzi {w["pojedynczo"]} — wpisano więcej '
                              'braków, uszkodzonych, podwójnych i potrójnych niż sztuk w tym wierszu.')
    else:
        for w in grupy.values():
            w['ilosc'] = w['pojedynczo'] + w['podwojnie'] + w['potrojnie'] + w['uszkodzone']

    dodatki = {}
    for pole, nazwa in DODATKI_TABELI:
        n, blad = wartosc(dodatki_we, pole, nazwa)
        if blad:
            return None, blad
        dodatki[pole] = n
    return {'tryb': tryb, 'grupy': grupy, 'dodatki': dodatki}, None


# Dymek „ⓘ" przy kolumnie w Statystykach ogolnych: skad sie bierze ilosc.
# Musi sie zgadzac z kategorie_z_tabeli() — zmiana tam = zmiana tu.
ZRODLO_KATEGORII = {
    'labelling_on': 'Biżuteria → „Pojedynczo”. Pojedynczo = Ilość − Brak + Nadwyżka − Uszkodzone − Podwójnie − Potrójnie.',
    'labelling_tvl': 'Biżuteria → „Podwójnie” × 1,5. Pierwsza etykieta liczy się jako 1, każda kolejna jako 0,5 (2 sztuki = 3).',
    'labelling_try': 'Biżuteria → „Potrójnie” × 2. Pierwsza etykieta liczy się jako 1, każda kolejna jako 0,5 (3 sztuki = 6).',
    'textile': 'Tekstylia: wszystkie sztuki grupy (także klejone podwójnie i potrójnie) bez uszkodzonych, czyli Ilość − Brak + Nadwyżka − Uszkodzone.',
    'accessoire': 'Akcesoria: wszystkie sztuki grupy (także klejone podwójnie i potrójnie) bez uszkodzonych, czyli Ilość − Brak + Nadwyżka − Uszkodzone.',
    'sunglasses': 'Okulary: wszystkie sztuki grupy (także klejone podwójnie i potrójnie) bez uszkodzonych, czyli Ilość − Brak + Nadwyżka − Uszkodzone. Jedna stawka za oklejanie i czynności poboczne.',
    'card_facture': '„Podmiana karty uszkodzonej” + „Podmiana karty ze względu na algorytm”. Liczba kart.',
    'labelling_polybag': '„Etykietowanie worków”. Liczba worków.',
    'sorting': 'Kolumna „Uszkodzone” ze wszystkich grup + „Sortowanie inne”.',
}


def kategorie_z_tabeli(tabela):
    """Tabela → kolumny rozliczenia {kategoria: ilosc} (bez zer).

    Labelling one/twice/triple = TYLKO biżuteria (twice ×1,5, triple ×2);
    pozostale grupy = wszystkie ich sztuki bez uszkodzonych, kazda do swojej
    kolumny; Sorting = uszkodzone ze wszystkich grup + sortowanie inne.
    """
    if not tabela:
        return {}
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
    """Sztuki przerobione wg tabeli: Pojedynczo + Podwojnie + Potrojnie +
    Uszkodzone ze wszystkich grup. Tyle osoba dostaje do Norm przy paczce
    kilku osob. Brak, karty, worki i sortowanie inne nie sa sztukami."""
    if not tabela:
        return 0
    return sum((w.get('pojedynczo', 0) or 0) + (w.get('podwojnie', 0) or 0)
               + (w.get('potrojnie', 0) or 0) + (w.get('uszkodzone', 0) or 0)
               for w in (tabela.get('grupy') or {}).values())


def suma_tabel(tabele):
    """Tabele kilku osob → jedna tabela kartonu (tryb zespol), pole po polu."""
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
    """
    if not tabela:
        return []
    powody = []
    grupy = tabela.get('grupy') or {}
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
