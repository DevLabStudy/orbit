let cachedData = null;
let activeTab = null;

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
        document.getElementById('count-stacks').innerText = data.counts.stacks;

        updateNetworkSelect();

        if (activeTab) {
            updateList(activeTab);
        }
    } catch (err) {
        console.error("Fetch error:", err);
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

    // Pokaż przycisk dodawania
    addBtn.style.display = ['containers', 'volumes', 'networks', 'images'].includes(type) ? 'block' : 'none';

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
                        <div class="item-name">${item.name}</div>
                        <div class="item-details">${item.image}</div>
                    </div>
                </div>
                <div class="item-meta">
                    <div class="actions">
                        ${item.status !== 'running' ? `<button class="action-btn start" onclick="containerAction('${item.id}', 'start')">▶</button>` : ''}
                        ${item.status === 'running' ? `<button class="action-btn stop" onclick="containerAction('${item.id}', 'stop')">⏹</button>` : ''}
                        <button class="action-btn restart" onclick="containerAction('${item.id}', 'restart')">🔄</button>
                        <button class="action-btn remove" onclick="containerAction('${item.id}', 'remove')">🗑</button>
                    </div>
                    <div style="text-align:right;">
                        <div class="item-details">${item.status.toUpperCase()}</div>
                        <div class="item-id">${item.id}</div>
                    </div>
                </div>
            `;
        } else if (type === 'images') {
            div.innerHTML = `
                <div class="info">
                    <div class="dot default"></div>
                    <div>
                        <div class="item-name">${item.tags[0]}</div>
                        <div class="item-id">${item.id}</div>
                    </div>
                </div>
                <div class="item-meta">
                    <div class="actions">
                        <button class="action-btn remove" onclick="imageRemove('${item.id}')">🗑</button>
                    </div>
                    <div class="item-details">${item.size}</div>
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
                        <button class="action-btn remove" onclick="volumeRemove('${item.name}')">🗑</button>
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
                        <button class="action-btn remove" onclick="networkRemove('${item.id}')">🗑</button>
                    </div>
                    <div class="item-details">${item.driver} / ${item.scope}</div>
                </div>
            `;
        }

        list.appendChild(div);
    });
}

// ============ AKCJE ============

async function containerAction(id, action) {
    if (action === 'remove' && !confirm('Czy na pewno usunąć kontener?')) return;
    try {
        const res = await fetch(`/container/${id}/${action}`, { method: 'POST' });
        const data = await res.json();
        showToast(data.message, res.ok ? 'success' : 'error');
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
        showToast(data.message, res.ok ? 'success' : 'error');
        refreshData();
    } catch (err) {
        showToast('Błąd: ' + err, 'error');
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
    }
}

function closeModal(id) {
    document.getElementById(id).classList.remove('visible');
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

    // Porty
    if (portHost && portContainer) {
        body.ports = {};
        body.ports[`${portContainer}/tcp`] = parseInt(portHost);
    }

    // Env
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
        if (res.ok) {
            closeModal('container-modal');
            document.getElementById('c-image').value = '';
            document.getElementById('c-name').value = '';
            document.getElementById('c-port-host').value = '';
            document.getElementById('c-port-container').value = '';
            document.getElementById('c-env').value = '';
        }
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
        if (res.ok) {
            closeModal('pull-modal');
            document.getElementById('pull-image').value = '';
        }
        refreshData();
    } catch (err) {
        showToast('Błąd: ' + err, 'error');
    }
}

// Simple create (sieć/volume)
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

// ============ TOAST ============

function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    toast.innerText = message;
    toast.className = `toast visible ${type}`;
    setTimeout(() => toast.classList.remove('visible'), 4000);
}

// ============ ZAKŁADKI ============

document.querySelectorAll('.tab').forEach(tab => {
    tab.onclick = function() {
        // Ignoruj kliknięcie na disabled (Stacks)
        if (this.classList.contains('disabled')) {
            showToast(' Stacks - coming soon!', 'error');
            return;
        }

        const type = this.dataset.type;
        const section = document.getElementById('details-section');

        if (activeTab === type) {
            section.classList.remove('visible');
            this.classList.remove('active');
            activeTab = null;
            return;
        }

        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        this.classList.add('active');
        activeTab = type;

        section.classList.add('visible');
        updateList(type);
        section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
});

function logout() {
    fetch('/logout').then(() => window.location.reload());
}

// Odświeżanie co 5 sekund
setInterval(refreshData, 5000);
refreshData();