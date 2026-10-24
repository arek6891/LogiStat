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

async function processScan(barcode) {
    try {
        const res = await fetch('/api/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                barcode: barcode,
                shift_number: SHIFT_NUMBER,
                date: TODAY
            })
        });
        const data = await res.json();

        if (res.status === 404) {
            showToast(data.error, 'error');
            return;
        }
        if (data.already_scanned) {
            showToast(data.warning, 'warning');
            return;
        }
        if (res.ok) {
            showToast(data.message, 'success');
            addScannedCard(data.user, data.attendance);
            scanCount.textContent = parseInt(scanCount.textContent) + 1;
        }
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
    <button class="remove-btn" onclick="removeAttendance(${attendance.id})" title="Usuń">✕</button>
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
        }
    } catch (err) {
        showToast('Błąd.', 'error');
    }
}
