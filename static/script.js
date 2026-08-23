let currentUser = null;

document.addEventListener('DOMContentLoaded', async () => {
    // Only run logic if we are on the dashboard
    if (document.getElementById('username-display')) {
        await fetchUser();
        await fetchTokens();

        const addForm = document.getElementById('add-token-form');
        if (addForm) {
            addForm.addEventListener('submit', handleAddToken);
        }
    }
});

async function fetchUser() {
    try {
        const res = await fetch('/api/me');
        if (res.ok) {
            currentUser = await res.json();
            const display = document.getElementById('username-display');
            if (currentUser.is_admin) {
                display.innerHTML = `🛡️ Admin: <b>${currentUser.username}</b>`;
            } else {
                display.innerHTML = `👤 <b>${currentUser.username}</b>`;
            }
        } else {
            window.location.href = '/';
        }
    } catch (e) {
        console.error("Failed to fetch user", e);
    }
}

async function fetchTokens() {
    try {
        const res = await fetch('/api/tokens');
        if (res.ok) {
            const tokens = await res.json();
            renderTokens(tokens);
        }
    } catch (e) {
        console.error("Failed to fetch tokens", e);
    }
}

function renderTokens(tokens) {
    const grid = document.getElementById('tokens-grid');
    grid.innerHTML = '';
    const template = document.getElementById('token-card-template');

    if (tokens.length === 0) {
        grid.innerHTML = '<p style="color: #94a3b8; grid-column: 1/-1; text-align: center; padding: 2rem;">Aucun selfbot configuré. Ajoutez votre premier token ci-dessus !</p>';
        return;
    }

    tokens.forEach((token, index) => {
        const clone = template.content.cloneNode(true);
        const card = clone.querySelector('.token-card');
        card.style.animationDelay = `${index * 0.1}s`;

        clone.querySelector('.t-id').textContent = token.id;
        
        if (currentUser && currentUser.is_admin) {
            const badge = clone.querySelector('.owner-badge');
            badge.classList.remove('hidden');
            clone.querySelector('.t-owner').textContent = token.owner_id;
        }

        const statusSelect = clone.querySelector('.status-select');
        statusSelect.value = token.status;

        const guildInput = clone.querySelector('.guild-input');
        guildInput.value = token.guild_id || '';

        const channelInput = clone.querySelector('.channel-input');
        channelInput.value = token.channel_id || '';

        // Add event listeners
        clone.querySelector('.delete-btn').addEventListener('click', () => handleDelete(token.id));
        
        const updateBtn = clone.querySelector('.update-btn');
        updateBtn.addEventListener('click', (e) => {
            const btn = e.target;
            const originalText = btn.textContent;
            btn.textContent = '...';
            btn.disabled = true;

            const muteChecked = card.querySelector('.mute-checkbox').checked;
            const deafChecked = card.querySelector('.deaf-checkbox').checked;

            handleUpdate(token.id, {
                status: statusSelect.value,
                guild_id: guildInput.value || null,
                channel_id: channelInput.value || null,
                self_mute: muteChecked,
                self_deaf: deafChecked
            }).then(() => {
                btn.textContent = 'Sauvegardé!';
                btn.style.backgroundColor = '#10b981'; // success green
                setTimeout(() => {
                    btn.textContent = originalText;
                    btn.style.backgroundColor = '';
                    btn.disabled = false;
                }, 2000);
            });
        });

        grid.appendChild(clone);
    });
}

async function handleAddToken(e) {
    e.preventDefault();
    const input = document.getElementById('new-token-input');
    const btn = document.getElementById('add-btn');
    const btnText = btn.querySelector('.btn-text');
    const loader = btn.querySelector('.loader');
    const errorDiv = document.getElementById('add-error');

    const tokenValue = input.value.trim();
    if (!tokenValue) return;

    btn.disabled = true;
    btnText.classList.add('hidden');
    loader.classList.remove('hidden');
    errorDiv.textContent = '';

    try {
        const res = await fetch('/api/tokens', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: tokenValue })
        });

        const data = await res.json();

        if (res.ok) {
            input.value = '';
            fetchTokens(); // reload list
        } else {
            errorDiv.textContent = data.detail || 'Erreur inconnue';
        }
    } catch (e) {
        errorDiv.textContent = 'Erreur réseau';
    } finally {
        btn.disabled = false;
        btnText.classList.remove('hidden');
        loader.classList.add('hidden');
    }
}

async function handleUpdate(id, data) {
    try {
        const res = await fetch(`/api/tokens/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!res.ok) {
            console.error("Update failed");
            alert("Erreur lors de la mise à jour");
        }
    } catch (e) {
        console.error("Network error on update", e);
    }
}

async function handleDelete(id) {
    if (!confirm("Voulez-vous vraiment supprimer ce token ?")) return;

    try {
        const res = await fetch(`/api/tokens/${id}`, {
            method: 'DELETE'
        });
        if (res.ok) {
            fetchTokens();
        } else {
            alert("Erreur lors de la suppression");
        }
    } catch (e) {
        console.error("Network error on delete", e);
    }
}
