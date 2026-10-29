// Skrypt strony templates/zwroty_paczek.html (2026-10-27): poprawka i usuniecie
// przyjetego zwrotu przez lidera. Data przyjecia i stanowisko sie nie zmieniaja.
// „➕ Część” (2026-10-29): ten sam formularz dopisuje kolejna czesc paczki (2/2)
// jako nowy wiersz — stanowisko drugiego skanu tego samego numeru nie przyjmie.
const modal = document.getElementById('zwrotModal');
const form = document.getElementById('zwrotForm');
let edytowany = null;
let czesc = false;
let wysylam = false;   // podwojny klik „Zapisz” przy czesci dopisalby dwa wiersze

function zamknij() { modal.style.display = 'none'; }

function wypelnijListe(select, opcje, obecna) {
    select.replaceChildren();
    // Wylaczona w Ustawieniach pozycja, ktora zwrot juz ma, zostaje do wyboru.
    const wszystkie = opcje.includes(obecna) ? opcje : [obecna, ...opcje];
    wszystkie.forEach(n => select.append(new Option(n, n)));
    select.value = obecna;
}

function otworz(b, jakoCzesc) {
    edytowany = JSON.parse(b.dataset.zwrot);
    czesc = jakoCzesc;
    form.querySelectorAll('input').forEach(p => { p.value = edytowany[p.name]; });
    form.querySelectorAll('select[data-lista]').forEach(s =>
        wypelnijListe(s, LISTY_ZWROTOW[s.dataset.lista] || [], edytowany[s.name]));
    form.paketnummer.readOnly = czesc;
    document.getElementById('zwrotTytul').textContent =
        czesc ? `➕ Kolejna część paczki ${edytowany.paketnummer}` : '✎ Popraw zwrot';
    document.getElementById('zwrotCzescInfo').hidden = !czesc;
    modal.style.display = 'flex';
}

document.querySelectorAll('.js-popraw').forEach(b => b.addEventListener('click', () => otworz(b, false)));
document.querySelectorAll('.js-czesc').forEach(b => b.addEventListener('click', () => otworz(b, true)));

document.getElementById('zwrotAnuluj').addEventListener('click', zamknij);
modal.addEventListener('click', e => { if (e.target === modal) zamknij(); });

form.addEventListener('submit', async e => {
    e.preventDefault();
    const body = {};
    form.querySelectorAll('input, select').forEach(p => {
        body[p.name] = p.type === 'number' ? (p.value === '' ? null : Number(p.value)) : p.value;
    });
    body.pos_nummer = (body.pos_nummer || '').toUpperCase();
    if (wysylam) return;
    wysylam = true;
    try {
        if (czesc) {
            await zapiszJson(`/api/zwroty/przyjecie/${edytowany.id}/czesc`, 'POST', body);
            showToast('✓ Dopisano kolejną część', 'success');
        } else {
            await zapiszJson(`/api/zwroty/przyjecie/${edytowany.id}`, 'PUT', body);
            showToast('✓ Zwrot poprawiony', 'success');
        }
        location.reload();
    } catch (err) {
        wysylam = false;
        showToast(err.message, 'error');
    }
});

document.querySelectorAll('.js-usun').forEach(b => b.addEventListener('click', async () => {
    if (!confirm(`Usunąć zwrot ${b.dataset.paket}?\n\nZniknie z raportu, Sorting returns i dashboardu.`)) return;
    try {
        await zapiszJson(`/api/zwroty/przyjecie/${b.dataset.id}`, 'DELETE', {});
        showToast('Zwrot usunięty', 'success');
        location.reload();
    } catch (err) {
        showToast(err.message, 'error');
    }
}));
