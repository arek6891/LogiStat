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
