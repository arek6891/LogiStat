// Skrypt strony templates/admin_users.html (wyniesiony z szablonu 2026-10-16).
// Search
document.getElementById('userSearch').addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase();
    document.querySelectorAll('.user-row').forEach(row => {
        row.style.display = row.dataset.name.includes(q) ? '' : 'none';
    });
});

// Show/hide password based on role
document.getElementById('userRole').addEventListener('change', () => {
    const role = document.getElementById('userRole').value;
    document.getElementById('passwordGroup').style.display =
        role === 'operator' ? 'none' : 'block';
});

function showAddModal() {
    document.getElementById('modalTitle').textContent = 'Dodaj użytkownika';
    document.getElementById('editUserId').value = '';
    document.getElementById('userUsername').value = '';
    document.getElementById('userDisplayName').value = '';
    document.getElementById('userBarcode').value = '';
    document.getElementById('userRole').value = 'operator';
    document.getElementById('userWorkerType').value = '';
    document.getElementById('userShiftGroup').value = '';
    document.getElementById('userIsTrainer').checked = false;
    ustawCzynnosci([]);
    document.getElementById('userPassword').value = '';
    document.getElementById('passwordGroup').style.display = 'none';
    document.getElementById('userUsername').disabled = false;
    document.getElementById('userModal').style.display = 'flex';
    document.getElementById('userUsername').focus();
}

function ustawCzynnosci(ids) {
    document.querySelectorAll('.czynnosc-szkolenie').forEach(cb => {
        cb.checked = ids.includes(parseInt(cb.value, 10));
    });
}

function zaznaczCzynnosci(tak) {
    document.querySelectorAll('.czynnosc-szkolenie').forEach(cb => { cb.checked = tak; });
}

function editUser(id, user, czynnosci) {
    document.getElementById('modalTitle').textContent = 'Edytuj użytkownika';
    document.getElementById('editUserId').value = id;
    document.getElementById('userUsername').value = user.username;
    document.getElementById('userDisplayName').value = user.display_name;
    document.getElementById('userBarcode').value = user.barcode_id || '';
    document.getElementById('userRole').value = user.role;
    document.getElementById('userWorkerType').value = user.worker_type_id || '';
    document.getElementById('userShiftGroup').value = user.shift_group_id || '';
    document.getElementById('userIsTrainer').checked = !!user.is_trainer;
    ustawCzynnosci(czynnosci || []);
    document.getElementById('userPassword').value = '';
    document.getElementById('passwordGroup').style.display =
        user.role === 'operator' ? 'none' : 'block';
    document.getElementById('userUsername').disabled = true;
    document.getElementById('userModal').style.display = 'flex';
}

function closeModal() {
    document.getElementById('userModal').style.display = 'none';
}

async function saveUser() {
    const id = document.getElementById('editUserId').value;
    const payload = {
        username: document.getElementById('userUsername').value.trim(),
        display_name: document.getElementById('userDisplayName').value.trim(),
        barcode_id: document.getElementById('userBarcode').value.trim(),
        role: document.getElementById('userRole').value,
        worker_type_id: document.getElementById('userWorkerType').value || null,
        shift_group_id: document.getElementById('userShiftGroup').value || null,
        is_trainer: document.getElementById('userIsTrainer').checked,
        czynnosci: [...document.querySelectorAll('.czynnosc-szkolenie:checked')]
            .map(cb => parseInt(cb.value, 10)),
        password: document.getElementById('userPassword').value
    };

    if (!payload.username || !payload.display_name) {
        showToast('Login i nazwa wyświetlana są wymagane.', 'warning');
        return;
    }

    try {
        let res;
        if (id) {
            res = await fetch(`/api/users/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        } else {
            res = await fetch('/api/users', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        }

        const data = await res.json();
        if (res.ok) {
            showToast('Zapisano.', 'success');
            location.reload();
        } else {
            showToast(data.error || 'Błąd.', 'error');
        }
    } catch (err) {
        showToast('Błąd połączenia.', 'error');
    }
}

async function deactivateUser(id) {
    if (!confirm('Dezaktywować użytkownika?')) return;
    try {
        const res = await fetch(`/api/users/${id}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('Dezaktywowano.', 'success');
            location.reload();
        } else {
            await pokazBladOdpowiedzi(res, 'Nie dezaktywowano');
        }
    } catch (err) {
        showToast('Błąd.', 'error');
    }
}

async function activateUser(id) {
    try {
        const res = await fetch(`/api/users/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_active_user: true })
        });
        if (res.ok) {
            showToast('Aktywowano.', 'success');
            location.reload();
        } else {
            await pokazBladOdpowiedzi(res, 'Nie aktywowano');
        }
    } catch (err) {
        showToast('Błąd.', 'error');
    }
}

// Close modal on backdrop click
document.getElementById('userModal').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeModal();
});
