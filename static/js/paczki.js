// Skrypt strony templates/paczki.html (wyniesiony z szablonu 2026-10-16).
// Dane z serwera: blok <script> w szablonie tuz przed tym plikiem.
// ── Filtry: status „Zrobione" / „Wszystkie" wymaga zakresu dat ────────────
// Bez daty ten widok obejmowałby całą historię paczek. Serwer i tak odrzuci
// taki zestaw (ręcznie sklejony URL), ale tu zatrzymujemy go zanim strona
// się przeładuje i pokazujemy, czego brakuje.
(function () {
    const form = document.getElementById('filtryPaczek');
    if (!form) return;
    const status = document.getElementById('fpStatus');
    const od = document.getElementById('fpDateFrom');
    const doo = document.getElementById('fpDateTo');

    function brakujeDaty() {
        // Niezrobione i Do dokonczenia to male zbiory — bez wymaganego zakresu.
        return !['niezrobione', 'do_dokonczenia'].includes(status.value) && !od.value && !doo.value;
    }

    function odswiezPodpowiedz() {
        const brak = brakujeDaty();
        [od, doo].forEach(p => p.style.outline = brak ? '2px solid var(--danger)' : '');
    }

    form.addEventListener('submit', function (e) {
        if (brakujeDaty()) {
            e.preventDefault();
            odswiezPodpowiedz();
            od.focus();
            alert('Status „Zrobione" / „Wszystkie" — ustaw datę „od" lub „do".\n\n'
                + 'Bez zakresu dat widok objąłby całą historię paczek.');
        }
    });

    [status, od, doo].forEach(p => p.addEventListener('change', odswiezPodpowiedz));
    odswiezPodpowiedz();
})();

// ── Dodawanie / edycja paczki ręcznie ─────────────────────────────────────
let editingCartonId = null;   // null = tryb dodawania, id = tryb edycji
let editingScanned = false;   // czy edytowana paczka ma czasy skanowania

function openAddPackage() {
    editingCartonId = null;
    editingScanned = false;
    document.getElementById('apModalTitle').textContent = '➕ Dodaj paczkę ręcznie';
    document.getElementById('apSubmitBtn').textContent = 'Dodaj paczkę';
    document.getElementById('apBarcode').value = '';
    document.getElementById('apStueckzahl').value = '';
    document.getElementById('apLand').value = '';
    document.getElementById('apZielDatum').value = '';
    document.getElementById('apDataPliku').value = DZIS;
    document.getElementById('apUebergabe').value = '';
    document.getElementById('apKategorie').value = '';
    document.getElementById('apDoubleRate').checked = false;
    document.getElementById('addPackageModal').style.display = 'flex';
    setTimeout(() => document.getElementById('apBarcode').focus(), 50);
}
function openEditPackage(btn) {
    const d = btn.dataset;
    editingCartonId = parseInt(d.id, 10);
    editingScanned = d.scanned === '1';
    document.getElementById('apModalTitle').textContent = '✎ Edytuj paczkę';
    document.getElementById('apSubmitBtn').textContent = 'Zapisz zmiany';
    document.getElementById('apBarcode').value = d.barcode || '';
    document.getElementById('apStueckzahl').value = d.stueckzahl || '';
    document.getElementById('apLand').value = d.land || '';
    document.getElementById('apZielDatum').value = d.ziel || '';
    document.getElementById('apDataPliku').value = d.plik || '';
    document.getElementById('apUebergabe').value = d.uebergabe || '';
    document.getElementById('apKategorie').value = d.kategorie || '';
    document.getElementById('apDoubleRate').checked = d.double === '1';
    document.getElementById('addPackageModal').style.display = 'flex';
    setTimeout(() => document.getElementById('apBarcode').focus(), 50);
}
function closeAddPackage() {
    document.getElementById('addPackageModal').style.display = 'none';
    editingCartonId = null;
}
document.getElementById('addPackageModal').addEventListener('click', function(e) {
    if (e.target === this) closeAddPackage();
});
// Skaner EAN-128 kończy skan Enterem — nie pozwól mu wysłać/zamknąć modala,
// przenieś focus na kolejne pole zamiast tego.
document.getElementById('addPackageModal').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') {
        e.preventDefault();
        const order = ['apBarcode', 'apStueckzahl', 'apLand', 'apDataPliku', 'apZielDatum', 'apUebergabe', 'apKategorie'];
        const idx = order.indexOf(e.target.id);
        if (idx >= 0 && idx < order.length - 1) {
            document.getElementById(order[idx + 1]).focus();
        }
    }
});

async function submitAddPackage() {
    const payload = {
        barcode: document.getElementById('apBarcode').value.trim(),
        stueckzahl: parseInt(document.getElementById('apStueckzahl').value, 10),
        land: document.getElementById('apLand').value,
        ziel_datum: document.getElementById('apZielDatum').value,
        data_pliku: document.getElementById('apDataPliku').value,
        uebergabe_nr: document.getElementById('apUebergabe').value.trim(),
        kategorie: document.getElementById('apKategorie').value.trim(),
        double_rate: document.getElementById('apDoubleRate').checked,
    };

    // Walidacja po stronie klienta (serwer i tak waliduje)
    if (!payload.barcode) { showToast('Podaj barcode.', 'error'); return; }
    if (!payload.stueckzahl || payload.stueckzahl <= 0) { showToast('Podaj ilość (Stückzahl) > 0.', 'error'); return; }
    if (!payload.land) { showToast('Wybierz kraj (Land).', 'error'); return; }
    if (!payload.data_pliku) { showToast('Podaj Loading date.', 'error'); return; }
    if (!payload.uebergabe_nr) { showToast('Podaj Übergabe Nr.', 'error'); return; }

    // Ostrzeżenie przy edycji paczki z zarejestrowanymi czasami skanowania
    if (editingCartonId && editingScanned) {
        if (!confirm('Ta paczka ma już zarejestrowany start/koniec skanowania. Edytować mimo to?')) {
            return;
        }
    }

    const isEdit = editingCartonId != null;
    const url = isEdit ? `/api/packages/${editingCartonId}` : '/api/packages';
    const method = isEdit ? 'PUT' : 'POST';

    const btn = document.getElementById('apSubmitBtn');
    btn.disabled = true;
    try {
        const res = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            showToast(data.error || 'Błąd zapisu paczki.', 'error');
            return;
        }
        showToast(data.message || (isEdit ? 'Zapisano paczkę.' : 'Dodano paczkę.'), 'success');
        closeAddPackage();
        setTimeout(() => location.reload(), 800);
    } catch {
        showToast('Błąd połączenia.', 'error');
    } finally {
        btn.disabled = false;
    }
}

// ── Przepisanie pracownika ────────────────────────────────────────────────
let reassignCartonId = null;

function openReassign(cartonId, barcode, currentUserId) {
    reassignCartonId = cartonId;
    document.getElementById('reassignBarcode').textContent = barcode;
    const sel = document.getElementById('reassignUser');
    sel.value = currentUserId || '';
    document.getElementById('reassignModal').style.display = 'flex';
}
function closeReassign() {
    document.getElementById('reassignModal').style.display = 'none';
    reassignCartonId = null;
}
async function confirmReassign() {
    if (!reassignCartonId) return;
    const userId = document.getElementById('reassignUser').value;
    try {
        const res = await fetch(`/api/packages/${reassignCartonId}/assign`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId ? parseInt(userId) : null })
        });
        if (!res.ok) { showToast('Błąd zapisu.', 'error'); return; }
        showToast('Przepisano pomyślnie.', 'success');
        closeReassign();
        setTimeout(() => location.reload(), 800);
    } catch { showToast('Błąd połączenia.', 'error'); }
}
document.getElementById('reassignModal').addEventListener('click', function(e) {
    if (e.target === this) closeReassign();
});

async function odblokujPaczke(btn) {
    const id = btn.dataset.id;
    const barcode = btn.dataset.barcode;
    if (!confirm(`Odblokować paczkę ${barcode}?\n\nStart skanu zostanie skasowany — paczka wróci do stanu „nierozpoczęta" i każdy pracownik będzie mógł ją zeskanować od nowa. Zapisany czas rozpoczęcia przepadnie.`)) return;
    btn.disabled = true;
    try {
        const res = await fetch(`/api/packages/${id}/unlock-scan`, { method: 'POST' });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { showToast(data.error || 'Błąd odblokowania.', 'error'); btn.disabled = false; return; }
        showToast(data.message || 'Odblokowano.', 'success');
        setTimeout(() => location.reload(), 600);
    } catch {
        showToast('Błąd połączenia.', 'error');
        btn.disabled = false;
    }
}

// Paczka zespolowa, w ktorej ktos nie wbil konca (poszedl do domu).
async function zamknijZespol(btn) {
    if (!confirm(`Zamknąć paczkę ${btn.dataset.barcode}?\n\nNie wbili końca: ${btn.dataset.otwarci}.\n`
                 + 'Skończą teraz, BEZ swoich ilości (i bez liczenia do norm).')) return;
    btn.disabled = true;
    try {
        const res = await fetch(`/api/packages/${btn.dataset.id}/zamknij-zespol`, { method: 'POST' });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { showToast(data.error || 'Błąd zamykania.', 'error'); btn.disabled = false; return; }
        showToast(data.message || 'Zamknięto.', 'success');
        setTimeout(() => location.reload(), 600);
    } catch {
        showToast('Błąd połączenia.', 'error');
        btn.disabled = false;
    }
}

async function toggleCartonDoubleRate(cartonId, checkbox) {
    const val = checkbox.checked;
    checkbox.disabled = true;
    try {
        const res = await fetch(`/api/packages/${cartonId}/double-rate`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ double_rate: val })
        });
        if (!res.ok) { throw new Error(); }
        showToast(val ? 'Oznaczono jako double rate.' : 'Usunięto double rate.', 'success');
    } catch {
        checkbox.checked = !val;  // rollback
        showToast('Błąd zapisu double rate.', 'error');
    } finally {
        checkbox.disabled = false;
    }
}

// ── Korekta ilosci per kategoria ────────────────────────────────────────────

let qtyKartonId = null;

function qtyPola() {
    return Array.from(document.querySelectorAll('#qtyRows input[data-kategoria]'));
}

function qtyPrzelicz() {
    const suma = qtyPola().reduce((a, i) => a + (parseInt(i.value, 10) || 0), 0);
    document.getElementById('qtySuma').textContent = suma;
}

function otworzQty(btn) {
    if (btn.dataset.edytor && btn.dataset.edytor !== 'stary') return otworzTabele(btn);
    qtyKartonId = btn.dataset.id;
    document.getElementById('qtyBarcode').textContent = btn.dataset.barcode;
    document.getElementById('qtyStueck').textContent = btn.dataset.stueckzahl;
    // Kto wpisal ilosci = kto zakonczyl paczke (krok 3 przy koncu).
    const kto = document.getElementById('qtyKto');
    let udzialy = [];
    try { udzialy = JSON.parse(btn.dataset.udzialy || '[]'); } catch { udzialy = []; }
    if (udzialy.length) {
        // Paczka kilku osob: pola pokazuja SUME, tu rozbicie — poprawka zmienia sume.
        kto.textContent = 'Wpisali: ' + udzialy.map(u =>
            `${u.kto} ${u.otwarty ? '(pracuje)' : u.suma + ' szt.'}`).join(' · ')
            + (btn.dataset.koniec ? ` · koniec ${btn.dataset.koniec}` : ' · paczka niezakończona');
    } else {
        kto.textContent = btn.dataset.koniec
            ? `Wpisał(a): ${btn.dataset.kto || '—'} · koniec ${btn.dataset.koniec}`
            : 'Paczka niezakończona — pracownik jeszcze nic nie wpisał.';
    }
    document.getElementById('qtyBlad').style.display = 'none';

    let biezace = {};
    try { biezace = JSON.parse(btn.dataset.cats || '{}'); } catch { biezace = {}; }
    qtyPola().forEach(i => { i.value = biezace[i.dataset.kategoria] || ''; });
    qtyPrzelicz();

    document.getElementById('qtyModal').style.display = 'flex';
    const pierwsze = qtyPola()[0];
    if (pierwsze) pierwsze.focus();
}

function zamknijQty() {
    document.getElementById('qtyModal').style.display = 'none';
    qtyKartonId = null;
}

async function zapiszQty() {
    if (!qtyKartonId) return;
    const categories = {};
    qtyPola().forEach(i => {
        const n = parseInt(i.value, 10);
        if (n > 0) categories[i.dataset.kategoria] = n;
    });

    try {
        const res = await fetch(`/api/packages/${qtyKartonId}/categories`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ categories })
        });
        const data = await res.json();
        if (!res.ok) {
            const el = document.getElementById('qtyBlad');
            el.textContent = data.error || 'Błąd zapisu.';
            el.style.display = 'block';
            return;
        }
        zamknijQty();
        showToast('Ilości zapisane — rozliczenie przeliczone.', 'success');
        setTimeout(() => location.reload(), 700);
    } catch {
        const el = document.getElementById('qtyBlad');
        el.textContent = 'Błąd połączenia.';
        el.style.display = 'block';
    }
}

document.addEventListener('input', e => {
    if (e.target.matches('#qtyRows input[data-kategoria]')) qtyPrzelicz();
});

// ── Tabela ilosci (paczki od 2026-10-15) ────────────────────────────────────

let tab = null;   // {kartonId, edytor, stueckzahl, udzialy, komponent}

function zbudujTabele() {
    const kontener = document.getElementById('tabTabela');
    let wartosci = null, tryb = 'wzor';
    if (tab.edytor === 'zespol') {
        tryb = 'zespol';
        const id = parseInt(document.getElementById('tabOsoba').value, 10);
        const u = tab.udzialy.find(x => x.id === id);
        wartosci = u ? u.tabela : null;
    } else {
        wartosci = tab.tabela;
    }
    tab.komponent = TabelaIlosci.zbuduj(kontener, {
        tryb, stueckzahl: tab.stueckzahl, wartosci, naKoniec: zapiszTabele,
    });
}

function otworzTabele(btn) {
    let udzialy = [], tabela = null;
    try { udzialy = JSON.parse(btn.dataset.udzialy || '[]'); } catch { udzialy = []; }
    try { tabela = JSON.parse(btn.dataset.tabela || 'null'); } catch { tabela = null; }
    tab = { kartonId: btn.dataset.id, edytor: btn.dataset.edytor,
            stueckzahl: parseInt(btn.dataset.stueckzahl, 10) || 0, udzialy, tabela };
    document.getElementById('tabBarcode').textContent = btn.dataset.barcode;
    document.getElementById('tabStueck').textContent = tab.stueckzahl;
    document.getElementById('tabBlad').style.display = 'none';

    const kto = document.getElementById('tabKto');
    const wiersz = document.getElementById('tabOsobaWiersz');
    const zapisz = document.getElementById('tabZapisz');
    zapisz.disabled = false;
    if (tab.edytor === 'zespol') {
        // Kazda osoba wpisala swoje sztuki — lider poprawia jedna osobe naraz.
        const zamkniete = udzialy.filter(u => !u.otwarty);
        const sel = document.getElementById('tabOsoba');
        sel.innerHTML = zamkniete.map(u =>
            `<option value="${u.id}">${escapeHtml(u.kto)} — ${u.bez_ilosci ? 'bez ilości' : u.sztuki + ' szt.'}</option>`).join('');
        const razem = zamkniete.reduce((a, u) => a + (u.sztuki || 0), 0);
        document.getElementById('tabOsoby').textContent =
            `Razem wpisano ${razem} szt. przy ${tab.stueckzahl} w pliku.`
            + (udzialy.some(u => u.otwarty) ? ' Część osób jeszcze pracuje.' : '');
        wiersz.style.display = zamkniete.length ? 'block' : 'none';
        kto.textContent = btn.dataset.koniec ? `Paczka kilku osób · koniec ${btn.dataset.koniec}`
                                             : 'Paczka kilku osób · niezakończona';
        if (!zamkniete.length) {
            document.getElementById('tabTabela').innerHTML =
                '<p style="color:var(--text-muted);">Nikt jeszcze nie wpisał swoich ilości.</p>';
            zapisz.disabled = true;
            document.getElementById('tabelaModal').style.display = 'flex';
            return;
        }
        sel.onchange = zbudujTabele;
    } else {
        wiersz.style.display = 'none';
        kto.textContent = btn.dataset.koniec
            ? `Wpisał(a): ${btn.dataset.kto || '—'} · koniec ${btn.dataset.koniec}`
            : 'Paczka niezakończona — pracownik jeszcze nic nie wpisał.';
    }
    zbudujTabele();
    document.getElementById('tabelaModal').style.display = 'flex';
    const pierwsze = tab.komponent.pierwszePole();
    if (pierwsze) pierwsze.focus();
}

function zamknijTabele() {
    document.getElementById('tabelaModal').style.display = 'none';
    tab = null;
}

async function zapiszTabele() {
    if (!tab || !tab.komponent) return;
    const blad = document.getElementById('tabBlad');
    const odczyt = tab.komponent.odczytaj();
    if (odczyt.blad) {
        blad.textContent = odczyt.blad;
        blad.style.display = 'block';
        if (odczyt.pole) odczyt.pole.focus();
        return;
    }
    const body = { tabela: odczyt.tabela };
    if (tab.edytor === 'zespol') body.udzial_id = parseInt(document.getElementById('tabOsoba').value, 10);
    try {
        const res = await fetch(`/api/packages/${tab.kartonId}/tabela`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const data = await res.json();
        if (!res.ok) {
            blad.textContent = data.error || 'Błąd zapisu.';
            blad.style.display = 'block';
            return;
        }
        zamknijTabele();
        showToast('Ilości zapisane — rozliczenie przeliczone.', 'success');
        setTimeout(() => location.reload(), 700);
    } catch {
        blad.textContent = 'Błąd połączenia.';
        blad.style.display = 'block';
    }
}

async function potwierdzRoznice(btn) {
    if (!confirm(`Potwierdzić różnicę w paczce ${btn.dataset.barcode}?\n\n`
                 + 'Wykrzyknik zniknie, a na liście zostanie, kto i kiedy potwierdził.')) return;
    btn.disabled = true;
    try {
        const res = await fetch(`/api/packages/${btn.dataset.id}/potwierdz-roznice`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) {
            showToast(data.error || 'Błąd potwierdzenia.', 'error');
            btn.disabled = false;
            return;
        }
        showToast('Różnica potwierdzona.', 'success');
        setTimeout(() => location.reload(), 600);
    } catch {
        showToast('Błąd połączenia.', 'error');
        btn.disabled = false;
    }
}
