// Skrypt strony templates/admin_przyjecie_zwrotu.html (2026-10-27): napisy ekranow
// Przyjecia zwrotu, autozapis jak nazwy kategorii. Listy przyciskow obsluguje
// admin_licencje_zwrotow.js (te same API co listy Sorting Data).
document.querySelectorAll('.js-etykieta').forEach(pole => {
    autoZapis.poWpisaniu(pole, () => {
        const klucz = pole.dataset.klucz;
        const body = { etykiety: { [klucz]: pole.value } };
        autoZapis.zaplanuj(`etykieta:${klucz}`, () => zapiszJson('/api/zwroty/etykiety', 'PUT', body), [pole]);
    });
});
