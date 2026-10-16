// Skrypt strony templates/admin_settings.html (wyniesiony z szablonu 2026-10-16).
async function saveSettings() {
    const pola = {
        break_threshold_minutes: parseInt(document.getElementById('breakThreshold').value, 10),
        max_work_minutes:        parseInt(document.getElementById('maxWork').value, 10),
        min_break_minutes:       parseInt(document.getElementById('minBreak').value, 10),
        norm_good_pct:           parseInt(document.getElementById('normGood').value, 10),
        norm_weak_pct:           parseInt(document.getElementById('normWeak').value, 10),
        min_packages_rank:       parseInt(document.getElementById('minPackages').value, 10),
    };
    if (pola.norm_weak_pct >= pola.norm_good_pct) {
        showToast('Próg słabego wyniku musi być niższy niż próg dobrego.', 'error'); return;
    }
    if (Object.values(pola).some(v => !v || v < 1)) {
        showToast('Wszystkie wartości muszą być większe od zera.', 'error'); return;
    }
    const btn = document.getElementById('saveBtn');
    btn.disabled = true;
    try {
        const res = await fetch('/api/settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(pola)
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { showToast(data.error || 'Błąd zapisu.', 'error'); return; }
        showToast(data.message || 'Zapisano.', 'success');
    } catch {
        showToast('Błąd połączenia.', 'error');
    } finally {
        btn.disabled = false;
    }
}
