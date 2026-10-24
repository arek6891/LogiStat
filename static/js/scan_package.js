// Skrypt strony templates/scan_package.html (wyniesiony z szablonu 2026-10-16).
const scanInput = document.getElementById('scanInput');
const resultCard = document.getElementById('resultCard');
let scanTimer = null;

scanInput.addEventListener('input', () => {
    clearTimeout(scanTimer);
    if (scanInput.value.length > 0) {
        scanInput.classList.add('scanning');
        scanTimer = setTimeout(() => {
            const barcode = scanInput.value.trim();
            scanInput.value = '';
            scanInput.classList.remove('scanning');
            if (barcode.length >= 3) lookup(barcode);
        }, 300);
    }
});

scanInput.addEventListener('blur', () => {
    setTimeout(() => scanInput.focus(), 100);
});

async function lookup(barcode) {
    try {
        const res = await fetch('/api/package-lookup?barcode=' + encodeURIComponent(barcode));
        const data = await res.json();
        if (!res.ok) {
            showToast(data.error, 'error');
            renderNotFound(barcode, data.error);
            return;
        }
        renderCard(data.carton);
    } catch {
        showToast('Błąd połączenia.', 'error');
    }
}

function fmtDateTime(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleDateString('pl') + ' ' + d.toLocaleTimeString('pl');
}

function fmtDuration(secs) {
    if (secs === null || secs === undefined) return '—';
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return (m > 0 ? m + 'm ' : '') + s + 's';
}

function renderNotFound(barcode, msg) {
    resultCard.style.display = '';
    resultCard.innerHTML = `
        <div class="card" style="border-left:4px solid var(--danger);">
            <div style="display:flex;align-items:center;gap:.75rem;">
                <div style="font-size:1.8rem;">❌</div>
                <div>
                    <div style="font-family:monospace;font-weight:700;color:var(--danger);">${escapeHtml(barcode)}</div>
                    <div style="color:var(--text-muted);font-size:.9rem;">${escapeHtml(msg)}</div>
                </div>
            </div>
        </div>`;
}

function pill(ok, okText, noText) {
    const bg = ok ? 'rgb(var(--success-rgb) / .15)' : 'rgb(var(--text-secondary-rgb) / .15)';
    const col = ok ? 'var(--success)' : 'var(--text-secondary)';
    return `<span style="display:inline-block;padding:.3rem .8rem;border-radius:999px;
        background:${bg};color:${col};font-weight:700;font-size:.85rem;">${ok ? okText : noText}</span>`;
}

function row(label, value) {
    return `<div style="display:flex;justify-content:space-between;gap:1rem;padding:.4rem 0;
                border-bottom:1px solid var(--border);">
                <span style="color:var(--text-muted);">${label}</span>
                <span style="font-weight:600;text-align:right;">${value}</span>
            </div>`;
}

function renderCard(c) {
    resultCard.style.display = '';

    // Status zakończenia: zakończona / w trakcie / nierozpoczęta
    let finishText, finishOk = c.finished;
    if (c.finished) finishText = '✅ Zakończona';
    else if (c.scan_start_at) finishText = '⏳ W trakcie (rozpoczęta, bez końca)';
    else if (c.do_dokonczenia) finishText = '📤 Do dokończenia (czeka na następną osobę)';
    else finishText = '⏳ Niezakończona';

    const borderCol = c.finished ? 'var(--success)'
                    : (c.scanned ? 'var(--warning)' : 'var(--text-muted)');

    const drBadge = c.double_rate
        ? `<span style="display:inline-block;padding:.15rem .6rem;border-radius:999px;
             background:rgb(var(--double-rate-rgb) / .15);color:var(--double-rate);font-weight:700;font-size:.8rem;">DOUBLE RATE</span>`
        : '—';

    resultCard.innerHTML = `
        <div class="card" style="border-left:4px solid ${borderCol};">
            <div style="display:flex;align-items:center;gap:.75rem;margin-bottom:1rem;">
                <div style="font-size:1.8rem;">📦</div>
                <div style="font-family:monospace;font-weight:700;font-size:1.2rem;">${escapeHtml(c.barcode)}</div>
            </div>

            <div style="display:flex;flex-wrap:wrap;gap:1.5rem;margin-bottom:1.25rem;">
                <div>
                    <div style="color:var(--text-muted);font-size:.8rem;margin-bottom:.35rem;">Przeskanowana</div>
                    ${pill(c.scanned, '✅ TAK', '❌ NIE')}
                    ${c.scanned && c.scanned_by ? `<div style="margin-top:.35rem;font-size:.85rem;">przez <strong>${escapeHtml(c.scanned_by)}</strong></div>` : ''}
                </div>
                <div>
                    <div style="color:var(--text-muted);font-size:.8rem;margin-bottom:.35rem;">Status</div>
                    ${pill(finishOk, finishText, finishText)}
                </div>
            </div>

            <div style="margin-bottom:1rem;">
                ${row('Kraj (Land)', escapeHtml(c.land) || '—')}
                ${row('Ilość (Stückzahl)', c.stueckzahl)}
                ${row('Kategoria', escapeHtml(c.kategorie) || '—')}
                ${row('Ziel-Datum', c.ziel_datum ? new Date(c.ziel_datum).toLocaleDateString('pl') : '—')}
                ${row('Übergabe Nr.', escapeHtml(c.uebergabe_nr) || '—')}
                ${row('Double rate', drBadge)}
            </div>

            <div style="background:rgb(var(--text-secondary-rgb) / .06);border-radius:8px;padding:.75rem 1rem;">
                <div style="color:var(--text-muted);font-size:.8rem;margin-bottom:.4rem;">Szczegóły procesowania</div>
                ${row('Przypisano', c.processed_by_name ? `${escapeHtml(c.processed_by_name)} · ${fmtDateTime(c.processed_at)}` : '—')}
                ${row('Start', c.scan_start_at ? `${escapeHtml(c.scan_start_by_name) || '—'} · ${fmtDateTime(c.scan_start_at)}` : '—')}
                ${row('Koniec', c.scan_end_at ? `${escapeHtml(c.scan_end_by_name) || '—'} · ${fmtDateTime(c.scan_end_at)}` : '—')}
                ${row('Czas procesowania', fmtDuration(c.processing_seconds))}
                ${(c.udzialy || []).map(u => row('👤 ' + escapeHtml(u.user_name || '?'),
                    `${fmtDateTime(u.start_at)} – ${u.otwarty ? 'pracuje' : fmtDateTime(u.end_at) + ' · ' + u.sztuki + ' szt.'}`
                    + (u.zamkniete_przez ? ` · zamknął: ${escapeHtml(u.zamkniete_przez)}` : ''))).join('')}
            </div>
        </div>`;
}
