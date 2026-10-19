"""Normy — dane z bazy: praca osob przy paczkach (`prace_osob`, jedyna definicja
„kto ile zrobil"), okresy szkolen, cele dnia z historii, przeglad zespolu i karta
pracownika. Liczenie szt./h robi czyste `logistat.normy.policz_wydajnosc`."""
from bisect import bisect_right
from datetime import date, timedelta

from sqlalchemy.orm import joinedload

from logistat.czas import local_day_bounds, local_today, teraz_utc
from logistat.extensions import db
from logistat.models import (
    HistoriaCelu, ImportedCarton, POCZATEK_HISTORII_CELU, UdzialPaczki, User, WorkerTimeEvent,
    get_setting_int)
from logistat.normy import policz_wydajnosc


def prace_osob(date_from=None, date_to=None, user_ids=None):
    """Zakonczona praca kazdej osoby przy paczkach: `{uid: [(start, koniec, sztuk)]}`.

    JEDYNA definicja „kto ile zrobil" — Normy, wykresy, Dashboard (per
    pracownik, per zmiana). Dwa zrodla:
    - paczka jednej osoby (bez `udzial_paczki`): kto zakonczyl, start–koniec,
      sztuk = Stückzahl — jak zawsze;
    - paczka wielu osob (przekazana / zespol): kazdy swoj udzial — jego czas
      i jego WPISANE ilosci (decyzja operacji 2026-10-13; od 2026-10-15 z tabeli:
      Pojedynczo + Podwojnie + Potrojnie + Uszkodzone — UdzialPaczki.sztuki()),
      liczony po koncu
      udzialu, takze gdy paczke dokonczy ktos inny pozniej. Udzial zamkniety
      przez kogos innego (bez ilosci) pomijamy — nie ma czego liczyc.
    Zakres po DOBIE LOKALNEJ konca, polotwarty.
    """
    ma_udzialy = db.session.query(UdzialPaczki.id).filter(
        UdzialPaczki.carton_id == ImportedCarton.id).exists()
    q = db.session.query(
        ImportedCarton.scan_end_by,
        ImportedCarton.scan_start_at,
        ImportedCarton.scan_end_at,
        ImportedCarton.stueckzahl,
    ).filter(
        ImportedCarton.scan_end_at.isnot(None),
        ImportedCarton.scan_end_by.isnot(None),
        ~ma_udzialy,
    )
    uq = UdzialPaczki.query.filter(
        UdzialPaczki.end_at.isnot(None),
        UdzialPaczki.zamkniete_przez.is_(None),
    )
    # `scan_end_at` / `end_at` to naive UTC — granice doby jak wszedzie indziej.
    if date_from:
        q = q.filter(ImportedCarton.scan_end_at >= local_day_bounds(date_from)[0])
        uq = uq.filter(UdzialPaczki.end_at >= local_day_bounds(date_from)[0])
    if date_to:
        q = q.filter(ImportedCarton.scan_end_at < local_day_bounds(date_to)[1])
        uq = uq.filter(UdzialPaczki.end_at < local_day_bounds(date_to)[1])
    if user_ids is not None:
        q = q.filter(ImportedCarton.scan_end_by.in_(list(user_ids)))
        uq = uq.filter(UdzialPaczki.user_id.in_(list(user_ids)))

    per_osoba = {}
    for uid, start, koniec, sztuk in q.all():
        per_osoba.setdefault(uid, []).append((start, koniec, sztuk or 0))
    for u in uq.all():
        per_osoba.setdefault(u.user_id, []).append((u.start_at, u.end_at, u.sztuki()))
    return per_osoba


def wydajnosc_pracownikow(date_from=None, date_to=None):
    """Zakonczone paczki kazdego pracownika: `{uid: [(start, koniec, sztuk)]}`.

    Dlaczego z paczek, a nie z `DailyStat`: wpis ilosci jest uzupelniany
    sporadycznie (na `.31` to kilka wierszy), a skan paczek leci przy kazdej
    sztuce — to jedyne zrodlo, ktore realnie pokrywa zespol.

    Liczenie (szt./h, szkolenia) robi `policz_wydajnosc()` — tu tylko dane
    z `prace_osob()`. `start` bywa None (paczka zamknieta bez skanu „Start").
    """
    return prace_osob(date_from, date_to)


# Szkolenie bez „konca" (zapomniany skan, brak „Koniec pracy") liczymy do teraz,
# ale najwyzej tyle — inaczej jedno zapomniane wejscie sprzed tygodnia robiloby
# „szkoleniowymi" wszystkie paczki tej osoby az do dzis.
MAKS_OTWARTEGO_SZKOLENIA = timedelta(hours=12)


def okresy_szkolen(user_ids, date_from=None, date_to=None, najwczesniej=None):
    """`(prowadzone, jako_szkolony)` — dwa `{uid: [(start, koniec)]}` (naive UTC).

    `prowadzone` = szkolenia, ktore osoba prowadzila (`training_*`),
    `jako_szkolony` = czas, w ktorym sama byla szkolona (`trainee_*`). Jedno
    zapytanie na oba rodzaje. Pary start/koniec skladamy w obrebie (osoba,
    zmiana), tak samo jak `_compute_worker_times()`. Margines doby przy
    granicach zakresu: paczka zakonczona tuz po polnocy moze lezec w szkoleniu
    zaczetym wieczorem. `najwczesniej` = najwczesniejszy start paczki w
    zakresie (naive UTC): paczka zaczeta dni przed `date_from` liczy sie cala,
    gdy zahaczyla o szkolenie — bez tego wynik zalezal od wybranego zakresu.
    """
    if not user_ids:
        return {}, {}
    q = WorkerTimeEvent.query.filter(
        WorkerTimeEvent.user_id.in_(list(user_ids)),
        WorkerTimeEvent.event_type.in_(
            ('training_start', 'training_end', 'trainee_start', 'trainee_end')))
    margines = timedelta(days=1)
    if date_from:
        od = local_day_bounds(date_from)[0]
        if najwczesniej and najwczesniej < od:
            od = najwczesniej
        q = q.filter(WorkerTimeEvent.timestamp >= od - margines)
    if date_to:
        q = q.filter(WorkerTimeEvent.timestamp < local_day_bounds(date_to)[1] + margines)

    otwarte = {}
    wynik = {'training': {}, 'trainee': {}}
    for e in q.order_by(WorkerTimeEvent.timestamp, WorkerTimeEvent.id):
        rodzaj, _, koncowka = e.event_type.rpartition('_')
        klucz = (rodzaj, e.user_id, e.shift_id)
        if koncowka == 'start':
            otwarte[klucz] = e.timestamp
        elif klucz in otwarte:
            wynik[rodzaj].setdefault(e.user_id, []).append((otwarte.pop(klucz), e.timestamp))
    teraz = teraz_utc()
    for (rodzaj, uid, _), start in otwarte.items():
        wynik[rodzaj].setdefault(uid, []).append(
            (start, min(teraz, start + MAKS_OTWARTEGO_SZKOLENIA)))
    return wynik['training'], wynik['trainee']


def cele_dzienne():
    """Funkcja `dzien -> cel szt./h obowiazujacy tego dnia` (0 = nie ustawiono).

    Z `HistoriaCelu`; dzien sprzed pierwszego wpisu (historia jeszcze nie
    zasiana) dostaje biezaca wartosc ustawienia.
    """
    wiersze = HistoriaCelu.query.order_by(HistoriaCelu.dzien).all()
    dni = [w.dzien for w in wiersze]
    wartosci = [w.wartosc for w in wiersze]
    biezacy = get_setting_int('target_szt_h', 0)

    def cel(dzien):
        i = bisect_right(dni, dzien)
        return wartosci[i - 1] if i else biezacy
    return cel


def zmiany_celu(date_from=None, date_to=None):
    """Cele obowiazujace w zakresie dni: `[{'od': iso|None, 'wartosc'}]`, rosnaco.

    Pierwszy element to cel obowiazujacy juz na poczatku zakresu (`od` = jego
    prawdziwy dzien wpisu; `None` = zasiew „od zawsze"). Wartosc 0 = brak celu.
    """
    wiersze = HistoriaCelu.query.order_by(HistoriaCelu.dzien).all()
    wynik = []
    for w in wiersze:
        if date_to and w.dzien > date_to:
            break
        wpis = {'od': None if w.dzien == POCZATEK_HISTORII_CELU else w.dzien.isoformat(),
                'wartosc': w.wartosc}
        if date_from and w.dzien <= date_from:
            wynik = [wpis]             # obowiazywal juz na poczatku zakresu
        else:
            wynik.append(wpis)
    if not wynik:
        wynik = [{'od': None, 'wartosc': get_setting_int('target_szt_h', 0)}]
    return wynik


def zasiej_historie_celu():
    """Pusta `HistoriaCelu` → jeden wiersz z biezacym celem od `POCZATEK_HISTORII_CELU`.

    Bez tego pierwsza zmiana celu po wdrozeniu przeliczylaby wstecz wszystkie
    wczesniejsze szkolenia (dzien bez wpisu bralby biezacy cel). Bez commitu.
    """
    if HistoriaCelu.query.first() is None:
        db.session.add(HistoriaCelu(dzien=POCZATEK_HISTORII_CELU,
                                    wartosc=get_setting_int('target_szt_h', 0)))


def przeglad_zespolu(date_from, date_to):
    """Przeglad calego zespolu: kto wyrabia najlepiej, kto odstaje.

    Jedyna definicja oceny — korzysta z niej i zakladka „Przeglad ogolny",
    i karta oceny w widoku per pracownik (`norma_pracownika()`), zeby ta sama
    osoba w tym samym okresie nigdy nie dostala dwoch roznych wynikow.

    Odniesieniem jest **srednia zespolu** z wybranego okresu, liczona jako
    wszystkie sztuki / wszystkie godziny skanowania (decyzja z 2026-09-28,
    wczesniej mediana). Wchodza WSZYSCY ze zmierzonym czasem, takze osoby
    ponizej `min_packages_rank` — ale kazda wazy tyle, ile przepracowala, wiec
    konto z dwiema blyskawicznymi paczkami (26 038 szt./h na .31) nie wypacza
    wyniku, jak zrobilaby to zwykla srednia z wynikow osob (2 570 zamiast 292).
    Prog paczek nadal decyduje tylko o tym, kto jest w rankingu i dostaje ocene.

    Paczki zahaczajace o szkolenie (osoba szkolaca) licza sie jej cale jako
    100% celu i nie wchodza do sredniej — patrz `policz_wydajnosc()`.
    """
    prog_dobry = get_setting_int('norm_good_pct', 110)
    prog_slaby = get_setting_int('norm_weak_pct', 90)
    min_paczek = get_setting_int('min_packages_rank', 3)

    dane = wydajnosc_pracownikow(date_from, date_to)
    szkolenia, szkoleni = okresy_szkolen(
        dane.keys(), date_from, date_to,
        najwczesniej=min((p[0] for ps in dane.values() for p in ps if p[0]), default=None))
    # Cel z dnia pracy (2026-10-13): kazdy liczony celem, ktory obowiazywal,
    # gdy skanowal — zmiana celu nie przelicza starych dni.
    cel_dnia = cele_dzienne()
    # joinedload: rodzaj pracownika i nazwa zmiany ida do kazdego wiersza.
    uzytkownicy = {u.id: u for u in User.query.options(
        joinedload(User.worker_type), joinedload(User.shift_group)).filter(
        User.id.in_(dane.keys())).all()} if dane else {}

    wiersze = []
    suma_sztuk_z_czasem = 0
    suma_godzin_z_czasem = 0.0
    sekundy_z_celem = 0.0
    cel_x_sekundy = 0.0
    for uid, paczki in dane.items():
        user = uzytkownicy.get(uid)
        if not user:
            continue                   # konto skasowane twardo — pomijamy
        w = policz_wydajnosc(paczki, szkolenia.get(uid, ()), cel_dnia,
                             szkoleni.get(uid, ()))
        if w['sekundy_do_sredniej'] > 0:
            # Paczki bez zmierzonego czasu nie wchodza do sredniej — sztuki
            # bez godzin zawyzylyby ja. Paczki ze szkolenia tez nie (sa
            # z definicji rowno w celu).
            suma_sztuk_z_czasem += w['sztuk_do_sredniej']
            suma_godzin_z_czasem += w['sekundy_do_sredniej'] / 3600.0
        sekundy_z_celem += w['sekundy_z_celem']
        cel_x_sekundy += w['cel_x_sekundy']
        wiersze.append({
            'user_id': uid,
            'display_name': user.display_name,
            'is_active_user': user.is_active_user,
            'worker_type': user.worker_type.name if user.worker_type else None,
            'shift_group': user.shift_group.name if user.shift_group else None,
            'paczek': w['paczek'],
            'sztuk': w['sztuk'],
            'godzin': round(w['sekundy'] / 3600.0, 2),
            'szt_h': w['szt_h'],
            # Paczki zrobione w czasie szkolenia (liczone jako 100% celu dnia).
            'paczek_szkolenia': w['paczek_szkolenia'],
            'godzin_szkolenia': round(w['sekundy_szkolenia'] / 3600.0, 2),
            # Paczki zrobione jako osoba szkolona — wypadaja z oceny.
            'paczek_jako_szkolony': w['paczek_jako_szkolony'],
            'godzin_jako_szkolony': round(w['sekundy_jako_szkolony'] / 3600.0, 2),
            'paczek_do_oceny': w['paczek_do_oceny'],
            # Cel tej osoby: srednia celow z dni, w ktore skanowala (wazona godzinami).
            'cel_szt_h': w['cel_szt_h'],
        })

    # Do rankingu wchodzi tylko ten, kto ma dosc paczek i zmierzony czas.
    # Reszta ladu je w osobnym koszyku — ukrycie jej sugerowaloby, ze nie
    # pracowala, a to nieprawda: po prostu nie ma z czego liczyc sredniej.
    def kwalifikuje(r):
        return r['paczek_do_oceny'] >= min_paczek and r['szt_h'] is not None

    ranking = [r for r in wiersze if kwalifikuje(r)]
    za_malo = [r for r in wiersze if not kwalifikuje(r)]

    srednia = (suma_sztuk_z_czasem / suma_godzin_z_czasem
               if suma_godzin_z_czasem > 0 else None)

    for r in ranking:
        if srednia and srednia > 0:
            proc = round(r['szt_h'] / srednia * 100)
            r['proc_sredniej'] = proc
            r['ocena'] = ('dobra' if proc >= prog_dobry
                          else 'slaba' if proc <= prog_slaby else 'ok')
        else:
            r['proc_sredniej'] = None
            r['ocena'] = None
        # Cel jest poprzeczka do przeskoczenia, wiec ocena jest dwustanowa:
        # 100% = spelnia. NIE uzywamy tu pasm norm_good/norm_weak — te opisuja
        # odchylenie od sredniej zespolu, a lider, ktory wpisal liczbe jako
        # wymagany poziom, przeczytalby „rowno w celu = tylko ok" jako blad.
        if r['cel_szt_h']:
            proc_celu = round(r['szt_h'] / r['cel_szt_h'] * 100)
            r['proc_celu'] = proc_celu
            r['ocena_celu'] = 'spelnia' if proc_celu >= 100 else 'ponizej'
        else:
            r['proc_celu'] = None
            r['ocena_celu'] = None
    for r in za_malo:
        r['proc_sredniej'] = None
        r['ocena'] = None
        r['proc_celu'] = None
        r['ocena_celu'] = None

    ranking.sort(key=lambda r: r['szt_h'], reverse=True)
    za_malo.sort(key=lambda r: r['display_name'])

    # Cel zespolu w okresie: wazony godzinami wszystkich; bez godzin — cel
    # z ostatniego dnia zakresu (zeby kolumna celu nie znikala na pustym dniu).
    zmiany = zmiany_celu(date_from, date_to)
    if sekundy_z_celem > 0:
        cel = round(cel_x_sekundy / sekundy_z_celem, 1)
    else:
        cel = cel_dnia(date_to or local_today()) or None

    return {
        'date_from': date_from.isoformat() if date_from else None,
        'date_to': date_to.isoformat() if date_to else None,
        'srednia_szt_h': round(srednia, 1) if srednia else None,
        'cel_szt_h': cel,
        # Cele obowiazujace w zakresie, rosnaco — >1 = cel zmienial sie po drodze.
        'cele_w_okresie': zmiany,
        'progi': {'dobry': prog_dobry, 'slaby': prog_slaby, 'min_paczek': min_paczek},
        # Bez celu albo bez nikogo w rankingu nie ma czego zliczac — `None`,
        # nie 0. „0 / 0" czytaloby sie jak „nikt nie spelnia" albo, gorzej,
        # jak komplet (0 z 0 to przeciez wszyscy).
        'spelnia_cel': (sum(1 for r in ranking if r['ocena_celu'] == 'spelnia')
                        if cel and ranking else None),
        'pracownicy': ranking,
        'za_malo_danych': za_malo,
        'podsumowanie': {
            'osob': len(wiersze),
            'w_rankingu': len(ranking),
            'paczek': sum(r['paczek'] for r in wiersze),
            'sztuk': sum(r['sztuk'] for r in wiersze),
            'godzin': round(sum(r['godzin'] for r in wiersze), 2),
        },
    }


def norma_pracownika(user_id, date_from, date_to):
    """Ocena jednej osoby na tle zespolu — wiersz wyjety z `przeglad_zespolu()`.

    Nie liczymy niczego drugi raz: srednia, progi i cel sa te same co w
    przegladzie, wiec % sredniej i ocena zgadzaja sie z rankingiem co do joty.
    """
    p = przeglad_zespolu(date_from, date_to)
    wynik = {
        'srednia_szt_h': p['srednia_szt_h'],
        'cel_szt_h': p['cel_szt_h'],
        'progi': p['progi'],
        'w_rankingu': len(p['pracownicy']),
        'miejsce': None,
        'powod_braku_oceny': None,
        'wiersz': None,
    }
    for i, r in enumerate(p['pracownicy']):
        if r['user_id'] == user_id:
            wynik['miejsce'] = i + 1
            wynik['wiersz'] = r
            # Cel tej osoby — z dni, w ktore pracowala (% celu liczony wlasnie nim).
            if r['cel_szt_h'] is not None:
                wynik['cel_szt_h'] = r['cel_szt_h']
            return wynik
    for r in p['za_malo_danych']:
        if r['user_id'] == user_id:
            wynik['wiersz'] = r
            if r['cel_szt_h'] is not None:
                wynik['cel_szt_h'] = r['cel_szt_h']
            wynik['powod_braku_oceny'] = (
                'szkolony' if r['paczek_do_oceny'] == 0 and r['paczek_jako_szkolony']
                else 'brak_czasu' if r['szt_h'] is None
                else 'za_malo_paczek')
            return wynik
    wynik['powod_braku_oceny'] = 'brak_paczek'
    return wynik


def wykres_wydajnosci(paczki_per_klucz, szkolenia=(), cel_dnia=None, jako_szkolony=()):
    """`{klucz: [(start, koniec, sztuk)]}` → lista punktow wykresu, rosnaco.

    Liczy `policz_wydajnosc()` — ta sama miara co w przegladzie, lacznie
    z paczkami ze szkolenia (100% celu dnia). Slupki (`sztuk`) to prawdziwe
    sztuki. Bez zmierzonego czasu `szt_h` = None, nie 0: zero wygladaloby na
    fatalny dzien, a to po prostu brak skanu „Start".
    """
    punkty = []
    for klucz in sorted(paczki_per_klucz):
        w = policz_wydajnosc(paczki_per_klucz[klucz], szkolenia, cel_dnia, jako_szkolony)
        punkty.append({
            'okres': klucz,
            'paczek': w['paczek'],
            'sztuk': w['sztuk'],
            'godzin': round(w['sekundy'] / 3600.0, 2),
            'szt_h': w['szt_h'],
            'paczek_szkolenia': w['paczek_szkolenia'],
            'paczek_jako_szkolony': w['paczek_jako_szkolony'],
            # Cel z dni tego punktu; dzien bez zmierzonego czasu — cel tego dnia.
            'cel': (w['cel_szt_h'] if w['cel_szt_h'] is not None
                    else (cel_dnia(date.fromisoformat(klucz)) or None)
                    if cel_dnia and len(klucz) == 10 else None),
        })
    return punkty


def podsumuj_paczki_pracownika(per_day):
    """Srednie paczek i sztuk jednej osoby z `{'YYYY-MM-DD': {'cnt', 'pcs'}}`.

    Mianownikiem sa dni i miesiace, w ktorych osoba FAKTYCZNIE zakonczyla
    choc jedna paczke — nie dni kalendarzowe zakresu. Inaczej urlop albo
    weekend zanizalyby srednia, a lider czyta ja jako „ile robi, kiedy jest".
    Srednia miesieczna liczy miesiace z praca w wybranym okresie, wiec przy
    zakresie „30 dni" przecinajacym dwa miesiace dzieli przez 2.
    """
    paczek = sum(a['cnt'] for a in per_day.values())
    sztuk = sum(a['pcs'] for a in per_day.values())
    dni = len(per_day)
    miesiecy = len({d[:7] for d in per_day})

    def srednio(ile, przez):
        return round(ile / przez, 1) if przez else None

    return {
        'paczek': paczek,
        'sztuk': sztuk,
        'dni_pracy': dni,
        'miesiecy_pracy': miesiecy,
        'srednio_dziennie': {'paczek': srednio(paczek, dni), 'sztuk': srednio(sztuk, dni)},
        'srednio_miesiecznie': {'paczek': srednio(paczek, miesiecy),
                                'sztuk': srednio(sztuk, miesiecy)},
    }
