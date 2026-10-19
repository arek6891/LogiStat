"""Paczka jako agregat: udzialy osob, tabela ilosci kartonu, flaga ❗, bledy paczki."""
from logistat.kategorie import STAT_CATEGORIES, STAT_CATEGORY_LABELS
from logistat.models import etykieta_kategorii
from logistat.rozliczenie import klucz_linii, recompute_general_stat
from logistat.tabela_ilosci import kategorie_z_tabeli, suma_tabel

#  Prog tolerancji: ilosc wpisana per kategoria wieksza niz Stueckzahl o wiecej
#  niz 10% traktujemy jako pomylke wpisujacego.
TOLERANCJA_ILOSCI = 1.10


def otwarte_udzialy(carton):
    return [u for u in carton.udzialy if u.end_at is None]


def lista_osob(udzialy):
    return ', '.join(u.user.display_name if u.user else '?' for u in udzialy)


def przelicz_ilosci_udzialow(carton, actor_id):
    """Karton = SUMA ilosci wszystkich udzialow (z sumy, nigdy delta) → linia
    rozliczenia, jak przy zwyklym koncu paczki. Tabela kartonu = suma tabel
    osob (tryb zespol); ❗ liczy sie dopiero po zamknieciu paczki."""
    suma = {}
    for u in carton.udzialy:
        for kat, ile in u.get_ilosci().items():
            suma[kat] = suma.get(kat, 0) + ile
    tabele = [t for t in (u.get_tabela() for u in carton.udzialy) if t]
    if tabele:
        carton.set_tabela(suma_tabel(tabele))
    poprzednie = carton.get_scan_categories()
    carton.set_scan_categories(suma)
    odswiez_roznice(carton)
    if suma or poprzednie:
        recompute_general_stat(*klucz_linii(carton), actor_id=actor_id, from_scan=True)


def odswiez_roznice(carton):
    """Flaga ❗ z tabeli zakonczonej paczki. Paczka bez tabeli (sprzed
    2026-10-15) ma stare reguly w bledy_paczki() i flagi nie dostaje."""
    carton.roznica = bool(carton.scan_end_at and carton.tabela_ilosci
                          and carton.powody_roznicy())


def zapisz_tabele_kartonu(carton, tabela, actor_id):
    """Paczka jednej osoby: tabela → kolumny rozliczenia → linia (z sumy)."""
    carton.set_tabela(tabela)
    carton.set_scan_categories(kategorie_z_tabeli(tabela))
    odswiez_roznice(carton)
    recompute_general_stat(*klucz_linii(carton), actor_id=actor_id, from_scan=True)


def zamknij_paczke_wielu_osob(carton, kto_id, teraz):
    """Ostatni udzial zamkniety → paczka zakonczona. Start = pierwszy udzial,
    zeby „kto/kiedy zaczal" na /paczki opisywal cala paczke."""
    pierwszy = min(carton.udzialy, key=lambda u: u.start_at)
    carton.scan_start_at = pierwszy.start_at
    carton.scan_start_by = pierwszy.user_id
    carton.scan_end_at = teraz
    carton.scan_end_by = kto_id


def bledy_paczki(carton):
    """Lista bledow paczki: brak zakonczenia, przekroczona ilosc per kategoria.

    Paczka z tabela ilosci (od 2026-10-15): bez progow — blad to tylko
    niepotwierdzony ❗ (Brak / Nadwyzka / Uszkodzone / suma kilku osob ≠
    plik). Paczki sprzed tabeli zachowuja stare reguly ponizej, inaczej
    historia bledow zmienilaby sie wstecz.
    """
    bledy = []
    if carton.scan_start_at and not carton.scan_end_at:
        bledy.append('Rozpoczęta, ale nie zakończona')
    if carton.tabela_ilosci:
        if carton.roznica_do_potwierdzenia():
            bledy.append('❗ Do potwierdzenia: ' + '; '.join(carton.powody_roznicy()))
        return bledy

    limit = (carton.stueckzahl or 0) * TOLERANCJA_ILOSCI
    ilosci = carton.get_scan_categories()
    for kat, ile in ilosci.items():
        if ile > limit:
            bledy.append(
                f'{STAT_CATEGORY_LABELS.get(kat, kat)}: {ile} szt. '
                f'przy {carton.stueckzahl or 0} w paczce'
            )

    # Paczka wielu osob z nadwyzka (suma > Stückzahl LUB kategoria > +10 %,
    # decyzja operacji 2026-10-13): nie wiadomo, kto zawyzyl — lider wyjasnia.
    osoby = {u.user_id: (u.user.display_name if u.user else '?') for u in carton.udzialy}
    suma = sum(ilosci.values())
    if len(osoby) >= 2 and (suma > (carton.stueckzahl or 0) or any(i > limit for i in ilosci.values())):
        bledy.append(
            f'Procesowało {len(osoby)} os. ({", ".join(osoby.values())}) — wpisano {suma} szt. '
            f'przy {carton.stueckzahl or 0} w paczce. Do wyjaśnienia przez lidera'
        )
    return bledy


def parse_scan_categories(surowe):
    """Waliduje ilosci per kategoria. Zwraca (dict, komunikat_bledu).

    Suma NIE jest porownywana ze `stueckzahl` — rozbieznosc miedzy deklaracja
    a zawartoscia paczki jest normalna i nie moze blokowac pracy.
    """
    if surowe is None:
        return {}, None
    if not isinstance(surowe, dict):
        return None, 'Nieprawidłowy format ilości.'
    wynik = {}
    for kat, wartosc in surowe.items():
        if kat not in STAT_CATEGORIES:
            return None, f'Nieznana kategoria: {kat}.'
        try:
            ile = int(wartosc)
        except (TypeError, ValueError):
            return None, f'Ilość dla „{etykieta_kategorii(kat)}" musi być liczbą.'
        if ile < 0:
            return None, f'Ilość dla „{etykieta_kategorii(kat)}" nie może być ujemna.'
        if ile:
            wynik[kat] = ile
    return wynik, None
