"""Normy: szt./h z listy paczek jednej osoby (`policz_wydajnosc`).
Jedyne miejsce liczenia wydajnosci — przeglad, karta osoby i wykresy ida tedy."""
from logistat.czas import utc_to_local
from logistat.okresy import (
    odejmij_okresy, w_okresach, zlacz_okresy, suma_zlaczonych_okresow)

def policz_wydajnosc(paczki, szkolenia=(), cel_dnia=None, jako_szkolony=()):
    """Szt./h z listy paczek `[(start, koniec, sztuk)]` jednej osoby.

    Jedyne miejsce liczenia wydajnosci — przeglad zespolu, ocena osoby i jej
    wykresy ida przez nie, wiec nigdy sie nie rozjada.

    Mianownikiem jest czas SKANOWANIA paczek liczony `suma_zlaczonych_okresow()`
    (dwie paczki otwarte naraz nie licza tego samego kwadransa dwa razy), nie
    czas obecnosci — przerwy i „Inne" go nie pomniejszaja. To „sztuki na
    godzine skanowania", nie „na godzine pracy".

    **Osoba szkolona** (`jako_szkolony`, decyzja operacji 2026-10-08): czas jej
    paczek przypadajacy na szkolenie wypada z Norm i sredniej w calosci —
    czas i proporcjonalna czesc sztuk. Liczone PIERWSZE i niezaleznie od celu.
    Paczka bez skanu „Start" zakonczona w szkoleniu wypada cala.

    **Osoba szkolaca** (`szkolenia`, decyzja 2026-10-06, zmiana 2026-10-14): z
    tego, co zostalo, paczka nakladajaca sie choc troche na prowadzone
    szkolenie liczy sie CALA jako czas × cel z dnia zakonczenia paczki
    (dokladnie 100%) — takze minuty przed/po szkoleniu i w przerwie miedzy
    blokami szkolenia. Zaliczony czas to suma ZLACZONYCH okresow takich paczek
    dla calego zakresu (dwie paczki naraz nie dostana tej samej minuty dwa
    razy — takze przez polnoc), a zwykla paczka rownolegla do zaliczonej
    liczy tylko czas poza zaliczonym (code review 2026-10-16). Samo
    szkolenie bez paczek nic nie dolicza; dzien bez celu (0) — normalnie.
    Paczka bez „Start" zakonczona w szkoleniu nie ma czasu, wiec nie wchodzi
    do szt./h (nie udajemy ani zera, ani celu).

    `sztuk_do_sredniej` / `sekundy_do_sredniej` to wylacznie czas i sztuki
    liczone normalnie — zaliczone ciagnelyby srednia zespolu w strone celu.
    """
    cel_dnia = cel_dnia or (lambda _dzien: 0)
    szkolenia = zlacz_okresy(szkolenia)
    jako_szkolony = zlacz_okresy(jako_szkolony)
    wszystkie_okresy = []
    zwykle_okresy = []         # czas liczony normalnie
    sztuk_zwykle = 0.0         # prawdziwe sztuki liczone normalnie
    zwykle_paczki = []         # (okresy, sztuki) — przyciete dopiero po zaliczonych
    zaliczone_fragmenty = []   # okresy paczek zaliczonych po celu (cale paczki)
    paczek_szkolenia = 0
    paczek_jako_szkolony = 0
    paczek_wylaczonych = 0     # w calosci z czasu bycia szkolonym
    sekundy_jako_szkolony = 0.0
    for start, koniec, sztuk in paczki:
        dzien = utc_to_local(koniec).date()
        trwanie = (koniec - start).total_seconds() if start else 0.0
        if trwanie <= 0:
            # Bez zmierzonego czasu nie ma czego przycinac — decyduje koniec.
            if jako_szkolony and w_okresach(koniec, jako_szkolony):
                paczek_jako_szkolony += 1
                paczek_wylaczonych += 1
                continue
            if not start and szkolenia and w_okresach(koniec, szkolenia) \
                    and cel_dnia(dzien) > 0:
                paczek_szkolenia += 1
                continue
            sztuk_zwykle += sztuk
            if start:
                wszystkie_okresy.append((start, koniec))
                zwykle_okresy.append((start, koniec))
            continue

        pozostale = (odejmij_okresy(start, koniec, jako_szkolony)
                     if jako_szkolony else [(start, koniec)])
        sek_pozostale = sum((k - s).total_seconds() for s, k in pozostale)
        if sek_pozostale < trwanie:
            paczek_jako_szkolony += 1
            sekundy_jako_szkolony += trwanie - sek_pozostale
            if not pozostale:
                paczek_wylaczonych += 1
                continue
        wszystkie_okresy.extend(pozostale)

        w_szkoleniu = (szkolenia and cel_dnia(dzien) > 0
                       and any(min(b, k) > max(a, s)
                               for a, b in pozostale for s, k in szkolenia))
        if not w_szkoleniu:
            zwykle_paczki.append((pozostale, sztuk * (sek_pozostale / trwanie)))
            continue
        # Paczka zahaczajaca o szkolenie liczy sie CALA (operacje, 2026-10-14):
        # szkolacy konczy szkolenie na kazda przerwe, a paczka zostaje otwarta —
        # czas przerwy szedl z prawdziwych sztuk i trener wychodzil ponizej celu.
        paczek_szkolenia += 1
        zaliczone_fragmenty.extend(pozostale)

    # Zaliczony czas = JEDNA suma zlaczonych okresow dla calego zakresu, nie
    # per dzien konca paczki — dwie paczki przez polnoc dostawaly wspolne
    # minuty dwa razy. Kazdy zlaczony okres po celu z dnia swojego konca.
    zaliczone = zlacz_okresy(zaliczone_fragmenty)
    sekundy_szkolenia = 0.0
    sztuk_zaliczonych = 0.0
    for start, koniec in zaliczone:
        sek = (koniec - start).total_seconds()
        sekundy_szkolenia += sek
        sztuk_zaliczonych += sek / 3600.0 * cel_dnia(utc_to_local(koniec).date())

    # Zwykla paczka rownolegle do zaliczonej: jej minuty sa juz zaliczone po
    # celu, wiec liczy tylko czesc POZA zaliczonymi — inaczej ta sama minuta
    # wchodzila dwa razy (cel + prawdziwe sztuki), szt./h ponad 100 % celu.
    # Sztuki proporcjonalnie do czasu, ktory zostal.
    for okresy, sztuk in zwykle_paczki:
        sek = sum((k - s).total_seconds() for s, k in okresy)
        poza = [fragment for s, k in okresy for fragment in odejmij_okresy(s, k, zaliczone)]
        sek_poza = sum((k - s).total_seconds() for s, k in poza)
        if sek > 0:
            sztuk_zwykle += sztuk * (sek_poza / sek)
        zwykle_okresy.extend(poza)

    sekundy = suma_zlaczonych_okresow(wszystkie_okresy)
    # Cel obowiazujacy w dniu pracy (2026-10-13): kazda godzina skanowania
    # wazy cel ze swojego dnia (dzien konca zlaczonego okresu, jak przy
    # szkoleniu). Godziny z dni bez celu (0) nie wchodza — nie ma ich z czym
    # porownac.
    sekundy_z_celem = 0.0
    cel_x_sekundy = 0.0
    for start, koniec in zlacz_okresy(wszystkie_okresy):
        cel = cel_dnia(utc_to_local(koniec).date())
        if cel > 0:
            sek = (koniec - start).total_seconds()
            sekundy_z_celem += sek
            cel_x_sekundy += sek * cel
    return {
        'paczek': len(paczki),
        'sztuk': sum(p[2] for p in paczki),
        # Do progu `min_packages_rank` licza sie tylko paczki, ktore zostaly
        # w ocenie — szkolony z 3 wylaczonymi i 1 zwykla nie wchodzi do rankingu.
        'paczek_do_oceny': len(paczki) - paczek_wylaczonych,
        'sekundy': sekundy,
        # Bez zmierzonego czasu szt./h nie istnieje — nie udajemy zera.
        'szt_h': (round((sztuk_zwykle + sztuk_zaliczonych) / (sekundy / 3600.0), 1)
                  if sekundy > 0 else None),
        'paczek_szkolenia': paczek_szkolenia,
        'sekundy_szkolenia': sekundy_szkolenia,
        'paczek_jako_szkolony': paczek_jako_szkolony,
        'sekundy_jako_szkolony': sekundy_jako_szkolony,
        'sztuk_do_sredniej': sztuk_zwykle,
        'sekundy_do_sredniej': suma_zlaczonych_okresow(zwykle_okresy),
        'cel_szt_h': (round(cel_x_sekundy / sekundy_z_celem, 1)
                      if sekundy_z_celem > 0 else None),
        'sekundy_z_celem': sekundy_z_celem,
        'cel_x_sekundy': cel_x_sekundy,
    }
