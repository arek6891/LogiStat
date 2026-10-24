// Skrypt strony templates/admin_activities.html (wyniesiony z szablonu 2026-10-16).
function showAddModal() {
    document.getElementById('modalTitle').textContent = 'Dodaj czynność';
    document.getElementById('activityName').value = '';
    document.getElementById('activityId').value = '';
    document.getElementById('activityModal').style.display = 'flex';
    document.getElementById('activityName').focus();
}

function editActivity(id, name) {
    document.getElementById('modalTitle').textContent = 'Edytuj czynność';
    document.getElementById('activityName').value = name;
    document.getElementById('activityId').value = id;
    document.getElementById('activityModal').style.display = 'flex';
    document.getElementById('activityName').focus();
}

function closeModal() {
    document.getElementById('activityModal').style.display = 'none';
}

async function saveActivity() {
    const id = document.getElementById('activityId').value;
    const name = document.getElementById('activityName').value.trim();
    if (!name) {
        showToast('Nazwa jest wymagana.', 'warning');
        return;
    }

    try {
        let res;
        if (id) {
            res = await fetch(`/api/activities/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: name })
            });
        } else {
            res = await fetch('/api/activities', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: name })
            });
        }

        if (res.ok) {
            showToast('Zapisano.', 'success');
            location.reload();
        } else {
            const data = await res.json();
            showToast(data.error || 'Błąd.', 'error');
        }
    } catch (err) {
        showToast('Błąd połączenia.', 'error');
    }
}

async function toggleActivity(id, isActive) {
    try {
        const res = await fetch(`/api/activities/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_active: !isActive })
        });
        if (res.ok) {
            showToast(isActive ? 'Dezaktywowano.' : 'Aktywowano.', 'success');
            location.reload();
        } else {
            await pokazBladOdpowiedzi(res);
        }
    } catch (err) {
        showToast('Błąd.', 'error');
    }
}

// Close modal on backdrop click
document.getElementById('activityModal').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeModal();
});
