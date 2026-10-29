// Skrypt strony templates/displays_stock.html (2026-10-28): Dekoracje → Stock stojaków.
// Filtry w przegladarce, autozapis per pole (klucz stojak:<id>:<pole>, czesciowy PUT),
// historia ruchow rozwijana pod wierszem. Tekst z bazy przez escapeHtml().
let stojaki = STOCK.stojaki;
const PP = { true: 'Tak', false: 'Nie' };

document.getElementById('listaPos').innerHTML =
    STOCK.pos.map(n => `<option value="${escapeHtml(n)}"></option>`).join('');
for (const a of STOCK.akcje) {
    document.getElementById('filtrAkcja').insertAdjacentHTML('beforeend',
        `<option value="${a.id}">${escapeHtml(a.nazwa)}${a.zakonczona ? ' (zakończona)' : ''}</option>`);
}
for (const s of STOCK.strefy) {
    document.getElementById('filtrStrefa').insertAdjacentHTML('beforeend',
        `<option value="${s.id}">${escapeHtml(s.nazwa)}</option>`);
}

function opcjeAkcji(wybrana) {
    return '<option value="">—</option>' + STOCK.akcje
        .filter(a => !a.zakonczona || a.id === wybrana)
        .map(a => `<option value="${a.id}" ${a.id === wybrana ? 'selected' : ''}>${escapeHtml(a.nazwa)}</option>`).join('');
}

function opcjeStref(wybrana) {
    const brak = wybrana === null ? '<option value="" selected disabled>—</option>' : '';
    return brak + STOCK.strefy
        .filter(s => s.aktywna || s.id === wybrana)
        .map(s => `<option value="${s.id}" ${s.id === wybrana ? 'selected' : ''}>${escapeHtml(s.nazwa)}</option>`).join('');
}

function ruchTekst(s) {
    return s.ostatni_ruch ? `${escapeHtml(s.ostatni_ruch)}${s.ostatni_kto ? '<br><small style="color:var(--text-muted);">' + escapeHtml(s.ostatni_kto) + '</small>' : ''}` : '—';
}

function wiersz(s) {
    return `<tr data-id="${s.id}">
        <td style="white-space:nowrap;"><strong>${escapeHtml(s.nosnik)}</strong></td>
        <td><input class="form-control js-pos" list="listaPos" value="${escapeHtml(s.pos || '')}" style="width:120px;" placeholder="—"></td>
        <td class="js-pp">${s.post_processing === null ? '—' : PP[s.post_processing]}</td>
        <td><select class="form-control js-akcja" style="min-width:140px;">${opcjeAkcji(s.akcja_id)}</select></td>
        <td><select class="form-control js-strefa" style="min-width:110px;">${opcjeStref(s.strefa_id)}</select></td>
        <td class="js-ruch" style="white-space:nowrap;">${ruchTekst(s)}</td>
        <td style="white-space:nowrap;">
            <button type="button" class="btn btn-ghost btn-sm js-historia" title="Historia ruchów">🕓</button>
            <button type="button" class="btn btn-danger btn-sm js-usun" title="Usuń (pomyłkowy skan)">✕</button>
        </td>
    </tr>`;
}

function widoczne() {
    const akcja = document.getElementById('filtrAkcja').value;
    const strefa = document.getElementById('filtrStrefa').value;
    const szukaj = document.getElementById('filtrSzukaj').value.trim().toUpperCase();
    return stojaki.filter(s =>
        (!akcja || (akcja === 'brak' ? s.akcja_id === null : s.akcja_id === Number(akcja)))
        && (!strefa || (strefa === 'brak' ? s.strefa_id === null : s.strefa_id === Number(strefa)))
        && (!szukaj || s.nosnik.includes(szukaj) || (s.pos || '').includes(szukaj)));
}

function rysuj() {
    const lista = widoczne();
    document.getElementById('licznikStock').textContent = `${lista.length} z ${stojaki.length}`;
    document.getElementById('tabelaStock').innerHTML = lista.length ? lista.map(wiersz).join('')
        : `<tr><td colspan="7" style="color:var(--text-muted);">${stojaki.length
            ? 'Brak stojaków dla tych filtrów.' : 'Stock jest pusty — nośniki zakłada skan na stanowisku „Skan stojaków”.'}</td></tr>`;
}

// Pole POS nadpisuje tylko odpowiedz na zapis POS — inaczej zapis akcji wyczyscilby
// odrzucony numer, ktory lider jeszcze poprawia.
function odswiezWiersz(tr, s, pole) {
    stojaki = stojaki.map(x => (x.id === s.id ? s : x));
    tr.querySelector('.js-pp').textContent = s.post_processing === null ? '—' : PP[s.post_processing];
    tr.querySelector('.js-ruch').innerHTML = ruchTekst(s);
    const pos = tr.querySelector('.js-pos');
    if (pole === 'pos' && document.activeElement !== pos) pos.value = s.pos || '';
}

function zapisz(tr, pole, body, el) {
    const id = Number(tr.dataset.id);
    autoZapis.zaplanuj(`stojak:${id}:${pole}`,
        async () => odswiezWiersz(tr, await zapiszJson(`/api/dekoracje/stojaki/${id}`, 'PUT', body), pole), [el]);
}

const tabela = document.getElementById('tabelaStock');
tabela.addEventListener('change', e => {
    const tr = e.target.closest('tr[data-id]');
    if (!tr) return;
    if (e.target.classList.contains('js-pos')) zapisz(tr, 'pos', { pos: e.target.value.trim() }, e.target);
    if (e.target.classList.contains('js-akcja')) {
        zapisz(tr, 'akcja', { akcja_id: e.target.value ? Number(e.target.value) : null }, e.target);
    }
    if (e.target.classList.contains('js-strefa')) zapisz(tr, 'strefa', { strefa_id: Number(e.target.value) }, e.target);
});

tabela.addEventListener('click', async e => {
    const tr = e.target.closest('tr[data-id]');
    if (!tr) return;
    const id = Number(tr.dataset.id);
    const s = stojaki.find(x => x.id === id);
    if (e.target.classList.contains('js-usun')) {
        if (!confirm(`Usunąć nośnik ${s.nosnik} ze stocku razem z historią ruchów?`)) return;
        const res = await fetch(`/api/dekoracje/stojaki/${id}`, { method: 'DELETE' });
        if (!res.ok) return pokazBladOdpowiedzi(res, 'Nie udało się usunąć');
        stojaki = stojaki.filter(x => x.id !== id);
        rysuj();
    }
    if (e.target.classList.contains('js-historia')) {
        const nast = tr.nextElementSibling;
        if (nast && nast.classList.contains('dekoracje-historia')) { nast.remove(); return; }
        const res = await fetch(`/api/dekoracje/stojaki/${id}/ruchy`);
        if (!res.ok) return pokazBladOdpowiedzi(res, 'Nie udało się pobrać historii');
        const ruchy = await res.json();
        tr.insertAdjacentHTML('afterend', `<tr class="dekoracje-historia"><td colspan="7">${ruchy.length
            ? '<ul>' + ruchy.map(r => `<li>${escapeHtml(r.kiedy)} · ${escapeHtml(r.kto || '—')}: ${escapeHtml(r.z || 'nowy')} → <strong>${escapeHtml(r.do)}</strong>${r.recznie ? ' <small>(ręcznie w tabeli)</small>' : ''}</li>`).join('') + '</ul>'
            : 'Brak ruchów.'}</td></tr>`);
    }
});

for (const id of ['filtrAkcja', 'filtrStrefa']) document.getElementById(id).addEventListener('change', rysuj);
document.getElementById('filtrSzukaj').addEventListener('input', rysuj);
rysuj();
