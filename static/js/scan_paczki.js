// Skrypt strony templates/scan_paczki.html (wyniesiony z szablonu 2026-10-16).
const TIMEOUT_MS = 300;
const ZAKLADKI = ['start', 'end', 'dok', 'zespol'];
// Zakladki z panelem ilosci (krok 3).
const Z_PANELEM = ['end', 'dok'];
const recent = { start: [], end: [], dok: [], zespol: [] };
// Zadanie w locie per zakladka. Podwojny Enter / powtorny skan wysylal to samo
// kilka razy (15.09 na .31: piec „koniec" jednej paczki w sekunde).
const zajete = { start: false, end: false, dok: false, zespol: false };
// Pracownik potwierdzony w kroku 1 (id z /api/employee-lookup).
const pracownik = { start: null, end: null, dok: null, zespol: null };
// Liczba >= 100 000 w polu ilosci to prawie na pewno zeskanowany kod —
// sprawdza to TabelaIlosci.odczytaj() (i serwer).
// Otwarta paczka per panel: tabela (TabelaIlosci) i kto jeszcze pracuje.
// Pytanie o nadwyzke i „Poinformuj lidera" usuniete 2026-10-15: nadwyzka jest
// zwyklym wpisem w tabeli, a lider widzi ❗ na /paczki i na Dashboardzie.
const paczkaPanelu = { end: null, dok: null };
let pytanieOtwarte = false;

function panelOtwarty(prefix) {
    const lista = prefix ? [prefix] : Z_PANELEM;
    return lista.some(p => {
        const panel = document.getElementById(p + '-qty-panel');
        return !!panel && panel.style.display === 'block';
    });
}

window.addEventListener('beforeunload', (e) => {
    if (panelOtwarty()) { e.preventDefault(); e.returnValue = ''; }
});

function switchTab(name) {
    for (const p of Z_PANELEM) {
        if (!panelOtwarty(p)) continue;
        if (name === p) return;   // juz tu jestesmy — nie kasuj wpisanych ilosci
        const pkg = document.getElementById(p + '-qty-barcode').textContent;
        if (!confirm(`Ilości dla paczki ${pkg} NIE zostały zapisane.\n\n`
                     + 'Przejść mimo to? Wpisane ilości przepadną.')) return;
        anulujKoniec(p);
    }
    document.querySelectorAll('.scan-tab').forEach(t => {
        t.classList.toggle('active', t.dataset.tab === name);
    });
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');

    setTimeout(() => {
        const el = document.getElementById(name + '-emp');
        if (el) { el.value = ''; el.focus(); }
    }, 50);
    resetSteps(name);
}

function resetSteps(prefix) {
    document.getElementById(prefix + '-step1-num').className = 'scan-step-num active';
    document.getElementById(prefix + '-step2-num').className = 'scan-step-num waiting';
    document.getElementById(prefix + '-pkg').disabled = true;
    document.getElementById(prefix + '-emp').disabled = false;
    pracownik[prefix] = null;
    document.getElementById(prefix + '-emp-name').textContent = '';
    if (Z_PANELEM.includes(prefix)) ukryjPanelIlosci(prefix);
}

// ── Panel ilosci (krok 3: koniec / do dokonczenia) ───────────────────────────

function ukryjPanelIlosci(prefix) {
    const panel = document.getElementById(prefix + '-qty-panel');
    if (!panel) return;
    panel.style.display = 'none';
    document.getElementById(prefix + '-qty-tabela').innerHTML = '';
    document.getElementById(prefix + '-qty-inni').innerHTML = '';
    paczkaPanelu[prefix] = null;
}

function wyczyscKroki(prefix) {
    document.getElementById(prefix + '-emp').value = '';
    document.getElementById(prefix + '-pkg').value = '';
    resetSteps(prefix);
    document.getElementById(prefix + '-emp').focus();
}

function anulujKoniec(prefix) { wyczyscKroki(prefix); }

// Zly kod w polu paczki (np. identyfikator) — pracownik zostaje, skanuje paczke jeszcze raz.
function ponowPaczke(prefix) {
    const pkg = document.getElementById(prefix + '-pkg');
    pkg.disabled = false;
    pkg.value = '';
    pkg.focus();
}

// Ten sam warunek co 403/409 w /api/package-time/end|przekaz — sprawdzony
// PRZED wpisaniem ilosci, zeby nie przepadly przy odmowie. Zwraca blad albo null.
function bladWlasciciela(prefix, carton) {
    const ja = pracownik[prefix]?.id;
    const otwarte = (carton.udzialy || []).filter(u => u.otwarty);
    if (otwarte.length) {
        if (!otwarte.some(u => u.user_id === ja)) {
            return 'Nie pracujesz przy tej paczce (pracują: ' + otwarte.map(u => u.user_name).join(', ') + ').';
        }
        const inni = otwarte.filter(u => u.user_id !== ja);
        if (prefix === 'dok' && inni.length) {
            return 'Przy paczce pracują jeszcze: ' + inni.map(u => u.user_name).join(', ')
                + '. Wbij zwykły „Koniec paczki" — zamknie tylko Twój udział.';
        }
        return null;
    }
    if (carton.scan_start_by && ja && carton.scan_start_by !== ja) {
        return `Paczkę rozpoczął ${carton.scan_start_by_name || 'inny pracownik'} — tylko on może ją zakończyć.`;
    }
    return null;
}

// Paczka kilku osob: tylko KTO jeszcze pracuje. Ilosci innych nie pokazujemy
// (operacja 2026-10-15: kazdy deklaruje swoja czesc, rozbieznosc sprawdza lider).
function pokazInnych(prefix, carton, tryb) {
    const ja = pracownik[prefix]?.id;
    const udzialy = carton.udzialy || [];
    const pracuja = udzialy.filter(u => u.otwarty && u.user_id !== ja);
    const box = document.getElementById(prefix + '-qty-inni');
    const linie = [];
    if (tryb === 'zespol') {
        linie.push('👥 Przy paczce pracuje kilka osób — wpisz <strong>tylko swoje</strong> sztuki. '
            + 'Lider porówna sumę wszystkich z ilością w pliku.');
    }
    if (pracuja.length) {
        linie.push('Pracują jeszcze: ' + pracuja.map(u => `<strong>${escapeHtml(u.user_name)}</strong>`).join(', '));
    }
    box.innerHTML = linie.map(l => `<div>${l}</div>`).join('');
    return { pracuja };
}

async function otworzPanelIlosci(prefix) {
    if (zajete[prefix]) return;
    const pkgEl = document.getElementById(prefix + '-pkg');
    const pkg = pkgEl.value.trim();
    if (!pkg) return;
    // Zablokowane pole nie przyjmie kolejnego skanu — wczesniej 28.09 ten sam
    // kod doklejal sie cztery razy i szly cztery zapytania.
    zajete[prefix] = true;
    pkgEl.disabled = true;

    let data;
    try {
        const res = await fetch('/api/package-lookup?barcode=' + encodeURIComponent(pkg));
        data = await res.json();
        if (!res.ok) {
            showResult(prefix, '❌ ' + data.error, 'error');
            if (data.kod_pracownika) ponowPaczke(prefix); else anulujKoniec(prefix);
            return;
        }
    } catch (e) {
        showResult(prefix, '❌ Błąd połączenia.', 'error'); anulujKoniec(prefix); return;
    } finally {
        zajete[prefix] = false;
    }

    const carton = data.carton || {};
    if (carton.finished) {
        showResult(prefix, '❌ Paczka jest już zakończona.', 'error'); anulujKoniec(prefix); return;
    }
    if (!carton.scan_start_at) {
        showResult(prefix, carton.do_dokonczenia
            ? '❌ Paczka czeka na dokończenie — najpierw wbij „Start paczki".'
            : '❌ Brak zarejestrowanego startu dla tej paczki.', 'error');
        anulujKoniec(prefix); return;
    }
    const blad = bladWlasciciela(prefix, carton);
    if (blad) { showResult(prefix, '❌ ' + blad, 'error'); anulujKoniec(prefix); return; }

    // Przekazanie zawsze tworzy udzial osoby → tabela „zespol" (swoje sztuki wprost).
    const tryb = prefix === 'dok' ? 'zespol' : (carton.tryb_tabeli || 'wzor');
    const inni = pokazInnych(prefix, carton, tryb);
    const sztuk = Number.isFinite(carton.stueckzahl) ? carton.stueckzahl : null;
    const tabela = TabelaIlosci.zbuduj(document.getElementById(prefix + '-qty-tabela'), {
        tryb, stueckzahl: sztuk ?? 0, naKoniec: () => zapiszIlosci(prefix),
    });
    paczkaPanelu[prefix] = { barcode: pkg, sztuk, tryb, tabela, pracuja: inni.pracuja };
    document.getElementById(prefix + '-qty-barcode').textContent = pkg;
    document.getElementById(prefix + '-qty-panel').style.display = 'block';
    const pierwsze = tabela.pierwszePole();
    if (pierwsze) pierwsze.focus();
}

function handleKey(event, currentId, nextId, submitFn) {
    if (event.key !== 'Enter') return;
    const val = document.getElementById(currentId).value.trim();
    if (!val) return;

    if (nextId) {
        potwierdzPracownika(currentId.split('-')[0]);
    } else if (submitFn) {
        submitFn();
    }
}

// Krok 1: kod pracownika sprawdzamy od razu. Wczesniej zly kod wychodzil
// dopiero przy zapisie konca — juz po wpisaniu ilosci, ktore wtedy przepadaly.
async function potwierdzPracownika(prefix) {
    if (zajete[prefix]) return;
    const emp = document.getElementById(prefix + '-emp');
    const kod = emp.value.trim();
    if (!kod) return;
    zajete[prefix] = true;
    emp.disabled = true;

    let res = null, data = {};
    try {
        res = await fetch('/api/employee-lookup?barcode=' + encodeURIComponent(kod));
        data = await res.json();
    } catch (e) {
        res = null;
    } finally {
        zajete[prefix] = false;
    }

    if (!res || !res.ok) {
        showResult(prefix, '❌ ' + (data.error || 'Błąd połączenia.'), 'error');
        emp.disabled = false;
        emp.value = '';
        emp.focus();
        return;
    }

    pracownik[prefix] = data.user;
    document.getElementById(prefix + '-emp-name').textContent = '👤 ' + data.user.display_name;
    document.getElementById(prefix + '-step1-num').className = 'scan-step-num done';
    document.getElementById(prefix + '-step2-num').className = 'scan-step-num active';
    ponowPaczke(prefix);
}

function showResult(prefix, msg, type) {
    const el = document.getElementById(prefix + '-result');
    el.textContent = msg;
    el.className = 'result-box ' + type;
    el.style.display = 'block';
    clearTimeout(el._timer);
    el._timer = setTimeout(() => { el.style.display = 'none'; }, type === 'error' ? 6000 : 4000);
}

function addRecent(prefix, barcode, workerName, extraInfo) {
    const arr = recent[prefix];
    arr.unshift({ barcode, workerName, extraInfo, time: new Date().toLocaleTimeString('pl') });
    if (arr.length > 8) arr.pop();

    const listEl = document.getElementById(prefix + '-recent-list');
    const wrapEl = document.getElementById(prefix + '-recent');
    wrapEl.style.display = 'block';
    listEl.innerHTML = arr.map(r => `
        <div class="recent-item">
            <div>
                <span class="barcode">${escapeHtml(r.barcode)}</span>
                <span style="color:var(--text-muted);margin-left:8px;font-size:.8rem;">${escapeHtml(r.workerName)}</span>
                ${r.extraInfo ? `<span style="color:var(--success);margin-left:8px;font-size:.8rem;">${escapeHtml(r.extraInfo)}</span>` : ''}
            </div>
            <span class="time">${r.time}</span>
        </div>`).join('');
}

async function wyslij(url, body) {
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });
    return { res, data: await res.json() };
}

// Start i dolaczenie do zespolu: dwa kroki, bez ilosci.
async function wyslijBezIlosci(prefix, url, opis) {
    if (zajete[prefix]) return;
    const emp = document.getElementById(prefix + '-emp').value.trim();
    const pkgEl = document.getElementById(prefix + '-pkg');
    const pkg = pkgEl.value.trim();
    if (!emp || !pkg) return;
    zajete[prefix] = true;
    pkgEl.disabled = true;

    try {
        const { res, data } = await wyslij(url, { employee_barcode: emp, package_barcode: pkg });
        if (res.ok) {
            showResult(prefix, '✅ ' + data.message, 'success');
            addRecent(prefix, pkg, pracownik[prefix]?.display_name || emp, opis);
        } else {
            showResult(prefix, '❌ ' + data.error, 'error');
            if (data.kod_pracownika) { ponowPaczke(prefix); return; }
        }
    } catch (e) {
        showResult(prefix, '❌ Błąd połączenia.', 'error');
    } finally {
        zajete[prefix] = false;
    }
    wyczyscKroki(prefix);
}

function submitStart() { return wyslijBezIlosci('start', '/api/package-time/start', null); }
function submitDolacz() { return wyslijBezIlosci('zespol', '/api/package-time/dolacz', '👥 dołączył(a)'); }

// Okno z pytaniem → Promise z wybranym przyciskiem albo null (Esc / klik obok).
// Fokus na bezpiecznym przycisku: Enter ze skanera nie wybierze drugiego.
function zapytaj(modalId, przyciski, bezpieczny) {
    const modal = document.getElementById(modalId);
    pytanieOtwarte = true;
    modal.style.display = 'flex';
    document.getElementById(bezpieczny).focus();
    return new Promise(resolve => {
        const koniec = (wynik) => {
            modal.style.display = 'none';
            Object.keys(przyciski).forEach(id => { document.getElementById(id).onclick = null; });
            modal.onclick = modal.onkeydown = null;
            pytanieOtwarte = false;
            resolve(wynik);
        };
        Object.entries(przyciski).forEach(([id, wynik]) => {
            document.getElementById(id).onclick = () => koniec(wynik);
        });
        modal.onclick = (e) => { if (e.target === modal) koniec(null); };
        modal.onkeydown = (e) => { if (e.key === 'Escape') koniec(null); };
    });
}

function przywrocFokus(prefix) {
    const pierwsze = paczkaPanelu[prefix]?.tabela.pierwszePole();
    if (pierwsze) pierwsze.focus();
}

// Krok 3: „Zapisz koniec" (end) albo „Zapisz i przekaz" (dok).
async function zapiszIlosci(prefix) {
    if (zajete[prefix] || pytanieOtwarte) return;
    const emp = document.getElementById(prefix + '-emp').value.trim();
    const pkg = document.getElementById(prefix + '-pkg').value.trim();
    const paczka = paczkaPanelu[prefix];
    if (!emp || !pkg || !paczka) return;

    const odczyt = paczka.tabela.odczytaj();
    if (odczyt.blad) {
        showResult(prefix, '❌ ' + odczyt.blad, 'error');
        if (odczyt.pole) { odczyt.pole.focus(); odczyt.pole.select(); }
        return;
    }
    const moje = odczyt.wyliczone.sztuk;

    const body = { employee_barcode: emp, package_barcode: pkg,
                   tabela: odczyt.tabela, tryb: paczka.tryb };
    if (prefix === 'end' && paczka.pracuja.length) {
        document.getElementById('zespol-pozostali').textContent =
            paczka.pracuja.map(u => u.user_name).join(', ');
        const wybor = await zapytaj('zespolModal',
            { 'zespol-moj': 'moj', 'zespol-wszyscy': 'wszyscy' }, 'zespol-moj');
        if (!wybor) { przywrocFokus(prefix); return; }
        body.zamknij_wszystkich = wybor === 'wszyscy';
    }

    zajete[prefix] = true;
    let res = null, data = {};
    try {
        ({ res, data } = await wyslij(
            prefix === 'dok' ? '/api/package-time/przekaz' : '/api/package-time/end', body));
    } catch (e) {
        // Nie wiemy, czy serwer zapisal — zostawiamy panel, zeby mozna bylo
        // sprobowac ponownie (drugi zapis dostanie 409, nic sie nie zdubluje).
        zajete[prefix] = false;
        showResult(prefix, '❌ Błąd połączenia — zapis NIE jest pewny, spróbuj jeszcze raz.', 'error');
        return;
    }
    zajete[prefix] = false;

    if (res.ok) {
        const secs = data.carton?.processing_seconds;
        let timeStr = '';
        if (prefix === 'end' && data.zamknieta !== false && secs !== null && secs !== undefined) {
            const m = Math.floor(secs / 60), s = secs % 60;
            timeStr = (m > 0 ? m + 'm ' : '') + s + 's';
        }
        const opis = [timeStr ? `⏱ ${timeStr}` : null,
                      moje ? `${moje} szt.` : null,
                      prefix === 'dok' ? '📤 do dokończenia' : null,
                      data.zamknieta === false ? '👥 zespół pracuje dalej' : null]
            .filter(Boolean).join(' · ');
        showResult(prefix, '✅ ' + data.message, 'success');
        addRecent(prefix, pkg, pracownik[prefix]?.display_name || emp, opis || null);
    } else {
        showResult(prefix, '❌ ' + data.error, 'error');
        // Blad w tabeli (np. liczba jak kod, pusta tabela) — zostaw panel z wpisanymi
        // liczbami do poprawy. Inny blad (paczka zamknieta, zmiana skladu) — od nowa.
        if (res.status === 400) { przywrocFokus(prefix); return; }
    }
    wyczyscKroki(prefix);
}
