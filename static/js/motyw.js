// Skrypt strony templates/base.html (wyniesiony z szablonu 2026-10-16).
// Kolor motywu dla wykresow (Chart.js rysuje na canvasie i nie rozumie
// `var(--x)`). motyw('--accent') → '#8bc640', motyw('--accent', .45)
// → 'rgb(139 198 64 / 0.45)' (z tokenu `--accent-rgb`). W <head>, bo
// czesc stron ma skrypt w bloku content, przed skryptem base.html.
function motyw(nazwa, alfa) {
    const css = getComputedStyle(document.documentElement);
    if (alfa === undefined) return css.getPropertyValue(nazwa).trim();
    return `rgb(${css.getPropertyValue(nazwa + '-rgb').trim()} / ${alfa})`;
}

// Tryb ciemny (2026-10-22): wybor per przegladarka w localStorage, ustawiany
// tutaj — w <head>, przed narysowaniem strony — zeby nie mignal jasny motyw.
// Kolory: `:root[data-motyw="ciemny"]` w style.css. localStorage moze rzucic
// (tryb prywatny, zablokowane dane) — wtedy zostaje jasny, bez bledu.
const KLUCZ_MOTYWU = 'logistat-motyw';

function ustawMotyw(nazwa) {
    if (nazwa === 'ciemny') document.documentElement.dataset.motyw = 'ciemny';
    else delete document.documentElement.dataset.motyw;
    const przycisk = document.getElementById('przelacznikMotywu');
    if (!przycisk) return;
    const opis = nazwa === 'ciemny' ? 'Tryb jasny' : 'Tryb ciemny';
    przycisk.textContent = nazwa === 'ciemny' ? '☀️' : '🌙';
    przycisk.title = opis;
    przycisk.setAttribute('aria-label', opis);
}

function przelaczMotyw() {
    const nowy = document.documentElement.dataset.motyw === 'ciemny' ? 'jasny' : 'ciemny';
    try { localStorage.setItem(KLUCZ_MOTYWU, nowy); } catch (e) { /* bez zapamietania */ }
    ustawMotyw(nowy);
    // Wykresy (Chart.js) czytaja kolory przy rysowaniu — strony z wykresami
    // moga nasluchiwac i przerysowac; inaczej nowe kolory wejda przy odswiezeniu.
    document.dispatchEvent(new CustomEvent('zmiana-motywu'));
}

(function () {
    let zapisany = null;
    try { zapisany = localStorage.getItem(KLUCZ_MOTYWU); } catch (e) { /* jasny */ }
    ustawMotyw(zapisany);
    document.addEventListener('DOMContentLoaded', () => ustawMotyw(document.documentElement.dataset.motyw));
})();
