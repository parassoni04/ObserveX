// ObserveX Frontend State Management

const state = {
    activeView: 'dashboard',
    refreshInterval: 0.2, // seconds
    theme: 'dark',
    startupEnabled: false,
    chartsInitialized: false,
    
    // Multi-device mode
    mode: 'local',           // 'local' (standalone) or 'centralized' (server)
    devices: [],             // List of registered devices
    selectedDeviceId: null,  // Currently viewed device ID
    
    // Auth & Enterprise
    authToken: null,         // JWT access token
    currentUser: null,       // Authenticated User object
    adminUsers: [],          // Admin user management list
    
    // Live metrics cache
    metrics: {},
    
    // UI pagination and data caches
    processes: [],
    procSearch: '',
    procStatusFilter: 'all',
    procSortCol: 'cpu_usage',
    procSortDesc: true,
    procPage: 1,
    procPageSize: 15,
    
    apps: [],
    appSearch: '',
    appSortCol: 'name',
    appSortDesc: false,
    appPage: 1,
    appPageSize: 15,
    
    events: [],
    eventSearch: '',
    eventSeverityFilter: 'all',
    eventSourceFilter: '',
    eventDateFilter: '',
    eventPage: 1,
    eventPageSize: 15,
    
    // Notification parameters
    notificationsEnabled: true,
    limits: {
        cpu: 90,
        cpuWarn: 55,
        ram: 90,
        ramWarn: 65,
        disk: 10,
        cpu_temp: 85
    },
    lastAlertTimes: {
        cpu: 0,
        ram: 0,
        disk: 0,
        cpu_temp: 0,
        network: 0
    },
    alertCooldownMs: 30000 // 30 seconds cooldown between same alert
};

// Global variables for Chart.js instances
let charts = {};
const maxChartPoints = 30;

// Authenticated fetch wrapper
async function authFetch(url, options = {}) {
    options.headers = options.headers || {};
    if (state.authToken) {
        options.headers['Authorization'] = `Bearer ${state.authToken}`;
    }
    const res = await fetch(url, options);
    if (res.status === 401 && state.mode === 'centralized') {
        // Token expired or invalid
        logoutUser();
    }
    return res;
}

// Initialize app when DOM is fully loaded
document.addEventListener('DOMContentLoaded', async () => {
    try {
        loadSettingsFromStorage();
    } catch (e) {
        console.error("Error loading settings:", e);
    }
    
    try {
        initUITheme();
    } catch (e) {
        console.error("Error initializing theme:", e);
    }
    
    try {
        initEventListeners();
    } catch (e) {
        console.error("Error initializing event listeners:", e);
    }

    try {
        initAuthListeners();
    } catch (e) {
        console.error("Error initializing auth listeners:", e);
    }

    // Start heartbeat loop immediately to keep legacy standalone server alive
    startHeartbeatLoop();

    // Detect mode: check if centralized server API is available
    await detectMode();

    if (state.mode === 'local') {
        // Legacy standalone mode
        startHeartbeatLoop();
        try { connectWebSocket(); } catch (e) { console.error("Error connecting websocket:", e); }
        try { fetchHardwareSpecs(); } catch (e) { console.error("Error fetching hardware specs:", e); }
        try { syncStartupSetting(); } catch (e) { console.error("Error syncing startup setting:", e); }
    } else {
        // Centralized multi-device mode: check auth token
        const savedToken = localStorage.getItem('observex_token');
        if (savedToken) {
            state.authToken = savedToken;
            const valid = await checkAuthSession();
            if (valid) {
                await fetchDeviceList();
                connectDashboardWebSocket();
            } else {
                showAuthModal();
            }
        } else {
            showAuthModal();
        }
    }
    
    try {
        refreshViewContent();
    } catch (e) {
        console.error("Error refreshing view:", e);
    }
});

// ── Mode Detection ──
async function detectMode() {
    try {
        const res = await fetch('/api/v1/devices', { signal: AbortSignal.timeout(2000) });
        if (res.ok) {
            state.mode = 'centralized';
            console.log('ObserveX: Centralized server mode detected.');
            return;
        }
    } catch (e) {
        // Centralized API not available
    }
    state.mode = 'local';
    console.log('ObserveX: Standalone local mode.');
}

// ── Device Management ──
async function fetchDeviceList() {
    try {
        const res = await authFetch('/api/v1/devices');
        if (!res.ok) return;
        const devices = await res.json();
        state.devices = devices;
        updateDeviceSelector();
        renderDevicesView();
        
        // Auto-select first device if none selected
        if (!state.selectedDeviceId && devices.length > 0) {
            selectDevice(devices[0].id);
        }
    } catch (e) {
        console.error('Error fetching device list:', e);
    }
}

function updateDeviceSelector() {
    const sel = document.getElementById('device-selector');
    if (!sel) return;
    
    sel.innerHTML = '';
    if (state.mode === 'local') {
        sel.innerHTML = '<option value="local">Local Machine</option>';
        return;
    }
    
    if (state.devices.length === 0) {
        sel.innerHTML = '<option value="">No devices registered</option>';
        return;
    }
    
    state.devices.forEach(d => {
        const opt = document.createElement('option');
        opt.value = d.id;
        opt.textContent = `${d.hostname} ${d.is_online ? '●' : '○'}`;
        if (d.id === state.selectedDeviceId) opt.selected = true;
        sel.appendChild(opt);
    });
}

function selectDevice(deviceId) {
    const prevId = state.selectedDeviceId;
    state.selectedDeviceId = parseInt(deviceId);
    
    // Update status indicator
    const device = state.devices.find(d => d.id === state.selectedDeviceId);
    const dot = document.querySelector('#device-status-dot .status-dot');
    const text = document.getElementById('device-status-text');
    if (device && dot && text) {
        dot.className = `status-dot ${device.is_online ? 'online' : 'offline'}`;
        text.textContent = device.is_online ? 'Online' : 'Offline';
    }
    
    // Reset cached data for new device
    state.apps = [];
    state.events = [];
    state.processes = [];
    charts = {};
    
    // Resubscribe WebSocket
    if (dashboardWs && dashboardWs.readyState === WebSocket.OPEN) {
        if (prevId) {
            dashboardWs.send(JSON.stringify({ action: 'unsubscribe', device_id: prevId }));
        }
        dashboardWs.send(JSON.stringify({ action: 'subscribe', device_id: state.selectedDeviceId }));
    }
    
    // Reload current view data
    fetchHardwareSpecs();
    refreshViewContent();
}

function renderDevicesView() {
    const grid = document.getElementById('devices-grid');
    if (!grid) return;
    
    if (state.devices.length === 0) {
        grid.innerHTML = `
            <div class="no-devices-message">
                <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5">
                    <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
                    <line x1="8" y1="21" x2="16" y2="21"/>
                    <line x1="12" y1="17" x2="12" y2="21"/>
                </svg>
                <h3>No Devices Registered</h3>
                <p>Start the ObserveX agent on a Windows machine to register it with this server. Devices will appear here automatically.</p>
            </div>
        `;
        return;
    }
    
    grid.innerHTML = state.devices.map(d => {
        const statusClass = d.is_online ? 'online' : 'offline';
        const lastSeen = d.last_seen ? new Date(d.last_seen).toLocaleString() : 'Never';
        const registered = d.registered_at ? new Date(d.registered_at).toLocaleDateString() : 'Unknown';
        
        return `
            <div class="device-card ${statusClass}" data-device-id="${d.id}">
                <div class="device-card-header">
                    <div class="device-card-name">
                        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
                            <line x1="8" y1="21" x2="16" y2="21"/>
                            <line x1="12" y1="17" x2="12" y2="21"/>
                        </svg>
                        ${escapeHtml(d.hostname)}
                    </div>
                    <span class="device-card-badge ${statusClass}">
                        <span class="status-dot ${statusClass}"></span>
                        ${d.is_online ? 'Online' : 'Offline'}
                    </span>
                </div>
                <div class="device-card-meta">
                    <div class="device-meta-item">
                        <span class="device-meta-label">OS</span>
                        <span class="device-meta-value">${escapeHtml(d.os_name || 'N/A')} ${escapeHtml(d.os_version || '').substring(0, 20)}</span>
                    </div>
                    <div class="device-meta-item">
                        <span class="device-meta-label">Device ID</span>
                        <span class="device-meta-value">#${d.id}</span>
                    </div>
                    <div class="device-meta-item">
                        <span class="device-meta-label">Last Seen</span>
                        <span class="device-meta-value">${lastSeen}</span>
                    </div>
                    <div class="device-meta-item">
                        <span class="device-meta-label">Registered</span>
                        <span class="device-meta-value">${registered}</span>
                    </div>
                </div>
                <div class="device-card-actions">
                    <button class="device-action-btn" onclick="selectDevice(${d.id}); switchView('dashboard');">View Dashboard</button>
                    <button class="device-action-btn danger" onclick="removeDevice(${d.id})">Remove</button>
                </div>
            </div>
        `;
    }).join('');
}

async function removeDevice(deviceId) {
    if (!confirm('Remove this device and all its historical data?')) return;
    try {
        const res = await authFetch(`/api/v1/devices/${deviceId}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('Device Removed', 'Device has been unregistered.', 'success');
            await fetchDeviceList();
        } else {
            showToast('Error', 'Failed to remove device.', 'error');
        }
    } catch (e) {
        showToast('Error', 'Network error removing device.', 'error');
    }
}

// Load settings from LocalStorage
function loadSettingsFromStorage() {
    const savedTheme = localStorage.getItem('observex_theme');
    if (savedTheme) state.theme = savedTheme;
    
    const savedInterval = localStorage.getItem('observex_refresh');
    if (savedInterval) state.refreshInterval = parseFloat(savedInterval);
    
    const savedNotifications = localStorage.getItem('observex_notifications');
    if (savedNotifications !== null) state.notificationsEnabled = savedNotifications === 'true';
    
    const savedLimits = localStorage.getItem('observex_limits');
    if (savedLimits) {
        try {
            state.limits = { ...state.limits, ...JSON.parse(savedLimits) };
        } catch (e) {}
    }
    
    // Sync slider values in DOM
    document.getElementById('setting-refresh').value = state.refreshInterval;
    document.getElementById('refresh-value').textContent = state.refreshInterval.toFixed(1) + ' s';
    
    document.getElementById('setting-theme').value = state.theme;
    
    document.getElementById('setting-notifications-toggle').checked = state.notificationsEnabled;
    
    document.getElementById('limit-cpu').value = state.limits.cpu;
    document.getElementById('limit-cpu-val').textContent = state.limits.cpu + '%';
    
    const cpuWarnInput = document.getElementById('limit-cpu-warn');
    if (cpuWarnInput) {
        cpuWarnInput.value = state.limits.cpuWarn || 55;
        document.getElementById('limit-cpu-warn-val').textContent = (state.limits.cpuWarn || 55) + '%';
    }
    
    document.getElementById('limit-ram').value = state.limits.ram;
    document.getElementById('limit-ram-val').textContent = state.limits.ram + '%';
    
    const ramWarnInput = document.getElementById('limit-ram-warn');
    if (ramWarnInput) {
        ramWarnInput.value = state.limits.ramWarn || 65;
        document.getElementById('limit-ram-warn-val').textContent = (state.limits.ramWarn || 65) + '%';
    }
    
    document.getElementById('limit-disk').value = state.limits.disk;
    document.getElementById('limit-disk-val').textContent = state.limits.disk + '%';
}

// Sync startup status with backend registry query
async function syncStartupSetting() {
    try {
        const res = await fetch('/api/startup');
        const data = await res.json();
        state.startupEnabled = data.enabled;
        document.getElementById('setting-startup').checked = data.enabled;
    } catch (e) {
        console.error("Failed to query startup registry setting:", e);
    }
}

// UI Theme Toggle handler
function initUITheme() {
    document.documentElement.setAttribute('data-theme', state.theme);
}

// Setup navigation triggers and settings inputs listener events
function initEventListeners() {
    // Sidebar Navigation
    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const view = link.getAttribute('data-view');
            switchView(view);
        });
    });
    
    // Device Selector
    const deviceSelector = document.getElementById('device-selector');
    if (deviceSelector) {
        deviceSelector.addEventListener('change', (e) => {
            const val = e.target.value;
            if (val && val !== 'local') {
                selectDevice(parseInt(val));
            }
        });
    }
    
    // Inner Software Tabs
    document.querySelectorAll('.inner-tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.inner-tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active-tab'));
            
            btn.classList.add('active');
            const targetTab = btn.getAttribute('data-tab');
            document.getElementById(`tab-${targetTab}`).classList.add('active-tab');
            
            if (targetTab === 'win-updates') {
                fetchWindowsUpdates();
            } else if (targetTab === 'installed-apps') {
                fetchInstalledApps();
            }
        });
    });
    
    // Refresh Interval Slider
    const refreshSlider = document.getElementById('setting-refresh');
    refreshSlider.addEventListener('input', () => {
        const val = parseFloat(refreshSlider.value);
        state.refreshInterval = val;
        document.getElementById('refresh-value').textContent = val.toFixed(1) + ' s';
        localStorage.setItem('observex_refresh', val);
        
        // Notify WebSocket of interval change if open
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ action: 'set_interval', value: val }));
        }
    });
    
    // Theme Select dropdown
    const themeSelect = document.getElementById('setting-theme');
    themeSelect.addEventListener('change', () => {
        state.theme = themeSelect.value;
        localStorage.setItem('observex_theme', state.theme);
        initUITheme();
        
        // Update Chart color elements
        const isDark = state.theme === 'dark';
        const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
        const labelColor = isDark ? '#8b9bb4' : '#536279';
        
        Object.values(charts).forEach(chart => {
            chart.options.scales.x.grid.color = gridColor;
            chart.options.scales.x.ticks.color = labelColor;
            chart.options.scales.y.grid.color = gridColor;
            chart.options.scales.y.ticks.color = labelColor;
            chart.update('none');
        });
    });
    
    // Startup Windows Autostart Checkbox
    const startupCheck = document.getElementById('setting-startup');
    startupCheck.addEventListener('change', async () => {
        const enabled = startupCheck.checked;
        try {
            const res = await fetch('/api/startup', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled })
            });
            const data = await res.json();
            state.startupEnabled = data.enabled;
            showToast("Startup Setting Sync", `ObserveX startup run was ${enabled ? 'ENABLED' : 'DISABLED'}`, 'success');
        } catch (e) {
            showToast("Startup Registry Error", "Failed to update Windows startup key.", "error");
            startupCheck.checked = !enabled; // revert UI
        }
    });

    // Alert Toggle
    const notifToggle = document.getElementById('setting-notifications-toggle');
    notifToggle.addEventListener('change', () => {
        state.notificationsEnabled = notifToggle.checked;
        localStorage.setItem('observex_notifications', notifToggle.checked);
        if (notifToggle.checked) {
            // Request native permission
            if (Notification.permission === 'default') {
                Notification.requestPermission();
            }
        }
    });
    
    // Limit Threshold Sliders
    const bindThreshold = (sliderId, labelId, limitKey) => {
        const slider = document.getElementById(sliderId);
        slider.addEventListener('input', () => {
            const val = parseInt(slider.value);
            state.limits[limitKey] = val;
            document.getElementById(labelId).textContent = val + '%';
            localStorage.setItem('observex_limits', JSON.stringify(state.limits));
        });
    };
    bindThreshold('limit-cpu', 'limit-cpu-val', 'cpu');
    bindThreshold('limit-cpu-warn', 'limit-cpu-warn-val', 'cpuWarn');
    bindThreshold('limit-ram', 'limit-ram-val', 'ram');
    bindThreshold('limit-ram-warn', 'limit-ram-warn-val', 'ramWarn');
    bindThreshold('limit-disk', 'limit-disk-val', 'disk');
    
    // (Removed process search & status listeners as they are replaced by the 2x2 grid tables)
    
    // Sort columns click handling for process and software tables
    const setupSortHeader = (tableId, statePrefix, renderFunc) => {
        document.querySelectorAll(`#${tableId} th.sortable`).forEach(th => {
            th.addEventListener('click', () => {
                const column = th.getAttribute('data-sort');
                const isDescKey = `${statePrefix}SortDesc`;
                const colKey = `${statePrefix}SortCol`;
                
                if (state[colKey] === column) {
                    state[isDescKey] = !state[isDescKey];
                } else {
                    state[colKey] = column;
                    state[isDescKey] = true;
                }
                
                // Clear indicators and update this header
                document.querySelectorAll(`#${tableId} th.sortable`).forEach(h => {
                    h.classList.remove('sort-asc', 'sort-desc');
                });
                th.classList.add(state[isDescKey] ? 'sort-desc' : 'sort-asc');
                state[`${statePrefix}Page`] = 1;
                renderFunc();
            });
        });
    };
    // (Removed sort header call for process-table)
    setupSortHeader('apps-table', 'app', renderInstalledApps);
    
    // Installed Software Search
    document.getElementById('app-search').addEventListener('input', (e) => {
        state.appSearch = e.target.value.toLowerCase();
        state.appPage = 1;
        renderInstalledApps();
    });
    
    // Event Viewer Filters
    document.getElementById('event-search').addEventListener('input', (e) => {
        state.eventSearch = e.target.value.toLowerCase();
        state.eventPage = 1;
        renderEventLogs();
    });
    document.getElementById('event-filter-severity').addEventListener('change', (e) => {
        state.eventSeverityFilter = e.target.value;
        state.eventPage = 1;
        renderEventLogs();
    });
    document.getElementById('event-filter-source').addEventListener('input', (e) => {
        state.eventSourceFilter = e.target.value.toLowerCase();
        state.eventPage = 1;
        renderEventLogs();
    });
    document.getElementById('event-filter-date').addEventListener('change', (e) => {
        state.eventDateFilter = e.target.value;
        state.eventPage = 1;
        renderEventLogs();
    });
    
    // Windows update sync trigger button
    document.getElementById('refresh-updates-btn').addEventListener('click', async () => {
        const btn = document.getElementById('refresh-updates-btn');
        btn.disabled = true;
        btn.querySelector('span').textContent = 'Syncing...';
        try {
            await fetch('/api/updates/refresh', { method: 'POST' });
            showToast("System Updates Sync", "Scanning Microsoft Update catalog in background thread...", "info");
            // Set brief polling timeout to check status
            setTimeout(checkUpdatesLoading, 3000);
        } catch (e) {
            showToast("Sync Error", "Failed to start update scanner.", "error");
            btn.disabled = false;
            btn.querySelector('span').textContent = 'Sync Updates';
        }
    });

    // Pagination Click Listeners
    const bindPagination = (prevBtnId, nextBtnId, statePrefix, renderFunc) => {
        document.getElementById(prevBtnId).addEventListener('click', () => {
            const pageKey = `${statePrefix}Page`;
            if (state[pageKey] > 1) {
                state[pageKey]--;
                renderFunc();
            }
        });
        document.getElementById(nextBtnId).addEventListener('click', () => {
            const pageKey = `${statePrefix}Page`;
            state[pageKey]++;
            renderFunc();
        });
    };
    // (Removed process pagination bindings)
    bindPagination('apps-prev-page', 'apps-next-page', 'app', renderInstalledApps);
    bindPagination('event-prev-page', 'event-next-page', 'event', renderEventLogs);

    // Power Detail toggle listener
    const powerToggle = document.getElementById('power-detail-toggle');
    if (powerToggle) {
        const savedDetail = localStorage.getItem('observex_power_details');
        const isChecked = savedDetail === 'true'; // default to false
        powerToggle.checked = isChecked;
        
        document.querySelectorAll('.power-detail-item').forEach(el => {
            el.style.display = isChecked ? 'block' : 'none';
        });
        
        powerToggle.addEventListener('change', () => {
            const checked = powerToggle.checked;
            localStorage.setItem('observex_power_details', checked);
            document.querySelectorAll('.power-detail-item').forEach(el => {
                el.style.display = checked ? 'block' : 'none';
            });
        });
    }
    

    // Analytics Time Window Selector Buttons
    document.querySelectorAll('.time-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.time-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.analyticsPeriod = btn.getAttribute('data-period');
            fetchAnalyticsAndTrends();
        });
    });
    
    // Alert Filter & Clear History
    const alertSev = document.getElementById('alert-filter-severity');
    if (alertSev) alertSev.addEventListener('change', fetchAlertHistory);
    
    const btnClearAlerts = document.getElementById('btn-clear-alerts');
    if (btnClearAlerts) {
        btnClearAlerts.addEventListener('click', async () => {
            if (!confirm('Clear all historical alert log records?')) return;
            try {
                const devId = state.selectedDeviceId;
                const url = devId ? `/api/v1/alerts?device_id=${devId}` : `/api/v1/alerts`;
                await authFetch(url, { method: 'DELETE' });
                showToast('Alert History Cleared', 'All alert records have been deleted.', 'success');
                fetchAlertHistory();
            } catch (e) {
                showToast('Error', 'Failed to clear alert log.', 'error');
            }
        });
    }

    // Create Rule Modal & Form
    const btnOpenRule = document.getElementById('btn-open-create-rule-modal');
    const modalRule = document.getElementById('create-rule-modal');
    const closeRule = document.getElementById('create-rule-modal-close');
    const cancelRule = document.getElementById('btn-cancel-create-rule');
    const actionTypeSel = document.getElementById('rule-action-type');
    const targetGroup = document.getElementById('rule-target-group');
    
    if (btnOpenRule && modalRule) {
        btnOpenRule.addEventListener('click', () => modalRule.style.display = 'flex');
        if (closeRule) closeRule.addEventListener('click', () => modalRule.style.display = 'none');
        if (cancelRule) cancelRule.addEventListener('click', () => modalRule.style.display = 'none');
    }
    
    if (actionTypeSel && targetGroup) {
        actionTypeSel.addEventListener('change', () => {
            const val = actionTypeSel.value;
            targetGroup.style.display = (val === 'restart_service' || val === 'kill_process') ? 'block' : 'none';
        });
    }
    
    const formRule = document.getElementById('form-create-rule');
    if (formRule) {
        formRule.addEventListener('submit', async (e) => {
            e.preventDefault();
            const name = document.getElementById('rule-name').value;
            const metric_name = document.getElementById('rule-metric').value;
            const operator = document.getElementById('rule-operator').value;
            const threshold_value = parseFloat(document.getElementById('rule-threshold').value);
            const severity = document.getElementById('rule-severity').value;
            const action_type = document.getElementById('rule-action-type').value;
            const action_target = document.getElementById('rule-action-target').value;
            
            try {
                const res = await authFetch('/api/v1/automation/rules', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        device_id: state.selectedDeviceId || null,
                        name, metric_name, operator, threshold_value, severity, action_type, action_target
                    })
                });
                if (res.ok) {
                    showToast('Rule Created', `Automation rule '${name}' saved successfully.`, 'success');
                    modalRule.style.display = 'none';
                    formRule.reset();
                    fetchAutomationRules();
                }
            } catch (err) {
                showToast('Error', 'Failed to create automation rule.', 'error');
            }
        });
    }
    
    // Incident Filter
    const incFilter = document.getElementById('incident-filter-status');
    if (incFilter) incFilter.addEventListener('change', fetchIncidentHistory);
}

// Background checker for updates sync finish
async function checkUpdatesLoading() {
    try {
        const res = await fetch('/api/updates');
        const data = await res.json();
        if (data.fetching) {
            setTimeout(checkUpdatesLoading, 2000);
        } else {
            const btn = document.getElementById('refresh-updates-btn');
            btn.disabled = false;
            btn.querySelector('span').textContent = 'Sync Updates';
            showToast("Sync Completed", "Updates catalog has been updated.", "success");
            fetchWindowsUpdates();
        }
    } catch (e) {
        document.getElementById('refresh-updates-btn').disabled = false;
    }
}

// Switching view navigation routing
function switchView(view) {
    state.activeView = view;
    
    // Manage sidebar link states
    document.querySelectorAll('.nav-link').forEach(link => {
        if (link.getAttribute('data-view') === view) {
            link.classList.add('active');
        } else {
            link.classList.remove('active');
        }
    });
    
    // Manage section panels
    document.querySelectorAll('.content-view').forEach(viewPanel => {
        viewPanel.classList.remove('active-view');
    });
    document.getElementById(`view-${view}`).classList.add('active-view');
    
    // Update Header Bar
    const titles = {
        dashboard: ["Dashboard Overview", "Real-time system load and execution health."],
        processes: ["Process Monitor", "Active system task lists and process resource threads."],
        hardware: ["Hardware Configuration", "Detailed specifications of installed motherboards, storage, and network adapters."],
        software: ["Software Inventory & Windows Updates", "List of installed applications and Windows patches catalog status."],
        events: ["Windows Event Viewer logs", "Scanning System and Application diagnostic events from Microsoft Event Logs."],
        devices: ["Registered Devices", "All Windows agent machines reporting to this server."],
        admin: ["Admin Portal & User Management", "Enterprise organization summary and user permission controls."],
        analytics: ["Observability & Trend Analytics", "Historical telemetry metrics, downsampled growth trends, and anomaly log correlation."],
        alerts: ["Alert History & Threshold Events", "Historical audit log of system threshold warnings and critical telemetry alerts."],
        automation: ["Intelligent Automation Rules", "Rule-based threshold alerts, automated IT workflows, and remote service remediation."],
        incidents: ["Incident History & Audit Log", "Full lifecycle tracking of open, auto-remediated, and resolved system incidents."],
        settings: ["System Settings", "Configure indicators, warning thresholds, data rates, and autostart."]
    };
    
    document.getElementById('view-title').textContent = titles[view][0];
    document.getElementById('view-subtitle').textContent = titles[view][1];
    
    // Trigger specific page refresh load
    refreshViewContent();
}

function refreshViewContent() {
    if (state.activeView === 'processes') {
        pollProcesses();
    } else if (state.activeView === 'software') {
        const activeInnerTab = document.querySelector('.inner-tab-btn.active').getAttribute('data-tab');
        if (activeInnerTab === 'installed-apps') {
            fetchInstalledApps();
        } else {
            fetchWindowsUpdates();
        }
    } else if (state.activeView === 'events') {
        fetchEventLogs();
    } else if (state.activeView === 'devices') {
        if (state.mode === 'centralized') {
            fetchDeviceList();
        }
    } else if (state.activeView === 'admin') {
        if (state.mode === 'centralized' && state.currentUser && state.currentUser.role === 'admin') {
            fetchAdminOverview();
            fetchAdminUsers();
        }
    } else if (state.activeView === 'analytics') {
        fetchAnalyticsAndTrends();
    } else if (state.activeView === 'alerts') {
        fetchAlertHistory();
    } else if (state.activeView === 'automation') {
        fetchAutomationRules();
    } else if (state.activeView === 'incidents') {
        fetchIncidentHistory();
    }
}

// Heartbeat fetch query loop (standalone mode only)
function startHeartbeatLoop() {
    setInterval(async () => {
        try {
            await fetch('/api/heartbeat', { method: 'POST' });
        } catch (e) {
            console.error("ObserveX: Heartbeat server error:", e);
        }
    }, 2000);
}

// ── Standalone WebSocket Connection (local mode) ──
let ws = null;
function connectWebSocket() {
    const loc = window.location;
    const wsUrl = `ws://${loc.hostname}:${loc.port}/ws/metrics`;
    ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
        console.log("WebSocket connected to live metrics server.");
        ws.send(JSON.stringify({ action: 'set_interval', value: state.refreshInterval }));
    };
    
    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            state.metrics = data;
            updateDashboardDOM(data);
            updateDashboardCharts(data);
            evaluateWarningThresholds(data);
        } catch (e) {
            console.error("WS parse error:", e);
        }
    };
    
    ws.onclose = () => {
        console.log("WebSocket connection closed. Attempting reconnect in 2 seconds...");
        setTimeout(connectWebSocket, 2000);
    };
    
    ws.onerror = (err) => {
        console.error("WS error details:", err);
    };
}

// ── Centralized Dashboard WebSocket (multi-device mode) ──
let dashboardWs = null;
let devicePollInterval = null;

function connectDashboardWebSocket() {
    const loc = window.location;
    const proto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${proto}//${loc.hostname}:${loc.port}/ws/v1/dashboard`;
    dashboardWs = new WebSocket(wsUrl);
    
    dashboardWs.onopen = () => {
        console.log('Dashboard WebSocket connected.');
        // Subscribe to selected device
        if (state.selectedDeviceId) {
            dashboardWs.send(JSON.stringify({ action: 'subscribe', device_id: state.selectedDeviceId }));
        }
    };
    
    dashboardWs.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            
            if (msg.type === 'metrics' && msg.device_id === state.selectedDeviceId) {
                state.metrics = msg.data;
                updateDashboardDOM(msg.data);
                updateDashboardCharts(msg.data);
                evaluateWarningThresholds(msg.data);
            } else if (msg.type === 'processes' && msg.device_id === state.selectedDeviceId) {
                state.processes = msg.data || [];
                renderProcesses();
            } else if (msg.type === 'events' && msg.device_id === state.selectedDeviceId) {
                state.events = msg.data || [];
                renderEventLogs();
            }
        } catch (e) {
            console.error('Dashboard WS parse error:', e);
        }
    };
    
    dashboardWs.onclose = () => {
        console.log('Dashboard WebSocket closed. Reconnecting in 3s...');
        setTimeout(connectDashboardWebSocket, 3000);
    };
    
    dashboardWs.onerror = (err) => {
        console.error('Dashboard WS error:', err);
    };
    
    // Periodically refresh device list to update online/offline status
    if (devicePollInterval) clearInterval(devicePollInterval);
    devicePollInterval = setInterval(async () => {
        await fetchDeviceList();
    }, 15000);
}

// CPU, RAM, Disk rates formatter helper
function formatBytesRate(bytesPerSec) {
    if (bytesPerSec === undefined || isNaN(bytesPerSec)) return '0 B/s';
    if (bytesPerSec >= 1024**3) return `${(bytesPerSec / (1024**3)).toFixed(1)} GB/s`;
    if (bytesPerSec >= 1024**2) return `${(bytesPerSec / (1024**2)).toFixed(1)} MB/s`;
    if (bytesPerSec >= 1024) return `${(bytesPerSec / 1024).toFixed(1)} KB/s`;
    return `${bytesPerSec.toFixed(0)} B/s`;
}

function formatBytes(totalBytes) {
    if (totalBytes === undefined || isNaN(totalBytes)) return '0 B';
    if (totalBytes >= 1024**3) return `${(totalBytes / (1024**3)).toFixed(1)} GB`;
    if (totalBytes >= 1024**2) return `${(totalBytes / (1024**2)).toFixed(0)} MB`;
    if (totalBytes >= 1024) return `${(totalBytes / 1024).toFixed(0)} KB`;
    return `${totalBytes} B`;
}

// Updating primary metrics cards & gauges in Dashboard view
function updateDashboardDOM(data) {
    // Sidebar Header Time & Uptime
    document.getElementById('header-time').textContent = data.current_time.split(' ')[1] || '00:00:00';
    document.getElementById('header-uptime').textContent = data.system_uptime;
    
    // Sidebar Health status Ring
    const healthVal = data.health_score || 0;
    document.getElementById('sidebar-health-val').textContent = healthVal + '%';
    const ring = document.getElementById('sidebar-health-ring');
    ring.setAttribute('stroke-dasharray', `${healthVal}, 100`);
    
    // Change health ring accent color based on health state
    if (healthVal > 85) {
        ring.style.stroke = 'var(--accent-green)';
    } else if (healthVal > 65) {
        ring.style.stroke = 'var(--accent-yellow)';
    } else {
        ring.style.stroke = 'var(--accent-red)';
    }
    
    if (state.activeView !== 'dashboard') return;
    
    // Warning indicator card borders helper
    const setCardWarning = (cardId, isWarning, isCritical) => {
        const card = document.getElementById(cardId);
        if (!card) return;
        if (isCritical) {
            card.style.borderColor = 'rgba(var(--accent-red-rgb), 0.5)';
            card.style.boxShadow = '0 0 15px rgba(var(--accent-red-rgb), 0.15)';
        } else if (isWarning) {
            card.style.borderColor = 'rgba(var(--accent-yellow-rgb), 0.5)';
            card.style.boxShadow = '0 0 15px rgba(var(--accent-yellow-rgb), 0.15)';
        } else {
            card.style.borderColor = '';
            card.style.boxShadow = '';
        }
    };

    // 0. Live Infrastructure Overview Bar (Tabular data binding matching Image 2/5)
    const rawTime = data.current_time.split(' ')[1];
    let formattedTime = rawTime || '--:--:-- --';
    if (rawTime) {
        const [hStr, mStr, sStr] = rawTime.split(':');
        let h = parseInt(hStr);
        const ampm = h >= 12 ? 'PM' : 'AM';
        h = h % 12;
        h = h ? h : 12;
        const hh = h < 10 ? '0' + h : h;
        formattedTime = `${hh}:${mStr}:${sStr} ${ampm}`;
    }
    document.getElementById('overview-time').textContent = formattedTime;
    document.getElementById('overview-machine').textContent = state.computerName || 'ObserveXNode';
    document.getElementById('overview-cpu').textContent = Math.round(data.cpu_usage) + '%';
    document.getElementById('overview-mem').textContent = Math.round(data.ram_usage_percent) + '%';
    document.getElementById('overview-disk-read').textContent = formatBytesRate(data.disk_read_speed);
    document.getElementById('overview-disk-write').textContent = formatBytesRate(data.disk_write_speed);
    document.getElementById('overview-net-sent').textContent = formatBytesRate(data.net_upload_speed);
    document.getElementById('overview-net-recv').textContent = formatBytesRate(data.net_download_speed);

    // 1. CPU Card (Three-tier warnings)
    document.getElementById('cpu-percent-val').textContent = Math.round(data.cpu_usage);
    document.getElementById('cpu-freq').textContent = data.cpu_frequency;
    document.getElementById('cpu-temp-val').textContent = data.cpu_temp;
    
    const cpuSubtitle = document.getElementById('cpu-status-subtitle');
    const cpuCritical = data.cpu_usage > state.limits.cpu;
    const cpuWarning = !cpuCritical && data.cpu_usage > (state.limits.cpuWarn || 55); // moderate load warning
    
    if (cpuCritical) {
        cpuSubtitle.innerHTML = 'Status: <span class="status-crit">High Usage / Critical</span>';
    } else if (cpuWarning) {
        cpuSubtitle.innerHTML = 'Status: <span class="status-warn">Moderate Load / Warning</span>';
    } else {
        cpuSubtitle.innerHTML = 'Status: <span class="status-ok">Normal / Healthy</span>';
    }
    setCardWarning('cpu-card', cpuWarning, cpuCritical);
    
    // 2. Memory Card (Three-tier warnings)
    document.getElementById('ram-percent-val').textContent = Math.round(data.ram_usage_percent);
    document.getElementById('ram-usage-desc').textContent = `${data.ram_used_gb.toFixed(1)} / ${data.ram_total_gb.toFixed(0)} GB`;
    document.getElementById('ram-avail').textContent = `${data.ram_avail_gb.toFixed(1)} GB`;
    
    const ramSubtitle = document.getElementById('ram-status-subtitle');
    const ramCritical = data.ram_usage_percent > state.limits.ram;
    const ramWarning = !ramCritical && data.ram_usage_percent > (state.limits.ramWarn || 65); // moderate load warning
    
    if (ramCritical) {
        ramSubtitle.innerHTML = 'Status: <span class="status-crit">High Usage / Critical</span>';
    } else if (ramWarning) {
        ramSubtitle.innerHTML = 'Status: <span class="status-warn">Moderate Load / Warning</span>';
    } else {
        ramSubtitle.innerHTML = 'Status: <span class="status-ok">Normal / Healthy</span>';
    }
    setCardWarning('ram-card', ramWarning, ramCritical);
    
    // 3. GPU Card (Three-tier warnings)
    document.getElementById('gpu-percent-val').textContent = Math.round(data.gpu_usage);
    document.getElementById('gpu-name').textContent = data.gpu_name;
    document.getElementById('gpu-vram-val').textContent = `${data.gpu_memory_used.toFixed(0)} / ${data.gpu_memory_total.toFixed(0)} MB`;
    document.getElementById('gpu-temp-val').textContent = data.gpu_temp;
    
    const gpuSubtitle = document.getElementById('gpu-status-subtitle');
    const gpuCritical = data.gpu_usage > 80;
    const gpuWarning = !gpuCritical && data.gpu_usage > 45; // 45%-80% is moderate load warning
    
    if (gpuCritical) {
        gpuSubtitle.innerHTML = 'Status: <span class="status-crit">High Load / Hot</span>';
    } else if (gpuWarning) {
        gpuSubtitle.innerHTML = 'Status: <span class="status-warn">Moderate Load / Warning</span>';
    } else {
        gpuSubtitle.innerHTML = 'Status: <span class="status-ok">Normal / Healthy</span>';
    }
    setCardWarning('gpu-card', gpuWarning, gpuCritical);
    
    // 4. Storage Card (Three-tier warnings)
    document.getElementById('disk-percent-val').textContent = Math.round(data.disk_usage_percent);
    document.getElementById('disk-free-val').textContent = `${data.disk_free_gb.toFixed(0)} GB`;
    document.getElementById('disk-used-val').textContent = `${data.disk_used_gb.toFixed(0)} GB`;
    
    const diskSubtitle = document.getElementById('disk-status-subtitle');
    const freePercent = 100 - data.disk_usage_percent;
    const diskCritical = freePercent < state.limits.disk;
    const diskWarning = !diskCritical && freePercent < (state.limits.disk + 15); // Free space low margin warning
    
    if (diskCritical) {
        diskSubtitle.innerHTML = 'Status: <span class="status-crit">Low Free Space</span>';
    } else if (diskWarning) {
        diskSubtitle.innerHTML = 'Status: <span class="status-warn">Moderate / Low Space</span>';
    } else {
        diskSubtitle.innerHTML = 'Status: <span class="status-ok">Normal / Healthy</span>';
    }
    setCardWarning('disk-card', diskWarning, diskCritical);
    
    // 5. Network Card (Three-tier warnings)
    const netTotalSpeed = data.net_download_speed + data.net_upload_speed;
    let netVal = 0, netUnit = " B/s";
    if (netTotalSpeed >= 1024**2) {
        netVal = (netTotalSpeed / (1024**2)).toFixed(1);
        netUnit = " MB/s";
    } else if (netTotalSpeed >= 1024) {
        netVal = (netTotalSpeed / 1024).toFixed(1);
        netUnit = " KB/s";
    } else {
        netVal = netTotalSpeed.toFixed(0);
        netUnit = " B/s";
    }
    document.getElementById('net-io-speed-val').textContent = netVal;
    document.getElementById('net-io-unit-val').textContent = netUnit;
    document.getElementById('net-total-sent').textContent = formatBytes(data.net_bytes_sent);
    document.getElementById('net-total-recv').textContent = formatBytes(data.net_bytes_received);
    
    const netSubtitle = document.getElementById('net-status-subtitle');
    const netCritical = netTotalSpeed > 5 * 1024**2; // > 5 MB/s
    const netWarning = !netCritical && netTotalSpeed > 1 * 1024**2; // > 1 MB/s
    
    if (netCritical) {
        netSubtitle.innerHTML = 'Status: <span class="status-crit">Heavy I/O Transfer</span>';
    } else if (netWarning) {
        netSubtitle.innerHTML = 'Status: <span class="status-warn">Moderate Activity</span>';
    } else {
        netSubtitle.innerHTML = 'Status: <span class="status-ok">Normal / Healthy</span>';
    }
    setCardWarning('network-card', netWarning, netCritical);

    // 6. Power & Battery Card
    document.getElementById('battery-percent-val').textContent = data.battery_percent;
    const bFill = document.getElementById('battery-fill');
    bFill.style.width = data.battery_percent + '%';
    
    // Status colors for battery cell level
    if (data.battery_percent <= 15) {
        bFill.style.backgroundColor = '#ff3d00';
    } else if (data.battery_percent <= 40) {
        bFill.style.backgroundColor = '#ffaa00';
    } else {
        bFill.style.backgroundColor = '#00e676';
    }
    
    const bBadge = document.getElementById('battery-status-badge');
    const bLightning = document.getElementById('battery-lightning-icon');
    const batteryStatusSubtitle = document.getElementById('battery-status-subtitle');
    
    const battCritical = !data.battery_plugged && data.battery_percent <= 15;
    const battWarning = !data.battery_plugged && data.battery_percent <= 40;
    
    bBadge.textContent = data.battery_plugged ? "Charging" : "Discharging";
    if (data.battery_plugged) {
        bLightning.style.display = 'flex';
        if (batteryStatusSubtitle) {
            batteryStatusSubtitle.innerHTML = 'Status: <span class="status-ok">' + data.battery_time_left + '</span>';
        }
        document.getElementById('watt-adapter-container-tiny').style.display = 'block';
    } else {
        bLightning.style.display = 'none';
        if (batteryStatusSubtitle) {
            if (battCritical) {
                batteryStatusSubtitle.innerHTML = 'Remaining: <span class="status-crit">' + data.battery_time_left + '</span>';
            } else if (battWarning) {
                batteryStatusSubtitle.innerHTML = 'Remaining: <span class="status-warn">' + data.battery_time_left + '</span>';
            } else {
                batteryStatusSubtitle.innerHTML = 'Remaining: <span class="status-ok">' + data.battery_time_left + '</span>';
            }
        }
        document.getElementById('watt-adapter-container-tiny').style.display = 'none';
    }
    
    document.getElementById('watt-total-val').textContent = data.power_total_w.toFixed(1) + ' W';
    document.getElementById('watt-cpu-val').textContent = data.power_cpu_w.toFixed(1) + ' W';
    document.getElementById('watt-gpu-val').textContent = data.power_gpu_w.toFixed(1) + ' W';
    document.getElementById('watt-charging-val').textContent = data.power_charging_w.toFixed(1) + ' W';
    
    setCardWarning('power-battery-card', battWarning, battCritical);
}

// Evaluate limits and trigger browser alerts
function evaluateWarningThresholds(data) {
    const now = Date.now();
    const alert = (key, msg, type = 'warning') => {
        if (now - state.lastAlertTimes[key] > state.alertCooldownMs) {
            state.lastAlertTimes[key] = now;
            
            // In-app Toast warning
            showToast(`System Alert: ${key.toUpperCase()}`, msg, type === 'critical' ? 'error' : 'warning');
            
            // HTML5 notification
            if (state.notificationsEnabled && Notification.permission === 'granted') {
                new Notification(`ObserveX - System warning: ${key.toUpperCase()}`, {
                    body: msg,
                    icon: '/static/favicon.ico' // placeholder
                });
            }
        }
    };
    
    // CPU
    if (data.cpu_usage > state.limits.cpu) {
        alert('cpu', `CPU utilization is high at ${Math.round(data.cpu_usage)}% (Threshold: ${state.limits.cpu}%)`, 'critical');
    }
    
    // RAM
    if (data.ram_usage_percent > state.limits.ram) {
        alert('ram', `RAM utilization is high at ${Math.round(data.ram_usage_percent)}% (Threshold: ${state.limits.ram}%)`, 'critical');
    }
    
    // Disk Space
    const freePercent = 100 - data.disk_usage_percent;
    if (freePercent < state.limits.disk) {
        alert('disk', `Free Storage is critically low at ${freePercent.toFixed(1)}% (Threshold: ${state.limits.disk}%)`, 'critical');
    }
    
    // CPU Temperature
    if (data.cpu_temp && !data.cpu_temp.includes('N/A')) {
        const temp = parseFloat(data.cpu_temp);
        if (!isNaN(temp) && temp > state.limits.cpu_temp) {
            alert('cpu_temp', `CPU Temperature is high at ${temp}°C (Threshold: ${state.limits.cpu_temp}°C)`, 'critical');
        }
    }
    
    // Network connectivity
    if (!data.network_connected) {
        alert('network', `Local Network adapter disconnected. No internet access.`, 'warning');
    }

    // Battery low status
    if (!data.battery_plugged && data.battery_percent <= 15) {
        alert('battery', `Low battery warning! Level is at ${data.battery_percent}%. Connect your power adapter.`, 'critical');
    }
}

// Custom Toast notification widget helper
function showToast(title, body, type = 'warning') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    toast.innerHTML = `
        <div class="toast-head">
            <h4>${title}</h4>
            <span class="toast-close">&times;</span>
        </div>
        <div class="toast-body">${body}</div>
    `;
    
    // Bind close
    toast.querySelector('.toast-close').addEventListener('click', () => {
        toast.style.transform = 'translateX(120%)';
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    });
    
    container.appendChild(toast);
    
    // Auto remove after 5 seconds
    setTimeout(() => {
        if (toast.parentNode) {
            toast.style.transform = 'translateX(120%)';
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 300);
        }
    }, 5000);
}

// Chart.js Setup and Data Points update
function initCharts(firstMetrics = null) {
    const isDark = state.theme === 'dark';
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
    const labelColor = isDark ? '#8b9bb4' : '#536279';
    
    const chartOptions = (yMax = null, formatType = 'percent') => ({
        responsive: true,
        maintainAspectRatio: false,
        animation: {
            duration: 0
        },
        elements: {
            point: { radius: 0 },
            line: { tension: 0.15, borderWidth: 2 }
        },
        scales: {
            x: {
                type: 'category',
                grid: { display: false, color: gridColor },
                ticks: { display: false, color: labelColor }
            },
            y: {
                min: 0,
                max: yMax,
                grid: { color: gridColor },
                ticks: {
                    color: labelColor,
                    callback: function(value) {
                        if (formatType === 'speed') {
                            if (value >= 1024**2) return (value / (1024**2)).toFixed(0) + ' MB/s';
                            if (value >= 1024) return (value / 1024).toFixed(0) + ' KB/s';
                            return value + ' B/s';
                        }
                        return value + '%';
                    }
                }
            }
        },
        plugins: {
            legend: {
                display: true,
                position: 'top',
                labels: { boxWidth: 10, font: { size: 10 }, color: labelColor }
            }
        }
    });

    const labels = Array(maxChartPoints).fill('');

    // 1. CPU Chart
    const ctx1 = document.getElementById('cpuChart');
    if (ctx1) {
        charts.cpu = new Chart(ctx1.getContext('2d'), {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'CPU Usage',
                    data: Array(maxChartPoints).fill(firstMetrics ? firstMetrics.cpu_usage : 0),
                    borderColor: '#0088ff',
                    backgroundColor: 'rgba(0, 136, 255, 0.05)',
                    fill: true
                }]
            },
            options: chartOptions(100)
        });
    }

    // 2. Memory Chart
    const ctxMem = document.getElementById('memChart');
    if (ctxMem) {
        charts.mem = new Chart(ctxMem.getContext('2d'), {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Memory Usage',
                    data: Array(maxChartPoints).fill(firstMetrics ? firstMetrics.ram_usage_percent : 0),
                    borderColor: '#00e676',
                    backgroundColor: 'rgba(0, 230, 118, 0.05)',
                    fill: true
                }]
            },
            options: chartOptions(100)
        });
    }

    // 3. GPU Chart
    const ctx2 = document.getElementById('gpuChart');
    if (ctx2) {
        charts.gpu = new Chart(ctx2.getContext('2d'), {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'GPU Utilization',
                    data: Array(maxChartPoints).fill(firstMetrics ? firstMetrics.gpu_usage : 0),
                    borderColor: '#e040fb',
                    backgroundColor: 'rgba(224, 64, 251, 0.05)',
                    fill: true
                }]
            },
            options: chartOptions(100)
        });
    }

    // 4. Network Chart
    const ctx3 = document.getElementById('netChart');
    if (ctx3) {
        charts.network = new Chart(ctx3.getContext('2d'), {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Upload Rate',
                        data: Array(maxChartPoints).fill(firstMetrics ? firstMetrics.net_upload_speed : 0),
                        borderColor: '#ffaa00',
                        fill: false
                    },
                    {
                        label: 'Download Rate',
                        data: Array(maxChartPoints).fill(firstMetrics ? firstMetrics.net_download_speed : 0),
                        borderColor: '#00e676',
                        fill: false
                    }
                ]
            },
            options: chartOptions(null, 'speed')
        });
    }

    // 5. Disk Chart
    const ctx4 = document.getElementById('diskChart');
    if (ctx4) {
        charts.disk = new Chart(ctx4.getContext('2d'), {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Disk Read Rate',
                        data: Array(maxChartPoints).fill(firstMetrics ? firstMetrics.disk_read_speed : 0),
                        borderColor: '#0088ff',
                        fill: false
                    },
                    {
                        label: 'Disk Write Rate',
                        data: Array(maxChartPoints).fill(firstMetrics ? firstMetrics.disk_write_speed : 0),
                        borderColor: '#ff4d4d',
                        fill: false
                    }
                ]
            },
            options: chartOptions(null, 'speed')
        });
    }
}

function updateDashboardCharts(data) {
    if (state.activeView !== 'dashboard') return;
    
    // Lazily instantiate charts on first telemetry frame
    if (Object.keys(charts).length === 0) {
        initCharts(data);
        return;
    }
    
    const updateLineData = (chartInstance, datasetIndex, newValue) => {
        if (!chartInstance) return;
        const dataset = chartInstance.data.datasets[datasetIndex].data;
        dataset.shift();
        dataset.push(newValue);
    };

    const smoothUpdateOptions = {
        duration: 0
    };

    if (charts.cpu) {
        updateLineData(charts.cpu, 0, data.cpu_usage);
        charts.cpu.update(smoothUpdateOptions);
    }

    if (charts.mem) {
        updateLineData(charts.mem, 0, data.ram_usage_percent);
        charts.mem.update(smoothUpdateOptions);
    }

    if (charts.gpu) {
        updateLineData(charts.gpu, 0, data.gpu_usage);
        charts.gpu.update(smoothUpdateOptions);
    }

    if (charts.network) {
        updateLineData(charts.network, 0, data.net_upload_speed);
        updateLineData(charts.network, 1, data.net_download_speed);
        charts.network.update(smoothUpdateOptions);
    }

    if (charts.disk) {
        updateLineData(charts.disk, 0, data.disk_read_speed);
        updateLineData(charts.disk, 1, data.disk_write_speed);
        charts.disk.update(smoothUpdateOptions);
    }
}

// Processes Monitor REST Poller and Render
let processIntervalId = null;
function pollProcesses() {
    // Clear old loop
    if (processIntervalId) clearInterval(processIntervalId);
    
    if (state.mode === 'centralized') {
        // In centralized mode, request processes via dashboard WS
        if (dashboardWs && dashboardWs.readyState === WebSocket.OPEN && state.selectedDeviceId) {
            dashboardWs.send(JSON.stringify({ action: 'get_processes', device_id: state.selectedDeviceId }));
        }
        // Poll via WS every 3 seconds
        processIntervalId = setInterval(() => {
            if (state.activeView !== 'processes') { clearInterval(processIntervalId); return; }
            if (dashboardWs && dashboardWs.readyState === WebSocket.OPEN && state.selectedDeviceId) {
                dashboardWs.send(JSON.stringify({ action: 'get_processes', device_id: state.selectedDeviceId }));
            }
        }, 3000);
        return;
    }
    
    const query = async () => {
        if (state.activeView !== 'processes') {
            clearInterval(processIntervalId);
            return;
        }
        try {
            const res = await fetch('/api/processes');
            const data = await res.json();
            state.processes = data;
            renderProcesses();
        } catch (e) {
            console.error("Error polling process list:", e);
        }
    };
    
    // Poll immediately, then every second
    query();
    processIntervalId = setInterval(query, 1000);
}

function renderProcesses() {
    const list = state.processes || [];
    
    // Get formatted local time for the "Time" column (e.g. 05:59 PM)
    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    
    // 1. Top Processes - CPU (Sorted by cpu_usage descending)
    const cpuSorted = [...list].sort((a, b) => b.cpu_usage - a.cpu_usage).slice(0, 7);
    const cpuBody = document.getElementById('body-proc-cpu');
    if (cpuBody) {
        cpuBody.innerHTML = cpuSorted.map(p => `
            <tr>
                <td>${timeStr}</td>
                <td><a href="#" class="process-link" title="${escapeHtml(p.path)}">${escapeHtml(p.name)}</a></td>
                <td class="text-right text-secondary">${p.threads}</td>
                <td class="text-right"><strong>${p.cpu_usage.toFixed(1)}%</strong></td>
            </tr>
        `).join('') || '<tr><td colspan="4" class="loading-cell">No active processes</td></tr>';
    }

    // 2. Top Processes - Memory (Sorted by memory_mb descending)
    const memSorted = [...list].sort((a, b) => b.memory_mb - a.memory_mb).slice(0, 7);
    const memBody = document.getElementById('body-proc-mem');
    if (memBody) {
        memBody.innerHTML = memSorted.map(p => `
            <tr>
                <td>${timeStr}</td>
                <td><a href="#" class="process-link" title="${escapeHtml(p.path)}">${escapeHtml(p.name)}</a></td>
                <td class="text-right text-secondary">${p.commit_mb.toFixed(1)} MB</td>
                <td class="text-right"><strong>${p.memory_mb.toFixed(1)} MB</strong></td>
            </tr>
        `).join('') || '<tr><td colspan="4" class="loading-cell">No active processes</td></tr>';
    }

    // 3. Disk Activity (Sorted by read_speed + write_speed descending)
    const diskSorted = [...list].sort((a, b) => (b.read_speed + b.write_speed) - (a.read_speed + a.write_speed)).slice(0, 7);
    const diskBody = document.getElementById('body-proc-disk');
    if (diskBody) {
        diskBody.innerHTML = diskSorted.map(p => `
            <tr>
                <td>${timeStr}</td>
                <td><a href="#" class="process-link" title="${escapeHtml(p.path)}">${escapeHtml(p.name)}</a></td>
                <td class="text-right text-secondary">${formatBytesRate(p.read_speed)}</td>
                <td class="text-right text-secondary">${formatBytesRate(p.write_speed)}</td>
                <td class="text-right"><strong>${formatBytesRate(p.read_speed + p.write_speed)}</strong></td>
            </tr>
        `).join('') || '<tr><td colspan="5" class="loading-cell">No active I/O processes</td></tr>';
    }

    // 4. Network Activity (Sorted by net_up_speed + net_down_speed descending)
    const netSorted = [...list].sort((a, b) => (b.net_up_speed + b.net_down_speed) - (a.net_up_speed + a.net_down_speed)).slice(0, 7);
    const netBody = document.getElementById('body-proc-net');
    if (netBody) {
        netBody.innerHTML = netSorted.map(p => `
            <tr>
                <td>${timeStr}</td>
                <td><a href="#" class="process-link" title="${escapeHtml(p.path)}">${p.connections > 0 ? escapeHtml(p.name) : '-'}</a></td>
                <td class="text-right text-secondary">${p.connections > 0 ? formatBytesRate(p.net_up_speed) : '-'}</td>
                <td class="text-right text-secondary">${p.connections > 0 ? formatBytesRate(p.net_down_speed) : '-'}</td>
                <td class="text-right"><strong>${p.connections > 0 ? formatBytesRate(p.net_up_speed + p.net_down_speed) : '-'}</strong></td>
            </tr>
        `).join('') || '<tr><td colspan="5" class="loading-cell">No active connection processes</td></tr>';
    }
}

// Fetch Static Hardware specs
async function fetchHardwareSpecs() {
    try {
        let url = '/api/static-info';
        if (state.mode === 'centralized' && state.selectedDeviceId) {
            url = `/api/v1/devices/${state.selectedDeviceId}/static-info`;
        }
        
        const res = await fetch(url);
        const data = await res.json();
        
        // Cache node name for infrastructure overview
        state.computerName = data.computer_name || data.hostname || 'ObserveXNode';
        
        // System Information
        document.getElementById('spec-pc-name').textContent = data.computer_name || 'N/A';
        document.getElementById('spec-os-name').textContent = `${data.os_name || ''} ${data.os_release || ''}`.trim() || 'N/A';
        document.getElementById('spec-os-version').textContent = data.os_version || 'N/A';
        document.getElementById('spec-motherboard').textContent = `${data.motherboard_mfg || ''} ${data.motherboard_product || ''}`.trim() || 'N/A';
        document.getElementById('spec-bios').textContent = data.bios_name ? `${data.bios_name} (v${data.bios_version || ''})` : 'N/A';
        
        // Processor Specs
        document.getElementById('spec-cpu-model').textContent = data.cpu_model || 'N/A';
        document.getElementById('spec-cpu-physical').textContent = data.cpu_cores_physical || 'N/A';
        document.getElementById('spec-cpu-logical').textContent = data.cpu_cores_logical || 'N/A';
        document.getElementById('spec-ram-total').textContent = (data.total_ram_gb || 0) + ' GB';
        document.getElementById('spec-gpu-name').textContent = data.gpu_model || 'N/A';
        
        // Storage list
        const drivesBody = document.getElementById('spec-drives-body');
        if (data.storage_devices && data.storage_devices.length > 0) {
            drivesBody.innerHTML = data.storage_devices.map(d => {
                const isWarn = d.percent > 90;
                return `
                    <tr>
                        <td><strong>${d.device}</strong></td>
                        <td><span class="text-secondary">${d.mountpoint}</span></td>
                        <td>${d.fstype}</td>
                        <td>${d.total_gb} GB</td>
                        <td>${d.used_gb} GB</td>
                        <td>${d.free_gb} GB</td>
                        <td>
                            <span class="status-badge ${isWarn ? 'warning' : 'running'}">
                                ${d.percent}% Full
                            </span>
                        </td>
                    </tr>
                `;
            }).join('');
        } else {
            drivesBody.innerHTML = `<tr><td colspan="7" class="loading-cell">No logical storage device found.</td></tr>`;
        }
        
        // Network list
        const netBody = document.getElementById('spec-network-body');
        if (data.network_adapters && data.network_adapters.length > 0) {
            netBody.innerHTML = data.network_adapters.map(n => {
                const active = n.status === 'Up';
                return `
                    <tr>
                        <td><strong>${escapeHtml(n.name)}</strong></td>
                        <td>${n.ip}</td>
                        <td><span class="text-secondary font-mini">${n.mac}</span></td>
                        <td>
                            <span class="status-badge ${active ? 'running' : 'suspended'}">
                                ${n.status}
                            </span>
                        </td>
                        <td>${n.speed_mbps > 0 ? n.speed_mbps + ' Mbps' : 'N/A'}</td>
                    </tr>
                `;
            }).join('');
        } else {
            netBody.innerHTML = `<tr><td colspan="5" class="loading-cell">No active adapters configured.</td></tr>`;
        }
        
        // Copy CPU details to card once
        const cpuCoresEl = document.getElementById('cpu-cores');
        if (cpuCoresEl) cpuCoresEl.textContent = data.cpu_cores_logical || 'N/A';
        const ramDescEl = document.getElementById('ram-usage-desc');
        if (ramDescEl && data.total_ram_gb) ramDescEl.textContent = `0 / ${data.total_ram_gb.toFixed(0)} GB`;
    } catch (e) {
        console.error("Error fetching hardware specs:", e);
    }
}

// Fetch Software Installed list
async function fetchInstalledApps() {
    const tbody = document.getElementById('apps-table-body');
    if (state.apps.length > 0) {
        renderInstalledApps();
        return;
    }
    
    try {
        let url = '/api/software';
        if (state.mode === 'centralized' && state.selectedDeviceId) {
            url = `/api/v1/devices/${state.selectedDeviceId}/software`;
        }
        const res = await fetch(url);
        const data = await res.json();
        state.apps = data;
        renderInstalledApps();
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="4" class="loading-cell">Error reading Installed Software: ${e}</td></tr>`;
    }
}

function renderInstalledApps() {
    const tbody = document.getElementById('apps-table-body');
    
    // Search
    let filtered = state.apps.filter(app => {
        return app.name.toLowerCase().includes(state.appSearch) || app.publisher.toLowerCase().includes(state.appSearch);
    });
    
    // Sort
    const col = state.appSortCol;
    const desc = state.appSortDesc;
    filtered.sort((a, b) => {
        let valA = a[col].toLowerCase();
        let valB = b[col].toLowerCase();
        if (valA < valB) return desc ? 1 : -1;
        if (valA > valB) return desc ? -1 : 1;
        return 0;
    });
    
    // Count
    document.getElementById('apps-count').textContent = filtered.length;
    
    // Pagination
    const totalItems = filtered.length;
    const maxPage = Math.max(1, Math.ceil(totalItems / state.appPageSize));
    if (state.appPage > maxPage) state.appPage = maxPage;
    
    const startIndex = (state.appPage - 1) * state.appPageSize;
    const paginated = filtered.slice(startIndex, startIndex + state.appPageSize);
    
    document.getElementById('apps-prev-page').disabled = state.appPage === 1;
    document.getElementById('apps-next-page').disabled = state.appPage === maxPage;
    document.getElementById('apps-page-info').textContent = `Page ${state.appPage} of ${maxPage}`;
    
    if (paginated.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" class="loading-cell">No apps matched criteria.</td></tr>`;
        return;
    }
    
    tbody.innerHTML = paginated.map(a => {
        return `
            <tr>
                <td><strong>${escapeHtml(a.name)}</strong></td>
                <td><span class="text-secondary">${escapeHtml(a.version)}</span></td>
                <td>${escapeHtml(a.publisher)}</td>
                <td><span class="text-secondary">${escapeHtml(a.install_date)}</span></td>
            </tr>
        `;
    }).join('');
}

// Fetch Windows update lists
async function fetchWindowsUpdates() {
    const pendingContainer = document.getElementById('pending-list-container');
    const historyBody = document.getElementById('update-history-body');
    
    try {
        const res = await fetch('/api/updates');
        const data = await res.json();
        
        // 1. Render pending updates
        if (data.fetching) {
            pendingContainer.innerHTML = `
                <div class="loading-cell">
                    <div class="spinner"></div>
                    <span>Scanning catalog...</span>
                </div>
            `;
            document.getElementById('refresh-updates-btn').disabled = true;
        } else if (data.pending && data.pending.length > 0) {
            pendingContainer.innerHTML = data.pending.map(p => {
                const urgencyClass = p.mandatory ? 'mandatory-badge' : 'optional-badge';
                return `
                    <div class="update-item-card">
                        <h4>${escapeHtml(p.title)}</h4>
                        <p>${escapeHtml(p.description)}</p>
                        <span class="meta-lbl ${urgencyClass}">
                            ${p.mandatory ? 'Important Alert' : 'Optional Update'}
                        </span>
                    </div>
                `;
            }).join('');
        } else {
            pendingContainer.innerHTML = `
                <div class="loading-cell">
                    <span>No pending Windows updates. Your system is up to date!</span>
                </div>
            `;
        }
        
        // 2. Render update history logs
        if (data.history && data.history.length > 0) {
            historyBody.innerHTML = data.history.map(h => {
                let badgeClass = 'suspended';
                if (h.result === 'Succeeded') badgeClass = 'running';
                else if (h.result === 'Failed' || h.result === 'Aborted') badgeClass = 'error';
                
                return `
                    <tr>
                        <td><strong>${escapeHtml(h.title)}</strong></td>
                        <td><span class="text-secondary font-mini">${escapeHtml(h.date)}</span></td>
                        <td><span class="status-badge ${badgeClass}">${escapeHtml(h.result)}</span></td>
                        <td><span class="badge text-secondary font-mini">${escapeHtml(h.kb_article)}</span></td>
                    </tr>
                `;
            }).join('');
        } else {
            historyBody.innerHTML = `<tr><td colspan="4" class="loading-cell">No history update entries.</td></tr>`;
        }
    } catch (e) {
        pendingContainer.innerHTML = `<div class="loading-cell text-danger">Error querying pending updates.</div>`;
        historyBody.innerHTML = `<tr><td colspan="4" class="loading-cell text-danger">Error querying updates history: ${e}</td></tr>`;
    }
}

// Fetch Windows event viewer logs
async function fetchEventLogs() {
    const tbody = document.getElementById('event-table-body');
    if (state.events.length > 0) {
        renderEventLogs();
        return;
    }
    
    if (state.mode === 'centralized') {
        // In centralized mode, request events via dashboard WS
        if (dashboardWs && dashboardWs.readyState === WebSocket.OPEN && state.selectedDeviceId) {
            dashboardWs.send(JSON.stringify({ action: 'get_events', device_id: state.selectedDeviceId }));
        }
        return;
    }
    
    try {
        const res = await fetch('/api/event-logs');
        const data = await res.json();
        state.events = data;
        renderEventLogs();
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="6" class="loading-cell">Error reading events log channels: ${e}</td></tr>`;
    }
}

function renderEventLogs() {
    const tbody = document.getElementById('event-table-body');
    
    // Search & filter
    let filtered = state.events.filter(ev => {
        // Message check
        const matchesSearch = ev.message.toLowerCase().includes(state.eventSearch);
        
        // Source check
        const matchesSource = ev.source.toLowerCase().includes(state.eventSourceFilter);
        
        // Date check (timestamp formatted: "YYYY-MM-DD HH:MM:SS")
        let matchesDate = true;
        if (state.eventDateFilter) {
            matchesDate = ev.timestamp.startsWith(state.eventDateFilter);
        }
        
        // Severity check
        let matchesSeverity = true;
        if (state.eventSeverityFilter === 'error') {
            matchesSeverity = ev.severity === 'Error' || ev.severity === 'Audit Failure';
        } else if (state.eventSeverityFilter === 'warning') {
            matchesSeverity = ev.severity === 'Warning';
        } else if (state.eventSeverityFilter === 'information') {
            matchesSeverity = ev.severity === 'Information' || ev.severity === 'Audit Success';
        }
        
        return matchesSearch && matchesSource && matchesDate && matchesSeverity;
    });
    
    // Pagination
    const totalItems = filtered.length;
    const maxPage = Math.max(1, Math.ceil(totalItems / state.eventPageSize));
    if (state.eventPage > maxPage) state.eventPage = maxPage;
    
    const startIndex = (state.eventPage - 1) * state.eventPageSize;
    const paginated = filtered.slice(startIndex, startIndex + state.eventPageSize);
    
    document.getElementById('event-prev-page').disabled = state.eventPage === 1;
    document.getElementById('event-next-page').disabled = state.eventPage === maxPage;
    document.getElementById('event-page-info').textContent = `Page ${state.eventPage} of ${maxPage}`;
    
    if (paginated.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="loading-cell">No event viewer logs matched the filters.</td></tr>`;
        return;
    }
    
    tbody.innerHTML = paginated.map(e => {
        let badgeClass = 'suspended';
        if (e.severity === 'Error' || e.severity === 'Audit Failure') badgeClass = 'error';
        else if (e.severity === 'Warning') badgeClass = 'warning';
        else if (e.severity === 'Information' || e.severity === 'Audit Success') badgeClass = 'information';
        
        return `
            <tr>
                <td><span class="text-secondary font-mini">${escapeHtml(e.timestamp)}</span></td>
                <td><strong>${escapeHtml(e.log_type)}</strong></td>
                <td><span class="status-badge ${badgeClass}">${escapeHtml(e.severity)}</span></td>
                <td>${escapeHtml(e.source)}</td>
                <td><span class="badge text-secondary font-mini">${e.event_id}</span></td>
                <td class="text-secondary" title="${escapeHtml(e.message)}">${escapeHtml(e.message)}</td>
            </tr>
        `;
    }).join('');
}

// XSS Sanitizer Helper
function escapeHtml(str) {
    if (!str) return '';
    return str.toString()
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// ── Authentication & User Session ──

async function checkAuthSession() {
    if (!state.authToken) return false;
    try {
        const res = await authFetch('/api/v1/auth/me');
        if (res.ok) {
            const user = await res.json();
            state.currentUser = user;
            updateUserProfileUI();
            return true;
        }
    } catch (e) {
        console.error('Session validation error:', e);
    }
    logoutUser();
    return false;
}

function updateUserProfileUI() {
    const user = state.currentUser;
    if (!user) return;
    
    // Update sidebar profile panel
    const panel = document.getElementById('user-profile-panel');
    const initials = document.getElementById('user-avatar-initials');
    const nameEl = document.getElementById('user-display-name');
    const roleEl = document.getElementById('user-display-role');
    const adminNav = document.getElementById('nav-link-admin');
    
    if (panel) panel.style.display = 'flex';
    if (initials) initials.textContent = (user.full_name || user.username).charAt(0).toUpperCase();
    if (nameEl) nameEl.textContent = user.full_name || user.username;
    if (roleEl) {
        roleEl.textContent = user.role.toUpperCase();
        roleEl.className = `user-role-badge ${user.role}`;
    }
    
    // Display Admin Portal tab only for admin role
    if (adminNav) {
        adminNav.style.display = user.role === 'admin' ? 'flex' : 'none';
    }
}

function showAuthModal() {
    const modal = document.getElementById('auth-modal');
    if (modal) modal.style.display = 'flex';
}

function hideAuthModal() {
    const modal = document.getElementById('auth-modal');
    if (modal) modal.style.display = 'none';
}

function logoutUser() {
    state.authToken = null;
    state.currentUser = null;
    localStorage.removeItem('observex_token');
    
    const panel = document.getElementById('user-profile-panel');
    const adminNav = document.getElementById('nav-link-admin');
    if (panel) panel.style.display = 'none';
    if (adminNav) adminNav.style.display = 'none';
    
    if (state.mode === 'centralized') {
        showAuthModal();
    }
}

function initAuthListeners() {
    // Auth Tab Switcher
    const tabLogin = document.getElementById('auth-tab-login');
    const tabRegister = document.getElementById('auth-tab-register');
    const formLogin = document.getElementById('form-login');
    const formRegister = document.getElementById('form-register');
    const errorMsg = document.getElementById('auth-error-msg');
    
    if (tabLogin && tabRegister) {
        tabLogin.addEventListener('click', () => {
            tabLogin.classList.add('active');
            tabRegister.classList.remove('active');
            formLogin.style.display = 'block';
            formRegister.style.display = 'none';
            if (errorMsg) errorMsg.style.display = 'none';
        });
        tabRegister.addEventListener('click', () => {
            tabRegister.classList.add('active');
            tabLogin.classList.remove('active');
            formRegister.style.display = 'block';
            formLogin.style.display = 'none';
            if (errorMsg) errorMsg.style.display = 'none';
        });
    }
    
    // Login Form
    if (formLogin) {
        formLogin.addEventListener('submit', async (e) => {
            e.preventDefault();
            const username_or_email = document.getElementById('login-username').value;
            const password = document.getElementById('login-password').value;
            
            try {
                const res = await fetch('/api/v1/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username_or_email, password })
                });
                const data = await res.json();
                if (res.ok) {
                    state.authToken = data.access_token;
                    state.currentUser = data.user;
                    localStorage.setItem('observex_token', data.access_token);
                    hideAuthModal();
                    updateUserProfileUI();
                    showToast('Welcome back!', `Signed in as ${state.currentUser.username}`, 'success');
                    await fetchDeviceList();
                    connectDashboardWebSocket();
                } else {
                    if (errorMsg) {
                        errorMsg.textContent = data.detail || 'Login failed';
                        errorMsg.style.display = 'block';
                    }
                }
            } catch (err) {
                if (errorMsg) {
                    errorMsg.textContent = 'Server connection error';
                    errorMsg.style.display = 'block';
                }
            }
        });
    }
    
    // Register Form
    if (formRegister) {
        formRegister.addEventListener('submit', async (e) => {
            e.preventDefault();
            const full_name = document.getElementById('reg-fullname').value;
            const email = document.getElementById('reg-email').value;
            const username = document.getElementById('reg-username').value;
            const password = document.getElementById('reg-password').value;
            
            try {
                const res = await fetch('/api/v1/auth/register', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ full_name, email, username, password })
                });
                const data = await res.json();
                if (res.ok) {
                    showToast('Registration Successful', 'Logging you in...', 'success');
                    // Automatically log in
                    const loginRes = await fetch('/api/v1/auth/login', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username_or_email: username, password })
                    });
                    const loginData = await loginRes.json();
                    if (loginRes.ok) {
                        state.authToken = loginData.access_token;
                        state.currentUser = loginData.user;
                        localStorage.setItem('observex_token', loginData.access_token);
                        hideAuthModal();
                        updateUserProfileUI();
                        await fetchDeviceList();
                        connectDashboardWebSocket();
                    }
                } else {
                    if (errorMsg) {
                        errorMsg.textContent = data.detail || 'Registration failed';
                        errorMsg.style.display = 'block';
                    }
                }
            } catch (err) {
                if (errorMsg) {
                    errorMsg.textContent = 'Server connection error';
                    errorMsg.style.display = 'block';
                }
            }
        });
    }
    
    // Logout Button
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', () => {
            logoutUser();
        });
    }
    
    // Admin Modals & Form listeners
    const btnCreateUser = document.getElementById('btn-create-user');
    const createUserModal = document.getElementById('create-user-modal');
    const createUserClose = document.getElementById('create-user-modal-close');
    const createUserCancel = document.getElementById('btn-cancel-create-user');
    const formCreateUser = document.getElementById('form-create-user');
    
    if (btnCreateUser && createUserModal) {
        btnCreateUser.addEventListener('click', () => createUserModal.style.display = 'flex');
    }
    const closeCreateModal = () => { if (createUserModal) createUserModal.style.display = 'none'; };
    if (createUserClose) createUserClose.addEventListener('click', closeCreateModal);
    if (createUserCancel) createUserCancel.addEventListener('click', closeCreateModal);
    
    if (formCreateUser) {
        formCreateUser.addEventListener('submit', async (e) => {
            e.preventDefault();
            const full_name = document.getElementById('admin-user-fullname').value;
            const email = document.getElementById('admin-user-email').value;
            const username = document.getElementById('admin-user-username').value;
            const password = document.getElementById('admin-user-password').value;
            const role = document.getElementById('admin-user-role').value;
            
            try {
                const res = await authFetch('/api/v1/admin/users', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ full_name, email, username, password, role })
                });
                const data = await res.json();
                if (res.ok) {
                    showToast('User Created', `Added ${data.username} as ${data.role}`, 'success');
                    closeCreateModal();
                    formCreateUser.reset();
                    fetchAdminUsers();
                    fetchAdminOverview();
                } else {
                    showToast('Error', data.detail || 'Failed to create user', 'error');
                }
            } catch (err) {
                showToast('Error', 'Server connection error', 'error');
            }
        });
    }
    
    // Assign Device Modal
    const assignModal = document.getElementById('assign-device-modal');
    const assignClose = document.getElementById('assign-device-modal-close');
    const assignCancel = document.getElementById('btn-cancel-assign-device');
    const formAssign = document.getElementById('form-assign-device');
    
    const closeAssignModal = () => { if (assignModal) assignModal.style.display = 'none'; };
    if (assignClose) assignClose.addEventListener('click', closeAssignModal);
    if (assignCancel) assignCancel.addEventListener('click', closeAssignModal);
    
    if (formAssign) {
        formAssign.addEventListener('submit', async (e) => {
            e.preventDefault();
            const deviceId = parseInt(document.getElementById('assign-device-id').value);
            const assigned_user_id = parseInt(document.getElementById('assign-target-user').value);
            
            try {
                const res = await authFetch(`/api/v1/devices/${deviceId}/assign`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ assigned_user_id })
                });
                if (res.ok) {
                    showToast('Device Assigned', 'Device ownership updated', 'success');
                    closeAssignModal();
                    await fetchDeviceList();
                } else {
                    showToast('Error', 'Failed to assign device', 'error');
                }
            } catch (err) {
                showToast('Error', 'Server error', 'error');
            }
        });
    }
}

// ── Admin Dashboard Rendering ──

async function fetchAdminOverview() {
    try {
        const res = await authFetch('/api/v1/admin/overview');
        if (!res.ok) return;
        const data = await res.json();
        
        document.getElementById('admin-stat-users').textContent = data.total_users;
        document.getElementById('admin-stat-devices').textContent = data.total_devices;
        document.getElementById('admin-stat-online').textContent = `${data.online_devices} / ${data.total_devices}`;
        document.getElementById('admin-stat-health').textContent = `${data.avg_health_score}%`;
    } catch (e) {
        console.error('Error fetching admin overview:', e);
    }
}

async function fetchAdminUsers() {
    const tbody = document.getElementById('admin-users-table-body');
    if (!tbody) return;
    
    try {
        const res = await authFetch('/api/v1/admin/users');
        if (!res.ok) return;
        const users = await res.json();
        state.adminUsers = users;
        
        tbody.innerHTML = users.map(u => {
            const roleBadgeClass = u.role === 'admin' ? 'admin' : 'user';
            const statusClass = u.is_active ? 'running' : 'suspended';
            
            return `
                <tr>
                    <td><strong>${escapeHtml(u.username)}</strong></td>
                    <td>${escapeHtml(u.email)}</td>
                    <td>${escapeHtml(u.full_name || 'N/A')}</td>
                    <td>
                        <select class="custom-select font-mini" onchange="updateUserRole(${u.id}, this.value)" style="width: auto;">
                            <option value="user" ${u.role === 'user' ? 'selected' : ''}>User</option>
                            <option value="admin" ${u.role === 'admin' ? 'selected' : ''}>Admin</option>
                        </select>
                    </td>
                    <td><span class="status-badge ${statusClass}">${u.is_active ? 'Active' : 'Disabled'}</span></td>
                    <td>
                        <button class="device-action-btn danger" onclick="deleteUserAdmin(${u.id})">Delete</button>
                    </td>
                </tr>
            `;
        }).join('');
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="6" class="loading-cell text-danger">Error loading users: ${e}</td></tr>`;
    }
}

async function updateUserRole(userId, newRole) {
    try {
        const res = await authFetch(`/api/v1/admin/users/${userId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ role: newRole })
        });
        if (res.ok) {
            showToast('Role Updated', `User role changed to ${newRole}`, 'success');
            fetchAdminOverview();
        }
    } catch (e) {
        showToast('Error', 'Failed to update user role', 'error');
    }
}

async function deleteUserAdmin(userId) {
    if (!confirm('Are you sure you want to delete this user?')) return;
    try {
        const res = await authFetch(`/api/v1/admin/users/${userId}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('User Deleted', 'User account removed.', 'success');
            fetchAdminUsers();
            fetchAdminOverview();
        }
    } catch (e) {
        showToast('Error', 'Failed to delete user', 'error');
    }
}

function openAssignDeviceModal(deviceId, deviceName) {
    const modal = document.getElementById('assign-device-modal');
    const inputId = document.getElementById('assign-device-id');
    const display = document.getElementById('assign-device-name-display');
    const selectUser = document.getElementById('assign-target-user');
    
    if (modal && inputId && display && selectUser) {
        inputId.value = deviceId;
        display.textContent = deviceName;
        
        // Populate users dropdown
        selectUser.innerHTML = '<option value="0">Unassigned (Organization Pool)</option>';
        if (state.adminUsers) {
            state.adminUsers.forEach(u => {
                selectUser.innerHTML += `<option value="${u.id}">${escapeHtml(u.username)} (${escapeHtml(u.email)})</option>`;
            });
        }
        modal.style.display = 'flex';
    }
}


// ── Part 4: Observability & Trend Analytics ──

state.analyticsPeriod = '1h';

async function fetchAnalyticsAndTrends() {
    const devId = state.selectedDeviceId || (state.devices[0] ? state.devices[0].id : null);
    if (!devId && state.mode === 'centralized') return;
    
    try {
        const url = state.mode === 'centralized'
            ? `/api/v1/devices/${devId}/metrics/trends?period=${state.analyticsPeriod}`
            : `/api/static-info`; // fallback
            
        const res = await authFetch(url);
        if (!res.ok) return;
        const trends = await res.json();
        
        // Render Trend Summary Cards
        const cpuBadge = document.getElementById('trend-cpu-badge');
        if (cpuBadge) {
            const slope = trends.cpu_trend_slope || 0;
            cpuBadge.textContent = `${slope >= 0 ? '+' : ''}${slope}%`;
            cpuBadge.className = `trend-badge ${slope > 5 ? 'negative' : slope < -5 ? '' : 'neutral'}`;
        }
        
        document.getElementById('trend-cpu-avg').textContent = (trends.cpu_avg || 0) + '%';
        document.getElementById('trend-cpu-min').textContent = (trends.cpu_min || 0) + '%';
        document.getElementById('trend-cpu-max').textContent = (trends.cpu_max || 0) + '%';
        
        document.getElementById('trend-ram-avg').textContent = (trends.ram_avg || 0) + '%';
        document.getElementById('trend-ram-min').textContent = (trends.ram_min || 0) + '%';
        document.getElementById('trend-ram-max').textContent = (trends.ram_max || 0) + '%';
        
        document.getElementById('trend-disk-max').textContent = formatBytesRate(trends.disk_write_max || 0);
        document.getElementById('trend-disk-read-max').textContent = formatBytesRate(trends.disk_read_max || 0);
        document.getElementById('trend-disk-write-max').textContent = formatBytesRate(trends.disk_write_max || 0);
        
        document.getElementById('trend-net-max').textContent = formatBytesRate(trends.net_download_max || 0);
        document.getElementById('trend-net-down-max').textContent = formatBytesRate(trends.net_download_max || 0);
        document.getElementById('trend-net-up-max').textContent = formatBytesRate(trends.net_upload_max || 0);
        
        // Fetch historical snapshots for Trend Charts
        const minutes = state.analyticsPeriod === '15m' ? 15 : state.analyticsPeriod === '1h' ? 60 : state.analyticsPeriod === '6h' ? 360 : state.analyticsPeriod === '24h' ? 1440 : 10080;
        const histUrl = state.mode === 'centralized'
            ? `/api/v1/devices/${devId}/metrics?minutes=${minutes}`
            : `/api/static-info`;
            
        const histRes = await authFetch(histUrl);
        if (histRes.ok) {
            const histData = await histRes.json();
            const snapshots = (histData.snapshots || []).slice().reverse();
            renderAnalyticsCharts(snapshots);
        }
    } catch (e) {
        console.error("Error fetching analytics & trends:", e);
    }
}

function renderAnalyticsCharts(snapshots) {
    const cpuCanvas = document.getElementById('chart-analytics-cpu');
    const ramCanvas = document.getElementById('chart-analytics-ram');
    if (!cpuCanvas || !ramCanvas) return;
    
    const labels = snapshots.map(s => new Date(s.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
    const cpuData = snapshots.map(s => s.metrics ? s.metrics.cpu_usage : 0);
    const ramData = snapshots.map(s => s.metrics ? s.metrics.ram_usage_percent : 0);
    
    if (charts.analyticsCpu) charts.analyticsCpu.destroy();
    if (charts.analyticsRam) charts.analyticsRam.destroy();
    
    const chartConfig = (ctx, label, data, color) => new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: label,
                data: data,
                borderColor: color,
                backgroundColor: color.replace('1)', '0.1)'),
                fill: true,
                tension: 0.3,
                pointRadius: 3,
                pointHoverRadius: 6
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            onClick: (e, elements) => {
                if (elements.length > 0) {
                    const idx = elements[0].index;
                    const targetSnap = snapshots[idx];
                    if (targetSnap) {
                        fetchLogCorrelation(targetSnap.timestamp);
                    }
                }
            },
            scales: {
                y: { min: 0, max: 100 }
            }
        }
    });
    
    charts.analyticsCpu = chartConfig(cpuCanvas, 'CPU %', cpuData, 'rgba(0, 180, 216, 1)');
    charts.analyticsRam = chartConfig(ramCanvas, 'RAM %', ramData, 'rgba(157, 78, 221, 1)');
}

async function fetchLogCorrelation(timestampStr) {
    const devId = state.selectedDeviceId || (state.devices[0] ? state.devices[0].id : 1);
    const label = document.getElementById('correlation-timestamp-label');
    const body = document.getElementById('correlation-body');
    if (!label || !body) return;
    
    label.textContent = `Inspecting events correlated with ${new Date(timestampStr).toLocaleString()}`;
    body.innerHTML = '<div class="loading-cell"><div class="spinner"></div><span>Correlating events...</span></div>';
    
    try {
        const url = `/api/v1/devices/${devId}/metrics/correlate?timestamp=${encodeURIComponent(timestampStr)}&window_minutes=5`;
        const res = await authFetch(url);
        if (!res.ok) return;
        const data = await res.json();
        
        const m = data.metrics_at_timestamp || {};
        const events = data.events || [];
        const procs = data.processes || [];
        
        body.innerHTML = `
            <div class="correlation-metrics-summary glass-panel" style="margin-bottom: 12px; padding: 10px 14px;">
                <strong>Snapshot Load:</strong> CPU ${Math.round(m.cpu_usage || 0)}% | RAM ${Math.round(m.ram_usage_percent || 0)}% | Temp ${m.cpu_temp || '--'}°C
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                <div>
                    <h4 style="margin-bottom: 8px; font-size: 0.8rem;" class="text-secondary">Correlated Event Logs (${events.length})</h4>
                    <ul style="list-style: none; padding: 0; font-size: 0.75rem; max-height: 200px; overflow-y: auto;">
                        ${events.length === 0 ? '<li class="text-muted">No diagnostic event entries in window</li>' : events.slice(0, 8).map(e => `
                            <li style="padding: 6px 0; border-bottom: 1px solid var(--card-border);">
                                <span class="severity-badge ${e.severity === 'Error' || e.severity === 'Critical' ? 'critical' : 'warning'}">${escapeHtml(e.severity)}</span>
                                <strong>${escapeHtml(e.source)}</strong>: ${escapeHtml(e.message).substring(0, 80)}...
                            </li>
                        `).join('')}
                    </ul>
                </div>
                <div>
                    <h4 style="margin-bottom: 8px; font-size: 0.8rem;" class="text-secondary">Active Top Processes (${procs.length})</h4>
                    <ul style="list-style: none; padding: 0; font-size: 0.75rem; max-height: 200px; overflow-y: auto;">
                        ${procs.length === 0 ? '<li class="text-muted">No process snapshot data available</li>' : procs.slice(0, 8).map(p => `
                            <li style="padding: 6px 0; border-bottom: 1px solid var(--card-border); display: flex; justify-content: space-between;">
                                <span>${escapeHtml(p.name)}</span>
                                <strong style="color: var(--accent-blue);">${p.cpu_usage ? p.cpu_usage.toFixed(1) : 0}% CPU</strong>
                            </li>
                        `).join('')}
                    </ul>
                </div>
            </div>
        `;
    } catch (e) {
        body.innerHTML = '<div class="no-correlation-msg text-danger">Failed to fetch correlated event logs.</div>';
    }
}

// ── Alert History ──

async function fetchAlertHistory() {
    const tbody = document.getElementById('alerts-table-body');
    if (!tbody) return;
    
    try {
        const severityFilter = document.getElementById('alert-filter-severity').value;
        const devId = state.selectedDeviceId;
        let url = `/api/v1/alerts?limit=100`;
        if (devId) url += `&device_id=${devId}`;
        if (severityFilter !== 'all') url += `&severity=${severityFilter}`;
        
        const res = await authFetch(url);
        if (!res.ok) return;
        const alerts = await res.json();
        
        if (alerts.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" class="no-data-cell">No historic threshold alerts logged.</td></tr>`;
            return;
        }
        
        tbody.innerHTML = alerts.map(a => `
            <tr>
                <td><span class="text-secondary font-mini">${new Date(a.timestamp).toLocaleString()}</span></td>
                <td><span class="severity-badge ${a.severity.toLowerCase()}">${escapeHtml(a.severity)}</span></td>
                <td><strong style="text-transform: uppercase;">${escapeHtml(a.alert_type)}</strong></td>
                <td>${escapeHtml(a.message)}</td>
                <td>
                    <button class="btn btn-secondary btn-sm" onclick="fetchLogCorrelation('${a.timestamp}'); switchView('analytics');">Inspect</button>
                    <button class="btn btn-danger btn-sm" onclick="deleteAlertRecord(${a.id})">Delete</button>
                </td>
            </tr>
        `).join('');
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="5" class="error-cell">Error loading alert history.</td></tr>`;
    }
}

async function deleteAlertRecord(alertId) {
    try {
        const res = await authFetch(`/api/v1/alerts/${alertId}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('Alert Deleted', 'Alert entry removed.', 'success');
            fetchAlertHistory();
        }
    } catch (e) {
        showToast('Error', 'Failed to delete alert record.', 'error');
    }
}


// ── Part 5 Automation & Incident Handlers ──

async function fetchAutomationRules() {
    const grid = document.getElementById('automation-rules-grid');
    if (!grid) return;
    try {
        const devId = state.selectedDeviceId;
        const url = devId ? `/api/v1/automation/rules?device_id=${devId}` : `/api/v1/automation/rules`;
        const res = await authFetch(url);
        if (!res.ok) throw new Error('Failed to load rules');
        const rules = await res.json();
        
        if (rules.length === 0) {
            grid.innerHTML = `
                <div class="glass-panel" style="grid-column: span 2; padding: 24px; text-align: center; color: var(--text-secondary);">
                    No automation rules defined yet. Click <strong>+ New Rule</strong> above to add intelligent alert rules.
                </div>`;
            return;
        }
        
        grid.innerHTML = rules.map(rule => `
            <div class="glass-panel" style="padding: 20px; border-radius: 14px; display: flex; flex-direction: column; justify-content: space-between; border: 1px solid var(--card-border);">
                <div>
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px;">
                        <h4 style="font-size: 1.05rem; font-weight: 700; color: var(--text-primary); margin: 0;">${escapeHtml(rule.name)}</h4>
                        <span class="severity-badge ${rule.severity}">${rule.severity.toUpperCase()}</span>
                    </div>
                    <p style="font-size: 0.9rem; color: var(--text-secondary); margin-bottom: 14px;">
                        Trigger condition: <strong>${escapeHtml(rule.metric_name)}</strong> ${rule.operator} <strong>${rule.threshold_value}</strong>
                    </p>
                    <div style="font-size: 0.85rem; color: var(--text-muted); background: var(--input-bg); padding: 8px 12px; border-radius: 8px;">
                        ⚡ Automated Remediation: <strong style="color: var(--accent-blue);">${escapeHtml(rule.action_type)}</strong> ${rule.action_target ? `(${escapeHtml(rule.action_target)})` : ''}
                    </div>
                </div>
                <div style="margin-top: 16px; display: flex; justify-content: flex-end;">
                    <button class="btn btn-danger btn-sm" onclick="deleteAutomationRule(${rule.id})">Delete Rule</button>
                </div>
            </div>
        `).join('');
    } catch (e) {
        grid.innerHTML = `
            <div class="glass-panel" style="grid-column: 1 / -1; padding: 28px; text-align: center; color: var(--text-secondary); border-radius: 14px;">
                No active automation rules found. Click <strong>+ New Rule</strong> above to create custom remediation workflows.
            </div>`;
    }
}

async function deleteAutomationRule(ruleId) {
    if (!confirm('Delete this automation rule?')) return;
    try {
        const res = await authFetch(`/api/v1/automation/rules/${ruleId}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('Rule Deleted', 'Automation rule removed.', 'success');
            fetchAutomationRules();
        }
    } catch (e) {
        showToast('Error', 'Failed to delete rule.', 'error');
    }
}

async function fetchIncidentHistory() {
    const tbody = document.getElementById('incidents-table-body');
    if (!tbody) return;
    try {
        const devId = state.selectedDeviceId;
        const statusFilter = document.getElementById('incident-filter-status')?.value || 'all';
        let url = `/api/v1/automation/incidents?limit=50`;
        if (devId) url += `&device_id=${devId}`;
        if (statusFilter !== 'all') url += `&status=${statusFilter}`;
        
        const res = await authFetch(url);
        if (!res.ok) throw new Error('Failed to load incidents');
        const incidents = await res.json();
        
        if (incidents.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted" style="padding: 24px;">No incident audit records found.</td></tr>`;
            return;
        }
        
        tbody.innerHTML = incidents.map(inc => `
            <tr>
                <td>${new Date(inc.triggered_at).toLocaleString()}</td>
                <td style="font-weight: 600; color: var(--text-primary);">${inc.title}</td>
                <td><span class="severity-badge ${inc.severity}">${inc.severity.toUpperCase()}</span></td>
                <td>
                    <span class="status-badge ${inc.status === 'auto_remediated' ? 'online' : (inc.status === 'resolved' ? 'online' : 'offline')}">
                        ${inc.status.replace('_', ' ').toUpperCase()}
                    </span>
                </td>
                <td style="font-family: monospace; font-size: 0.8rem; color: var(--text-secondary);">${inc.log_output || 'No output log'}</td>
                <td>
                    ${inc.status === 'open' ? `<button class="btn btn-secondary btn-sm" onclick="resolveIncident(${inc.id})">Mark Resolved</button>` : `<span class="text-muted font-mini">Resolved</span>`}
                </td>
            </tr>
        `).join('');
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="6" class="error-cell">Error loading incident history.</td></tr>`;
    }
}

async function resolveIncident(incidentId) {
    try {
        const res = await authFetch(`/api/v1/automation/incidents/${incidentId}/resolve`, { method: 'POST' });
        if (res.ok) {
            showToast('Incident Resolved', 'Incident status updated to resolved.', 'success');
            fetchIncidentHistory();
        }
    } catch (e) {
        showToast('Error', 'Failed to resolve incident.', 'error');
    }
}

async function triggerQuickAction(actionType, target = null) {
    const devId = state.selectedDeviceId || 1;
    try {
        const res = await authFetch('/api/v1/automation/trigger-action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device_id: devId, action_type: actionType, target: target })
        });
        if (res.ok) {
            const data = await res.json();
            showToast('Action Dispatched', `Remediation command '${actionType}' sent to device.`, 'success');
            if (state.activeView === 'incidents') fetchIncidentHistory();
        }
    } catch (e) {
        showToast('Error', 'Failed to dispatch remediation command.', 'error');
    }
}

function promptQuickAction(actionType) {
    const promptMsg = actionType === 'restart_service' ? 'Enter Windows Service name to restart (e.g. wuauserv):' : 'Enter Process name to terminate (e.g. notepad.exe):';
    const target = prompt(promptMsg);
    if (target && target.trim()) {
        triggerQuickAction(actionType, target.trim());
    }
}

function triggerDesktopNotification(title, body) {
    if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(title, { body: body, icon: '/static/favicon.ico' });
    } else if ('Notification' in window && Notification.permission !== 'denied') {
        Notification.requestPermission().then(permission => {
            if (permission === 'granted') {
                new Notification(title, { body: body, icon: '/static/favicon.ico' });
            }
        });
    }
}



