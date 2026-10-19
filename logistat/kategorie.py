"""Kategorie rozliczenia (kolumny Statystyk ogolnych), liczby w rozliczeniu
i Total Amount. Polskie nazwy edytowane przez admina (AppSetting) zostaja
w app.py — to juz baza."""

STAT_CATEGORIES = [
    'labelling_on', 'labelling_tvl', 'labelling_try', 'textile',
    'accessoire', 'sunglasses', 'card_facture', 'labelling_polybag',
    'sorting'
]

STAT_CATEGORY_LABELS = {
    'labelling_on': 'Labelling one',
    'labelling_tvl': 'Labelling twice',
    'labelling_try': 'Labelling triple',
    'textile': 'Textile',
    'accessoire': 'Accessoire',
    'sunglasses': 'Sunglasses',
    'card_facture': 'Card facture',
    'labelling_polybag': 'Labelling polybag',
    'sorting': 'Sorting'
}

# Polskie odpowiedniki — TYLKO dla ekranów. Naglowki eksportu Excel zostaja
# angielskie, bo to artefakt rozliczeniowy wychodzacy na zewnatrz.
# To sa DOMYSLNE nazwy: admin nadpisuje je w /admin/category-labels (AppSetting
# `kategoria_pl:<kat>`), bo pracownik na stanowisku musi widziec nazwe, ktora
# rozumie (np. „Niesprocesowane" zamiast „Sortowanie").
STAT_CATEGORY_LABELS_PL = {
    'labelling_on': 'Etykietowanie pojedyncze',
    'labelling_tvl': 'Etykietowanie podwójne',
    'labelling_try': 'Etykietowanie potrójne',
    'textile': 'Tekstylia',
    'accessoire': 'Akcesoria',
    'sunglasses': 'Okulary przeciwsłoneczne',
    'card_facture': 'Karta / faktura',
    'labelling_polybag': 'Etykietowanie polybag',
    'sorting': 'Sortowanie'
}


# Total Amount w Statystykach ogolnych = suma WSZYSTKICH kategorii poza tymi
# (operacja, 2026-10-15). Do tej daty liczyl wylacznie Labelling one. Twice
# i triple to te same sztuki biżuterii z dodatkowymi etykietami (×1,5 / ×2),
# wiec w sumie sztuk liczylyby sie drugi raz. Ta sama regula w obu wierszach
# (zwyklym i zoltym double rate) — trzy miejsca: Jinja w general_stats.html,
# JS po edycji w tym samym pliku, write_data_row() w eksporcie Excela.
TOTAL_AMOUNT_BEZ = ('labelling_tvl', 'labelling_try')


def liczba(wartosc):
    """Ilosc w rozliczeniu: int, gdy calkowita, inaczej float (×1,5 daje polowki)."""
    try:
        v = round(float(wartosc or 0), 2)
    except (TypeError, ValueError):
        return 0
    return int(v) if v.is_integer() else v


def total_amount_wiersza(category_data):
    """Total Amount wiersza — patrz TOTAL_AMOUNT_BEZ."""
    return liczba(sum(
        (category_data.get(kat) or {}).get('amount', 0) or 0
        for kat in STAT_CATEGORIES if kat not in TOTAL_AMOUNT_BEZ))
