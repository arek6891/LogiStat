// Skrypt strony templates/admin_user_options.html (wyniesiony z szablonu 2026-10-16).
async function wyslij(url, method, body) {
    try {
        const res = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: body ? JSON.stringify(body) : undefined
        });
        const data = await res.json();
        if (res.ok) {
            location.reload();
        } else {
            showToast(data.error || 'Błąd.', 'error');
        }
    } catch (err) {
        showToast('Błąd połączenia.', 'error');
    }
}

function addOption(kind) {
    const name = document.getElementById('new_' + kind).value.trim();
    if (!name) {
        showToast('Wpisz nazwę.', 'warning');
        return;
    }
    wyslij('/api/user-options', 'POST', { kind, name });
}

function renameOption(id, current) {
    const name = prompt('Nowa nazwa:', current);
    if (name === null || !name.trim() || name.trim() === current) return;
    wyslij(`/api/user-options/${id}`, 'PUT', { name: name.trim() });
}

function deleteOption(id, name) {
    if (!confirm(`Usunąć pozycję „${name}"?`)) return;
    wyslij(`/api/user-options/${id}`, 'DELETE');
}
