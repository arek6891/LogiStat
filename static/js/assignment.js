// Skrypt strony templates/assignment.html (wyniesiony z szablonu 2026-10-16).
let currentShift = 1;
let selectedCards = new Set();
// Data i wersja przydzialu wczytanej tablicy. Wersja wraca z kazdym
// zapisem; zapis ze stara wersja (ktos inny zmienil zmiane) dostaje 409.
let loadedDate = null;
let wersja = null;
// Srednia jednej osoby per czynnosc (/api/assignment/data → wydajnosc).
let wydajnosc = {};
// Grupy P1/P2/P3 {user_id: {grupa, proc_sredniej}} z ostatnich 20 dni pracy
// magazynu + ilosc do zrobienia dla Post Processing (2026-10-23).
let plan = { grupy: {}, okno_grup: null, do_zrobienia: null, pp_activity_id: null,
             osob_pp_druga_zmiana: 0 };
// Szkolenia {user_id: [activity_id]} i pary juz zapisane na tej zmianie —
// zapisany przydzial zostaje, choc szkolenie odznaczono (serwer tak samo).
let szkolenia = {};
let zapisanePary = new Set();
const para = (uid, aid) => `${uid}:${aid}`;
const przeszkolony = (uid, aid) => (szkolenia[uid] || []).includes(Number(aid));
const moznaPrzydzielic = (uid, aid) =>
    Number(aid) === 0 || przeszkolony(uid, aid) || zapisanePary.has(para(uid, aid));

// Init date to today
document.getElementById('assignDate').valueAsDate = new Date();
loadedDate = document.getElementById('assignDate').value;

async function switchShift(num) {
    if (!await autoZapis.przedOpuszczeniem()) return;
    currentShift = num;
    document.querySelectorAll('.shift-tab').forEach(t => {
        t.classList.toggle('active', parseInt(t.dataset.shift) === num);
    });
    document.getElementById('assignmentBoard').dataset.shift = num;
    loadData();
}

// ── Load assignment data ──
async function loadData() {
    const dateVal = document.getElementById('assignDate').value;
    try {
        const res = await fetch(`/api/assignment/data?date=${dateVal}&shift_number=${currentShift}`);
        const data = await res.json();
        loadedDate = dateVal;
        wersja = data.wersja;
        wydajnosc = data.wydajnosc || {};
        szkolenia = data.szkolenia || {};
        plan = {
            grupy: data.grupy || {}, okno_grup: data.okno_grup || null,
            do_zrobienia: data.do_zrobienia || null, pp_activity_id: data.pp_activity_id,
            osob_pp_druga_zmiana: data.osob_pp_druga_zmiana || 0,
        };
        zapisanePary = new Set(data.assignments.map(a => para(a.user_id, a.activity_id)));
        renderBoard(data);
    } catch (err) {
        showToast('Błąd ładowania danych.', 'error');
    }
}

function renderBoard(data) {
    // Clear all zones
    document.querySelectorAll('.assignment-drop-zone').forEach(z => z.innerHTML = '');
    selectedCards.clear();

    const assignedMap = {};
    data.assignments.forEach(a => {
        assignedMap[a.user_id] = a.activity_id;
    });

    // Render assigned users into their activity zones
    data.attendees.forEach(user => {
        const activityId = assignedMap[user.id] || 0;
        const zoneId = activityId === 0 ? 'unassignedZone' : `zone-${activityId}`;
        const zone = document.getElementById(zoneId);
        if (zone) {
            zone.appendChild(createUserCard(user));
        }
    });

    updateCounts();
}

function createUserCard(user) {
    const card = document.createElement('div');
    card.className = 'assignment-user-card';
    card.dataset.userId = user.id;
    card.draggable = true;
    const g = plan.grupy[String(user.id)];
    const okno = plan.okno_grup;
    const tytulGrupy = g
        ? `${g.grupa} — ${g.proc_sredniej}% średniej zespołu (Normy, ${okno ? okno.dni : 20} dni pracy do ${okno ? okno.do : ''})`
        : 'Bez grupy — za mało paczek z czasem w ostatnich 20 dniach pracy';
    card.innerHTML = `
    <div class="checkbox"></div>
    <div class="mini-avatar">${escapeHtml(user.display_name[0])}</div>
    <span>${escapeHtml(user.display_name)}</span>
    <em class="grupa-p" data-grupa="${g ? g.grupa : ''}" title="${escapeHtml(tytulGrupy)}">${g ? g.grupa : '—'}</em>
`;

    // Click to select/deselect
    card.addEventListener('click', (e) => {
        e.preventDefault();
        card.classList.toggle('selected');
        if (card.classList.contains('selected')) {
            selectedCards.add(card);
        } else {
            selectedCards.delete(card);
        }
    });

    // Drag single or group
    card.addEventListener('dragstart', (e) => {
        if (!card.classList.contains('selected')) {
            // If dragging an unselected card, clear selection and select only this one
            selectedCards.forEach(c => c.classList.remove('selected'));
            selectedCards.clear();
            card.classList.add('selected');
            selectedCards.add(card);
        }
        // Store user IDs being dragged
        const ids = [...selectedCards].map(c => c.dataset.userId);
        e.dataTransfer.setData('text/plain', JSON.stringify(ids));
        selectedCards.forEach(c => c.classList.add('dragging'));
    });

    card.addEventListener('dragend', () => {
        selectedCards.forEach(c => c.classList.remove('dragging'));
    });

    return card;
}

// ── Drop zones ──
document.addEventListener('DOMContentLoaded', () => {
    loadData();
    setupDropZones();
});

document.getElementById('assignDate').addEventListener('change', async (e) => {
    if (!await autoZapis.przedOpuszczeniem()) {
        e.target.value = loadedDate;
        return;
    }
    loadData();
});

function setupDropZones() {
    document.querySelectorAll('.assignment-drop-zone').forEach(zone => {
        zone.addEventListener('dragover', (e) => {
            e.preventDefault();
            zone.classList.add('drag-over');
        });

        zone.addEventListener('dragleave', () => {
            zone.classList.remove('drag-over');
        });

        zone.addEventListener('drop', (e) => {
            e.preventDefault();
            zone.classList.remove('drag-over');

            let userIds;
            try {
                userIds = JSON.parse(e.dataTransfer.getData('text/plain'));
            } catch {
                return;   // przeciagnieto cos spoza tablicy (np. zaznaczony tekst)
            }
            let przeniesiono = false;
            const bezSzkolenia = [];
            const actId = zone.dataset.activity;
            userIds.forEach(uid => {
                const card = document.querySelector(`.assignment-user-card[data-user-id="${uid}"]`);
                if (!card) return;
                card.classList.remove('selected', 'dragging');
                if (card.parentElement === zone) return;
                if (!moznaPrzydzielic(uid, actId)) {
                    bezSzkolenia.push(card.querySelector('span').textContent);
                    return;            // karta zostaje, gdzie byla
                }
                przeniesiono = true;
                zone.appendChild(card);
            });
            selectedCards.clear();
            updateCounts();
            if (przeniesiono) saveAssignments();
            if (bezSzkolenia.length) pokazBrakSzkolenia(bezSzkolenia, zone);
        });
    });
}

function updateCounts() {
    // Unassigned count
    const unassigned = document.getElementById('unassignedZone').children.length;
    document.getElementById('unassignedCount').textContent = unassigned;

    // Per-activity counts
    // Przydzial sprzed odznaczenia szkolenia zostaje, ale widac go od razu.
    document.querySelectorAll('.assignment-drop-zone:not(#unassignedZone)').forEach(zone => {
        zone.querySelectorAll('.assignment-user-card').forEach(card => {
            const brak = !przeszkolony(card.dataset.userId, zone.dataset.activity);
            card.classList.toggle('bez-szkolenia', brak);
            card.title = brak ? '⚠️ Brak szkolenia z tej czynności — przydział sprzed odznaczenia' : '';
        });
    });
    document.querySelectorAll('#unassignedZone .assignment-user-card').forEach(card => {
        card.classList.remove('bez-szkolenia');
        card.title = '';
    });

    document.querySelectorAll('[data-count-for]').forEach(badge => {
        const actId = badge.dataset.countFor;
        const zone = document.getElementById(`zone-${actId}`);
        badge.textContent = zone ? zone.children.length : 0;
    });
    pokazEstymacje();
}

// Ile zrobia przydzieleni: liczba osob × srednia jednej osoby (wszyscy
// pracownicy, 30 dni). Zmiana = 7,5 h bez przerwy.
function pokazEstymacje() {
    const fmt = n => Math.round(n).toLocaleString('pl');
    document.querySelectorAll('[data-est-for]').forEach(el => {
        const actId = el.dataset.estFor;
        const zone = document.getElementById(`zone-${actId}`);
        const osob = zone ? zone.children.length : 0;
        const w = wydajnosc[actId];
        if (!w) {
            el.textContent = 'brak danych do estymacji';
            el.title = 'Brak wpisów ilości dla tej czynności z ostatnich 30 dni.';
            el.classList.add('pusta');
            return;
        }
        el.classList.remove('pusta');
        el.textContent = `≈ ${fmt(osob * w.szt_zmiana_os)} szt./zmianę · ${fmt(osob * w.szt_h_os)} szt./h`;
        const skad = w.zrodlo === 'skany'
            ? 'średnia zespołu ze skanów paczek (jak w Normach)'
            : `średnia z Wpisu ilości (${w.probek} wpisów)`;
        el.title = `Na osobę: ${fmt(w.szt_zmiana_os)} szt./zmianę (7,5 h), `
            + `${fmt(w.szt_h_os)} szt./h — ${skad}, ostatnie 30 dni.`;
    });
    pokazDoZrobienia();
    const okno = document.getElementById('oknoGrup');
    if (okno) {
        const o = plan.okno_grup;
        okno.textContent = o
            ? `— wg Norm (% średniej zespołu), ostatnie ${o.dni} dni pracy: ${o.od.split('-').reverse().join('.')}–${o.do.split('-').reverse().join('.')}`
            : '— brak zakończonych paczek do policzenia grup';
    }
}

// Post Processing: ilosc do zrobienia na dzien (Loading date = dzien zmiany:
// Actual z importu, bez niego Forecast) vs estymacja obu zmian — ta zmiana
// z tablicy, druga z jej zapisanego przydzialu.
function pokazDoZrobienia() {
    const el = document.getElementById('doZrobieniaPP');
    if (!el) return;
    const fmt = n => Math.round(n).toLocaleString('pl');
    const d = plan.do_zrobienia;
    const ppId = plan.pp_activity_id;
    if (!ppId) { el.style.display = 'none'; return; }
    el.style.display = '';
    if (!d) {
        el.className = 'do-zrobienia pusta';
        el.textContent = 'Do zrobienia: brak Actual i Forecast na ten dzień.';
        return;
    }
    const w = wydajnosc[ppId];
    const zone = document.getElementById(`zone-${ppId}`);
    const ta = (zone ? zone.children.length : 0) * (w ? w.szt_zmiana_os : 0);
    const druga = plan.osob_pp_druga_zmiana * (w ? w.szt_zmiana_os : 0);
    const razem = ta + druga;
    const zrodlo = d.zrodlo === 'actual' ? 'Actual (import)' : 'Forecast (plan)';
    let wynik = '';
    if (w) {
        const roznica = razem - d.sztuk;
        wynik = ` · obie zmiany ≈ ${fmt(razem)} (ta ${fmt(ta)} + druga ${fmt(druga)})`
            + (roznica >= 0 ? ` · ✓ zapas ${fmt(roznica)}` : ` · brakuje ${fmt(-roznica)}`);
        el.className = 'do-zrobienia ' + (roznica >= 0 ? 'ok' : 'brak');
    } else {
        el.className = 'do-zrobienia';
    }
    el.innerHTML = `<strong>Do zrobienia: ${fmt(d.sztuk)} szt.</strong> <span>(${zrodlo})</span>${wynik}`;
    el.title = 'Loading date = dzień zmiany. Druga zmiana liczona z jej zapisanego przydziału '
        + `(${plan.osob_pp_druga_zmiana} os. na Post Processing).`;
}

function pokazBrakSzkolenia(osoby, zone) {
    const czynnosc = zone.closest('.assignment-column')
        .querySelector('.assignment-column-header span').textContent;
    pokazBrakSzkoleniaLista(osoby.map(o => ({ osoba: o, czynnosc })));
}

function pokazBrakSzkoleniaLista(lista) {
    document.getElementById('brakSzkoleniaLista').innerHTML = lista
        .map(x => `<li><strong>${escapeHtml(x.osoba)}</strong> — ${escapeHtml(x.czynnosc)}</li>`).join('');
    document.getElementById('brakSzkoleniaModal').style.display = 'flex';
    document.getElementById('brakSzkoleniaOk').focus();
}

function zamknijBrakSzkolenia() {
    document.getElementById('brakSzkoleniaModal').style.display = 'none';
}
document.getElementById('brakSzkoleniaModal').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) zamknijBrakSzkolenia();
});

// ── AI Suggestions ──
async function loadSuggestions() {
    const dateVal = document.getElementById('assignDate').value;
    try {
        const res = await fetch(`/api/assignment/suggestions?date=${dateVal}&shift_number=${currentShift}`);
        const data = await res.json();

        if (!data.suggestions || data.suggestions.length === 0) {
            showToast('Brak danych do sugestii.', 'info');
            return;
        }

        // Sugestie zapisuja sie od razu (jak kazde przeciagniecie), wiec
        // nadpisanie recznie ulozonej tablicy musi byc swiadome.
        const juzPrzydzieleni = document.querySelectorAll(
            '.assignment-drop-zone:not(#unassignedZone) .assignment-user-card').length;
        if (juzPrzydzieleni > 0 && !confirm(
            `Na tej zmianie przydzielono już ${juzPrzydzieleni} os. Sugestie AI zastąpią ten przydział i od razu go zapiszą.\n\nKontynuować?`)) {
            return;
        }

        // Move all cards back to unassigned first
        const allCards = document.querySelectorAll('.assignment-user-card');
        const unassignedZone = document.getElementById('unassignedZone');
        allCards.forEach(c => unassignedZone.appendChild(c));

        // Apply suggestions
        data.suggestions.forEach(s => {
            const card = document.querySelector(`.assignment-user-card[data-user-id="${s.user_id}"]`);
            const zone = document.getElementById(`zone-${s.activity_id}`);
            if (card && zone) {
                zone.appendChild(card);
            }
        });

        updateCounts();
        saveAssignments();
        showToast('Sugestie AI zastosowane i zapisane. Możesz je zmienić przeciągając.', 'success');
    } catch (err) {
        showToast('Błąd ładowania sugestii.', 'error');
    }
}

// ── Save ──
// Wywolywane po kazdej zmianie tablicy. Stan (data, zmiana, karty) jest
// zbierany TERAZ, a wersja w chwili wysylki — kolejne zapisy tej zmiany
// ida jeden po drugim (klucz), wiec kazdy dostaje wersje z poprzedniego.
function saveAssignments() {
    const assignments = [];
    document.querySelectorAll('.assignment-drop-zone').forEach(zone => {
        const activityId = parseInt(zone.dataset.activity);
        if (activityId === 0) return; // skip unassigned

        zone.querySelectorAll('.assignment-user-card').forEach(card => {
            assignments.push({
                user_id: parseInt(card.dataset.userId),
                activity_id: activityId,
                is_suggestion: false
            });
        });
    });

    const date = loadedDate;
    const shiftNumber = currentShift;
    autoZapis.zaplanuj(`przydzial:${date}:${shiftNumber}`, async () => {
        try {
            const dane = await zapiszJson('/api/assignment/save', 'POST', {
                date, shift_number: shiftNumber, assignments, wersja
            });
            if (date === loadedDate && shiftNumber === currentShift) {
                wersja = dane.wersja;
                zapisanePary = new Set(assignments.map(a => para(a.user_id, a.activity_id)));
            }
        } catch (e) {
            if (e.status === 409 && e.dane && e.dane.konflikt) {
                e.akcja = { etykieta: 'Wczytaj aktualny', fn: loadData };
            }
            // Szkolenie odznaczono w miedzyczasie (inny lider) — tablica
            // przepuscila ruch, serwer nie. Okno + powrot do stanu z bazy.
            if (e.dane && e.dane.brak_szkolenia) {
                pokazBrakSzkoleniaLista(e.dane.brak_szkolenia);
                e.akcja = { etykieta: 'Wczytaj aktualny', fn: loadData };
            }
            throw e;
        }
    });
}
