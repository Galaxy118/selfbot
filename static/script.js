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

        // Auto-polling for connection status (every 5 seconds)
        setInterval(async () => {
            try {
                const res = await fetch('/api/tokens');
                if (res.ok) {
                    const tokens = await res.json();
                    tokens.forEach(token => {
                        const card = document.getElementById(`token-card-${token.id}`);
                        if (card) {
                            const connBadge = card.querySelector('.connection-status-badge');
                            if (connBadge) {
                                if (token.is_connected) {
                                    connBadge.textContent = '🟢 Connecté';
                                    connBadge.style.backgroundColor = 'rgba(50, 215, 75, 0.15)';
                                    connBadge.style.color = 'var(--accent-success)';
                                    connBadge.style.border = '1px solid rgba(50, 215, 75, 0.3)';
                                } else {
                                    connBadge.textContent = '🔴 Déconnecté';
                                    connBadge.style.backgroundColor = 'rgba(255, 69, 58, 0.15)';
                                    connBadge.style.color = 'var(--accent-error)';
                                    connBadge.style.border = '1px solid rgba(255, 69, 58, 0.3)';
                                }
                            }
                        }
                    });
                }
            } catch (e) {
                console.error("Erreur lors de l'actualisation des statuts", e);
            }
        }, 5000);
    }
});

async function fetchUser() {
    try {
        const res = await fetch('/api/me');
        if (res.ok) {
            currentUser = await res.json();
            const display = document.getElementById('username-display');
            if (currentUser.is_admin) {
                display.innerHTML = `🛡️ Admin: <b></b>`;
                display.querySelector('b').textContent = currentUser.username;
            } else {
                display.innerHTML = `👤 <b></b>`;
                display.querySelector('b').textContent = currentUser.username;
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

    if (!currentUser.is_admin) {
        grid.classList.add('single-mode');
    } else {
        grid.classList.remove('single-mode');
    }

    if (tokens.length === 0) {
        grid.innerHTML = '<p style="color: #94a3b8; grid-column: 1/-1; text-align: center; padding: 2rem;">Aucun selfbot configuré. Ajoutez votre premier token ci-dessus !</p>';
    }

    const addSection = document.querySelector('.add-token-section');
    if (addSection) {
        if (!currentUser.is_admin && tokens.length >= 1) {
            addSection.style.display = 'none';
        } else {
            addSection.style.display = 'block';
        }
    }

    if (tokens.length === 0) return;

    tokens.forEach((token, index) => {
        const clone = template.content.cloneNode(true);
        const card = clone.querySelector('.token-card');
        card.id = `token-card-${token.id}`;
        card.style.animationDelay = `${index * 0.1}s`;

        const title = clone.querySelector('.token-id-display');
        title.innerHTML = '';
        if (token.bot_username && token.bot_username !== "Unknown") {
            title.appendChild(document.createTextNode('👤 '));
            
            const spanUsername = document.createElement('span');
            spanUsername.textContent = token.bot_username;
            title.appendChild(spanUsername);
            
            const spanId = document.createElement('span');
            spanId.style.fontSize = '0.8rem';
            spanId.style.color = '#94a3b8';
            spanId.textContent = ` (#${token.id})`;
            title.appendChild(spanId);
        } else {
            title.textContent = `Token #${token.id}`;
        }
        
        if (currentUser && currentUser.is_admin) {
            const badge = clone.querySelector('.owner-badge');
            badge.classList.remove('hidden');
            clone.querySelector('.t-owner').textContent = token.owner_id;
        }

        const connBadge = clone.querySelector('.connection-status-badge');
        connBadge.style.fontSize = '0.75rem';
        connBadge.style.fontWeight = '500';
        connBadge.style.padding = '2px 6px';
        connBadge.style.borderRadius = '4px';
        if (token.is_connected) {
            connBadge.textContent = '🟢 Connecté';
            connBadge.style.backgroundColor = 'rgba(50, 215, 75, 0.15)';
            connBadge.style.color = 'var(--accent-success)';
            connBadge.style.border = '1px solid rgba(50, 215, 75, 0.3)';
        } else {
            connBadge.textContent = '🔴 Déconnecté';
            connBadge.style.backgroundColor = 'rgba(255, 69, 58, 0.15)';
            connBadge.style.color = 'var(--accent-error)';
            connBadge.style.border = '1px solid rgba(255, 69, 58, 0.3)';
        }

        const statusSelect = clone.querySelector('.status-select');
        statusSelect.value = token.status;

        const guildInput = clone.querySelector('.guild-input');
        guildInput.value = token.guild_id || '';

        const channelInput = clone.querySelector('.channel-input');
        channelInput.value = token.channel_id || '';
        
        const isActiveCheckbox = clone.querySelector('.is-active-checkbox');
        const joinVoiceCheckbox = clone.querySelector('.join-voice-checkbox');
        const muteCheckbox = clone.querySelector('.mute-checkbox');
        const deafCheckbox = clone.querySelector('.deaf-checkbox');

        isActiveCheckbox.checked = token.is_active;
        joinVoiceCheckbox.checked = token.join_voice;
        muteCheckbox.checked = token.self_mute;
        deafCheckbox.checked = token.self_deaf;

        const rotateStatusCheckbox = clone.querySelector('.rotate-status-checkbox');
        rotateStatusCheckbox.checked = token.rotate_status || false;

        const rotationInput = clone.querySelector('.rotation-interval-input');
        rotationInput.value = token.rotation_interval || 30;

        const activitiesList = clone.querySelector('.activities-list');
        let currentActivities = token.activities_json || [];

        const renderActivities = () => {
            activitiesList.innerHTML = '';
            currentActivities.forEach((act, idx) => {
                const actDiv = document.createElement('div');
                actDiv.style.display = 'flex';
                actDiv.style.gap = '0.5rem';
                actDiv.style.alignItems = 'center';
                
                const typeLabels = {0: "Joue à", 2: "Écoute", 3: "Regarde", 5: "Participe à"};
                
                actDiv.innerHTML = `
                    <div class="glass-panel" style="flex-grow: 1; padding: 0.4rem 0.6rem; display: flex; gap: 0.5rem; align-items: center; border-radius: 4px; font-size: 0.85rem;">
                        <span style="color: var(--text-secondary); font-weight: bold;">${typeLabels[act.type] || '???'}</span>
                        <span>${act.name.replace(/</g, "&lt;")}</span>
                    </div>
                    <button type="button" class="glass-button glass-button-danger remove-act-btn" style="padding: 0.4rem 0.6rem; flex-shrink: 0;" data-idx="${idx}">✖</button>
                `;
                activitiesList.appendChild(actDiv);
            });

            activitiesList.querySelectorAll('.remove-act-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    const idx = parseInt(e.currentTarget.getAttribute('data-idx'));
                    currentActivities.splice(idx, 1);
                    renderActivities();
                });
            });
            updateDisabledStates();
        };

        const addActBtn = clone.querySelector('.add-activity-btn');
        const newActType = clone.querySelector('.new-activity-type');
        const newActName = clone.querySelector('.new-activity-name');

        addActBtn.addEventListener('click', () => {
            const t = parseInt(newActType.value);
            const n = newActName.value.trim();
            if (n) {
                currentActivities.push({type: t, name: n});
                newActName.value = '';
                renderActivities();
            }
        });
        rotateStatusCheckbox.addEventListener('change', updateDisabledStates);
        
        renderActivities();

        // Interactive logic to disable fields
        function updateDisabledStates() {
            const isActive = isActiveCheckbox.checked;
            const isVoice = joinVoiceCheckbox.checked;
            const isRotate = rotateStatusCheckbox.checked;
            
            statusSelect.disabled = !isActive;
            joinVoiceCheckbox.disabled = !isActive;
            rotateStatusCheckbox.disabled = !isActive;

            const voiceFieldsDisabled = !(isActive && isVoice);
            guildInput.disabled = voiceFieldsDisabled;
            channelInput.disabled = voiceFieldsDisabled;
            muteCheckbox.disabled = voiceFieldsDisabled;
            deafCheckbox.disabled = voiceFieldsDisabled;

            const rotateFieldsDisabled = !(isActive && isRotate);
            rotationInput.disabled = rotateFieldsDisabled;
            newActType.disabled = rotateFieldsDisabled;
            newActName.disabled = rotateFieldsDisabled;
            addActBtn.disabled = rotateFieldsDisabled;
            activitiesList.querySelectorAll('.remove-act-btn').forEach(btn => btn.disabled = rotateFieldsDisabled);

            // Toggle CSS classes for parent containers to ensure visual feedback
            statusSelect.closest('.form-group').classList.toggle('disabled-field', !isActive);
            rotateStatusCheckbox.closest('.form-group').classList.toggle('disabled-field', !isActive);
            rotationInput.closest('.rotation-interval-wrapper').classList.toggle('disabled-field', rotateFieldsDisabled);
            newActType.closest('.form-group').classList.toggle('disabled-field', rotateFieldsDisabled);
            joinVoiceCheckbox.parentElement.classList.toggle('disabled-field', !isActive);
            
            guildInput.parentElement.classList.toggle('disabled-field', voiceFieldsDisabled);
            channelInput.parentElement.classList.toggle('disabled-field', voiceFieldsDisabled);
            muteCheckbox.parentElement.classList.toggle('disabled-field', voiceFieldsDisabled);
            deafCheckbox.parentElement.classList.toggle('disabled-field', voiceFieldsDisabled);
        };

        isActiveCheckbox.addEventListener('change', updateDisabledStates);
        joinVoiceCheckbox.addEventListener('change', updateDisabledStates);
        updateDisabledStates(); // Init state

        // Add event listeners
        clone.querySelector('.delete-btn').addEventListener('click', () => handleDelete(token.id));
        
        const updateBtn = clone.querySelector('.update-btn');
        updateBtn.addEventListener('click', (e) => {
            const btn = e.target;
            const originalText = btn.textContent;
            btn.textContent = '...';
            btn.disabled = true;

            const activeChecked = isActiveCheckbox.checked;
            const joinChecked = joinVoiceCheckbox.checked;
            const muteChecked = muteCheckbox.checked;
            const deafChecked = deafCheckbox.checked;

            handleUpdate(token.id, {
                status: statusSelect.value,
                guild_id: guildInput.value || null,
                channel_id: channelInput.value || null,
                self_mute: muteChecked,
                self_deaf: deafChecked,
                join_voice: joinChecked,
                is_active: activeChecked,
                activities_json: currentActivities,
                rotation_interval: parseInt(rotationInput.value) || 30,
                rotate_status: rotateStatusCheckbox.checked
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
