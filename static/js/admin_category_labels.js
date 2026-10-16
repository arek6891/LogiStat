// Skrypt strony templates/admin_category_labels.html (wyniesiony z szablonu 2026-10-16).
// Ten sam format co etykieta_kategorii() w app.py: „Polska (English)".
function podglad(pole) {
    const pl = pole.value.trim() || pole.dataset.domyslna;
    const tekst = pl ? `${pl} (${pole.dataset.ang})` : pole.dataset.ang;
    pole.closest('tr').querySelector('.podglad').textContent = tekst;
}

document.querySelectorAll('.nazwa-pl').forEach(pole => {
    podglad(pole);
    pole.addEventListener('input', () => podglad(pole));
    autoZapis.poWpisaniu(pole, () => {
        const kat = pole.dataset.kat;
        const body = { nazwy: { [kat]: pole.value } };
        autoZapis.zaplanuj(`nazwa:${kat}`, () => zapiszJson('/api/category-labels', 'PUT', body), [pole]);
    });
});
