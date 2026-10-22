// Skrypt strony templates/forecast.html (wyniesiony z szablonu 2026-10-16).
const DAYS_PL = ['Niedziela','Poniedziałek','Wtorek','Środa','Czwartek','Piątek','Sobota'];
let chartBar = null, chartDiff = null;
let currentData = [];

async function loadData() {
    const from = document.getElementById('dateFrom').value;
    const to   = document.getElementById('dateTo').value;
    if (!from || !to) return;

    const resp = await fetch(`/api/forecast/chart-data?date_from=${from}&date_to=${to}`);
    if (!resp.ok) { showToast('Błąd ładowania danych', 'error'); return; }
    currentData = await resp.json();

    renderTable(currentData);
    renderCharts(currentData);
    renderSummary(currentData);
}

function renderTable(data) {
    const tbody = document.getElementById('forecastBody');
    if (!data.length) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:32px;color:var(--text-muted);">Brak danych w wybranym zakresie.</td></tr>';
        document.getElementById('rowCount').textContent = '';
        return;
    }

    tbody.innerHTML = data.map(row => {
        const d = new Date(row.date + 'T00:00:00');
        const dayName = DAYS_PL[d.getDay()];
        const isWeekend = d.getDay() === 0 || d.getDay() === 6;
        const diffClass = row.diff > 0 ? 'diff-positive' : row.diff < 0 ? 'diff-negative' : 'diff-zero';
        const diffSign  = row.diff > 0 ? '+' : '';
        return `<tr style="${isWeekend ? 'opacity:0.6' : ''}">
            <td><strong>${formatDate(row.date)}</strong></td>
            <td style="color:var(--text-muted)">${dayName}</td>
            <td>
                <input type="number" min="0" step="1"
                    data-date="${row.date}"
                    class="fc-input"
                    value="${parseInt(row.forecast) || 0}"
                    oninput="updateDiff(this)">
            </td>
            <td><span class="badge-actual">${row.actual.toLocaleString('pl')}</span></td>
            <td class="${diffClass}" data-diff="${row.date}">${diffSign}${row.diff.toLocaleString('pl')}</td>
            <td>
                <input type="text" placeholder="Notatka…"
                    data-date="${row.date}"
                    class="note-input"
                    value="${escHtml(row.notes)}">
            </td>
        </tr>`;
    }).join('');

    document.getElementById('rowCount').textContent = `${data.length} dni`;
    tbody.querySelectorAll('tr').forEach(tr => {
        tr.querySelectorAll('.fc-input, .note-input').forEach(pole =>
            autoZapis.poWpisaniu(pole, () => saveRow(tr)));
    });
}

function updateDiff(input) {
    const d = input.dataset.date;
    const row = currentData.find(r => r.date === d);
    if (!row) return;
    const newFc = parseInt(input.value) || 0;
    row.forecast = newFc;
    const diff = row.actual - newFc;
    row.diff = diff;
    const diffCell = document.querySelector(`[data-diff="${d}"]`);
    if (diffCell) {
        diffCell.textContent = (diff > 0 ? '+' : '') + diff.toLocaleString('pl');
        diffCell.className = diff > 0 ? 'diff-positive' : diff < 0 ? 'diff-negative' : 'diff-zero';
    }
    renderSummary(currentData);
}

function renderSummary(data) {
    const sumFc  = data.reduce((s, r) => s + (r.forecast || 0), 0);
    const sumAct = data.reduce((s, r) => s + (r.actual  || 0), 0);
    const sumDif = sumAct - sumFc;
    document.getElementById('sumForecast').textContent = sumFc.toLocaleString('pl');
    document.getElementById('sumActual').textContent   = sumAct.toLocaleString('pl');
    const el = document.getElementById('sumDiff');
    el.textContent = (sumDif > 0 ? '+' : '') + sumDif.toLocaleString('pl');
    el.style.color = sumDif > 0 ? 'var(--warning)' : sumDif < 0 ? 'var(--danger)' : 'var(--text-muted)';
    document.getElementById('summaryBar').style.display = 'flex';
}

// Tryb ciemny przelaczony na stronie — przerysuj w nowych kolorach (motyw.js).
document.addEventListener('zmiana-motywu', () => { if (chartBar) renderCharts(currentData); });

function renderCharts(data) {
    const labels   = data.map(r => formatDate(r.date));
    const fcVals   = data.map(r => r.forecast);
    const actVals  = data.map(r => r.actual);
    const diffVals = data.map(r => r.diff);
    const diffColors = diffVals.map(v => v >= 0 ? motyw('--warning', 0.7) : motyw('--danger', 0.7));

    document.getElementById('chartsSection').style.display = '';

    if (chartBar) chartBar.destroy();
    chartBar = new Chart(document.getElementById('barChart'), {
        type: 'bar',
        data: {
            labels,
            datasets: [
                { label: 'Forecast', data: fcVals,  backgroundColor: motyw('--info', 0.75), borderRadius: 4 },
                { label: 'Actual',   data: actVals, backgroundColor: motyw('--success', 0.75),  borderRadius: 4 }
            ]
        },
        options: {
            responsive: true,
            plugins: { legend: { labels: { color: motyw('--text-secondary') } } },
            scales: {
                x: { ticks: { color: motyw('--text-secondary'), maxRotation: 45 }, grid: { color: motyw('--border') } },
                y: { ticks: { color: motyw('--text-secondary') }, grid: { color: motyw('--border') }, beginAtZero: true }
            }
        }
    });

    if (chartDiff) chartDiff.destroy();
    chartDiff = new Chart(document.getElementById('diffChart'), {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                label: 'Różnica (A−F)',
                data: diffVals,
                backgroundColor: diffColors,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            plugins: { legend: { labels: { color: motyw('--text-secondary') } } },
            scales: {
                x: { ticks: { color: motyw('--text-secondary'), maxRotation: 45 }, grid: { color: motyw('--border') } },
                y: { ticks: { color: motyw('--text-secondary') }, grid: { color: motyw('--border') } }
            }
        }
    });
}

// Wiersz = jeden dzien = jeden zapis (endpoint robi upsert po dacie). Dawny
// „Zapisz wszystkie" wysylal kazdy dzien zakresu i zakladal wiersz z zerem
// dla dni, ktorych nikt nie planowal. Bez loadData() po zapisie — przerysowanie
// tabeli zabieraloby fokus z pola, do ktorego wlasnie przechodzi Tab.
function saveRow(tr) {
    const fcInput = tr.querySelector('.fc-input');
    const noteInput = tr.querySelector('.note-input');
    const entry = {
        date: fcInput.dataset.date,
        quantity: parseInt(fcInput.value) || 0,
        notes: noteInput.value
    };
    const row = currentData.find(r => r.date === entry.date);
    if (row) row.notes = entry.notes;
    renderCharts(currentData);
    autoZapis.zaplanuj(`forecast:${entry.date}`, async () => {
        const dane = await zapiszJson('/api/forecast/save', 'POST', [entry]);
        if (dane.saved !== 1) throw new Error(`Nie zapisano dnia ${formatDate(entry.date)}.`);
    }, [fcInput, noteInput]);
}

async function odswiez() {
    if (!await autoZapis.przedOpuszczeniem()) return;
    loadData();
}

async function exportExcel() {
    // Eksport czyta baze — najpierw niech wyjda zapisy, inaczej plik ma stare liczby.
    if (!await autoZapis.przedOpuszczeniem()) return;
    const from = document.getElementById('dateFrom').value;
    const to   = document.getElementById('dateTo').value;
    window.location.href = `/api/forecast/export?date_from=${from}&date_to=${to}`;
}

function formatDate(iso) {
    const [y, m, d] = iso.split('-');
    return `${d}.${m}.${y}`;
}

function escHtml(str) {
    return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

loadData();
