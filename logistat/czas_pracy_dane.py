"""Czas pracy — dane z bazy: podsumowanie przerw / Inne / szkolen osoby na zmianie
(`_compute_worker_times`), wiersze ekranu Czasy pracowników (`wiersze_czasow`)
i otwarci szkoleni danego trenera."""
from datetime import timedelta

from sqlalchemy.orm import joinedload

from logistat.czas import iso_z, teraz_utc
from logistat.extensions import db
from logistat.models import (
    Activity, ActivityAssignment, Shift, ShiftAttendance, User, WorkerTimeEvent)
from logistat.okresy import suma_zlaczonych_okresow

# Filtr po osobie na /worker-times: najdluzszy zakres dni naraz.
MAX_DNI_OSOBY = 92


def wiersze_czasow(date_from, date_to, user_id=None):
    """Wiersze ekranu Czasy pracowników: jeden na (osoba, dzien), od
    najwczesniejszej obecnosci tego dnia (obie zmiany), posortowane po dniu
    i nazwisku. `czynnosci` = nazwy czynnosci z Przydzielania tej osoby w tym
    dniu (bez godzin — przydzial nie ma godzin; operacja 2026-10-23)."""
    q = (ShiftAttendance.query.join(Shift)
         .filter(Shift.date >= date_from, Shift.date <= date_to)
         .options(joinedload(ShiftAttendance.user), joinedload(ShiftAttendance.shift),
                  joinedload(ShiftAttendance.poprawiajacy)))
    if user_id is not None:
        q = q.filter(ShiftAttendance.user_id == user_id)
    pierwsza = {}
    zmiany_dnia = {}    # (dzien, osoba) → shift_id wszystkich obecnosci tego dnia
    for att in q.all():
        klucz = (att.shift.date, att.user_id)
        zmiany_dnia.setdefault(klucz, set()).add(att.shift_id)
        if klucz not in pierwsza or att.scanned_at < pierwsza[klucz].scanned_at:
            pierwsza[klucz] = att
    if not pierwsza:
        return []

    czynnosci = {}
    przydzialy = (db.session.query(Shift.date, ActivityAssignment.user_id, Activity.name)
                  .join(ActivityAssignment, ActivityAssignment.shift_id == Shift.id)
                  .join(Activity, Activity.id == ActivityAssignment.activity_id)
                  .filter(Shift.date >= date_from, Shift.date <= date_to,
                          ActivityAssignment.user_id.in_({u for _, u in pierwsza}))
                  .order_by(Activity.sort_order, Activity.name))
    for dzien, uid, nazwa in przydzialy:
        lista = czynnosci.setdefault((dzien, uid), [])
        if nazwa not in lista:
            lista.append(nazwa)

    # Zdarzenia wszystkich wierszy jednym zapytaniem (filtr osoby: do 92 dni) — ze
    # wszystkich obecnosci dnia: do 2026-10-24 przy dwoch obecnosciach zdarzenia
    # szly na pozniejsza, a wiersz jest od najwczesniejszej.
    dzien_zmiany = {sid: d for (d, _), sids in zmiany_dnia.items() for sid in sids}
    zdarzenia = {}
    for e in (WorkerTimeEvent.query
              .filter(WorkerTimeEvent.shift_id.in_(set(dzien_zmiany)),
                      WorkerTimeEvent.user_id.in_({u for _, u in pierwsza}))
              .options(joinedload(WorkerTimeEvent.user), joinedload(WorkerTimeEvent.recorder))
              .order_by(WorkerTimeEvent.timestamp).all()):
        if e.shift_id in zmiany_dnia.get((dzien_zmiany[e.shift_id], e.user_id), ()):
            zdarzenia.setdefault((e.user_id, dzien_zmiany[e.shift_id]), []).append(e)

    wynik = []
    for (dzien, uid), att in pierwsza.items():
        wiersz = _compute_worker_times(uid, att.shift, att.scanned_at,
                                       zdarzenia.get((uid, dzien), []))
        wiersz.update({
            'date':          dzien.isoformat(),
            'user_id':       uid,
            'user_name':     att.user.display_name,
            'shift_id':      att.shift_id,
            'shift_number':  att.shift.shift_number,
            'shift_in':      iso_z(att.scanned_at),
            'attendance_id': att.id,
            'wejscie_poprawione': ({
                'pierwotny_skan': iso_z(att.pierwotny_skan),
                'kto': att.poprawiajacy.display_name if att.poprawiajacy else None,
                'kiedy': iso_z(att.poprawione_at),
            } if att.poprawione_at else None),
            'czynnosci':     czynnosci.get((dzien, uid), []),
        })
        wynik.append(wiersz)
    wynik.sort(key=lambda w: (w['date'], w['user_name']))
    return wynik


def _compute_worker_times(uid, shift, attendance_time, events=None):
    """Return break/work summary for one worker-shift pair.

    `events` — zdarzenia tej osoby na tej zmianie posortowane po czasie, jesli
    wolajacy pobral je hurtem (wiersze_czasow, bez N+1); inaczej zapytanie."""
    if events is None:
        events = WorkerTimeEvent.query.filter_by(
            user_id=uid, shift_id=shift.id
        ).order_by(WorkerTimeEvent.timestamp).all()

    break_secs = 0
    other_secs = 0
    training_secs = 0
    trainee_secs = 0
    open_break = None
    open_other = None
    open_training = None
    open_trainee = None
    work_end_ts = None
    breaks = []
    others = []
    trainings = []
    trainee_periods = []
    okresy = []          # (start, koniec) wszystkich zamknietych przerw i „Innych"

    for e in events:
        if e.event_type == 'break_start':
            open_break = e.timestamp
        elif e.event_type == 'break_end' and open_break:
            secs = (e.timestamp - open_break).total_seconds()
            breaks.append({'start': iso_z(open_break), 'end': iso_z(e.timestamp),
                           'minutes': int(secs / 60)})
            break_secs += secs
            okresy.append((open_break, e.timestamp))
            open_break = None
        elif e.event_type == 'other_start':
            open_other = e.timestamp
        elif e.event_type == 'other_end' and open_other:
            secs = (e.timestamp - open_other).total_seconds()
            others.append({'start': iso_z(open_other), 'end': iso_z(e.timestamp),
                           'minutes': int(secs / 60)})
            other_secs += secs
            okresy.append((open_other, e.timestamp))
            open_other = None
        elif e.event_type == 'training_start':
            open_training = e.timestamp
        elif e.event_type == 'training_end' and open_training:
            # Szkolenie to praca — NIE trafia do `okresy`, wiec nie pomniejsza
            # czasu pracy; raportujemy je tylko osobno.
            secs = (e.timestamp - open_training).total_seconds()
            trainings.append({'start': iso_z(open_training), 'end': iso_z(e.timestamp),
                              'minutes': int(secs / 60)})
            training_secs += secs
            open_training = None
        elif e.event_type == 'trainee_start':
            open_trainee = e.timestamp
        elif e.event_type == 'trainee_end' and open_trainee:
            # Bycie szkolonym to tez praca — nie pomniejsza czasu pracy.
            secs = (e.timestamp - open_trainee).total_seconds()
            trainee_periods.append({'start': iso_z(open_trainee), 'end': iso_z(e.timestamp),
                                    'minutes': int(secs / 60)})
            trainee_secs += secs
            open_trainee = None
        elif e.event_type == 'work_end':
            work_end_ts = e.timestamp

    if open_break:
        breaks.append({'start': iso_z(open_break), 'end': None, 'minutes': None})
    if open_other:
        others.append({'start': iso_z(open_other), 'end': None, 'minutes': None})
    if open_training:
        trainings.append({'start': iso_z(open_training), 'end': None, 'minutes': None})
    if open_trainee:
        trainee_periods.append({'start': iso_z(open_trainee), 'end': None, 'minutes': None})

    end_ref = work_end_ts or teraz_utc()
    # „Inne" (np. wyjscie do HR) pomniejsza czas pracy tak samo jak przerwa,
    # ale jest raportowane osobno — przerwa i „Inne" to rozne rzeczy dla operacji.
    #
    # Odejmujemy SUME ZLACZONYCH okresow, nie sume dlugosci: skan pilnuje, zeby
    # przerwa i „Inne" sie nie nakladaly, ale reczna korekta na /worker-times
    # (POST/PUT zdarzenia) moze stworzyc nachodzace okresy. Sumowanie dlugosci
    # odjeloby wtedy te same minuty dwa razy i czas pracy wyszedlby za niski.
    work_secs = max(0, (end_ref - attendance_time).total_seconds()
                    - suma_zlaczonych_okresow(okresy))

    return {
        'work_end':      iso_z(work_end_ts),
        'break_minutes': int(break_secs / 60),
        'other_minutes': int(other_secs / 60),
        'training_minutes': int(training_secs / 60),
        'trainee_minutes': int(trainee_secs / 60),
        'work_minutes':  int(work_secs / 60),
        'breaks':        breaks,
        'others':        others,
        'trainings':     trainings,
        'trainee_periods': trainee_periods,
        'on_break':      open_break is not None,
        'on_other':      open_other is not None,
        'on_training':   open_training is not None,
        'on_trainee':    open_trainee is not None,
        'work_ended':    work_end_ts is not None,
        'events':        [e.to_dict() for e in events],
    }


def otwarci_szkoleni(trener_id):
    """`[(user, shift_id)]` osob szkolonych z otwartym szkoleniem u `trener_id`."""
    od = teraz_utc() - timedelta(days=2)     # szkolenie nie trwa dluzej
    pary = {(e.user_id, e.shift_id) for e in WorkerTimeEvent.query.filter(
        WorkerTimeEvent.training_lead_id == trener_id,
        WorkerTimeEvent.event_type == 'trainee_start',
        WorkerTimeEvent.timestamp >= od)}
    wynik = []
    for uid, shift_id in sorted(pary):
        zdarzenia = WorkerTimeEvent.query.filter(
            WorkerTimeEvent.user_id == uid, WorkerTimeEvent.shift_id == shift_id,
            WorkerTimeEvent.event_type.in_(('trainee_start', 'trainee_end'))
        ).order_by(WorkerTimeEvent.timestamp, WorkerTimeEvent.id).all()
        typy = [e.event_type for e in zdarzenia]
        starty = [e for e in zdarzenia if e.event_type == 'trainee_start']
        # Otwarte szkolenie nalezy do szkolacego z OSTATNIEGO startu (stany sie
        # wykluczaja, wiec otwarty moze byc tylko jeden). Wczesniej wystarczal
        # dowolny start u tego trenera — koniec szkolenia A zamykal osobe u B.
        if (typy.count('trainee_start') > typy.count('trainee_end')
                and starty[-1].training_lead_id == trener_id):
            wynik.append((db.session.get(User, uid), shift_id))
    return wynik
