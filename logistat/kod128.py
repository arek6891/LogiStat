"""Kod kreskowy Code 128 (zestawy B i C) — czysta logika, bez bibliotek.

Uzywany przez etykiety POS (Dekoracje, 2026-10-28): numer POS → ciag modulow
'1' (kreska) / '0' (przerwa), ktory rysuje `logistat.pdf_etykiet`. Same cyfry
w parzystej liczbie (>= 4) ida zestawem C (dwie cyfry na znak — kod o polowe
krotszy), reszta zestawem B (ASCII 32–126).
"""

# Szerokosci kreska/przerwa/kreska… dla wartosci 0–105 (ISO/IEC 15417).
WZORY = (
    '212222', '222122', '222221', '121223', '121322', '131222', '122213', '122312', '132212', '221213',
    '221312', '231212', '112232', '122132', '122231', '113222', '123122', '123221', '223211', '221132',
    '221231', '213212', '223112', '312131', '311222', '321122', '321221', '312212', '322112', '322211',
    '212123', '212321', '232121', '111323', '131123', '131321', '112313', '132113', '132311', '211313',
    '231113', '231311', '112133', '112331', '132131', '113123', '113321', '133121', '313121', '211331',
    '231131', '213113', '213311', '213131', '311123', '311321', '331121', '312113', '312311', '332111',
    '314111', '221411', '431111', '111224', '111422', '121124', '121421', '141122', '141221', '112214',
    '112412', '122114', '122411', '142112', '142211', '241211', '221114', '413111', '241112', '134111',
    '111242', '121142', '121241', '114212', '124112', '124211', '411212', '421112', '421211', '212141',
    '214121', '412121', '111143', '111341', '131141', '114113', '114311', '411113', '411311', '113141',
    '114131', '311141', '411131', '211412', '211214', '211232',
)
START_B = 104
START_C = 105
STOP = '2331112'
CISZA = 10   # strefa ciszy (moduly) z kazdej strony


def wartosci(tekst):
    """Wartosci znakow kodu: start, dane, suma kontrolna (bez stopu).
    ValueError przy pustym tekscie albo znaku spoza ASCII 32–126."""
    if not tekst:
        raise ValueError('Pusty kod.')
    if any(not 32 <= ord(z) <= 126 for z in tekst):
        raise ValueError('Kod 128 B przyjmuje tylko znaki ASCII 32–126.')
    if tekst.isdigit() and len(tekst) % 2 == 0 and len(tekst) >= 4:
        dane = [START_C] + [int(tekst[i:i + 2]) for i in range(0, len(tekst), 2)]
    else:
        dane = [START_B] + [ord(z) - 32 for z in tekst]
    kontrolna = (dane[0] + sum(i * w for i, w in enumerate(dane[1:], start=1))) % 103
    return dane + [kontrolna]


def moduly(tekst):
    """Caly kod jako '1'/'0' na modul, ze strefami ciszy."""
    wynik = ['0' * CISZA]
    for wzor in [WZORY[w] for w in wartosci(tekst)] + [STOP]:
        for i, szer in enumerate(wzor):
            wynik.append(('1' if i % 2 == 0 else '0') * int(szer))
    wynik.append('0' * CISZA)
    return ''.join(wynik)
