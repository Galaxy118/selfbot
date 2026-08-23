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
        const userRes = await fetch('/api/me');
        const user = await userRes.json();
        
        if (user.is_admin) {
            document.getElementById('admin-panel').style.display = 'flex';
            fetchGlobalSettings();
        }

        const res = await fetch('/api/tokens');
        const tokens = await res.json();
        renderTokens(tokens, user);
    } catch (e) {
        console.error("Error fetching data", e);
    }
}

async function fetchGlobalSettings() {
    try {
        const res = await fetch('/api/settings');
        if (res.ok) {
            const data = await res.json();
            const toggle = document.getElementById('global-active-toggle');
            toggle.checked = data.global_active;
            toggle.addEventListener('change', async (e) => {
                const active = e.target.checked;
                await fetch('/api/settings/global_active', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ global_active: active })
                });
            });
        }
    } catch (e) {
        console.error(e);
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
        
        clone.querySelector('.is-active-checkbox').checked = token.is_active;
        clone.querySelector('.join-voice-checkbox').checked = token.join_voice;
        clone.querySelector('.mute-checkbox').checked = token.self_mute;
        clone.querySelector('.deaf-checkbox').checked = token.self_deaf;

        // Add event listeners
        clone.querySelector('.delete-btn').addEventListener('click', () => handleDelete(token.id));
        
        const updateBtn = clone.querySelector('.update-btn');
        updateBtn.addEventListener('click', (e) => {
            const btn = e.target;
            const originalText = btn.textContent;
            btn.textContent = '...';
            btn.disabled = true;

            const activeChecked = card.querySelector('.is-active-checkbox').checked;
            const joinChecked = card.querySelector('.join-voice-checkbox').checked;
            const muteChecked = card.querySelector('.mute-checkbox').checked;
            const deafChecked = card.querySelector('.deaf-checkbox').checked;

            handleUpdate(token.id, {
                status: statusSelect.value,
                guild_id: guildInput.value || null,
                channel_id: channelInput.value || null,
                self_mute: muteChecked,
                self_deaf: deafChecked,
                join_voice: joinChecked,
                is_active: activeChecked
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
