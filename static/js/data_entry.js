// Skrypt strony templates/data_entry.html (wyniesiony z szablonu 2026-10-16).
let currentShift = 1;

document.getElementById('entryDate').valueAsDate = new Date();

// Data, dla ktorej tabela jest wczytana. Zmiana pola daty zaczyna
// przeladowanie dopiero po dokonczeniu zapisow, a do tego czasu autozapis
// musi isc pod DOTYCHCZASOWA date — nie te juz wpisana w polu.
let loadedDate = document.getElementById('entryDate').value;

async function switchShift(num) {
    if (!await autoZapis.przedOpuszczeniem()) return;
    currentShift = num;
    document.querySelectorAll('.shift-tab').forEach(t => {
        t.classList.toggle('active', parseInt(t.dataset.shift) === num);
    });
    document.getElementById('entryFrame').dataset.shift = num;
    loadEntries();
}

document.getElementById('entryDate').addEventListener('change', async (e) => {
    if (!await autoZapis.przedOpuszczeniem()) {
        e.target.value = loadedDate;
        return;
    }
    loadEntries();
});
document.addEventListener('DOMContentLoaded', loadEntries);

async function loadEntries() {
    const dateVal = document.getElementById('entryDate').value;
    loadedDate = dateVal;
    const tbody = document.getElementById('dataBody');

    try {
        const res = await fetch(`/api/daily-stats?date=${dateVal}&shift_number=${currentShift}`);
        const data = await res.json();

        if (!data.assignments || data.assignments.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="empty-state"><div class="icon">📝</div><p>Brak przydziałów na tę datę i zmianę.<br>Najpierw przydziel pracowników do czynności.</p></td></tr>';
            return;
        }

        // Build existing stats map
        const statsMap = {};
        (data.stats || []).forEach(s => {
            statsMap[`${s.user_id}-${s.activity_id}`] = s;
        });

        tbody.innerHTML = '';
        data.assignments.forEach(a => {
            const key = `${a.user_id}-${a.activity_id}`;
            const stat = statsMap[key] || {};
            const tr = document.createElement('tr');
            tr.innerHTML = `
            <td>
                <div style="display:flex;align-items:center;gap:8px;">
                    <div class="mini-avatar" style="width:28px;height:28px;border-radius:50%;background:linear-gradient(135deg,var(--accent),var(--accent-2));display:flex;align-items:center;justify-content:center;font-weight:700;font-size:0.7rem;color:var(--on-accent);">
                        ${escapeHtml(a.user.display_name[0])}
                    </div>
                    ${escapeHtml(a.user.display_name)}
                </div>
            </td>
            <td>${escapeHtml(a.activity.name)}</td>
            <td><input type="number" class="qty-input" value="${parseInt(stat.quantity) || 0}" min="0"></td>
            <td><input type="text" class="form-control note-input"
                value="${escapeHtml(stat.note || '')}" placeholder="Uwagi..." style="width:200px;padding:6px 10px;font-size:0.85rem;"></td>
        `;
            const qty = tr.querySelector('.qty-input');
            const note = tr.querySelector('.note-input');
            const zapisz = () => saveEntry(a.user_id, a.activity_id, qty, note);
            autoZapis.poWpisaniu(qty, zapisz);
            autoZapis.poWpisaniu(note, zapisz);
            tbody.appendChild(tr);
        });
    } catch (err) {
        showToast('Błąd ładowania danych.', 'error');
    }
}

// Jeden wiersz = jeden zapis. Endpoint robi upsert per (zmiana, pracownik,
// czynnosc), wiec wyslanie pojedynczego wpisu nie rusza pozostalych.
// Ilosc i uwaga ida razem — klucz wiersza serializuje oba pola, wiec szybkie
// "ilosc, Tab, uwaga" na nowym wierszu nie robi dwoch rownoleglych INSERT-ow.
function saveEntry(userId, activityId, qtyInput, noteInput) {
    const body = {
        date: loadedDate,
        shift_number: currentShift,
        entries: [{
            user_id: userId,
            activity_id: activityId,
            quantity: parseInt(qtyInput.value) || 0,
            note: noteInput.value
        }]
    };
    const klucz = `daily:${body.date}:${body.shift_number}:${userId}:${activityId}`;
    autoZapis.zaplanuj(klucz, () => zapiszJson('/api/daily-stats', 'POST', body), [qtyInput, noteInput]);
}
