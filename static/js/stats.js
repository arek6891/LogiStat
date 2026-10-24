// Skrypt strony templates/stats.html (wyniesiony z szablonu 2026-10-16).
let currentUserId = null;
let dailyChart = null;
let monthlyChart = null;

// Jedno zrodlo kolorow oceny dla rankingu i karty pracownika.
const STYL_OCENY = {
    dobra: { tlo: 'rgb(var(--success-rgb) / .12)', kolor: 'var(--success)', tekst: '🟢 dobra' },
    ok:    { tlo: '',                    kolor: 'var(--text-secondary)', tekst: '⚪ w normie' },
    slaba: { tlo: 'rgb(var(--danger-rgb) / .12)', kolor: 'var(--danger)', tekst: '🔴 do dopracowania' },
};
const STYL_CELU = {
    spelnia: { kolor: 'var(--success)', tekst: '🟢 spełnia' },
    ponizej: { kolor: 'var(--danger)', tekst: '🔴 poniżej celu' },
};

// Data LOKALNA, nie toISOString() — ten zwraca UTC, wiec miedzy polnoca
// a 2:00 czasu polskiego dalby wczoraj. Druga zmiana pracuje przez polnoc.
function dataLokalna(d) {
    return `${d.getFullYear()}-`
        + String(d.getMonth() + 1).padStart(2, '0') + '-'
        + String(d.getDate()).padStart(2, '0');
}

// ── Zakładki ──────────────────────────────────────────────────────────
function pokazZakladke(ktora) {
    const przeglad = ktora === 'przeglad';
    document.getElementById('widokPrzeglad').style.display = przeglad ? '' : 'none';
    document.getElementById('widokOsoba').style.display = przeglad ? 'none' : '';
    document.getElementById('tabPrzeglad').className = przeglad ? 'btn btn-primary' : 'btn btn-secondary';
    document.getElementById('tabOsoba').className = przeglad ? 'btn btn-secondary' : 'btn btn-primary';
}

// ── Przegląd ogólny ───────────────────────────────────────────────────
function zakresDni(ile) {
    const od = document.getElementById('przegladOd');
    const doo = document.getElementById('przegladDo');
    if (ile === null) {
        od.value = ''; doo.value = '';
    } else {
        const dzis = new Date();
        const start = new Date(dzis);
        start.setDate(start.getDate() - (ile - 1));
        od.value = dataLokalna(start); doo.value = dataLokalna(dzis);
    }
    ladujPrzeglad();
}

async function ladujPrzeglad() {
    const p = new URLSearchParams();
    const od = document.getElementById('przegladOd').value;
    const doo = document.getElementById('przegladDo').value;
    if (od) p.set('date_from', od);
    if (doo) p.set('date_to', doo);

    const body = document.getElementById('przegladBody');
    body.innerHTML = '<tr><td colspan="13" style="text-align:center;color:var(--text-secondary);">Ładowanie…</td></tr>';

    let dane;
    try {
        const r = await fetch('/api/stats/overview?' + p.toString());
        dane = await r.json();
        if (!r.ok) throw new Error(dane.error || 'Błąd pobierania danych');
    } catch (err) {
        body.innerHTML = `<tr><td colspan="13" style="text-align:center;color:var(--danger);">${escapeHtml(err.message)}</td></tr>`;
        return;
    }

    przelaczKolumnyCelu(dane.cel_szt_h !== null);
    renderujPodsumowanie(dane);
    renderujRanking(dane);
    renderujZaMalo(dane);
}

function renderujPodsumowanie(d) {
    const s = d.podsumowanie;
    const kafel = (etykieta, wartosc, kolor) => `
        <div style="flex:1;min-width:130px;">
            <div style="color:var(--text-secondary);font-size:.8rem;">${etykieta}</div>
            <div style="font-size:1.5rem;font-weight:700;${kolor ? 'color:' + kolor + ';' : ''}">${wartosc}</div>
        </div>`;
    document.getElementById('przegladPodsumowanie').innerHTML =
        '<div style="display:flex;gap:1.5rem;flex-wrap:wrap;">'
        + kafel('Pracowników', s.osob)
        + kafel('W rankingu', s.w_rankingu)
        + kafel('Paczek', s.paczek)
        + kafel('Sztuk', s.sztuk.toLocaleString('pl'))
        + kafel('Godzin skanowania', s.godzin.toLocaleString('pl'))
        + kafel('Średnia szt./h', d.srednia_szt_h !== null ? d.srednia_szt_h.toLocaleString('pl') : '—', 'var(--accent)')
        + (d.cel_szt_h !== null
            ? kafel(d.cele_w_okresie.length > 1 && s.godzin > 0 ? '🎯 Cel szt./h (średnio w okresie)' : '🎯 Cel szt./h',
                    d.cel_szt_h.toLocaleString('pl')
                    + (d.cele_w_okresie.length > 1
                        ? `<div style="font-size:.75rem;font-weight:400;color:var(--text-muted);">${opisZmianCelu(d.cele_w_okresie)}</div>`
                        : ''),
                    'var(--accent)')
              + (d.spelnia_cel !== null
                  ? kafel('Spełnia cel', `${d.spelnia_cel} / ${s.w_rankingu}`,
                          d.spelnia_cel === s.w_rankingu ? 'var(--success)' : 'var(--danger)')
                  : kafel('Spełnia cel', '—'))
            : '')
        + '</div>';
}

function renderujRanking(d) {
    const body = document.getElementById('przegladBody');
    if (!d.pracownicy.length) {
        body.innerHTML = '<tr><td colspan="13" style="text-align:center;color:var(--text-secondary);padding:2rem;">'
            + 'Nikt nie ma jeszcze dość zakończonych paczek w tym okresie (próg: '
            + d.progi.min_paczek + ').</td></tr>';
        return;
    }
    const styl = STYL_OCENY;
    const stylCelu = STYL_CELU;
    body.innerHTML = d.pracownicy.map((r, i) => {
        const s = styl[r.ocena] || styl.ok;
        const c = stylCelu[r.ocena_celu] || { kolor: 'var(--text-muted)', tekst: '—' };
        return `<tr style="${s.tlo ? 'background:' + s.tlo + ';' : ''}">
            <td style="color:var(--text-secondary);">${i + 1}</td>
            <td><a href="#" class="js-osoba" data-user-id="${r.user_id}" data-user-name="${escapeHtml(r.display_name)}">${escapeHtml(r.display_name)}</a>${plakietkaNieaktywna(r)}${plakietkaSzkolenia(r)}</td>
            <td>${escapeHtml(r.worker_type || '—')}</td>
            <td>${escapeHtml(r.shift_group || '—')}</td>
            <td style="text-align:right;">${r.paczek}</td>
            <td style="text-align:right;">${r.sztuk.toLocaleString('pl')}</td>
            <td style="text-align:right;">${r.godzin.toLocaleString('pl')}</td>
            <td style="text-align:right;font-weight:700;">${r.szt_h.toLocaleString('pl')}</td>
            <td style="text-align:right;color:${s.kolor};font-weight:600;">${r.proc_sredniej !== null ? r.proc_sredniej + '%' : '—'}</td>
            <td style="color:${s.kolor};white-space:nowrap;">${s.tekst}</td>
            <td style="text-align:right;color:${c.kolor};font-weight:600;" class="kol-cel" title="${escapeHtml(r.cel_szt_h !== null ? 'Cel z dni pracy tej osoby: ' + r.cel_szt_h.toLocaleString('pl') + ' szt./h' : '')}">${r.proc_celu !== null ? r.proc_celu + '%' : '—'}</td>
            <td style="color:${c.kolor};white-space:nowrap;" class="kol-cel">${c.tekst}</td>
            <td>${linkDoPaczek(r)}</td>
        </tr>`;
    }).join('');
    podepnijLinkiOsob(body);
}

// Paczki ze szkolenia licza sie jako 100% celu dnia — bez tej plakietki
// szt./h szkolacego nie zgadzalby sie z „Sztuk / Godzin" w tym samym wierszu.
function plakietkaSzkolenia(r) {
    let html = '';
    if (r.paczek_jako_szkolony) {
        html += ` <span title="Paczek zrobionych jako osoba szkolona: ${r.paczek_jako_szkolony} (${r.godzin_jako_szkolony.toLocaleString('pl')} h) — czas szkolenia nie wchodzi do oceny ani średniej"
        style="margin-left:4px;font-size:.7rem;padding:1px 6px;border-radius:8px;background:var(--bg-secondary);color:var(--text-muted);">🎓 szkolony/a ${r.paczek_jako_szkolony}</span>`;
    }
    if (!r.paczek_szkolenia) return html;
    return html + ` <span title="Paczek zahaczających o szkolenie: ${r.paczek_szkolenia} — liczone w całości jako 100% celu. ${r.godzin_szkolenia.toLocaleString('pl')} h to czas tych paczek (od startu do końca), nie sam czas szkolenia"
        style="margin-left:4px;font-size:.7rem;padding:1px 6px;border-radius:8px;background:var(--info-bg);color:var(--info);">🎓 ${r.paczek_szkolenia}</span>`;
}

function renderujZaMalo(d) {
    const karta = document.getElementById('przegladZaMalo');
    if (!d.za_malo_danych.length) { karta.style.display = 'none'; return; }
    karta.style.display = '';
    document.getElementById('progMinPaczek').textContent = d.progi.min_paczek;
    document.getElementById('zaMaloBody').innerHTML = d.za_malo_danych.map(r => `
        <tr>
            <td><a href="#" class="js-osoba" data-user-id="${r.user_id}" data-user-name="${escapeHtml(r.display_name)}">${escapeHtml(r.display_name)}</a>${plakietkaNieaktywna(r)}${plakietkaSzkolenia(r)}</td>
            <td>${escapeHtml(r.worker_type || '—')}</td>
            <td>${escapeHtml(r.shift_group || '—')}</td>
            <td style="text-align:right;">${r.paczek}</td>
            <td style="text-align:right;">${r.sztuk.toLocaleString('pl')}</td>
            <td style="text-align:right;">${r.godzin.toLocaleString('pl')}</td>
            <td>${linkDoPaczek(r)}</td>
        </tr>`).join('');
    podepnijLinkiOsob(document.getElementById('zaMaloBody'));
}

// Skok na /paczki z filtrem po tej osobie i po DACIE KONCA, w tym samym
// zakresie dat co przeglad — czyli dokladnie te paczki, ktore zlozyly sie na
// jej wynik. `date_typ=koniec` sam zdejmuje domyslne „tylko niezrobione",
// wiec nie trzeba dokladac `status`.
function linkDoPaczek(r) {
    const p = new URLSearchParams({ osoba: r.user_id, date_typ: 'koniec' });
    const od = document.getElementById('przegladOd').value;
    const doo = document.getElementById('przegladDo').value;
    if (od) p.set('date_from', od);
    if (doo) p.set('date_to', doo);
    return `<a href="/paczki?${p.toString()}" class="btn btn-secondary"
               style="padding:.2rem .5rem;font-size:.8rem;white-space:nowrap;"
               title="Pokaż paczki zakończone przez tę osobę w tym okresie">📦</a>`;
}

const dataPL = iso => iso.split('-').reverse().join('.');

// „300 → 320 od 15.10.2026" — cel zmienial sie w wybranym okresie.
function opisZmianCelu(cele) {
    return cele.map((c, i) => (i ? '→ ' : '') + (c.wartosc || 'brak')
        + (i && c.od ? ' od ' + dataPL(c.od) : '')).join(' ');
}

function renderujHistorieCelu(historia) {
    document.getElementById('historiaCeluBody').innerHTML = historia.length
        ? historia.map(h => `<tr>
            <td>${h.od ? dataPL(h.od) : 'od początku'}</td>
            <td style="text-align:right;font-weight:600;">${h.wartosc ? h.wartosc.toLocaleString('pl') : '— (brak celu)'}</td>
            <td>${h.zmienil ? escapeHtml(h.zmienil) : '—'}</td>
            <td>${h.zmieniono_at ? new Date(h.zmieniono_at).toLocaleString('pl') : '—'}</td>
          </tr>`).join('')
        : '<tr><td colspan="4" style="color:var(--text-muted);">Cel jeszcze nie był ustawiany.</td></tr>';
}
document.addEventListener('DOMContentLoaded', () =>
    renderujHistorieCelu(JSON.parse(document.getElementById('historiaCeluDane').textContent)));

async function zapiszCel() {
    const btn = document.getElementById('zapiszCelBtn');
    const wartosc = parseInt(document.getElementById('celSztH').value, 10);
    if (isNaN(wartosc) || wartosc < 0) {
        showToast('Cel musi być liczbą całkowitą ≥ 0.', 'error'); return;
    }
    btn.disabled = true;
    try {
        const res = await fetch('/api/stats/target', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_szt_h: wartosc })
        });
        const dane = await res.json().catch(() => ({}));
        if (!res.ok) { showToast(dane.error || 'Błąd zapisu.', 'error'); return; }
        showToast(dane.message || 'Zapisano.', 'success');
        if (dane.historia) renderujHistorieCelu(dane.historia);
        ladujPrzeglad();
    } catch {
        showToast('Błąd połączenia.', 'error');
    } finally {
        btn.disabled = false;
    }
}

// Bez ustawionego celu kolumny celu nie maja co pokazywac — chowamy je,
// zamiast wypelniac kreskami.
function przelaczKolumnyCelu(jest) {
    document.querySelectorAll('.kol-cel').forEach(el => el.style.display = jest ? '' : 'none');
}

// Konto zdezaktywowane (soft-delete) nadal ma swoja prace w sumach, ale lider
// nie powinien planowac rozmowy z kims, kogo juz nie ma — stad plakietka.
function plakietkaNieaktywna(r) {
    return r.is_active_user ? '' :
        ' <span style="font-size:.7rem;padding:.1rem .35rem;border-radius:4px;'
        + 'background:var(--border);color:var(--text-muted);">nieaktywna</span>';
}

// Zamiast onclick z wklejona nazwa: data-* + jedna delegacja — nazwy z bazy
// nigdy nie trafiaja do kodu JS, tylko do wartosci atrybutu. Ten sam wzorzec
// co podepnijAkcje() w worker_times.html; pilnuje go tests/test_xss.py.
function podepnijLinkiOsob(korzen) {
    korzen.querySelectorAll('.js-osoba').forEach(a => {
        a.addEventListener('click', (e) => {
            e.preventDefault();
            // Ten sam zakres co przeglad — inaczej % sredniej na karcie
            // osoby nie zgadzalby sie z tym, w ktory wlasnie kliknieto.
            document.getElementById('filterFrom').value = document.getElementById('przegladOd').value;
            document.getElementById('filterTo').value = document.getElementById('przegladDo').value;
            pokazZakladke('osoba');
            selectUser(parseInt(a.dataset.userId), a.dataset.userName);
        });
    });
}

// User search
document.getElementById('userSearch').addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase();
    document.querySelectorAll('.user-list-item').forEach(item => {
        item.style.display = item.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
});

// Lista osob: data-* + jedna delegacja, nazwa nie trafia do kodu JS.
document.getElementById('userList').addEventListener('click', (e) => {
    const item = e.target.closest('.user-list-item');
    if (item) selectUser(parseInt(item.dataset.userId), item.dataset.userName);
});

// Domyslny zakres: ostatnie 30 dni, liczone tak samo jak w przegladzie.
(() => {
    const dzis = new Date();
    const start = new Date(dzis);
    start.setDate(start.getDate() - 29);
    document.getElementById('filterTo').value = dataLokalna(dzis);
    document.getElementById('filterFrom').value = dataLokalna(start);
})();

function selectUser(userId, name) {
    currentUserId = userId;
    document.querySelectorAll('.user-list-item').forEach(i =>
        i.classList.toggle('active', parseInt(i.dataset.userId) === userId));
    document.getElementById('statsPlaceholder').style.display = 'none';
    document.getElementById('statsDetail').style.display = 'block';
    document.getElementById('statsUserName').textContent = name;
    loadUserStats();
}

async function loadUserStats() {
    if (!currentUserId) return;

    const activityId = document.getElementById('filterActivity').value;
    const dateFrom = document.getElementById('filterFrom').value;
    const dateTo = document.getElementById('filterTo').value;

    let url = `/api/stats/user/${currentUserId}?`;
    if (activityId) url += `activity_id=${activityId}&`;
    if (dateFrom) url += `date_from=${dateFrom}&`;
    if (dateTo) url += `date_to=${dateTo}&`;

    try {
        const res = await fetch(url);
        const data = await res.json();
        if (!res.ok) throw new Error(data.error);
        // Nazwa z API — wejscie z dashboardu podaje samo id, a lista po
        // lewej zawiera tylko aktywne konta.
        document.getElementById('statsUserName').textContent = data.user.display_name;
        renderNorma(data.norma);
        renderPaczkiPodsumowanie(data.paczki_podsumowanie);
        renderMonthly(data.monthly);
        renderDaily(data.daily);
        ostatnieWykresy = data;
        dailyChart = rysujWykres('dailyChart', dailyChart, data.wykres_dzienny, data.norma);
        monthlyChart = rysujWykres('monthlyChart', monthlyChart, data.wykres_miesieczny, data.norma);
    } catch (err) {
        showToast('Błąd ładowania statystyk.', 'error');
    }
}

function renderPaczkiPodsumowanie(p) {
    const el = document.getElementById('paczkiPodsumowanie');
    if (!p || !p.paczek) {
        el.innerHTML = '<p style="color:var(--text-muted);margin:0;">Brak zakończonych paczek w tym okresie.</p>';
        return;
    }
    const liczba = v => v === null ? '—' : v.toLocaleString('pl');
    const kafel = (etykieta, wartosc, kolor) => `
        <div style="flex:1;min-width:120px;">
            <div style="color:var(--text-secondary);font-size:.8rem;">${etykieta}</div>
            <div style="font-size:1.4rem;font-weight:700;${kolor ? 'color:' + kolor + ';' : ''}">${wartosc}</div>
        </div>`;
    el.innerHTML = '<div style="display:flex;gap:1.5rem;flex-wrap:wrap;">'
        + kafel('Paczek', liczba(p.paczek))
        + kafel('Sztuk', liczba(p.sztuk))
        + kafel('Dni pracy', liczba(p.dni_pracy))
        + kafel('Śr. dziennie — paczek', liczba(p.srednio_dziennie.paczek), 'var(--accent)')
        + kafel('Śr. dziennie — szt.', liczba(p.srednio_dziennie.sztuk), 'var(--accent)')
        + kafel('Śr. miesięcznie — paczek', liczba(p.srednio_miesiecznie.paczek), 'var(--success)')
        + kafel('Śr. miesięcznie — szt.', liczba(p.srednio_miesiecznie.sztuk), 'var(--success)')
        + '</div>';
}

function renderMonthly(monthly) {
    const tbody = document.getElementById('monthlyBody');
    if (!monthly.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);">Brak danych</td></tr>';
        return;
    }
    tbody.innerHTML = monthly.map(m => `
    <tr>
        <td>${m.month}</td>
        <td>${escapeHtml(m.activity)}</td>
        <td><strong>${m.total_quantity}</strong></td>
        <td>${m.days_worked}</td>
        <td>${m.avg_per_day}</td>
    </tr>
`).join('');
}

function renderDaily(daily) {
    const tbody = document.getElementById('dailyBody');
    if (!daily.length) {
        tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--text-muted);">Brak danych</td></tr>';
        return;
    }
    tbody.innerHTML = daily.map(d => {
        if (d.is_package) {
            // Wiersz paczek — wyliczany automatycznie, tylko do odczytu
            return `
    <tr style="background:rgb(var(--double-rate-rgb) / .06);">
        <td>${d.date}</td>
        <td style="color:var(--text-muted);">—</td>
        <td>${escapeHtml(d.activity)}</td>
        <td style="text-align:center;"><strong>${d.quantity}</strong></td>
        <td style="color:var(--text-secondary);font-size:0.85rem;">-</td>
        <td style="font-size:0.8rem;color:var(--text-muted);">${escapeHtml(d.entered_by || '-')}</td>
        <td style="font-size:0.8rem;color:var(--text-muted);">-</td>
        <td style="color:var(--text-muted);">🔒</td>
    </tr>`;
        }
        return `
    <tr>
        <td>${d.date}</td>
        <td><span class="shift-badge" data-shift="${parseInt(d.shift_number) || ''}">Zmiana ${parseInt(d.shift_number) || ''}</span></td>
        <td>${escapeHtml(d.activity)}</td>
        <td>
            <input type="number" class="edit-qty" data-stat-id="${d.stat_id}" value="${d.quantity}"
                style="width:80px;padding:4px 8px;background:var(--bg-input);border:1px solid var(--border);border-radius:6px;color:var(--text-primary);font-family:var(--font);text-align:center;">
        </td>
        <td style="color:var(--text-secondary);font-size:0.85rem;">${escapeHtml(d.note || '-')}</td>
        <td style="font-size:0.8rem;color:var(--text-muted);">${escapeHtml(d.entered_by || '-')}</td>
        <td style="font-size:0.8rem;color:var(--text-muted);">${d.modified_by ? escapeHtml(d.modified_by) + '<br>' + escapeHtml(d.modified_at || '') : '-'}</td>
        <td><button class="btn btn-sm btn-ghost" onclick="updateStat(${d.stat_id}, this)">💾</button></td>
    </tr>`;
    }).join('');
}

function renderNorma(n) {
    const el = document.getElementById('normaPracownika');
    const liczba = v => v === null || v === undefined ? '—' : v.toLocaleString('pl');
    const kafel = (etykieta, wartosc, kolor) => `
        <div style="flex:1;min-width:120px;">
            <div style="color:var(--text-secondary);font-size:.8rem;">${etykieta}</div>
            <div style="font-size:1.4rem;font-weight:700;${kolor ? 'color:' + kolor + ';' : ''}">${wartosc}</div>
        </div>`;
    const r = n.wiersz;
    const srednia = kafel('Średnia zespołu szt./h', liczba(n.srednia_szt_h), 'var(--accent)');
    const cel = n.cel_szt_h !== null ? kafel('🎯 Cel szt./h', liczba(n.cel_szt_h), 'var(--accent)') : '';

    if (!r || n.powod_braku_oceny) {
        const powody = {
            brak_paczek: 'Brak zakończonych paczek w tym okresie — nie ma czego oceniać.',
            szkolony: 'Wszystkie paczki w tym okresie zrobione jako osoba szkolona — czas szkolenia nie wchodzi do norm.',
            za_malo_paczek: `Za mało paczek do oceny (próg: ${n.progi.min_paczek}). Jedna-dwie paczki potrafią dać przypadkowy wynik.`,
            brak_czasu: 'Paczki są, ale bez zmierzonego czasu (zamykane bez skanu „Start"). Nie da się policzyć szt./h — warto pokazać obsługę skanera.',
        };
        el.innerHTML = '<div style="display:flex;gap:1.5rem;flex-wrap:wrap;">'
            + (r ? kafel('Szt./h', liczba(r.szt_h)) + kafel('Godzin skanowania', liczba(r.godzin)) : '')
            + srednia + cel + '</div>'
            + `<p style="margin:.75rem 0 0;color:var(--text-secondary);">⚪ ${powody[n.powod_braku_oceny]}</p>`;
        return;
    }
    const s = STYL_OCENY[r.ocena] || STYL_OCENY.ok;
    const c = STYL_CELU[r.ocena_celu];
    el.innerHTML = '<div style="display:flex;gap:1.5rem;flex-wrap:wrap;">'
        + kafel('Szt./h', liczba(r.szt_h), s.kolor)
        + srednia
        + kafel('% średniej', r.proc_sredniej !== null ? r.proc_sredniej + '%' : '—', s.kolor)
        + kafel('Ocena', s.tekst, s.kolor)
        + kafel('Miejsce', `${n.miejsce} / ${n.w_rankingu}`)
        + kafel('Godzin skanowania', liczba(r.godzin))
        + cel
        + (c ? kafel('% celu', r.proc_celu + '%', c.kolor) + kafel('Wobec celu', c.tekst, c.kolor) : '')
        + (r.paczek_szkolenia ? kafel('🎓 Paczek ze szkolenia', liczba(r.paczek_szkolenia), 'var(--info)') : '')
        + '</div>'
        + `<p style="margin:.75rem 0 0;color:var(--text-muted);font-size:.8rem;">
             🟢 dobra ≥ ${n.progi.dobry}% średniej · 🔴 do dopracowania ≤ ${n.progi.slaby}% · pomiędzy: w normie</p>`;
}

// Slupki = sztuki (lewa os), linia = szt./h (prawa os) na tle sredniej
// zespolu i celu. Rzad wielkosci sztuk i szt./h jest inny, stad dwie osie.
// Dane z paczek, nie z „Wpisu ilosci" — ten jest wypelniany sporadycznie,
// wiec stary wykres byl pusty niemal u kazdego.
// Tryb ciemny przelaczony na stronie — przerysuj w nowych kolorach (motyw.js).
let ostatnieWykresy = null;
document.addEventListener('zmiana-motywu', () => {
    if (!ostatnieWykresy) return;
    dailyChart = rysujWykres('dailyChart', dailyChart, ostatnieWykresy.wykres_dzienny, ostatnieWykresy.norma);
    monthlyChart = rysujWykres('monthlyChart', monthlyChart, ostatnieWykresy.wykres_miesieczny, ostatnieWykresy.norma);
});

function rysujWykres(idCanvas, poprzedni, punkty, norma) {
    if (poprzedni) poprzedni.destroy();
    const canvas = document.getElementById(idCanvas);
    const pusty = document.getElementById(idCanvas + 'Pusty');
    const brak = !punkty.length;
    canvas.style.display = brak ? 'none' : '';
    pusty.style.display = brak ? '' : 'none';
    if (brak) return null;

    const labels = punkty.map(p => p.okres);
    const linia = (wartosc, etykieta, kolor) => ({
        type: 'line', label: etykieta, yAxisID: 'yWyd',
        data: labels.map(() => wartosc),
        borderColor: kolor, borderDash: [6, 4], borderWidth: 1.5,
        pointRadius: 0, fill: false,
    });
    const zbiory = [
        {
            type: 'bar', label: 'Sztuk', yAxisID: 'ySzt',
            data: punkty.map(p => p.sztuk),
            backgroundColor: motyw('--accent', 0.45),
            borderColor: motyw('--accent', 1), borderWidth: 1, borderRadius: 4,
        },
        {
            type: 'line', label: 'Szt./h', yAxisID: 'yWyd',
            data: punkty.map(p => p.szt_h),
            borderColor: motyw('--warning'), backgroundColor: motyw('--warning'),
            borderWidth: 2, pointRadius: 3, spanGaps: false, tension: 0.2,
        },
    ];
    if (norma.srednia_szt_h !== null) zbiory.push(linia(norma.srednia_szt_h, 'Średnia zespołu szt./h', motyw('--success')));
    // Cel ze swojego dnia/miesiaca — po zmianie celu linia robi schodek.
    if (punkty.some(p => p.cel !== null)) zbiory.push({
        ...linia(null, 'Cel szt./h', motyw('--danger')),
        data: punkty.map(p => p.cel), stepped: 'middle', spanGaps: true,
    });

    const siatka = { color: motyw('--border', 0.5) };
    const tekst = { color: motyw('--text-secondary') };
    return new Chart(canvas, {
        data: { labels, datasets: zbiory },
        options: {
            responsive: true,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { labels: tekst },
                tooltip: {
                    callbacks: {
                        afterBody: (items) => {
                            const p = punkty[items[0].dataIndex];
                            return `Paczek: ${p.paczek} · godzin: ${p.godzin.toLocaleString('pl')}`
                                + (p.paczek_szkolenia ? `\n🎓 ze szkolenia (100% celu): ${p.paczek_szkolenia}` : '');
                        }
                    }
                }
            },
            scales: {
                x: { ticks: tekst, grid: siatka },
                ySzt: { position: 'left', beginAtZero: true, ticks: tekst, grid: siatka,
                        title: { display: true, text: 'Sztuk', color: motyw('--text-secondary') } },
                yWyd: { position: 'right', beginAtZero: true, ticks: tekst, grid: { drawOnChartArea: false },
                        title: { display: true, text: 'Szt./h', color: motyw('--text-secondary') } },
            }
        }
    });
}

async function updateStat(statId, btn) {
    const row = btn.closest('tr');
    const input = row.querySelector('.edit-qty');
    const quantity = parseInt(input.value) || 0;

    try {
        const res = await fetch(`/api/daily-stats/${statId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ quantity: quantity })
        });
        if (res.ok) {
            showToast('Zaktualizowano.', 'success');
            loadUserStats(); // refresh to show audit info
        } else {
            showToast('Błąd.', 'error');
        }
    } catch (err) {
        showToast('Błąd połączenia.', 'error');
    }
}

// Wchodzimy od razu na przeglad — to on odpowiada na pytanie „jak idzie
// zespolowi", a widok per pracownik wymaga najpierw wybrania osoby.
// Domyslny zakres 30 dni, zeby jeden slaby dzien nie przesadzal o ocenie.
zakresDni(30);

// Wejscie z dashboardu: /stats?user=<id>[&date_from=&date_to=] otwiera od
// razu zakladke tej osoby.
(() => {
    const q = new URLSearchParams(location.search);
    const uid = parseInt(q.get('user'), 10);
    if (!uid) return;
    if (q.get('date_from')) document.getElementById('filterFrom').value = q.get('date_from');
    if (q.get('date_to')) document.getElementById('filterTo').value = q.get('date_to');
    pokazZakladke('osoba');
    selectUser(uid, '');
})();
