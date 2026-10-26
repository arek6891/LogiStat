// Skrypt strony templates/invoice_specification.html (2026-10-26).
// Dane z serwera: INVOICE = {rok, miesiac, pokaz_ceny, wiersze}. Rok i miesiac
// to te WCZYTANE — autozapis idzie pod nie, nie pod to, co stoi w polach okresu.

const eur = v => v.toLocaleString('pl', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' EUR';

// Puste pole = null (arkusz rozroznia puste od 0); inaczej liczba calkowita >= 0.
function liczbaZPola(pole) {
    const t = pole.value.trim();
    if (t === '') return null;
    return /^\d+$/.test(t) ? parseInt(t, 10) : NaN;
}

function przeliczKwoty() {
    if (!INVOICE.pokaz_ceny) return;
    let suma = 0;
    INVOICE.wiersze.forEach(w => {
        const pole = document.querySelector(`.ilosc-faktury[data-klucz="${w.klucz}"]`);
        const ilosc = pole ? (liczbaZPola(pole) || 0) : (w.ilosc || 0);
        const komorka = document.querySelector(`[data-charge="${w.klucz}"]`);
        if (w.cena === null) { komorka.textContent = '—'; return; }
        suma += ilosc * w.cena;
        komorka.textContent = eur(ilosc * w.cena);
    });
    document.getElementById('totalCharge').textContent = eur(suma);
}

document.querySelectorAll('.ilosc-faktury').forEach(pole => {
    const zapisz = () => {
        const ilosc = liczbaZPola(pole);
        if (Number.isNaN(ilosc)) {
            pole.classList.add('autozapis-blad');
            showToast('Wpisz liczbę całkowitą (albo zostaw puste).', 'error');
            return;
        }
        pole.classList.remove('autozapis-blad');
        przeliczKwoty();
        const body = { rok: INVOICE.rok, miesiac: INVOICE.miesiac, klucz: pole.dataset.klucz, ilosc };
        autoZapis.zaplanuj(`faktura:${body.rok}:${body.miesiac}:${body.klucz}`,
            () => zapiszJson('/api/zwroty/invoice-specification/ilosc', 'PUT', body), [pole]);
    };
    autoZapis.poWpisaniu(pole, zapisz);
});

// Zmiana okresu i eksport dopiero po wypchnieciu zapisow.
document.getElementById('okresFaktury').addEventListener('submit', async e => {
    e.preventDefault();
    if (await autoZapis.przedOpuszczeniem()) e.target.submit();
});
document.querySelectorAll('.js-eksport').forEach(a => a.addEventListener('click', async e => {
    e.preventDefault();
    if (await autoZapis.przedOpuszczeniem()) location.href = a.href;
}));
