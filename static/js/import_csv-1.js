// Skrypt strony templates/import_csv.html (wyniesiony z szablonu 2026-10-16).
// Dane z serwera: blok <script> w szablonie tuz przed tym plikiem.
function handleDrop(e) {
    e.preventDefault();
    e.target.closest('#dropZone').style.borderColor = 'var(--border)';
    e.target.closest('#dropZone').style.background = 'transparent';
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
}


let plikDoImportu = null;

function handleFile(file) {
    const name = file ? file.name.toLowerCase() : '';
    if (!file || !(name.endsWith('.csv') || name.endsWith('.xlsx'))) {
        showToast('Wybierz plik .csv lub .xlsx', 'error');
        return;
    }
    document.getElementById('fileName').textContent = '📎 ' + file.name;
    // Najpierw data pliku — import bez niej nie rusza.
    plikDoImportu = file;
    document.getElementById('dpNazwa').textContent = file.name;
    const pole = document.getElementById('dpData');
    pole.value = DZIS;
    sprawdzDate();
    document.getElementById('dataPlikuModal').style.display = 'flex';
    setTimeout(() => pole.focus(), 0);
}

// Data inna niz dzis jest dozwolona (plik za wczoraj), ale ma byc swiadoma.
function sprawdzDate() {
    const v = document.getElementById('dpData').value;
    const box = document.getElementById('dpOstrzezenie');
    if (v && v !== DZIS) {
        const [y, m, d] = v.split('-');
        box.textContent = `⚠ To nie jest dzisiejsza data — plik zostanie zapisany pod ${d}.${m}.${y}.`;
        box.style.display = '';
    } else {
        box.style.display = 'none';
    }
}
document.getElementById('dpData').addEventListener('input', sprawdzDate);
document.getElementById('dpData').addEventListener('keydown', e => { if (e.key === 'Enter') potwierdzImport(); });

function anulujImport() {
    plikDoImportu = null;
    document.getElementById('dataPlikuModal').style.display = 'none';
    document.getElementById('fileInput').value = '';
    document.getElementById('fileName').textContent = '';
}

function potwierdzImport() {
    const data = document.getElementById('dpData').value;
    if (!data) { showToast('Podaj Loading date.', 'error'); return; }
    if (!plikDoImportu) return;
    const plik = plikDoImportu;
    plikDoImportu = null;
    document.getElementById('dataPlikuModal').style.display = 'none';
    document.getElementById('fileInput').value = '';
    uploadFile(plik, data);
}

async function uploadFile(file, dataPliku) {
    const loading = document.getElementById('loading');
    const results = document.getElementById('results');
    loading.style.display = 'block';
    results.style.display = 'none';

    const endpoint = file.name.toLowerCase().endsWith('.xlsx')
        ? '/api/import/excel'
        : '/api/import-csv';

    const formData = new FormData();
    formData.append('file', file);
    formData.append('data_pliku', dataPliku);

    try {
        const resp = await fetch(endpoint, {
            method: 'POST',
            body: formData
        });
        const data = await resp.json();
        loading.style.display = 'none';

        if (!resp.ok) {
            showToast(data.error || 'Błąd importu', 'error');
            return;
        }

        results.style.display = 'block';
        let html = `
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1rem;margin-bottom:1.5rem;">
            <div style="background:var(--success-bg);padding:1rem;border-radius:8px;text-align:center;">
                <div style="font-size:1.8rem;font-weight:700;color:var(--success);">${data.imported}</div>
                <div style="font-size:.85rem;color:var(--text-muted);">Zaimportowane</div>
            </div>
            <div style="background:rgb(var(--warning-rgb) / .1);padding:1rem;border-radius:8px;text-align:center;">
                <div style="font-size:1.8rem;font-weight:700;color:var(--warning);">${data.skipped}</div>
                <div style="font-size:.85rem;color:var(--text-muted);">Pominięte (duplikaty)</div>
            </div>
            <div style="background:rgb(var(--accent-rgb) / .1);padding:1rem;border-radius:8px;text-align:center;">
                <div style="font-size:1.8rem;font-weight:700;color:var(--accent);">${data.stats_created}</div>
                <div style="font-size:.85rem;color:var(--text-muted);">Nowe wiersze statystyk</div>
            </div>
            <div style="background:rgb(var(--accent-2-rgb) / .1);padding:1rem;border-radius:8px;text-align:center;">
                <div style="font-size:1.8rem;font-weight:700;color:var(--accent-2);">${data.stats_updated}</div>
                <div style="font-size:.85rem;color:var(--text-muted);">Zaktualizowane statystyki</div>
            </div>
        </div>`;

        if (data.skipped_barcodes && data.skipped_barcodes.length > 0) {
            html += `<details style="margin-top:1rem;"><summary style="cursor:pointer;color:var(--text-muted);">Pominięte barcodes (${data.skipped_barcodes.length})</summary>`;
            html += `<div style="margin-top:.5rem;max-height:200px;overflow-y:auto;font-size:.8rem;color:var(--text-muted);">`;
            data.skipped_barcodes.forEach(b => { html += `<code>${escapeHtml(b)}</code> `; });
            html += `</div></details>`;
        }

        document.getElementById('resultContent').innerHTML = html;
        showToast(data.message, 'success');
        if (typeof szukajImportow === 'function') szukajImportow();

    } catch (err) {
        loading.style.display = 'none';
        showToast('Błąd połączenia: ' + err.message, 'error');
    }
}
