// Skrypt strony templates/admin_licencje_zwrotow.html (2026-10-26).
// Kazda operacja to osobne wywolanie API; po sukcesie strona sie przeladowuje.
// Adres API z `data-api` partiala (2026-10-28: te same listy dla Dekoracji).
const API_LIST = document.querySelector('[data-api]').dataset.api;

async function wyslij(url, method, body, ok) {
    try {
        await zapiszJson(url, method, body);
        if (ok) showToast(ok, 'success');
        location.reload();
    } catch (e) {
        showToast(e.message, 'error');
        return false;
    }
}

document.querySelectorAll('tr[data-id]').forEach(tr => {
    const url = `${API_LIST}/${tr.dataset.id}`;
    tr.querySelectorAll('.js-przesun').forEach(b => b.addEventListener('click', () =>
        wyslij(url, 'PUT', { przesun: parseInt(b.dataset.kierunek, 10) })));
    const nazwa = tr.querySelector('.js-nazwa');
    nazwa.addEventListener('change', async () => {
        if (nazwa.value.trim() === nazwa.dataset.oryginal) return;
        if (await wyslij(url, 'PUT', { nazwa: nazwa.value }) === false) nazwa.value = nazwa.dataset.oryginal;
    });
    tr.querySelector('.js-aktywna').addEventListener('change', e =>
        wyslij(url, 'PUT', { aktywna: e.target.checked }));
    const usun = tr.querySelector('.js-usun');
    if (usun) usun.addEventListener('click', () => {
        if (confirm(`Usunąć „${nazwa.dataset.oryginal}”?`)) wyslij(url, 'DELETE', {});
    });
});

document.querySelectorAll('.js-dodaj').forEach(f => f.addEventListener('submit', e => {
    e.preventDefault();
    wyslij(API_LIST, 'POST', { rodzaj: f.dataset.rodzaj, nazwa: f.nazwa.value });
}));
