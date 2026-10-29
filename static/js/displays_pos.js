// Dekoracje → Etykiety POS: tabela numerow, import z Excela, zaznaczanie do druku.
// Druk to zwykly formularz POST z target=_blank (klik uzytkownika — blokada
// wyskakujacych okien go nie zatrzyma); PDF otwiera sie w nowej karcie.
let lista = POS_DANE.lista;
const zaznaczone = new Set();

const PP = { true: 'Tak', false: 'Nie' };

function widoczne() {
    const szukaj = document.getElementById('szukajPos').value.trim().toUpperCase();
    return szukaj ? lista.filter(p => p.numer.includes(szukaj)) : lista;
}

function rysuj() {
    const wiersze = widoczne();
    const tbody = document.getElementById('tabelaPos');
    if (!wiersze.length) {
        tbody.innerHTML = `<tr><td colspan="5" style="color:var(--text-muted);">${lista.length ? 'Brak numerów pasujących do wyszukiwania.' : 'Lista jest pusta — wczytaj plik Excel.'}</td></tr>`;
    } else {
        tbody.innerHTML = wiersze.map(p => `<tr>
            <td><input type="checkbox" name="id" value="${p.id}" ${zaznaczone.has(p.id) ? 'checked' : ''} data-id="${p.id}"></td>
            <td><strong>${escapeHtml(p.numer)}</strong></td>
            <td>${p.post_processing === null ? '<span style="color:var(--text-muted);">—</span>' : PP[p.post_processing]}</td>
            <td>${escapeHtml(p.dodano)}</td>
            <td><button type="button" class="btn btn-danger btn-sm" data-usun="${p.id}" title="Usuń z listy">✕</button></td>
        </tr>`).join('');
    }
    // Zaznaczone, ale ukryte wyszukiwaniem — tez ida do druku (ukryte pola).
    const ukryte = [...zaznaczone].filter(id => !wiersze.some(p => p.id === id));
    tbody.insertAdjacentHTML('beforeend', ukryte.map(id => `<input type="hidden" name="id" value="${id}">`).join(''));
    const zazn = document.getElementById('zaznaczWszystkie');
    zazn.checked = wiersze.length > 0 && wiersze.every(p => zaznaczone.has(p.id));
    liczniki();
}

function liczniki(ostatniImport) {
    document.getElementById('drukWybrane').textContent = `Zaznaczone (${zaznaczone.size})`;
    document.getElementById('drukWszystkie').textContent = `Wszystkie (${lista.length})`;
    if (ostatniImport !== undefined) document.getElementById('drukImport').textContent = `Z ostatniego importu (${ostatniImport})`;
}

document.getElementById('tabelaPos').addEventListener('change', e => {
    const id = Number(e.target.dataset.id);
    if (!id) return;
    if (e.target.checked) zaznaczone.add(id); else zaznaczone.delete(id);
    rysuj();
});

document.getElementById('zaznaczWszystkie').addEventListener('change', e => {
    for (const p of widoczne()) {
        if (e.target.checked) zaznaczone.add(p.id); else zaznaczone.delete(p.id);
    }
    rysuj();
});

document.getElementById('szukajPos').addEventListener('input', rysuj);
// Enter w wyszukiwarce nie moze wyslac formularza druku.
document.getElementById('szukajPos').addEventListener('keydown', e => { if (e.key === 'Enter') e.preventDefault(); });

document.getElementById('tabelaPos').addEventListener('click', async e => {
    const id = Number(e.target.dataset.usun);
    if (!id) return;
    const p = lista.find(x => x.id === id);
    if (!confirm(`Usunąć ${p ? p.numer : 'numer'} z listy POS?`)) return;
    const res = await fetch(`/api/dekoracje/pos/${id}`, { method: 'DELETE' });
    if (!res.ok) return pokazBladOdpowiedzi(res, 'Nie udało się usunąć');
    lista = lista.filter(x => x.id !== id);
    zaznaczone.delete(id);
    rysuj();
});

document.getElementById('wczytajPos').addEventListener('click', async () => {
    const pole = document.getElementById('plikPos');
    if (!pole.files.length) return showToast('Wybierz plik Excel (.xlsx).', 'error');
    const przycisk = document.getElementById('wczytajPos');
    const dane = new FormData();
    dane.append('file', pole.files[0]);
    przycisk.disabled = true;
    try {
        const res = await fetch('/api/dekoracje/pos/import', { method: 'POST', body: dane });
        if (!res.ok) return pokazBladOdpowiedzi(res, 'Nie udało się wczytać pliku');
        const w = await res.json();
        lista = w.lista;
        const istnieja = new Set(lista.map(p => p.id));
        for (const id of [...zaznaczone]) if (!istnieja.has(id)) zaznaczone.delete(id);
        pole.value = '';
        pokazWynik(w);
        rysuj();
        liczniki(w.ostatni_import);
    } finally {
        przycisk.disabled = false;
    }
});

function pokazWynik(w) {
    const bledy = w.bledy.length ? `<p style="color:var(--danger);margin-bottom:4px;">⚠ Pominięte wiersze (${w.bledy.length}):</p>
        <ul style="margin-top:0;">${w.bledy.slice(0, 50).map(b => `<li>wiersz ${b.wiersz}${b.wartosc ? ` (${escapeHtml(b.wartosc)})` : ''}: ${escapeHtml(b.powod)}</li>`).join('')}
        ${w.bledy.length > 50 ? `<li>… i ${w.bledy.length - 50} kolejnych</li>` : ''}</ul>` : '';
    const pp = w.ma_pp ? '' : ' · plik bez kolumny Post Processing — ta kolumna bez zmian';
    document.getElementById('wynikImportu').innerHTML = `<div class="dekoracje-pos-wynik">
        <p style="margin:0;">✓ Wczytano ${w.wczytane} numerów: nowe ${w.dodane}, zmieniony Post Processing ${w.zmienione}, bez zmian ${w.bez_zmian}${pp}.
        Wydrukujesz je przyciskiem „Z ostatniego importu”.</p>${bledy}</div>`;
}

rysuj();
