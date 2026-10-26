// Skrypt strony templates/sorting_data.html (2026-10-26).
// Dane z serwera: SORTING = {rok, licencje: [id licencji nad „Total boxes built”]}.
// Kazda komorka zapisuje sie sama (autozapis, klucz = komorka) pod WCZYTANY rok.

function liczbaZPola(pole) {
    const t = pole.value.trim();
    if (t === '') return null;
    return /^\d+$/.test(t) ? parseInt(t, 10) : NaN;
}

// „Total boxes built” = suma licencji w kolumnie (puste = 0), na zywo.
function przeliczSume(m, pole) {
    let suma = 0;
    SORTING.licencje.forEach(id => {
        const p = document.querySelector(`.sd-pole[data-lic="${id}"][data-m="${m}"][data-pole="${pole}"]`);
        const v = p ? liczbaZPola(p) : null;
        if (v) suma += v;
    });
    const komorka = document.querySelector(`[data-suma="${m}-${pole}"]`);
    if (komorka) komorka.textContent = suma;
}

document.querySelectorAll('.sd-pole').forEach(pole => {
    const zapisz = () => {
        const wartosc = liczbaZPola(pole);
        if (Number.isNaN(wartosc)) {
            pole.classList.add('autozapis-blad');
            showToast('Wpisz liczbę całkowitą (albo zostaw puste).', 'error');
            return;
        }
        pole.classList.remove('autozapis-blad');
        const m = parseInt(pole.dataset.m, 10);
        const body = { rok: SORTING.rok, miesiac: m, pole: pole.dataset.pole, wartosc };
        if (pole.dataset.lic) body.licencja_id = parseInt(pole.dataset.lic, 10);
        if (body.pole !== 'pos_processed') przeliczSume(m, body.pole);
        autoZapis.zaplanuj(`sorting:${body.rok}:${pole.dataset.lic || 'pos'}:${m}:${body.pole}`,
            () => zapiszJson('/api/zwroty/sorting-data', 'PUT', body), [pole]);
    };
    autoZapis.poWpisaniu(pole, zapisz);
});

document.getElementById('okresSorting').addEventListener('submit', async e => {
    e.preventDefault();
    if (await autoZapis.przedOpuszczeniem()) e.target.submit();
});
document.querySelectorAll('.js-eksport').forEach(a => a.addEventListener('click', async e => {
    e.preventDefault();
    if (await autoZapis.przedOpuszczeniem()) location.href = a.href;
}));
