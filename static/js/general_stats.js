// Skrypt strony templates/general_stats.html (wyniesiony z szablonu 2026-10-16).
// Dane z serwera: blok <script> w szablonie tuz przed tym plikiem.
// Track modifications
document.querySelectorAll('.inline-input').forEach(input => {
    const original = input.value;
    input.dataset.original = original;
    input.addEventListener('input', function () {
        if (this.value !== this.dataset.original) {
            this.classList.add('modified');
        } else {
            this.classList.remove('modified');
        }
        updateRowTotal(this.closest('tr'));
        updateGlobalSums();
    });
});
// Tylko pola ilosci — pole kosztu (readonly) tez ma klase inline-input.
// Po DOMContentLoaded: ten skrypt stoi w bloku `content`, czyli PRZED
// skryptem base.html z `autoZapis` — wywolany od razu dostalby ReferenceError.
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.inline-input[data-field="amount"]').forEach(input => {
        autoZapis.poWpisaniu(input, () => saveRow(input.closest('tr')));
    });
});

// Filtr, eksport i przeladowanie czytaja baze — najpierw dokoncz zapisy,
// inaczej plik rozliczeniowy wyszedlby ze starymi ilosciami.
document.getElementById('filtrForm').addEventListener('submit', async function (e) {
    e.preventDefault();
    if (await autoZapis.przedOpuszczeniem()) this.submit();
});
document.getElementById('exportBtn').addEventListener('click', async function (e) {
    e.preventDefault();
    if (await autoZapis.przedOpuszczeniem()) window.location.href = this.href;
});



// Ilosci ze skanow moga miec polowki (Labelling twice ×1,5).
const ilosc = (v) => parseFloat(v) || 0;
const pokazIlosc = (v) => String(Math.round(v * 100) / 100);

function updateRowTotal(row) {
    let total = 0;
    let totalAmount = 0;
    const categories = KATEGORIE;
    const ym = row.dataset.ym;
    const rates = ratesByYm[ym] || {};

    // Total Amount = wszystko poza TOTAL_AMOUNT_BEZ, w obu wierszach.

    categories.forEach(cat => {
        const amountInput = row.querySelector(`[data-cat="${cat}"][data-field="amount"]`);
        const costInput = row.querySelector(`[data-cat="${cat}"][data-field="cost"]`);
        if (amountInput && costInput) {
            const amt = ilosc(amountInput.value);
            const rate = parseFloat(rates[cat]) || 0.0;
            if (!TOTAL_AMOUNT_BEZ.includes(cat)) totalAmount += amt;
            const cst = amt * rate;
            costInput.value = cst.toFixed(2);
            total += cst;
        }
    });

    const totalCell = row.querySelector('.total-cost');
    if (totalCell) {
        totalCell.textContent = total.toFixed(2) + ' €';
        totalCell.dataset.val = total;
    }

    const totalAmountCell = row.querySelector('.row-total-amount');
    if (totalAmountCell) {
        totalAmountCell.textContent = pokazIlosc(totalAmount);
        totalAmountCell.dataset.val = totalAmount;
    }
}

function updateGlobalSums() {
    // Amount Sums
    let sumAmounts = 0;
    document.querySelectorAll('.row-amounts').forEach(td => {
        sumAmounts += parseInt(td.dataset.val) || 0;
    });
    document.getElementById('sumAmounts').textContent = sumAmounts;

    let sumTotalAmounts = 0;
    document.querySelectorAll('.row-total-amount').forEach(td => {
        let rowAmt = parseFloat(td.dataset.val);
        if (isNaN(rowAmt)) rowAmt = ilosc(td.textContent);
        sumTotalAmounts += rowAmt;
    });
    const sumTotAmtEl = document.getElementById('sumTotalAmounts');
    if (sumTotAmtEl) sumTotAmtEl.textContent = pokazIlosc(sumTotalAmounts);

    // Category Amounts and Costs
    const categories = KATEGORIE;
    categories.forEach(cat => {
        let catAmount = 0;
        let catCost = 0;
        document.querySelectorAll(`[data-cat="${cat}"][data-field="amount"]`).forEach(inp => {
            catAmount += ilosc(inp.value);
        });
        document.querySelectorAll(`[data-cat="${cat}"][data-field="cost"]`).forEach(inp => {
            // Cost is already calculated per row based on mapping
            catCost += parseFloat(inp.value) || 0;
        });
        const amtEl = document.getElementById(`sum-${cat}-amount`);
        const costEl = document.getElementById(`sum-${cat}-cost`);
        if (amtEl) amtEl.textContent = pokazIlosc(catAmount);
        if (costEl) costEl.textContent = catCost.toFixed(2) + ' €';
    });

    // Global Total Cost
    let sumTotalCost = 0;
    document.querySelectorAll('.total-cost').forEach(td => {
        let rowVal = parseFloat(td.dataset.val);
        if (isNaN(rowVal)) { // initialize fallback if dataset is missing
            rowVal = parseFloat(td.textContent.replace('€', '').trim()) || 0;
            td.dataset.val = rowVal;
        }
        sumTotalCost += rowVal;
    });
    // Lider nie widzi kosztow — komorki sumy kosztu nie ma w DOM.
    const sumTotalCostEl = document.getElementById('sumTotalCost');
    if (sumTotalCostEl) sumTotalCostEl.textContent = sumTotalCost.toFixed(2) + ' €';
}

// Keep export link in sync with filter inputs
function syncExportLink() {
    const df = document.querySelector('input[name="date_from"]').value;
    const dt = document.querySelector('input[name="date_to"]').value;
    const params = new URLSearchParams();
    if (df) params.set('date_from', df);
    if (dt) params.set('date_to', dt);
    document.getElementById('exportBtn').href = '/general-stats/export?' + params.toString();
}
document.querySelector('input[name="date_from"]').addEventListener('change', syncExportLink);
document.querySelector('input[name="date_to"]').addEventListener('change', syncExportLink);

// Initialize sums on load
updateGlobalSums();

async function przelaczNaSkany(btn) {
    if (!confirm('Zastąpić ręcznie wpisane ilości sumą ze skanów paczek?\n\n' +
                 'Tej operacji nie cofniesz — ręczne wartości tej linii zostaną nadpisane.')) return;
    if (!await autoZapis.przedOpuszczeniem()) return;
    btn.disabled = true;
    try {
        const res = await fetch(`/api/general-stats/${btn.dataset.id}/use-scan`,
                                { method: 'POST' });
        if (!res.ok) {
            const d = await res.json().catch(() => ({}));
            alert('Błąd: ' + (d.error || 'nie udało się przełączyć linii.'));
            btn.disabled = false;
            return;
        }
        location.reload();
    } catch {
        alert('Błąd połączenia.');
        btn.disabled = false;
    }
}

// Wiersz (linia albo jej zolty wiersz double rate) = jeden PUT ze
// wszystkimi kategoriami tego wiersza. Zolty wiersz pisze do osobnego pola
// tego samego rekordu, wiec ma osobny klucz — oba moga isc rownolegle.
function saveRow(row) {
    const id = row.dataset.id;
    const isDr = row.dataset.drRow === 'true';
    // Tylko pola ilosci: pole kosztu tez ma klase inline-input (readonly) i
    // nadpisaloby ilosc kategorii swoja wartoscia.
    const inputs = [...row.querySelectorAll('.inline-input[data-field="amount"]')];
    // Bez pol ilosci (linia ze skanow / zmieniony szablon) nie wysylaj nic —
    // pusty slownik wyczyscilby kategorie, czyli rozliczenie tej linii.
    if (inputs.length === 0) return;
    const categoryData = {};
    inputs.forEach(inp => {
        // Backend no longer needs cost, but we preserve the schema structure
        categoryData[inp.dataset.cat] = { amount: parseInt(inp.value) || 0, cost: 0 };
    });
    const payload = isDr
        ? { double_rate_category_data: categoryData }
        : { category_data: categoryData };
    const values = inputs.map(inp => inp.value);

    autoZapis.zaplanuj(`gs:${id}:${isDr ? 'dr' : 'main'}`, async () => {
        await zapiszJson(`/api/general-stats/${id}`, 'PUT', payload);
        inputs.forEach((inp, k) => {
            inp.dataset.original = values[k];
            inp.classList.toggle('modified', inp.value !== values[k]);
        });
    }, inputs);
}
