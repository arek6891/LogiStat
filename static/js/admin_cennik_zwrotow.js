// Skrypt strony templates/admin_cennik_zwrotow.html (2026-10-26).
// Jak Cennik kategorii: zapis i kopiowanie ida pod WCZYTANY miesiac
// (wczytanyRok / wczytanyMiesiac), nie pod to, co stoi na listach.

const pola = [...document.querySelectorAll('.cena-pole')];
let wczytanyRok = null;
let wczytanyMiesiac = null;

// Nic nie wczytane = nic do stracenia (inaczej pierwsze wczytanie pytalo o zmiany).
const zmienione = () => wczytanyRok !== null && pola.some(p => p.value !== p.dataset.oryginal);
function odswiezZnacznik() {
    document.getElementById('cenyZmienione').style.display = zmienione() ? '' : 'none';
    pola.forEach(p => p.style.borderColor = wczytanyRok !== null && p.value !== p.dataset.oryginal ? 'var(--warning)' : '');
}
pola.forEach(p => p.addEventListener('input', odswiezZnacznik));
window.addEventListener('beforeunload', e => {
    if (zmienione()) { e.preventDefault(); e.returnValue = ''; }
});

function wpiszCeny(ceny, jakoOryginal) {
    pola.forEach(p => {
        const v = ceny[p.dataset.klucz];
        p.value = (v === undefined || v === null) ? '' : Number(v).toFixed(2);
        if (jakoOryginal) p.dataset.oryginal = p.value;
    });
    odswiezZnacznik();
}

async function pobierzCeny(rok, miesiac) {
    const res = await fetch(`/api/zwroty/cennik/${rok}/${miesiac}`);
    const dane = res.ok ? await res.json().catch(() => null) : null;
    if (!dane || typeof dane !== 'object') throw new Error(`Nie udało się wczytać cen (błąd ${res.status}).`);
    return dane;
}

async function wczytaj() {
    const rokPole = document.getElementById('rokCen');
    const miesiacPole = document.getElementById('miesiacCen');
    if (zmienione() && !confirm('Ceny tego miesiąca mają niezapisane zmiany.\n\nWczytać inny miesiąc i je porzucić?')) {
        rokPole.value = wczytanyRok;
        miesiacPole.value = wczytanyMiesiac;
        return;
    }
    const rok = parseInt(rokPole.value, 10);
    const miesiac = parseInt(miesiacPole.value, 10);
    // Bez wczytanych cen nie ma formularza — zapis zer po bledzie nadpisalby miesiac.
    pola.forEach(p => p.disabled = true);
    ['zapiszCeny', 'kopiujCeny'].forEach(id => document.getElementById(id).disabled = true);
    wczytanyRok = wczytanyMiesiac = null;
    try {
        wpiszCeny(await pobierzCeny(rok, miesiac), true);
    } catch (e) {
        showToast(e.message, 'error');
        return;
    }
    wczytanyRok = rok;
    wczytanyMiesiac = miesiac;
    pola.forEach(p => p.disabled = false);
    ['zapiszCeny', 'kopiujCeny'].forEach(id => document.getElementById(id).disabled = false);
    document.getElementById('cenyOkres').textContent = `(${String(miesiac).padStart(2, '0')}/${rok})`;
}

async function zapisz() {
    if (!wczytanyRok) return;
    const ceny = {};
    for (const p of pola) {
        const t = p.value.trim();
        if (t !== '' && !(parseFloat(t) >= 0)) { showToast('Cena musi być liczbą ≥ 0 albo pusta.', 'error'); return; }
        ceny[p.dataset.klucz] = t === '' ? null : parseFloat(t);
    }
    try {
        wpiszCeny(await zapiszJson(`/api/zwroty/cennik/${wczytanyRok}/${wczytanyMiesiac}`, 'PUT', { ceny }), true);
        showToast(`Ceny ${String(wczytanyMiesiac).padStart(2, '0')}/${wczytanyRok} zapisane.`, 'success');
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function kopiuj() {
    if (!wczytanyRok) return;
    let rok = wczytanyRok, miesiac = wczytanyMiesiac - 1;
    if (miesiac === 0) { miesiac = 12; rok -= 1; }
    try {
        const ceny = await pobierzCeny(rok, miesiac);
        if (!Object.keys(ceny).length) { showToast('Poprzedni miesiąc nie ma cen.', 'warning'); return; }
        wpiszCeny(ceny, false);
        showToast(`Skopiowano ceny z ${String(miesiac).padStart(2, '0')}/${rok} — kliknij „Zapisz”.`, 'info');
    } catch (e) {
        showToast(e.message, 'error');
    }
}

document.getElementById('pokazCeny').addEventListener('click', wczytaj);
document.getElementById('zapiszCeny').addEventListener('click', zapisz);
document.getElementById('kopiujCeny').addEventListener('click', kopiuj);
wczytaj();
