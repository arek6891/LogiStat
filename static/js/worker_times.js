// Skrypt strony templates/worker_times.html (wyniesiony z szablonu 2026-10-16).
// Dane z serwera: blok <script> w szablonie tuz przed tym plikiem
// (BREAK_THRESHOLD, MAX_WORK_MINUTES, MIN_BREAK_MINUTES — progi z ustawien admina).
//
// Dwa widoki (2026-10-23, operacja):
// - bez osoby: jeden dzien, wszyscy obecni (`/api/worker-times?date=`);
// - z osoba: kazdy jej dzien w zakresie od–do (`?user_id=&date_from=&date_to=`).
// Pod kazdym wierszem os czasu: pasek wejscie → koniec pracy, na nim przerwy,
// Inne, szkolenie. Klik w znacznik = korekta tej godziny (takze wejscia),
// klik w pasek = nowy wpis o tej godzinie. Czynnosci z Przydzielania bez godzin.

// Dzis = lokalny dzien przegladarki (Warszawa), nie data UTC.
const dzisISO = toLocalDT(new Date().toISOString()).slice(0, 10);
document.getElementById('dateFilter').value = dzisISO;
document.getElementById('dateFrom').value = dzisISO.slice(0, 8) + '01';
document.getElementById('dateTo').value = dzisISO;

const ET_LABEL = {
    break_start: '☕ Przerwa wyjście', break_end: '✅ Przerwa powrót',
    other_start: '🚪 Inne wyjście',    other_end: '✅ Inne powrót',
    training_start: '🎓 Szkolenie start', training_end: '✅ Szkolenie koniec',
    trainee_start: '🎓 Szkolony start',   trainee_end: '✅ Szkolony koniec',
    work_end: '🏁 Koniec pracy',
};
const ET_IKONA = {
    break_start: '☕', break_end: '☕', other_start: '🚪', other_end: '🚪',
    training_start: '🎓', training_end: '🎓', trainee_start: '🎓', trainee_end: '🎓',
    work_end: '🏁',
};
const ET_COLOR = {
    break_start: 'var(--warning)', break_end: 'var(--success)',
    other_start: 'var(--accent)',  other_end: 'var(--success)',
    training_start: 'var(--info)', training_end: 'var(--success)',
    trainee_start: 'var(--info)',  trainee_end: 'var(--success)',
    work_end: 'var(--danger)',
};
const DNI_TYG = ['nd', 'pn', 'wt', 'śr', 'cz', 'pt', 'sb'];

function fmt(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleTimeString('pl', { hour: '2-digit', minute: '2-digit' });
}
function fmtMins(m) {
    if (m === null || m === undefined) return '—';
    const h = Math.floor(m / 60), mn = m % 60;
    return h > 0 ? `${h}h ${mn}min` : `${mn}min`;
}
function fmtDzien(iso) {
    const d = new Date(iso + 'T12:00:00');
    return `${DNI_TYG[d.getDay()]} ${iso.slice(8, 10)}.${iso.slice(5, 7)}`;
}
function toLocalDT(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const offset = d.getTimezoneOffset() * 60000;
    return new Date(d - offset).toISOString().slice(0, 16);
}
// Minuty od lokalnej polnocy dnia `dzien` (os czasu jest w czasie lokalnym).
function minutyDnia(iso, dzien) {
    const t = new Date(iso);
    const polnoc = new Date(dzien + 'T00:00:00');
    return (t - polnoc) / 60000;
}

const osobaWybrana = () => document.getElementById('workerFilter').value;

// Ostatnio pobrane dane — filtr bledow dziala na nich, bez ponownego zapytania.
let ostatniWynik = [];

function zmianaOsoby() {
    const osoba = !!osobaWybrana();
    document.getElementById('dateFilter').style.display = osoba ? 'none' : '';
    document.getElementById('zakresOsoby').style.display = osoba ? 'inline-flex' : 'none';
    loadData();
}

async function loadData() {
    const uid = osobaWybrana();
    let url;
    if (uid) {
        const od = document.getElementById('dateFrom').value;
        const doo = document.getElementById('dateTo').value;
        if (!od || !doo) { showToast('Wybierz zakres dat od–do.', 'error'); return; }
        url = `/api/worker-times?user_id=${encodeURIComponent(uid)}&date_from=${od}&date_to=${doo}`;
    } else {
        const dzien = document.getElementById('dateFilter').value;
        if (!dzien) return;
        url = `/api/worker-times?date=${dzien}`;
    }
    try {
        const res = await fetch(url);
        const data = await res.json();
        if (!res.ok) { showToast(data.error || 'Błąd ładowania.', 'error'); return; }
        ostatniWynik = data.workers || [];
    } catch {
        showToast('Błąd połączenia.', 'error');
        return;
    }
    rerender();
}

// Blad = cos, co lider powinien poprawic recznie. Brak przerwy i za krotka
// przerwa licza sie DOPIERO po koncu pracy — na trwajacej zmianie pracownik
// ma prawo jeszcze nie miec przerwy i nie jest to pomylka.
function bledyPracownika(w) {
    const bledy = [];
    if (w.work_minutes > MAX_WORK_MINUTES) {
        bledy.push(`Czas pracy ${fmtMins(w.work_minutes)} — ponad ${fmtMins(MAX_WORK_MINUTES)}`);
    }
    if (w.work_ended) {
        if (!w.break_minutes) {
            bledy.push('Brak przerwy');
        } else if (w.break_minutes < MIN_BREAK_MINUTES) {
            bledy.push(`Przerwa ${fmtMins(w.break_minutes)} — poniżej ${MIN_BREAK_MINUTES} min`);
        }
    }
    return bledy;
}

function filtrujWierszy(workers) {
    const tylkoBledy = document.getElementById('errorFilter').checked;
    return workers.filter(w => !tylkoBledy || bledyPracownika(w).length > 0);
}

function rerender() {
    const wiersze = filtrujWierszy(ostatniWynik);
    renderPodsumowanie(wiersze);
    renderTable(wiersze);
}

function renderPodsumowanie(wiersze) {
    const el = document.getElementById('podsumowanieOsoby');
    if (!osobaWybrana() || !wiersze.length) { el.style.display = 'none'; return; }
    const suma = (k) => wiersze.reduce((a, w) => a + (w[k] || 0), 0);
    el.innerHTML = `<strong>${escapeHtml(wiersze[0].user_name)}</strong>
        · dni: <strong>${wiersze.length}</strong>
        · czas pracy razem: <strong>${fmtMins(suma('work_minutes'))}</strong>
        · przerwy razem: <strong>${fmtMins(suma('break_minutes'))}</strong>
        · z błędami: <strong>${wiersze.filter(w => bledyPracownika(w).length).length}</strong>`;
    el.style.display = 'block';
}

// Koniec paska: koniec pracy, a bez niego — teraz (dzis) albo ostatnie zdarzenie.
function koniecPaska(w) {
    if (w.work_end) return w.work_end;
    if (w.date === dzisISO) return new Date().toISOString();
    const ostatnie = w.events.length ? w.events[w.events.length - 1].timestamp : null;
    return ostatnie || w.shift_in;
}

// Wspolna skala dla wszystkich wierszy (pelne godziny, min. 8 h) — paski
// roznych osob / dni mozna porownac wzrokiem.
function skala(wiersze) {
    let od = Infinity, doo = -Infinity;
    wiersze.forEach(w => {
        od = Math.min(od, minutyDnia(w.shift_in, w.date));
        doo = Math.max(doo, minutyDnia(koniecPaska(w), w.date));
    });
    od = Math.max(0, Math.floor(od / 60) * 60);
    doo = Math.min(24 * 60, Math.ceil(doo / 60) * 60);
    if (doo - od < 8 * 60) doo = Math.min(24 * 60, od + 8 * 60);
    return { od, doo };
}

function osCzasu(w, sk) {
    const zakres = sk.doo - sk.od;
    const pct = (iso) => Math.max(0, Math.min(100,
        (minutyDnia(iso, w.date) - sk.od) / zakres * 100));
    const koniec = koniecPaska(w);
    const odcinek = (klasa, okres, opis) => {
        const l = pct(okres.start), r = pct(okres.end || koniec);
        const czas = `${fmt(okres.start)}–${okres.end ? fmt(okres.end) : 'w trakcie'}`;
        return `<div class="os-odcinek ${klasa}" style="left:${l}%;width:${Math.max(r - l, .4)}%;"
                    title="${opis} ${czas}${okres.minutes != null ? ` (${okres.minutes} min)` : ''}"></div>`;
    };
    let godziny = '';
    for (let m = sk.od; m <= sk.doo; m += 60) {
        const l = (m - sk.od) / zakres * 100;
        godziny += `<span class="os-godzina" style="left:${l}%;">${String(m / 60).padStart(2, '0')}</span>`;
    }
    const lPraca = pct(w.shift_in), rPraca = pct(koniec);
    const znaczniki = w.events.map(e => `
        <button type="button" class="os-znacznik js-edit-event" style="left:${pct(e.timestamp)}%;--kolor:${ET_COLOR[e.event_type]};"
            data-event="${escapeHtml(JSON.stringify(e))}"
            title="${ET_LABEL[e.event_type]} ${fmt(e.timestamp)} — kliknij, aby poprawić">${ET_IKONA[e.event_type]}</button>`).join('');
    const popr = w.wejscie_poprawione;
    const tytulWejscia = `Wejście ${fmt(w.shift_in)}`
        + (popr ? ` (poprawione: ${popr.kto || '?'}, skan ${fmt(popr.pierwotny_skan)})` : '')
        + ' — kliknij, aby poprawić';
    return `
        <div class="os-czasu" data-dzien="${w.date}" data-od="${sk.od}" data-doo="${sk.doo}">
            <div class="os-godziny">${godziny}</div>
            <div class="os-tor js-add-na-osi" title="Kliknij, aby dodać wpis o tej godzinie"
                 data-user-id="${w.user_id}" data-user-name="${escapeHtml(w.user_name)}"
                 data-shift-id="${w.shift_id}">
                <div class="os-odcinek os-praca ${w.work_ended ? '' : 'os-otwarta'}"
                     style="left:${lPraca}%;width:${Math.max(rPraca - lPraca, .4)}%;"></div>
                ${w.breaks.map(b => odcinek('os-przerwa', b, 'Przerwa')).join('')}
                ${(w.others || []).map(b => odcinek('os-inne', b, 'Inne')).join('')}
                ${(w.trainings || []).map(b => odcinek('os-szkolenie', b, 'Szkolenie (prowadzi)')).join('')}
                ${(w.trainee_periods || []).map(b => odcinek('os-szkolony', b, 'Szkolony/a')).join('')}
                <button type="button" class="os-znacznik os-wejscie js-edit-wejscie ${popr ? 'os-poprawione' : ''}"
                    style="left:${lPraca}%;" title="${escapeHtml(tytulWejscia)}"
                    data-attendance-id="${w.attendance_id}" data-user-name="${escapeHtml(w.user_name)}"
                    data-shift-in="${w.shift_in}" data-dzien="${w.date}">▶</button>
                ${znaczniki}
            </div>
        </div>`;
}

function renderTable(workers) {
    const wrap = document.getElementById('tableWrap');
    const osoba = !!osobaWybrana();
    if (!workers.length) {
        const tekst = ostatniWynik.length && document.getElementById('errorFilter').checked
            ? 'Brak wierszy pasujących do filtrów.'
            : (osoba ? 'Ta osoba nie była na zmianie w tym zakresie dni.'
                     : 'Brak pracowników na zmianie w tym dniu.');
        wrap.innerHTML = `<div style="text-align:center;padding:3rem;color:var(--text-muted);">${tekst}</div>`;
        return;
    }
    const sk = skala(workers);
    const kolumn = osoba ? 11 : 10;

    let html = `<div style="overflow-x:auto;">
    <table class="data-table">
    <thead><tr>
        ${osoba ? '<th>Dzień</th>' : ''}
        <th>Pracownik</th>
        <th>Zmiana</th>
        <th>Wejście</th>
        <th>Przerwy</th>
        <th>Czas przerw</th>
        <th>Inne</th>
        <th title="Szkolenie to czas pracy — nie pomniejsza „Czasu pracy"">Szkolenie</th>
        <th>Koniec pracy</th>
        <th>Czas pracy</th>
        <th style="width:100px;"></th>
    </tr></thead>
    <tbody>`;

    workers.forEach(w => {
        const overBreak = w.break_minutes > BREAK_THRESHOLD;
        const bledy     = bledyPracownika(w);
        const rowStyle  = (overBreak || bledy.length)
            ? 'background:rgb(var(--danger-rgb) / .10);border-left:3px solid var(--danger);'
            : '';

        const okresy = lista => lista.map(b =>
            `${fmt(b.start)}–${b.end ? fmt(b.end) : '<span style="color:var(--warning);">w trakcie</span>'}${b.minutes !== null ? ` (${b.minutes}min)` : ''}`
        ).join('<br>') || '—';
        const breaksSummary = okresy(w.breaks);
        const otherSummary  = okresy(w.others || []);
        const trainingSummary = (w.trainings || []).length ? 'prowadzi: ' + okresy(w.trainings) : '';
        const traineeSummary  = (w.trainee_periods || []).length ? 'szkolony/a: ' + okresy(w.trainee_periods) : '';

        const bledyHtml = bledy.length ? `
            <div style="margin-top:4px;display:flex;flex-wrap:wrap;gap:4px;">
                ${bledy.map(b => `<span style="font-size:.7rem;background:var(--danger-bg);
                    color:var(--danger);padding:2px 8px;border-radius:8px;">⚠️ ${escapeHtml(b)}</span>`).join('')}
            </div>` : '';
        const czynnosci = (w.czynnosci || []).length
            ? `<div class="os-czynnosci">📋 ${w.czynnosci.map(c => `<span>${escapeHtml(c)}</span>`).join('')}</div>`
            : '<div class="os-czynnosci os-brak">📋 bez przydziału</div>';

        html += `
        <tr style="${rowStyle}">
            ${osoba ? `<td style="font-weight:700;white-space:nowrap;">${fmtDzien(w.date)}</td>` : ''}
            <td>
                <div style="display:flex;align-items:center;gap:8px;">
                    <div style="width:30px;height:30px;border-radius:50%;flex-shrink:0;
                        background:linear-gradient(135deg,var(--accent),var(--accent-2));
                        display:flex;align-items:center;justify-content:center;
                        font-size:.8rem;font-weight:700;color:var(--on-accent);">${escapeHtml(w.user_name[0])}</div>
                    <a class="link-normy" href="/stats?user=${w.user_id}" title="Otwórz normy pracownika" style="font-weight:600;">${escapeHtml(w.user_name)}</a>
                    ${w.on_break ? '<span style="margin-left:4px;font-size:.75rem;background:var(--warning-bg);color:var(--warning);padding:2px 8px;border-radius:8px;">na przerwie</span>' : ''}
                    ${w.on_other ? '<span style="margin-left:4px;font-size:.75rem;background:rgb(var(--accent-rgb) / .18);color:var(--accent);padding:2px 8px;border-radius:8px;">Inne</span>' : ''}
                    ${w.on_trainee ? '<span style="margin-left:4px;font-size:.75rem;background:var(--info-bg);color:var(--info);padding:2px 8px;border-radius:8px;">🎓 szkolony/a</span>' : ''}
                    ${w.on_training ? '<span style="margin-left:4px;font-size:.75rem;background:var(--info-bg);color:var(--info);padding:2px 8px;border-radius:8px;">🎓 szkolenie</span>' : ''}
                </div>
                ${czynnosci}
                ${bledyHtml}
            </td>
            <td><span class="shift-badge" data-shift="${parseInt(w.shift_number) || ''}">Zmiana ${parseInt(w.shift_number) || ''}</span></td>
            <td style="font-family:monospace;">${fmt(w.shift_in)}${w.wejscie_poprawione ? ' <span style="color:var(--warning);" title="poprawione">✎</span>' : ''}</td>
            <td style="font-size:.82rem;line-height:1.6;">${breaksSummary}</td>
            <td style="font-weight:700;color:${overBreak ? 'var(--danger)' : 'var(--warning)'};">
                ${fmtMins(w.break_minutes)}${overBreak ? ' ⚠️' : ''}
            </td>
            <td style="font-size:.82rem;line-height:1.6;">
                ${otherSummary}
                ${w.other_minutes ? `<div style="font-weight:700;color:var(--accent);">${fmtMins(w.other_minutes)}</div>` : ''}
            </td>
            <td style="font-size:.82rem;line-height:1.6;">
                ${trainingSummary}${trainingSummary && traineeSummary ? '<br>' : ''}${traineeSummary}
                ${!trainingSummary && !traineeSummary ? '—' : ''}
                ${(w.training_minutes || w.trainee_minutes) ? `<div style="font-weight:700;color:var(--info);">${fmtMins((w.training_minutes || 0) + (w.trainee_minutes || 0))}</div>` : ''}
            </td>
            <td style="font-family:monospace;${w.work_end ? 'color:var(--danger);font-weight:600;' : 'color:var(--text-muted);'}">${fmt(w.work_end)}</td>
            <td style="font-weight:700;color:var(--success);">${fmtMins(w.work_minutes)}</td>
            <td>
                <button class="btn btn-ghost btn-sm js-add-event"
                    data-user-id="${w.user_id}"
                    data-user-name="${escapeHtml(w.user_name)}"
                    data-shift-id="${w.shift_id}"
                    data-dzien="${w.date}">+ Dodaj</button>
            </td>
        </tr>
        <tr class="os-wiersz">
            <td colspan="${kolumn}">
                ${osCzasu(w, sk)}
                ${w.events.length ? `
                <div style="display:flex;flex-wrap:wrap;gap:6px;padding:6px 0 2px;">
                    ${w.events.map(e => `
                    <div style="display:inline-flex;align-items:center;gap:6px;
                        background:var(--bg-card-solid);border:1px solid var(--border);
                        border-radius:8px;padding:3px 9px;font-size:.78rem;">
                        <span style="color:${ET_COLOR[e.event_type]};">${ET_LABEL[e.event_type]}</span>
                        <span style="font-family:monospace;color:var(--text-secondary);">${fmt(e.timestamp)}</span>
                        ${e.is_manual ? '<span style="color:var(--warning);font-size:.7rem;">✎</span>' : ''}
                        ${e.note ? `<span style="color:var(--text-muted);font-size:.72rem;" title="${escapeHtml(e.note)}">📝</span>` : ''}
                        <button class="js-edit-event" data-event="${escapeHtml(JSON.stringify(e))}"
                            style="background:none;border:none;cursor:pointer;color:var(--text-muted);padding:0 2px;"
                            title="Edytuj">✎</button>
                        <button class="js-delete-event" data-event-id="${e.id}"
                            style="background:none;border:none;cursor:pointer;color:var(--danger);padding:0 2px;"
                            title="Usuń">✕</button>
                    </div>`).join('')}
                </div>` : ''}
            </td>
        </tr>`;
    });

    html += '</tbody></table></div>';
    wrap.innerHTML = html;
    podepnijAkcje(wrap);
}

// Zamiast onclick z wklejonymi danymi: data-* + delegacja. Dane z bazy
// (nazwy, notatki) nigdy nie trafiaja do kodu JS, tylko do wartosci atrybutu.
function podepnijAkcje(wrap) {
    wrap.querySelectorAll('.js-add-event').forEach(btn => {
        btn.addEventListener('click', () => openAddModal(
            parseInt(btn.dataset.userId), btn.dataset.userName,
            parseInt(btn.dataset.shiftId), null, btn.dataset.dzien));
    });
    wrap.querySelectorAll('.js-edit-event').forEach(btn => {
        btn.addEventListener('click', (ev) => {
            ev.stopPropagation();
            openEditModal(JSON.parse(btn.dataset.event));
        });
    });
    wrap.querySelectorAll('.js-edit-wejscie').forEach(btn => {
        btn.addEventListener('click', (ev) => {
            ev.stopPropagation();
            openWejscieModal(parseInt(btn.dataset.attendanceId), btn.dataset.userName,
                             btn.dataset.shiftIn, btn.dataset.dzien);
        });
    });
    wrap.querySelectorAll('.js-delete-event').forEach(btn => {
        btn.addEventListener('click', () => deleteEvent(parseInt(btn.dataset.eventId)));
    });
    // Klik w pasek (nie w znacznik) = nowy wpis o kliknietej godzinie.
    wrap.querySelectorAll('.js-add-na-osi').forEach(tor => {
        tor.addEventListener('click', (ev) => {
            const os = tor.closest('.os-czasu');
            const od = parseFloat(os.dataset.od), doo = parseFloat(os.dataset.doo);
            const r = tor.getBoundingClientRect();
            const minuty = Math.round(od + (ev.clientX - r.left) / r.width * (doo - od));
            const kiedy = new Date(os.dataset.dzien + 'T00:00:00');
            kiedy.setMinutes(minuty);
            openAddModal(parseInt(tor.dataset.userId), tor.dataset.userName,
                         parseInt(tor.dataset.shiftId), kiedy.toISOString(), os.dataset.dzien);
        });
    });
}

// — Modal —
function ustawTrybModalu(tryb) {
    document.getElementById('modalTryb').value = tryb;
    const wejscie = tryb === 'wejscie';
    document.getElementById('modalTypGrupa').style.display = wejscie ? 'none' : '';
    document.getElementById('modalNotatkaGrupa').style.display = wejscie ? 'none' : '';
    document.getElementById('modalWejscieInfo').style.display = wejscie ? 'block' : 'none';
}

function openAddModal(userId, userName, shiftId, kiedyIso, dzien) {
    ustawTrybModalu('zdarzenie');
    document.getElementById('modalTitle').textContent     = 'Dodaj zdarzenie';
    document.getElementById('modalEventId').value         = '';
    document.getElementById('modalUserId').value          = userId;
    document.getElementById('modalShiftId').value         = shiftId;
    document.getElementById('modalUserName').value        = userName;
    document.getElementById('modalEventType').value       = 'break_start';
    // Bez godziny z osi: teraz (dzis) albo poludnie wybranego dnia.
    const domyslnie = kiedyIso
        || (dzien && dzien !== dzisISO ? new Date(dzien + 'T12:00:00').toISOString() : new Date().toISOString());
    document.getElementById('modalTimestamp').value       = toLocalDT(domyslnie);
    document.getElementById('modalNote').value            = '';
    document.getElementById('eventModal').style.display  = 'flex';
}

function openEditModal(e) {
    ustawTrybModalu('zdarzenie');
    document.getElementById('modalTitle').textContent     = 'Edytuj zdarzenie';
    document.getElementById('modalEventId').value         = e.id;
    document.getElementById('modalUserId').value          = e.user_id;
    document.getElementById('modalShiftId').value         = e.shift_id;
    document.getElementById('modalUserName').value        = e.user_name;
    document.getElementById('modalEventType').value       = e.event_type;
    document.getElementById('modalTimestamp').value       = toLocalDT(e.timestamp);
    document.getElementById('modalNote').value            = e.note || '';
    document.getElementById('eventModal').style.display  = 'flex';
}

function openWejscieModal(attendanceId, userName, shiftIn, dzien) {
    ustawTrybModalu('wejscie');
    document.getElementById('modalTitle').textContent     = 'Popraw godzinę wejścia';
    document.getElementById('modalAttendanceId').value    = attendanceId;
    document.getElementById('modalUserName').value        = userName;
    document.getElementById('modalTimestamp').value       = toLocalDT(shiftIn);
    document.getElementById('modalWejscieInfo').textContent =
        `Skan wejścia ${fmtDzien(dzien)} o ${fmt(shiftIn)}. Nowa godzina musi być tego dnia `
        + 'i przed pierwszą przerwą / końcem pracy. Pierwotny skan zostaje zapisany.';
    document.getElementById('eventModal').style.display  = 'flex';
}

function closeModal() {
    document.getElementById('eventModal').style.display = 'none';
}

async function saveEvent() {
    const localVal  = document.getElementById('modalTimestamp').value;
    if (!localVal) { showToast('Podaj godzinę.', 'error'); return; }
    // Convert local datetime-local to ISO (naive UTC)
    const ts        = new Date(localVal).toISOString().slice(0, 19);
    let url, method, body;
    if (document.getElementById('modalTryb').value === 'wejscie') {
        url = `/api/worker-times/wejscie/${parseInt(document.getElementById('modalAttendanceId').value)}`;
        method = 'PUT';
        body = { timestamp: ts };
    } else {
        const id        = document.getElementById('modalEventId').value;
        const userId    = parseInt(document.getElementById('modalUserId').value);
        const shiftId   = parseInt(document.getElementById('modalShiftId').value);
        const eventType = document.getElementById('modalEventType').value;
        const note      = document.getElementById('modalNote').value;
        url    = id ? `/api/worker-times/event/${id}` : '/api/worker-times/event';
        method = id ? 'PUT' : 'POST';
        body   = id
            ? { event_type: eventType, timestamp: ts, note }
            : { user_id: userId, shift_id: shiftId, event_type: eventType, timestamp: ts, note };
    }

    try {
        const res = await fetch(url, {
            method, headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!res.ok) {
            const d = await res.json().catch(() => ({}));
            showToast(d.error || 'Błąd zapisu.', 'error');
            return;
        }
        showToast('Zapisano.', 'success');
        closeModal();
        loadData();
    } catch { showToast('Błąd połączenia.', 'error'); }
}

async function deleteEvent(id) {
    if (!confirm('Usunąć zdarzenie?')) return;
    try {
        const res = await fetch(`/api/worker-times/event/${id}`, { method: 'DELETE' });
        if (res.ok) { showToast('Usunięto.', 'info'); loadData(); }
        else await pokazBladOdpowiedzi(res, 'Nie usunięto');
    } catch { showToast('Błąd.', 'error'); }
}

document.getElementById('eventModal').addEventListener('click', e => {
    if (e.target === document.getElementById('eventModal')) closeModal();
});

// Auto-load today on page open
loadData();
