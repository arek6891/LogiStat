// Skrypt strony templates/admin_cost_mapping.html (wyniesiony z szablonu 2026-10-16).
// Dane z serwera: blok <script> w szablonie tuz przed tym plikiem.
// Ustaw dzisiejszy rok i miesiąc
const today = new Date();
document.getElementById('yearSelect').value = today.getFullYear();
document.getElementById('monthSelect').value = today.getMonth() + 1;

// Stawki to rozliczenie i zostaja z jawnym „Zapisz" (bez autozapisu) — ale
// nie moga po cichu przepasc przy wyjsciu ze strony albo zmianie miesiaca.
function niezapisaneStawki() {
    return [...document.querySelectorAll('.rate-input')].some(i => i.value !== i.dataset.original);
}
function odswiezZnacznikStawek() {
    document.getElementById('ratesDirty').style.display = niezapisaneStawki() ? '' : 'none';
}
window.addEventListener('beforeunload', e => {
    if (niezapisaneStawki()) { e.preventDefault(); e.returnValue = ''; }
});

// Miesiac, ktorego stawki SA w formularzu. Zapis i kopiowanie ida pod niego,
// nie pod to, co aktualnie stoi na listach: przestawienie miesiaca bez
// „Pokaz stawki" zapisywalo stawki starego miesiaca pod nowy (rozliczenie!).
let loadedYear = null;
let loadedMonth = null;

// Automatycznie załaduj po wejściu na stronę
loadRates();

async function loadRates() {
    if (niezapisaneStawki() && !confirm('Stawki tego miesiąca mają niezapisane zmiany.\n\nWczytać inny miesiąc i je porzucić?')) {
        // Listy wracaja do miesiaca, ktory naprawde jest w formularzu.
        document.getElementById('yearSelect').value = loadedYear;
        document.getElementById('monthSelect').value = loadedMonth;
        return;
    }
    const year = document.getElementById('yearSelect').value;
    const month = document.getElementById('monthSelect').value;
    if (!year || !month) return;

    const container = document.getElementById('ratesContainer');
    container.innerHTML = '<p style="text-align:center; color:var(--text-muted);">Wczytywanie stawek...</p>';
    document.getElementById('ratesFooter').style.display = 'none';
    loadedYear = loadedMonth = null;

    try {
        const res = await fetch(`/api/cost-mapping/${year}/${month}`);
        const rates = res.ok ? await res.json() : {};

        renderRatesForm(rates);
        loadedYear = parseInt(year);
        loadedMonth = parseInt(month);
        document.getElementById('ratesMonthLabel').textContent =
            `(${String(loadedMonth).padStart(2, '0')}/${loadedYear})`;
        document.getElementById('ratesFooter').style.display = 'flex';
    } catch (err) {
        container.innerHTML = '<p style="text-align:center; color:var(--danger);">Błąd połączenia. Nie można pobrać stawek.</p>';
    }
}

function renderRatesForm(rates) {
    const container = document.getElementById('ratesContainer');
    let html = '<table style="width:100%; border-collapse:collapse;">';
    html += `
        <thead>
            <tr style="border-bottom:2px solid var(--border);">
                <th style="text-align:left; padding:8px 0; color:var(--text-muted); font-size:0.85rem; text-transform:uppercase;">Kategoria / Akcja</th>
                <th style="text-align:right; padding:8px 0; color:var(--text-muted); font-size:0.85rem; text-transform:uppercase;">Stawka Cost (EUR)</th>
            </tr>
        </thead>
        <tbody>
    `;

    categories.forEach(cat => {
        const val = rates[cat] || 0.0;
        const label = categoryLabels[cat] || cat;

        html += `
            <tr style="border-bottom:1px solid var(--border);">
                <td style="padding:12px 0; font-weight:500;">${label}</td>
                <td style="padding:12px 0; text-align:right;">
                    <input type="number" class="form-control rate-input" data-cat="${cat}" value="${parseFloat(val).toFixed(2)}" min="0" step="0.01" style="width:100px; text-align:right; display:inline-block;">
                </td>
            </tr>
        `;
    });

    html += '</tbody></table>';
    container.innerHTML = html;

    // Setup highlighting on change
    document.querySelectorAll('.rate-input').forEach(input => {
        input.dataset.original = input.value;
        input.addEventListener('input', function () {
            if (this.value !== this.dataset.original) {
                this.style.borderColor = 'var(--warning)';
                this.style.backgroundColor = 'rgb(var(--warning-rgb) / 0.1)';
            } else {
                this.style.borderColor = '';
                this.style.backgroundColor = '';
            }
            odswiezZnacznikStawek();
        });
    });
    odswiezZnacznikStawek();
}

async function saveRates() {
    const year = loadedYear;
    const month = loadedMonth;
    if (!year || !month) return;

    const newRates = {};
    document.querySelectorAll('.rate-input').forEach(input => {
        const cat = input.dataset.cat;
        newRates[cat] = parseFloat(input.value) || 0.0;
    });

    try {
        const res = await fetch(`/api/cost-mapping/${year}/${month}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rates: newRates })
        });

        if (res.ok) {
            showToast(`Stawki ${String(month).padStart(2, '0')}/${year} zapisano pomyślnie!`, 'success');
            // Reset styling
            document.querySelectorAll('.rate-input').forEach(input => {
                input.dataset.original = input.value;
                input.style.borderColor = '';
                input.style.backgroundColor = '';
            });
            odswiezZnacznikStawek();
        } else {
            showToast('Błąd zapisu stawek.', 'error');
        }
    } catch (err) {
        showToast('Błąd połączenia. Nie zapisano stawek.', 'error');
    }
}

async function copyFromPreviousMonth() {
    // Poprzedni wzgledem WCZYTANEGO miesiaca — kopia laduje w jego formularzu.
    let year = loadedYear;
    let month = loadedMonth;

    if (!year || !month) return;

    let prevMonth = month - 1;
    let prevYear = year;
    if (prevMonth === 0) {
        prevMonth = 12;
        prevYear -= 1;
    }

    try {
        const res = await fetch(`/api/cost-mapping/${prevYear}/${prevMonth}`);
        if (res.ok) {
            const prevRates = await res.json();
            if (Object.keys(prevRates).length === 0) {
                showToast('Brak skonfigurowanych stawek dla poprzedniego miesiąca.', 'warning');
                return;
            }

            let copied = false;
            document.querySelectorAll('.rate-input').forEach(input => {
                const cat = input.dataset.cat;
                const prevVal = prevRates[cat] || 0.0;
                const formattedPrev = parseFloat(prevVal).toFixed(2);

                if (input.value !== formattedPrev) {
                    input.value = formattedPrev;
                    // Trigger highlight indicating unsaved changes
                    if (input.value !== input.dataset.original) {
                        input.style.borderColor = 'var(--warning)';
                        input.style.backgroundColor = 'rgb(var(--warning-rgb) / 0.1)';
                    } else {
                        input.style.borderColor = '';
                        input.style.backgroundColor = '';
                    }
                    copied = true;
                }
            });

            if (copied) {
                odswiezZnacznikStawek();
                showToast(`Skopiowano stawki z ${prevMonth}/${prevYear}. Pamiętaj, aby kliknąć Zapisz.`, 'info');
            } else {
                showToast('Stawki w poprzednim miesiącu są identyczne jak obecnie wpisane.', 'info');
            }
        } else {
            showToast('Wystąpił błąd podczas pobierania stawek.', 'error');
        }
    } catch (err) {
        showToast('Błąd połączenia z serwerem.', 'error');
    }
}
