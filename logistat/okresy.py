"""Okresy czasu (start, koniec): scalanie, dlugosc bez podwojnego liczenia,
odejmowanie. Jedna implementacja dla Norm i czasu pracy — do 2026-10-16
scalanie bylo napisane dwa razy (`_zlacz_okresy` i `suma_zlaczonych_okresow`)."""


def zlacz_okresy(okresy):
    """Posortowane, rozlaczne okresy (start, koniec) — nakladajace sie scalone.
    Odwrocony albo pusty zakres (koniec <= start, np. po recznej korekcie) pomija."""
    wynik = []
    for start, koniec in sorted(okresy):
        if koniec <= start:
            continue
        if wynik and start <= wynik[-1][1]:
            wynik[-1] = (wynik[-1][0], max(wynik[-1][1], koniec))
        else:
            wynik.append((start, koniec))
    return wynik


def suma_zlaczonych_okresow(okresy):
    """Laczna dlugosc okresow w sekundach — wspolny fragment liczony raz."""
    return sum((koniec - start).total_seconds() for start, koniec in zlacz_okresy(okresy or ()))


def odejmij_okresy(start, koniec, wylaczone):
    """Czesci `[start, koniec)` lezace poza okresami `wylaczone` (zlaczonymi)."""
    reszta = []
    biezacy = start
    for s, k in wylaczone:
        if k <= biezacy or s >= koniec:
            continue
        if s > biezacy:
            reszta.append((biezacy, s))
        biezacy = max(biezacy, k)
        if biezacy >= koniec:
            break
    if biezacy < koniec:
        reszta.append((biezacy, koniec))
    return reszta


def w_okresach(chwila, okresy):
    """Czy chwila lezy w ktoryms z okresow (granice wlacznie)."""
    return any(s <= chwila <= k for s, k in okresy)
