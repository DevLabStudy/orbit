let cachedData = null;
let activeTab = 'containers';
let currentLogsContainer = null;

function escapeHtml(value) {
    const node = document.createElement('span');
    node.textContent = value == null ? '' : String(value);
    return node.innerHTML;
}

function formatPorts(ports) {
    if (!ports || ports.length === 0) return 'brak wystawionych portów';
    return ports.map(port => {
        const mapping = port.host ? `${port.host} → ${port.container}` : `→ ${port.container}`;
        return port.url ? `<a href="${escapeHtml(port.url)}" target="_blank" rel="noopener">${escapeHtml(mapping)}</a>` : escapeHtml(mapping);
    }).join(', ');
}

function showError(data, fallback = 'Wystąpił błąd') {
    const message = data && data.message ? data.message : fallback;
    const help = data && data.help_url ? `<br><a href="${data.help_url}" target="_blank" rel="noopener">Kontakt i pomoc: devlabstudy.ovh</a>` : '';
    showToast(message + help, 'error', true);
}

// ============ ODŚWIEŻANIE DANYCH ============

async function refreshData() {
    try {
        const response = await fetch('/status');
        if (!response.ok) return;

        const data = await response.json();
        cachedData = data;

        document.getElementById('count-containers').innerText = data.counts.containers;
        document.getElementById('count-images').innerText = data.counts.images;
        document.getElementById('count-volumes').innerText = data.counts.volumes;
        document.getElementById('count-networks').innerText = data.counts.networks;
        document.getElementById('count-stacks').innerText = data.counts.stacks || 0;

        updateNetworkSelect();

        if (activeTab) {
            updateList(activeTab);
        }
    } catch (err) {
        showToast('Nie udało się odświeżyć danych. <a href="https://www.devlabstudy.ovh" target="_blank" rel="noopener">Kontakt i pomoc: devlabstudy.ovh</a>', 'error', true);
    }
}

function updateNetworkSelect() {
    const select = document.getElementById('c-network');
    if (!cachedData || !select) return;

    select.innerHTML = '<option value="">Domyślna (bridge)</option>';
    cachedData.networks.forEach(net => {
        select.innerHTML += `<option value="${net.name}">${net.name}</option>`;
    });
}

// ============ WYŚWIETLANIE LISTY ============

function updateList(type) {
    const list = document.getElementById('details-list');
    const header = document.getElementById('details-header');
    const addBtn = document.getElementById('btn-add');
    const cleanBtn = document.getElementById('btn-clean');
    list.innerHTML = '';

    if (!cachedData) return;

    const titles = {
        containers: 'Containers',
        images: 'Images',
        volumes: 'Volumes',
        networks: 'Networks',
        stacks: 'Stacks'
    };
    header.innerText = titles[type] || 'Lista';
    const subtitle = document.getElementById('details-subtitle');
    if (subtitle) {
        subtitle.innerText = {
            containers: 'Wszystkie kontenery i ich mapowania portów',
            images: 'Obrazy dostępne lokalnie',
            volumes: 'Trwałe dane Dockera',
            networks: 'Sieci i połączenia kontenerów',
            stacks: 'Projekty Docker Compose'
        }[type] || 'Zasoby środowiska';
    }

    // Pokaż przycisk dodawania dla wszystkich typów
    addBtn.style.display = ['containers', 'volumes', 'networks', 'images', 'stacks'].includes(type) ? 'block' : 'none';
    if (cleanBtn) cleanBtn.style.display = type === 'images' ? 'inline-block' : 'none';

    const items = cachedData[type] || [];

    if (items.length === 0) {
        list.innerHTML = '<div class="empty-state">Brak elementów</div>';
        return;
    }

    items.forEach(item => {
        const div = document.createElement('div');
        div.className = 'list-item';

        if (type === 'containers') {
            div.innerHTML = `
                <div class="info">
                    <div class="dot ${item.status}"></div>
                    <div>
                        <div class="item-name">${escapeHtml(item.name)}</div>
                        <div class="item-details">${escapeHtml(item.image)}</div>
                        <div class="item-details ports">${formatPorts(item.ports)}</div>
                    </div>
                </div>
                <div class="item-meta">
                    <div class="actions">
                        ${item.status !== 'running' ? `<button class="action-btn start" title="Uruchom kontener" onclick="containerAction('${item.id}', 'start')">Uruchom</button>` : ''}
                        ${item.status === 'running' ? `<button class="action-btn stop" title="Zatrzymaj kontener" onclick="containerAction('${item.id}', 'stop')">Zatrzymaj</button>` : ''}
                        <button class="action-btn restart" title="Uruchom kontener ponownie" onclick="containerAction('${item.id}', 'restart')">Restart</button>
                        <button class="action-btn logs" title="Pokaż ostatnie logi" onclick="showLogs('${item.id}', '${escapeHtml(item.name)}')">Logi</button>
                        <button class="action-btn logs" title="Pokaż konfigurację kontenera" onclick="showContainerDetails('${item.id}', '${escapeHtml(item.name)}')">Opcje</button>
                        <button class="action-btn remove" title="Usuń kontener" onclick="containerAction('${item.id}', 'remove')">Usuń</button>
                    </div>
                    <div style="text-align:right;">
                        <div class="item-details">${escapeHtml(item.status.toUpperCase())}</div>
                        <div class="item-id">${escapeHtml(item.id)}</div>
                    </div>
                </div>
            `;
        } else if (type === 'images') {
            div.innerHTML = `
                <div class="info">
                    <div class="dot default"></div>
                    <div>
                        <div class="item-name">${escapeHtml(item.tags[0])}</div>
                        <div class="item-details">${escapeHtml(item.tags.slice(1).join(', '))}</div>
                        <div class="item-id">${escapeHtml(item.id)}</div>
                    </div>
                </div>
                <div class="item-meta">
                    <div class="actions">
                        <button class="action-btn logs" title="Pokaż szczegóły obrazu" onclick="showImageDetails('${item.id}')">Szczegóły</button>
                        <button class="action-btn remove" title="Usuń obraz" onclick="imageRemove('${item.id}')">Usuń</button>
                    </div>
                    <div class="item-details">${escapeHtml(item.size)}</div>
                </div>
            `;
        } else if (type === 'volumes') {
            div.innerHTML = `
                <div class="info">
                    <div class="dot default"></div>
                    <div>
                        <div class="item-name">${item.name}</div>
                        <div class="item-details">${item.mountpoint}</div>
                    </div>
                </div>
                <div class="item-meta">
                    <div class="actions">
                        <button class="action-btn remove" title="Usuń volume" onclick="volumeRemove('${item.name}')">Usuń</button>
                    </div>
                    <div class="item-details">${item.driver}</div>
                </div>
            `;
        } else if (type === 'networks') {
            div.innerHTML = `
                <div class="info">
                    <div class="dot default"></div>
                    <div>
                        <div class="item-name">${item.name}</div>
                        <div class="item-id">${item.id}</div>
                    </div>
                </div>
                <div class="item-meta">
                    <div class="actions">
                        <button class="action-btn remove" title="Usuń sieć" onclick="networkRemove('${item.id}')">Usuń</button>
                    </div>
                    <div class="item-details">${item.driver} / ${item.scope}</div>
                </div>
            `;
        } else if (type === 'stacks') {
            const runningCount = item.containers.filter(c => c.status === 'running').length;
            const totalCount = item.containers.length;
            const allRunning = runningCount === totalCount;
            const statusClass = allRunning ? 'running' : (runningCount > 0 ? 'paused' : 'stopped');

            let containerDots = item.containers.map(c =>
                `<div class="stack-dot" style="background: var(--${c.status === 'running' ? 'success' : 'error'})"></div>`
            ).join('');

            div.innerHTML = `
                <div class="info">
                    <div class="dot ${statusClass}"></div>
                    <div>
                        <div class="item-name">${escapeHtml(item.name)}</div>
                        <div class="item-details">${item.containers.map(c => `${escapeHtml(c.name)} (${escapeHtml(c.image || '')})`).join(' · ')}</div>
                        <div class="stack-containers">${containerDots}</div>
                    </div>
                </div>
                <div class="item-meta">
                    <div class="actions">
                        <button class="action-btn start" title="Uruchom stack" onclick="stackAction('${item.name}', 'start')">Uruchom</button>
                        <button class="action-btn stop" title="Zatrzymaj stack" onclick="stackAction('${item.name}', 'stop')">Zatrzymaj</button>
                        <button class="action-btn restart" title="Uruchom stack ponownie" onclick="stackAction('${item.name}', 'restart')">Restart</button>
                        <button class="action-btn logs" title="Pokaż Compose i usługi" onclick="showStackDetails('${item.name}')">Opcje</button>
                        <button class="action-btn remove" title="Usuń stack" onclick="stackAction('${item.name}', 'remove')">Usuń</button>
                    </div>
                    <div style="text-align:right;">
                        <div class="item-details">${runningCount}/${totalCount} running</div>
                        <div class="item-id">${item.path || ''}</div>
                    </div>
                </div>
            `;
        }

        list.appendChild(div);
    });
}

// ============ AKCJE KONTENERÓW ============

async function containerAction(id, action) {
    if (action === 'remove' && !confirm('Czy na pewno usunąć kontener?')) return;
    try {
        const res = await fetch(`/container/${id}/${action}`, { method: 'POST' });
        const data = await res.json();
        res.ok ? showToast(data.message, 'success') : showError(data);
        refreshData();
    } catch (err) {
        showToast('Błąd: ' + err, 'error');
    }
}

async function imageRemove(id) {
    if (!confirm('Czy na pewno usunąć obraz?')) return;
    try {
        const res = await fetch(`/image/${id}/remove`, { method: 'POST' });
        const data = await res.json();
        res.ok ? showToast(data.message, 'success') : showError(data);
        refreshData();
    } catch (err) {
        showToast('Błąd: ' + err, 'error');
    }

}

async function showImageDetails(id) {
    try {
        const res = await fetch(`/image/${encodeURIComponent(id)}/inspect`);
        const data = await res.json();
        if (!res.ok) return showError(data, 'Nie udało się odczytać obrazu');
        const size = Math.round((data.size || 0) / 1024 / 1024);
        showToast(`${data.tags.join(', ')} · ${size} MB · ${data.layers} warstw`, 'success');
    } catch (err) {
        showToast('Błąd odczytu obrazu: ' + err, 'error');
    }
}

async function showContainerDetails(id, name) {
    document.getElementById('details-title').innerText = `Opcje kontenera: ${name}`;
    document.getElementById('details-content').innerText = 'Ładowanie...';
    document.getElementById('details-modal').classList.add('visible');
    try {
        const res = await fetch(`/container/${encodeURIComponent(id)}/inspect`);
        const data = await res.json();
        if (!res.ok) return showError(data);
        document.getElementById('details-content').innerText = JSON.stringify(data, null, 2);
    } catch (err) {
        showToast('Nie udało się pobrać opcji kontenera. <a href="https://www.devlabstudy.ovh" target="_blank" rel="noopener">Kontakt i pomoc</a>', 'error', true);
    }
}

async function showStackDetails(name) {
    document.getElementById('details-title').innerText = `Opcje stacka: ${name}`;
    document.getElementById('details-content').innerText = 'Ładowanie...';
    document.getElementById('details-modal').classList.add('visible');
    try {
        const res = await fetch(`/stack/${encodeURIComponent(name)}/details`);
        const data = await res.json();
        if (!res.ok) return showError(data);
        const services = data.services.map(service => `${service.name}: ${service.image || 'build'} | porty: ${(service.ports || []).join(', ')}`).join('\n');
        document.getElementById('details-content').innerText = `Usługi:\n${services || 'brak'}\n\nDocker Compose:\n${data.compose}`;
    } catch (err) {
        showToast('Nie udało się pobrać opcji stacka. <a href="https://www.devlabstudy.ovh" target="_blank" rel="noopener">Kontakt i pomoc</a>', 'error', true);
    }
}

async function pruneImages() {
    if (!confirm('Usunąć nieużywane obrazy bez tagów?')) return;
    try {
        const res = await fetch('/image/prune', { method: 'POST' });
        const data = await res.json();
        res.ok ? showToast(data.message, 'success') : showError(data);
        refreshData();
    } catch (err) {
        showToast('Błąd czyszczenia obrazów: ' + err, 'error');
    }
}

async function networkRemove(id) {
    if (!confirm('Czy na pewno usunąć sieć?')) return;
    try {
        const res = await fetch(`/network/${id}/remove`, { method: 'POST' });
        const data = await res.json();
        showToast(data.message, res.ok ? 'success' : 'error');
        refreshData();
    } catch (err) {
        showToast('Błąd: ' + err, 'error');
    }
}

async function volumeRemove(name) {
    if (!confirm('Czy na pewno usunąć volume?')) return;
    try {
        const res = await fetch(`/volume/${name}/remove`, { method: 'POST' });
        const data = await res.json();
        showToast(data.message, res.ok ? 'success' : 'error');
        refreshData();
    } catch (err) {
        showToast('Błąd: ' + err, 'error');
    }
}

// ============ AKCJE STACKÓW ============

async function stackAction(name, action) {
    if (action === 'remove' && !confirm('Czy na pewno usunąć stack i wszystkie jego kontenery?')) return;
    try {
        showToast(`${action === 'remove' ? 'Usuwanie' : 'Wykonywanie'} stacka...`, 'success');
        const res = await fetch(`/stack/${name}/${action}`, { method: 'POST' });
        const data = await res.json();
        showToast(data.message, res.ok ? 'success' : 'error');
        refreshData();
    } catch (err) {
        showToast('Błąd: ' + err, 'error');
    }
}

async function createStack() {
    const name = document.getElementById('stack-name').value.trim();
    const compose = document.getElementById('stack-compose').value.trim();

    if (!name || !compose) {
        showToast('Podaj nazwę i konfigurację!', 'error');
        return;
    }

    try {
        showToast('Tworzenie stacka...', 'success');
        const res = await fetch('/stack/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, compose })
        });
        const data = await res.json();
        showToast(data.message, res.ok ? 'success' : 'error');
        if (res.ok) {
            closeModal('stack-modal');
            document.getElementById('stack-name').value = '';
            document.getElementById('stack-compose').value = '';
            refreshData();
        }
    } catch (err) {
        showToast('Błąd: ' + err, 'error');
    }
}

// ============ LOGI KONTENERÓW ============

async function showLogs(containerId, containerName) {
    currentLogsContainer = containerId;
    document.getElementById('logs-title').innerText = `📋 Logi: ${containerName}`;
    document.getElementById('logs-content').innerText = 'Ładowanie...';
    document.getElementById('logs-modal').classList.add('visible');
    await refreshLogs();
}

async function refreshLogs() {
    if (!currentLogsContainer) return;
    try {
        const res = await fetch(`/container/${currentLogsContainer}/logs`);
        const data = await res.json();
        if (res.ok) {
            document.getElementById('logs-content').innerText = data.logs || 'Brak logów';
        } else {
            document.getElementById('logs-content').innerText = 'Błąd: ' + data.message;
        }
    } catch (err) {
        document.getElementById('logs-content').innerText = 'Błąd pobierania logów: ' + err;
    }
}

// ============ MODAL TWORZENIA ============

function openCreateModal() {
    if (activeTab === 'containers') {
        document.getElementById('container-modal').classList.add('visible');
    } else if (activeTab === 'images') {
        document.getElementById('pull-modal').classList.add('visible');
    } else if (activeTab === 'networks') {
        document.getElementById('simple-modal-title').innerText = '🌐 Utwórz sieć';
        document.getElementById('driver-group').style.display = 'block';
        document.getElementById('simple-name').value = '';
        document.getElementById('simple-modal').classList.add('visible');
    } else if (activeTab === 'volumes') {
        document.getElementById('simple-modal-title').innerText = '💾 Utwórz volume';
        document.getElementById('driver-group').style.display = 'none';
        document.getElementById('simple-name').value = '';
        document.getElementById('simple-modal').classList.add('visible');
    } else if (activeTab === 'stacks') {
        document.getElementById('stack-modal').classList.add('visible');
    }
}

function closeModal(id) {
    document.getElementById(id).classList.remove('visible');
    if (id === 'logs-modal') {
        currentLogsContainer = null;
    }
}

// Tworzenie kontenera
async function createContainer() {
    const image = document.getElementById('c-image').value.trim();
    const name = document.getElementById('c-name').value.trim();
    const portHost = document.getElementById('c-port-host').value.trim();
    const portContainer = document.getElementById('c-port-container').value.trim();
    const envRaw = document.getElementById('c-env').value.trim();
    const restart = document.getElementById('c-restart').value;
    const network = document.getElementById('c-network').value;

    if (!image) {
        showToast('Podaj nazwę obrazu!', 'error');
        return;
    }

    const body = {
        image: image,
        name: name || null,
        restart_policy: restart,
        network: network || null
    };

    if (portHost && portContainer) {
        body.ports = {};
        body.ports[`${portContainer}/tcp`] = parseInt(portHost);
    }

    if (envRaw) {
        body.env = envRaw.split(',').map(e => e.trim());
    }

    try {
        showToast('Tworzenie kontenera...', 'success');
        const res = await fetch('/container/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const data = await res.json();
        showToast(data.message, res.ok ? 'success' : 'error');
        closeModal('container-modal');
        refreshData();
    } catch (err) {
        showToast('Błąd: ' + err, 'error');
    }
}

// Tworzenie sieci/volume
async function confirmSimpleCreate() {
    const name = document.getElementById('simple-name').value.trim();
    if (!name) {
        showToast('Podaj nazwę!', 'error');
        return;
    }

    let url, body;
    if (activeTab === 'networks') {
        const driver = document.getElementById('simple-driver').value;
        url = '/network/create';
        body = { name, driver };
    } else if (activeTab === 'volumes') {
        url = '/volume/create';
        body = { name };
    }

    try {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const data = await res.json();
        showToast(data.message, res.ok ? 'success' : 'error');
        closeModal('simple-modal');
        refreshData();
    } catch (err) {
        showToast('Błąd: ' + err, 'error');
    }
}

// Pull image
async function pullImage() {
    const image = document.getElementById('pull-image').value.trim();
    if (!image) {
        showToast('Podaj nazwę obrazu!', 'error');
        return;
    }

    try {
        showToast('Pobieranie obrazu...', 'success');
        const res = await fetch('/image/pull', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image })
        });
        const data = await res.json();
        showToast(data.message, res.ok ? 'success' : 'error');
        closeModal('pull-modal');
        refreshData();
    } catch (err) {
        showToast('Błąd: ' + err, 'error');
    }
}

async function buildImage() {
    const tag = document.getElementById('build-tag').value.trim();
    const dockerfile = document.getElementById('build-dockerfile').value.trim();
    if (!tag || !dockerfile) {
        showToast('Podaj tag i Dockerfile.', 'error');
        return;
    }
    try {
        showToast('Budowanie obrazu...', 'success');
        const res = await fetch('/image/build', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({tag, dockerfile})
        });
        const data = await res.json();
        res.ok ? showToast(data.message, 'success') : showError(data);
        if (res.ok) {
            closeModal('build-modal');
            refreshData();
        }
    } catch (err) {
        showToast('Błąd budowania obrazu: ' + err, 'error');
    }
}

// ============ TABS ============

function toggleTab(type) {
    const section = document.getElementById('details-section');
    const tabs = document.querySelectorAll('.tab');

    if (activeTab === type) {
        activeTab = null;
        section.classList.remove('visible');
        tabs.forEach(t => t.classList.remove('active'));
    } else {
        activeTab = type;
        section.classList.add('visible');
        tabs.forEach(t => {
            t.classList.toggle('active', t.dataset.type === type);
        });
        updateList(type);
    }
}

// ============ TOAST ============

function showToast(message, type = 'success', html = false) {
    const toast = document.getElementById('toast');
    if (html) toast.innerHTML = message;
    else toast.innerText = message;
    toast.className = 'toast visible ' + type;
    setTimeout(() => toast.classList.remove('visible'), 3000);
}

// ============ LOGOUT ============

function logout() {
    window.location.href = '/logout';
}

// ============ UPDATE CHECKER ============

async function checkForUpdate() {
    try {
        const currentVersion = "1.0.0";
        const res = await fetch('https://api.github.com/repos/DevLabStudy/orbit/releases/latest');
        if (!res.ok) return;

        const data = await res.json();
        const latestVersion = data.tag_name.replace('v', '');

        if (latestVersion !== currentVersion) {
            document.getElementById('update-banner').classList.add('visible');
        }
    } catch (err) {
        console.log('Update check failed:', err);
    }
}

// ============ INIT ============

document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => toggleTab(tab.dataset.type));
});

refreshData();
updateList('containers');
setInterval(refreshData, 5000);
checkForUpdate();