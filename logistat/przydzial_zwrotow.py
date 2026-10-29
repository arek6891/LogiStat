"""Przydzial osob do stanowisk zwrotow i dashboard zwrotow (operacja 2026-10-27).

Pracownik nie skanuje identyfikatora przy przyjeciu zwrotu — paczka nalezy do
STANOWISKA (konto roli `stanowisko`, ktore ja zapisalo), a osoby do stanowiska
przydziela lider: Przydzielanie → czynnosc „Zwroty” → ekran stanowisk. Paczka
dzieli sie po rowno na osoby przydzielone do stanowiska w chwili przyjecia.
Kto byl na stanowisku, liczy JEDNA funkcja `kto_na_stanowisku()` — ta sama dla
blokady przyjecia (409 bez obsady) i dla dashboardu.
"""
from datetime import timedelta

from logistat.czas import iso_z, local_day_bounds, local_today, utc_to_local
from logistat.extensions import db
from logistat.models import (
    Activity, ActivityAssignment, PrzydzialZwrotow, Shift, User, WorkerTimeEvent, ZwrotPaczki)
from logistat.okresy import odejmij_okresy
from logistat.przyjecie_zwrotu import (
    CZYNNOSC_ZWROTOW, MAX_GODZIN_PRZYDZIALU, efektywne_okresy, kto_na_stanowisku, przerwy_osob)


def stanowiska_zwrotow():
    """Stanowiska = aktywne konta roli `stanowisko` (operacja: kazdy komputer
    zwrotow loguje sie swoim kontem)."""
    return User.query.filter_by(role='stanowisko', is_active_user=True)\
        .order_by(User.display_name, User.id).all()


def okresy_w_zakresie(start, koniec):
    """`efektywne_okresy()` przydzialow, ktore moga zachodzic na [start, koniec)
    (naive UTC). Otwarty wiersz starszy niz MAX_GODZIN_PRZYDZIALU juz sie nie liczy."""
    najwczesniej = start - timedelta(hours=MAX_GODZIN_PRZYDZIALU)
    wiersze = PrzydzialZwrotow.query.filter(
        PrzydzialZwrotow.od < koniec, PrzydzialZwrotow.od >= najwczesniej,
        db.or_(PrzydzialZwrotow.do.is_(None), PrzydzialZwrotow.do > start)).all()
    if not wiersze:
        return []
    osoby = {w.user_id for w in wiersze}
    konce = {}
    for user_id, kiedy in db.session.query(WorkerTimeEvent.user_id, WorkerTimeEvent.timestamp)\
            .filter(WorkerTimeEvent.event_type == 'work_end', WorkerTimeEvent.user_id.in_(osoby),
                    WorkerTimeEvent.timestamp > najwczesniej)\
            .order_by(WorkerTimeEvent.timestamp):
        konce.setdefault(user_id, []).append(kiedy)
    return efektywne_okresy(
        [(w.user_id, w.stanowisko_id, w.support, w.od, w.do) for w in wiersze], konce)


def obsada_stanowiska(stanowisko_id, chwila):
    """Id osob na stanowisku w danej chwili (blokada przyjecia zwrotu)."""
    return kto_na_stanowisku(okresy_w_zakresie(chwila, chwila + timedelta(seconds=1)),
                             stanowisko_id, chwila)


# ── ekran przydzialu ─────────────────────────────────────────────────────────

def czynnosc_zwrotow():
    """Czynnosc „Zwroty” z Przydzielania (po nazwie) albo None."""
    return Activity.query.filter_by(name=CZYNNOSC_ZWROTOW).first()


def osoby_na_zwrotach(shift):
    """Id osob przydzielonych w Przydzielaniu do czynnosci „Zwroty” na zmianie."""
    czynnosc = czynnosc_zwrotow()
    if czynnosc is None:
        return set()
    return {u for (u,) in db.session.query(ActivityAssignment.user_id).filter_by(
        shift_id=shift.id, activity_id=czynnosc.id)}


def stan_przydzialu(shift):
    """Dane ekranu: pula osob (z czynnosci Zwroty + kazdy z otwartym wierszem tej
    zmiany), gdzie kto teraz jest, i otwarte przydzialy INNYCH zmian na stanowiskach
    (poprzednia zmiana bez „Koniec pracy” — lider moze je zakonczyc)."""
    na_zwrotach = osoby_na_zwrotach(shift)
    pula = set(na_zwrotach)
    otwarte = PrzydzialZwrotow.query.filter(PrzydzialZwrotow.do.is_(None)).all()
    otwarte_os = {w.user_id: w for w in otwarte}
    pula |= {w.user_id for w in otwarte if w.shift_id == shift.id}
    ludzie = {u.id: u for u in User.query.filter(User.id.in_(pula | set(otwarte_os))).all()} \
        if (pula or otwarte_os) else {}

    def miejsce(w):
        # Support siedzi przy stanowisku (2026-10-29) — miejsce = to stanowisko,
        # `support` mowi, ze bez udzialu w paczkach.
        if w is None or w.shift_id != shift.id:
            return None
        return w.stanowisko_id

    osoby = sorted((
        {'user_id': u, 'nazwa': ludzie[u].display_name if u in ludzie else f'#{u}',
         'miejsce': miejsce(otwarte_os.get(u)),
         'support': bool(otwarte_os.get(u) and otwarte_os[u].shift_id == shift.id
                         and otwarte_os[u].support),
         'od': iso_z(otwarte_os[u].od) if u in otwarte_os else None,
         'na_innej_zmianie': u in otwarte_os and otwarte_os[u].shift_id != shift.id,
         'poza_zwrotami': u not in na_zwrotach}
        for u in pula), key=lambda o: o['nazwa'].lower())
    zmiany = {s.id: s for s in Shift.query.filter(
        Shift.id.in_({w.shift_id for w in otwarte})).all()} if otwarte else {}
    inne = [{'user_id': w.user_id, 'nazwa': ludzie[w.user_id].display_name,
             'stanowisko_id': w.stanowisko_id, 'support': w.support,
             'od': iso_z(w.od),
             'zmiana': f'{zmiany[w.shift_id].date:%d.%m} · Zmiana {zmiany[w.shift_id].shift_number}'}
            for w in otwarte if w.shift_id != shift.id]
    return {
        'stanowiska': [{'id': s.id, 'nazwa': s.display_name} for s in stanowiska_zwrotow()],
        'osoby': osoby, 'inne_zmiany': inne,
        'czynnosc': CZYNNOSC_ZWROTOW, 'brak_czynnosci': czynnosc_zwrotow() is None,
        'edycja': zmiana_edytowalna(shift.date),
    }


def zmiana_edytowalna(dzien):
    """Przydzial dziala „od teraz”, wiec zmienia sie tylko biezace zmiany: dzis albo
    wczoraj (druga zmiana pracuje po polnocy)."""
    return (local_today() - dzien).days in (0, 1)


def zamknij_otwarty(user_id, teraz):
    """Zamyka otwarty przydzial osoby (dowolnej zmiany) — True, gdy byl."""
    w = PrzydzialZwrotow.query.filter_by(user_id=user_id, do=None).with_for_update().first()
    if w is None:
        return False
    w.do = teraz
    return True


def przydziel(shift, user_id, stanowisko_id, support, teraz, kto_id):
    """Przeniesienie osoby: zamyka jej otwarty wiersz i otwiera nowy w TEJ SAMEJ
    chwili (bez dziury i nakladki). `stanowisko_id` None = zdjecie; `support` =
    pomaga przy tym stanowisku bez udzialu w paczkach.
    Commit robi wolajacy (blad indeksu „jeden otwarty” = rownolegla zmiana)."""
    zamknij_otwarty(user_id, teraz)
    db.session.flush()
    if stanowisko_id is not None:
        db.session.add(PrzydzialZwrotow(
            shift_id=shift.id, user_id=user_id, stanowisko_id=stanowisko_id,
            support=bool(support), od=teraz, przydzielil_id=kto_id))


def zamknij_poza_zwrotami(shift, teraz):
    """Po zapisie Przydzielania: kto zniknal z czynnosci „Zwroty”, ten schodzi ze
    stanowiska (inaczej dalej dostawalby paczki). Wolajacy trzyma blokade zmiany."""
    zostaja = osoby_na_zwrotach(shift)
    for w in PrzydzialZwrotow.query.filter_by(shift_id=shift.id, do=None).all():
        if w.user_id not in zostaja:
            w.do = teraz


# ── dashboard ────────────────────────────────────────────────────────────────

def _godziny_na_dni(start, koniec, dni):
    """Godziny okresu [start, koniec) w kazdym lokalnym dniu z `dni` (naive UTC)."""
    wynik = {}
    for d in dni:
        poczatek, nastepny = local_day_bounds(d)
        nakladka = (min(koniec, nastepny) - max(start, poczatek)).total_seconds()
        if nakladka > 0:
            wynik[d] = nakladka / 3600
    return wynik


def przerwy_w_zakresie(osoby, start, koniec, teraz):
    """`przerwy_osob()` osob z przerw i „Innych” zachodzacych na [start, koniec)."""
    if not osoby:
        return {}
    najwczesniej = start - timedelta(hours=MAX_GODZIN_PRZYDZIALU)
    zdarzenia = db.session.query(
        WorkerTimeEvent.user_id, WorkerTimeEvent.shift_id, WorkerTimeEvent.event_type,
        WorkerTimeEvent.timestamp).filter(
        WorkerTimeEvent.user_id.in_(osoby),
        WorkerTimeEvent.event_type.in_(('break_start', 'break_end', 'other_start', 'other_end',
                                        'work_end')),
        WorkerTimeEvent.timestamp >= najwczesniej, WorkerTimeEvent.timestamp < koniec)\
        .order_by(WorkerTimeEvent.timestamp, WorkerTimeEvent.id).all()
    return przerwy_osob(zdarzenia, teraz)


def dashboard_zwrotow(dni, teraz):
    """Statystyki dni `dni` (lista dat lokalnych, np. caly miesiac): przyjete paczki
    per stanowisko (+ kto pomagal jako Support), paczki i godziny per osoba (paczka
    po rowno na obsade stanowiska w chwili przyjecia) i obsada dnia.
    Godziny = czas na stanowisku NETTO — bez przerw i „Innych” z Czasu pracy
    (operacja 2026-10-29, jak w PP); trwajacy przydzial liczony do `teraz`.
    Support nie ma statystyk (operacja 2026-10-29) — tylko nazwiska przy stole."""
    start, koniec = local_day_bounds(dni[0])[0], local_day_bounds(dni[-1])[1]
    okresy = okresy_w_zakresie(start, koniec)
    przerwy = przerwy_w_zakresie({o[0] for o in okresy if not o[2]}, start, koniec, teraz)
    po_stanowisku = {}
    for o in okresy:
        po_stanowisku.setdefault(o[1], []).append(o)

    stanowiska = {s.id: {'id': s.id, 'nazwa': s.display_name, 'dni': {}, 'suma': 0, 'support': []}
                  for s in stanowiska_zwrotow()}
    osoby, support, nieprzypisane = {}, {}, {}
    zwroty = db.session.query(ZwrotPaczki.przyjal_id, ZwrotPaczki.przyjeto_at).filter(
        ZwrotPaczki.przyjeto_at >= start, ZwrotPaczki.przyjeto_at < koniec).all()
    for przyjal_id, kiedy in zwroty:
        dzien = utc_to_local(kiedy).date()
        if przyjal_id not in stanowiska:
            konto = db.session.get(User, przyjal_id) if przyjal_id else None
            stanowiska[przyjal_id] = {'id': przyjal_id, 'dni': {}, 'suma': 0, 'support': [],
                                      'nazwa': konto.display_name if konto else '—'}
        st = stanowiska[przyjal_id]
        st['dni'][dzien] = st['dni'].get(dzien, 0) + 1
        st['suma'] += 1
        obsada = kto_na_stanowisku(po_stanowisku.get(przyjal_id, []), przyjal_id, kiedy)
        if not obsada:
            nieprzypisane[dzien] = nieprzypisane.get(dzien, 0) + 1
        for u in obsada:
            os_ = osoby.setdefault(u, {'dni': {}, 'paczki': 0.0, 'godziny': 0.0})
            komorka = os_['dni'].setdefault(dzien, {'paczki': 0.0, 'godziny': 0.0})
            komorka['paczki'] += 1 / len(obsada)
            os_['paczki'] += 1 / len(obsada)

    obsada_dnia = {d: {'osoby': set(), 'support': set()} for d in dni}
    for user_id, stanowisko_id, sup, od, do in okresy:
        if sup:
            # Support: kto pomagal przy ktorym stole i ilu ich bylo w dniu — bez godzin.
            dni_okresu = _godziny_na_dni(od, min(do, teraz), dni)
            if dni_okresu:
                support.setdefault(stanowisko_id, set()).add(user_id)
            for d in dni_okresu:
                obsada_dnia[d]['support'].add(user_id)
            continue
        for czesc_od, czesc_do in odejmij_okresy(od, min(do, teraz), przerwy.get(user_id, ())):
            for d, godz in _godziny_na_dni(czesc_od, czesc_do, dni).items():
                os_ = osoby.setdefault(user_id, {'dni': {}, 'paczki': 0.0, 'godziny': 0.0})
                komorka = os_['dni'].setdefault(d, {'paczki': 0.0, 'godziny': 0.0})
                komorka['godziny'] += godz
                os_['godziny'] += godz
                obsada_dnia[d]['osoby'].add(user_id)

    pomocnicy = set().union(*support.values()) if support else set()
    nazwy = {u.id: (u.display_name, u.is_active_user) for u in User.query.filter(
        User.id.in_(set(osoby) | pomocnicy)).all()} if (osoby or pomocnicy) else {}
    for stanowisko_id, ludzie in support.items():
        if stanowisko_id in stanowiska:
            stanowiska[stanowisko_id]['support'] = sorted(
                (nazwy.get(u, (f'#{u}',))[0] for u in ludzie), key=str.lower)

    def wiersz(user_id, dane):
        nazwa, aktywny = nazwy.get(user_id, (f'#{user_id}', True))
        return {'id': user_id, 'nazwa': nazwa, 'aktywny': aktywny, **dane}

    for dane in osoby.values():
        dane['na_godzine'] = dane['paczki'] / dane['godziny'] if dane['godziny'] > 0 else None
    return {
        'dni': dni,
        'stanowiska': sorted(stanowiska.values(), key=lambda s: s['nazwa'].lower()),
        'osoby': sorted((wiersz(u, d) for u, d in osoby.items()), key=lambda r: r['nazwa'].lower()),
        'obsada': {d: {'osoby': len(v['osoby']), 'support': len(v['support'])}
                   for d, v in obsada_dnia.items()},
        'nieprzypisane': nieprzypisane,
        'suma_dni': {d: sum(s['dni'].get(d, 0) for s in stanowiska.values()) for d in dni},
    }
