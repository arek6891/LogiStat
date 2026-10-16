// Skrypt strony templates/admin_country_mapping.html (wyniesiony z szablonu 2026-10-16).
function showAddModal() {
    document.getElementById('modalTitle').textContent = 'Dodaj mapowanie';
    document.getElementById('mappingCountry').value = '';
    document.getElementById('mappingInnenauftrag').value = '';
    document.getElementById('mappingId').value = '';
    document.getElementById('mappingModal').style.display = 'flex';
    document.getElementById('mappingCountry').focus();
}

function editMapping(id, country, innenauftrag) {
    document.getElementById('modalTitle').textContent = 'Edytuj mapowanie';
    document.getElementById('mappingCountry').value = country;
    document.getElementById('mappingInnenauftrag').value = innenauftrag;
    document.getElementById('mappingId').value = id;
    document.getElementById('mappingModal').style.display = 'flex';
    document.getElementById('mappingCountry').focus();
}

function closeModal() {
    document.getElementById('mappingModal').style.display = 'none';
}

function deleteMapping(id, country) {
    document.getElementById('deleteId').value = id;
    document.getElementById('deleteCountryName').textContent = country;
    document.getElementById('deleteModal').style.display = 'flex';
}

function closeDeleteModal() {
    document.getElementById('deleteModal').style.display = 'none';
}

async function saveMapping() {
    const id = document.getElementById('mappingId').value;
    const country = document.getElementById('mappingCountry').value.trim();
    const innenauftrag = document.getElementById('mappingInnenauftrag').value.trim();

    if (!country || !innenauftrag) {
        showToast('Oba pola są wymagane.', 'warning');
        return;
    }

    try {
        let res;
        if (id) {
            res = await fetch(`/api/country-mappings/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ country, innenauftrag })
            });
        } else {
            res = await fetch('/api/country-mappings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ country, innenauftrag })
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

async function confirmDelete() {
    const id = document.getElementById('deleteId').value;
    try {
        const res = await fetch(`/api/country-mappings/${id}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('Usunięto mapowanie.', 'success');
            location.reload();
        } else {
            showToast('Błąd usuwania.', 'error');
        }
    } catch (err) {
        showToast('Błąd połączenia.', 'error');
    }
}

// Close modals on backdrop click
document.getElementById('mappingModal').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeModal();
});
document.getElementById('deleteModal').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeDeleteModal();
});
