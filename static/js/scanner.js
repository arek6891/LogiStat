// Skrypt strony templates/scanner.html (wyniesiony z szablonu 2026-10-16).
// Dane z serwera: blok <script> w szablonie tuz przed tym plikiem.
const barcodeInput = document.getElementById('barcodeInput');
const scannedList = document.getElementById('scannedList');
const scanCount = document.getElementById('scanCount');
let scanTimer = null;

// Timeout-based barcode detection (EAN-128, no Enter)
barcodeInput.addEventListener('input', () => {
    clearTimeout(scanTimer);
    if (barcodeInput.value.length > 0) {
        barcodeInput.classList.add('scanning');
        scanTimer = setTimeout(() => {
            const barcode = barcodeInput.value.trim();
            if (barcode.length >= 3) {
                processScan(barcode);
            }
            barcodeInput.value = '';
            barcodeInput.classList.remove('scanning');
        }, 300);
    }
});

// Keep focus on input
barcodeInput.addEventListener('blur', () => {
    setTimeout(() => barcodeInput.focus(), 100);
});

// Karta stanowiska bywa otwarta przez noc (sesja 30 dni): po zmianie dnia
// przeladuj — lista i naglowek sa z wczoraj (obecnosc serwer i tak zapisze na dzis).
// Porownanie z dniem ZALADOWANIA wg zegara przegladarki, nie z TODAY serwera:
// tablet ze zla strefa / data nigdy by sie z TODAY nie zgodzil i przeladowywal w kolko.
const DZIEN_ZALADOWANIA = dzisLokalnie();
function nowyDzien() {
    if (dzisLokalnie() === DZIEN_ZALADOWANIA) return false;
    location.reload();
    return true;
}
setInterval(nowyDzien, 60000);

async function processScan(barcode) {
    try {
        const res = await fetch('/api/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                barcode: barcode,
                shift_number: SHIFT_NUMBER
            })
        });
        // Wygasla sesja = przekierowanie na /login (HTML) — bez tego operator
        // myslal, ze skan przeszedl.
        const data = await res.json().catch(() => ({}));

        if (data.already_scanned) {
            showToast(data.warning, 'warning');
            return;
        }
        if (res.ok && data.attendance) {
            showToast(data.message, 'success');
            addScannedCard(data.user, data.attendance);
            scanCount.textContent = parseInt(scanCount.textContent) + 1;
            return;
        }
        showToast(data.error || `Skan NIE został zapisany (błąd ${res.status}) — odśwież stronę i zaloguj się ponownie.`, 'error');
    } catch (err) {
        showToast('Błąd połączenia z serwerem.', 'error');
    }
}

function addScannedCard(user, attendance) {
    const card = document.createElement('div');
    card.className = 'scanned-card';
    card.dataset.id = attendance.id;
    const time = new Date(attendance.scanned_at).toLocaleTimeString('pl');
    card.innerHTML = `
    <div class="user-avatar">${escapeHtml(user.display_name[0] || '')}</div>
    <div class="user-info">
        <div class="user-name">${escapeHtml(user.display_name)}</div>
        <div class="user-time">${time}</div>
    </div>
    ${MOZE_USUWAC ? `<button class="remove-btn" onclick="removeAttendance(${attendance.id})" title="Usuń">✕</button>` : ''}
`;
    scannedList.prepend(card);
}

async function removeAttendance(id) {
    if (!confirm('Usunąć rejestrację?')) return;
    try {
        const res = await fetch(`/api/scan/${id}`, { method: 'DELETE' });
        if (res.ok) {
            document.querySelector(`.scanned-card[data-id="${id}"]`)?.remove();
            scanCount.textContent = Math.max(0, parseInt(scanCount.textContent) - 1);
            showToast('Usunięto rejestrację.', 'info');
            return;
        }
        const data = await res.json().catch(() => ({}));
        showToast(data.error || `Nie usunięto (błąd ${res.status}).`, 'error');
    } catch (err) {
        showToast('Błąd.', 'error');
    }
}
