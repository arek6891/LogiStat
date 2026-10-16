// Skrypt strony templates/import_csv.html (wyniesiony z szablonu 2026-10-16).
// Import = pliki jednej osoby z jednej minuty i jednej daty pliku.
const fmtData = iso => { if (!iso) return '—'; const [y, m, d] = iso.split('-'); return `${d}.${m}.${y}`; };
const num = n => (n || 0).toLocaleString('pl');
let importy = [];
let osobyWczytane = false;

function zaznaczone() {
    return [...document.querySelectorAll('.imp-check:checked')].map(c => c.value);
}

function odswiezZaznaczenie() {
    const wybrane = new Set(zaznaczone());
    const lista = importy.filter(i => wybrane.has(i.klucz));
    const paczek = lista.reduce((s, i) => s + i.paczek, 0);
    document.getElementById('zaznaczenieInfo').textContent = lista.length
        ? `Zaznaczono ${lista.length} import(ów), ${num(paczek)} paczek.` : '';
    document.getElementById('podgladBtn').disabled = !lista.length;
    document.getElementById('skutki').style.display = 'none';
}

async function szukajImportow() {
    const p = new URLSearchParams();
    const pole = (id, nazwa) => { const v = document.getElementById(id).value; if (v) p.set(nazwa, v); };
    pole('fDataPliku', 'data_pliku'); pole('fDzien', 'dzien_importu');
    pole('fOd', 'godz_od'); pole('fDo', 'godz_do'); pole('fOsoba', 'osoba');
    const body = document.getElementById('importyBody');
    try {
        const res = await fetch('/api/imports?' + p.toString());
        const d = await res.json();
        if (!res.ok) { showToast(d.error || 'Błąd ładowania importów.', 'error'); return; }
        importy = d.importy;
        if (!osobyWczytane) {
            const sel = document.getElementById('fOsoba');
            d.osoby.forEach(o => sel.insertAdjacentHTML('beforeend',
                `<option value="${o.id}">${escapeHtml(o.nazwa)} (${escapeHtml(o.login)})</option>`));
            osobyWczytane = true;
        }
        body.innerHTML = importy.length ? importy.map(i => `
            <tr>
                <td><input type="checkbox" class="imp-check" value="${escapeHtml(i.klucz)}"></td>
                <td>${new Date(i.imported_at).toLocaleString('pl', {dateStyle: 'short', timeStyle: 'short'})}</td>
                <td>${escapeHtml(i.osoba)}${i.recznych ? ` <span class="badge" title="Paczki dodane ręcznie">ręczne: ${i.recznych}</span>` : ''}</td>
                <td><strong>${fmtData(i.data_pliku)}</strong></td>
                <td style="text-align:right;">${num(i.paczek)}</td>
                <td style="text-align:right;">${num(i.sztuk)}</td>
                <td style="text-align:right;">${num(i.zrobionych)}</td>
            </tr>`).join('')
            : '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:1.5rem;">Brak importów dla tych filtrów.</td></tr>';
        if (d.ucieto) showToast('Pokazano pierwsze 300 importów — zawęź filtry.', 'warning');
        document.getElementById('zaznaczWszystkie').checked = false;
        body.querySelectorAll('.imp-check').forEach(c => c.addEventListener('change', odswiezZaznaczenie));
        odswiezZaznaczenie();
    } catch {
        body.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--danger);padding:1.5rem;">Błąd połączenia.</td></tr>';
    }
}

document.getElementById('zaznaczWszystkie').addEventListener('change', e => {
    document.querySelectorAll('.imp-check').forEach(c => { c.checked = e.target.checked; });
    odswiezZaznaczenie();
});
document.getElementById('nowaData').addEventListener('change', () => {
    document.getElementById('skutki').style.display = 'none';
});

async function wyslijZmiane(podglad) {
    const nowa = document.getElementById('nowaData').value;
    if (!nowa) { showToast('Podaj nową Loading date.', 'error'); return null; }
    const res = await fetch('/api/imports/zmien-date', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({importy: zaznaczone(), nowa_data: nowa, podglad})
    });
    const d = await res.json().catch(() => ({}));
    return {ok: res.ok, status: res.status, d, nowa};
}

// Najpierw skutki (nic nie zapisuje), potem swiadome potwierdzenie.
async function podgladZmiany() {
    const w = await wyslijZmiane(true);
    if (!w) return;
    const box = document.getElementById('skutki');
    const d = w.d;
    if (!w.ok) {
        box.innerHTML = `<div class="alert alert-error" style="border:1px solid var(--danger);background:var(--danger-bg);padding:1rem;border-radius:8px;">⚠ ${escapeHtml(d.error || 'Nie można zmienić daty.')}</div>`;
        box.style.display = '';
        return;
    }
    box.innerHTML = `
        <div style="border:1px solid var(--warning);background:var(--warning-bg);padding:1rem;border-radius:8px;">
            <div style="font-weight:600;margin-bottom:.5rem;">Zmiana Loading date na ${fmtData(w.nowa)}:</div>
            <ul style="margin:.25rem 0 .75rem 1.2rem;line-height:1.6;">
                <li><strong>${num(d.paczek)}</strong> paczek (${num(d.sztuk)} szt., w tym ${num(d.zrobionych)} zrobionych)${d.juz_z_ta_data ? ` · ${num(d.juz_z_ta_data)} już ma tę datę` : ''}</li>
                <li>Statystyki ogólne: ${num(d.linii_przenoszonych)} linii przechodzi w całości${d.linii_dzielonych ? `, ${num(d.linii_dzielonych)} linii traci część paczek` : ''}${d.linii_docelowych_istniejacych ? `, ${num(d.linii_docelowych_istniejacych)} łączy się z istniejącymi liniami z ${fmtData(w.nowa)}` : ''}</li>
            </ul>
            ${d.paczek ? `<button class="btn btn-primary" onclick="potwierdzZmiane()">Zmień datę ${num(d.paczek)} paczek</button>` : '<em>Nic do zmiany.</em>'}
            <button class="btn btn-ghost" onclick="document.getElementById('skutki').style.display='none'">Anuluj</button>
        </div>`;
    box.style.display = '';
}

async function potwierdzZmiane() {
    const w = await wyslijZmiane(false);
    if (!w) return;
    if (!w.ok) { showToast(w.d.error || 'Błąd zmiany daty.', 'error'); return; }
    showToast(w.d.message, 'success');
    document.getElementById('skutki').style.display = 'none';
    szukajImportow();
}

szukajImportow();
