// ObserveX Frontend State Management

const state = {
    activeView: 'dashboard',
    refreshInterval: 1.0, // seconds
    theme: 'dark',
    startupEnabled: false,
    
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
        ram: 90,
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

// Initialize app when DOM is fully loaded
document.addEventListener('DOMContentLoaded', () => {
    // Start server heartbeat loop immediately to prevent backend shutdown
    startHeartbeatLoop();
    
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
        initCharts();
    } catch (e) {
        console.error("Error initializing charts (possibly offline):", e);
    }
    
    try {
        connectWebSocket();
    } catch (e) {
        console.error("Error connecting websocket:", e);
    }
    
    try {
        fetchHardwareSpecs();
    } catch (e) {
        console.error("Error fetching hardware specs:", e);
    }
    
    try {
        refreshViewContent();
    } catch (e) {
        console.error("Error refreshing view:", e);
    }
    
    try {
        syncStartupSetting();
    } catch (e) {
        console.error("Error syncing startup setting:", e);
    }
});

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
            state.limits = JSON.parse(savedLimits);
        } catch (e) {}
    }
    
    // Sync slider values in DOM
    document.getElementById('setting-refresh').value = state.refreshInterval;
    document.getElementById('refresh-value').textContent = state.refreshInterval.toFixed(1) + ' s';
    
    document.getElementById('setting-theme').value = state.theme;
    
    document.getElementById('setting-notifications-toggle').checked = state.notificationsEnabled;
    
    document.getElementById('limit-cpu').value = state.limits.cpu;
    document.getElementById('limit-cpu-val').textContent = state.limits.cpu + '%';
    
    document.getElementById('limit-ram').value = state.limits.ram;
    document.getElementById('limit-ram-val').textContent = state.limits.ram + '%';
    
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
    bindThreshold('limit-ram', 'limit-ram-val', 'ram');
    bindThreshold('limit-disk', 'limit-disk-val', 'disk');
    
    // Processes Search and Status Filtering
    document.getElementById('process-search').addEventListener('input', (e) => {
        state.procSearch = e.target.value.toLowerCase();
        state.procPage = 1;
        renderProcesses();
    });
    document.getElementById('process-filter-status').addEventListener('change', (e) => {
        state.procStatusFilter = e.target.value;
        state.procPage = 1;
        renderProcesses();
    });
    
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
    setupSortHeader('process-table', 'proc', renderProcesses);
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
    bindPagination('proc-prev-page', 'proc-next-page', 'proc', renderProcesses);
    bindPagination('apps-prev-page', 'apps-next-page', 'app', renderInstalledApps);
    bindPagination('event-prev-page', 'event-next-page', 'event', renderEventLogs);
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
    }
}

// Heartbeat fetch query loop
function startHeartbeatLoop() {
    setInterval(async () => {
        try {
            await fetch('/api/heartbeat', { method: 'POST' });
        } catch (e) {
            console.error("ObserveX: Heartbeat server error:", e);
        }
    }, 2000);
}

// Websocket Connection
let ws = null;
function connectWebSocket() {
    const loc = window.location;
    const wsUrl = `ws://${loc.hostname}:${loc.port}/ws/metrics`;
    ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
        console.log("WebSocket connected to live metrics server.");
        // Set initial interval rate
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
    
    // 1. CPU
    document.getElementById('cpu-percent-val').textContent = Math.round(data.cpu_usage);
    document.getElementById('cpu-bar').style.width = data.cpu_usage + '%';
    document.getElementById('cpu-freq').textContent = data.cpu_frequency;
    document.getElementById('cpu-temp-val').textContent = data.cpu_temp;
    
    // Apply warning indicator colors to cards
    const setCardWarning = (cardId, isWarning, isCritical) => {
        const card = document.getElementById(cardId);
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
    setCardWarning('cpu-card', data.cpu_usage > state.limits.cpu - 10, data.cpu_usage > state.limits.cpu);
    
    // 2. Memory
    document.getElementById('ram-percent-val').textContent = Math.round(data.ram_usage_percent);
    document.getElementById('ram-bar').style.width = data.ram_usage_percent + '%';
    document.getElementById('ram-usage-desc').textContent = `${data.ram_used_gb.toFixed(1)} / ${data.ram_total_gb.toFixed(0)} GB`;
    document.getElementById('ram-avail').textContent = `${data.ram_avail_gb.toFixed(1)} GB`;
    setCardWarning('ram-card', data.ram_usage_percent > state.limits.ram - 10, data.ram_usage_percent > state.limits.ram);
    
    // 3. GPU
    document.getElementById('gpu-name').textContent = data.gpu_name;
    document.getElementById('gpu-percent-val').textContent = Math.round(data.gpu_usage);
    document.getElementById('gpu-bar').style.width = data.gpu_usage + '%';
    document.getElementById('gpu-vram-val').textContent = `${data.gpu_memory_used.toFixed(0)} / ${data.gpu_memory_total.toFixed(0)} MB`;
    document.getElementById('gpu-temp-val').textContent = data.gpu_temp;
    setCardWarning('gpu-card', data.gpu_usage > 85, data.gpu_usage > 95);
    
    // 4. Storage Drive (C:)
    document.getElementById('disk-percent-val').textContent = Math.round(data.disk_usage_percent);
    document.getElementById('disk-bar').style.width = data.disk_usage_percent + '%';
    document.getElementById('disk-free-val').textContent = `${data.disk_free_gb.toFixed(0)} GB`;
    document.getElementById('disk-used-val').textContent = `${data.disk_used_gb.toFixed(0)} GB`;
    setCardWarning('disk-card', (100 - data.disk_usage_percent) < state.limits.disk + 5, (100 - data.disk_usage_percent) < state.limits.disk);
    
    // 5. Speed elements
    document.getElementById('disk-read-val').textContent = formatBytesRate(data.disk_read_speed);
    document.getElementById('disk-write-val').textContent = formatBytesRate(data.disk_write_speed);
    document.getElementById('net-up-val').textContent = formatBytesRate(data.net_upload_speed);
    document.getElementById('net-down-val').textContent = formatBytesRate(data.net_download_speed);
    document.getElementById('net-total-sent').textContent = formatBytes(data.net_bytes_sent);
    document.getElementById('net-total-recv').textContent = formatBytes(data.net_bytes_received);
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
function initCharts() {
    const isDark = state.theme === 'dark';
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
    const labelColor = isDark ? '#8b9bb4' : '#536279';
    
    const chartOptions = (yMax = null, isSpeed = false) => ({
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 }, // Disable animations for real-time scrolling speed
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
                        if (isSpeed) {
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

    // 1. CPU & Memory Chart
    const ctx1 = document.getElementById('cpuMemChart').getContext('2d');
    charts.cpuMem = new Chart(ctx1, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'CPU Usage',
                    data: Array(maxChartPoints).fill(0),
                    borderColor: '#0088ff',
                    backgroundColor: 'rgba(0, 136, 255, 0.05)',
                    fill: true
                },
                {
                    label: 'Memory Usage',
                    data: Array(maxChartPoints).fill(0),
                    borderColor: '#00e676',
                    backgroundColor: 'rgba(0, 230, 118, 0.05)',
                    fill: true
                }
            ]
        },
        options: chartOptions(100)
    });

    // 2. GPU Chart
    const ctx2 = document.getElementById('gpuChart').getContext('2d');
    charts.gpu = new Chart(ctx2, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'GPU Utilization',
                data: Array(maxChartPoints).fill(0),
                borderColor: '#e040fb',
                backgroundColor: 'rgba(224, 64, 251, 0.05)',
                fill: true
            }]
        },
        options: chartOptions(100)
    });

    // 3. Network Chart
    const ctx3 = document.getElementById('netChart').getContext('2d');
    charts.network = new Chart(ctx3, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Upload Rate',
                    data: Array(maxChartPoints).fill(0),
                    borderColor: '#ffaa00',
                    fill: false
                },
                {
                    label: 'Download Rate',
                    data: Array(maxChartPoints).fill(0),
                    borderColor: '#00e676',
                    fill: false
                }
            ]
        },
        options: chartOptions(null, true)
    });

    // 4. Disk Chart
    const ctx4 = document.getElementById('diskChart').getContext('2d');
    charts.disk = new Chart(ctx4, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Disk Read Rate',
                    data: Array(maxChartPoints).fill(0),
                    borderColor: '#0088ff',
                    fill: false
                },
                {
                    label: 'Disk Write Rate',
                    data: Array(maxChartPoints).fill(0),
                    borderColor: '#ff4d4d',
                    fill: false
                }
            ]
        },
        options: chartOptions(null, true)
    });
}

function updateDashboardCharts(data) {
    if (state.activeView !== 'dashboard') return;
    if (!charts.cpuMem || !charts.gpu || !charts.network || !charts.disk) return;
    
    const updateLineData = (chartInstance, datasetIndex, newValue) => {
        const dataset = chartInstance.data.datasets[datasetIndex].data;
        dataset.shift();
        dataset.push(newValue);
    };

    // CPU & RAM
    updateLineData(charts.cpuMem, 0, data.cpu_usage);
    updateLineData(charts.cpuMem, 1, data.ram_usage_percent);
    charts.cpuMem.update('none');

    // GPU
    updateLineData(charts.gpu, 0, data.gpu_usage);
    charts.gpu.update('none');

    // Network (Bytes/sec)
    updateLineData(charts.network, 0, data.net_upload_speed);
    updateLineData(charts.network, 1, data.net_download_speed);
    charts.network.update('none');

    // Disk (Bytes/sec)
    updateLineData(charts.disk, 0, data.disk_read_speed);
    updateLineData(charts.disk, 1, data.disk_write_speed);
    charts.disk.update('none');
}

// Processes Monitor REST Poller and Render
let processIntervalId = null;
function pollProcesses() {
    // Clear old loop
    if (processIntervalId) clearInterval(processIntervalId);
    
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
    const tbody = document.getElementById('process-table-body');
    
    // Search, Filter
    let filtered = state.processes.filter(p => {
        // Name & PID Search
        const matchesSearch = p.name.toLowerCase().includes(state.procSearch) || p.pid.toString().includes(state.procSearch);
        
        // Status Filter
        let matchesStatus = true;
        if (state.procStatusFilter === 'running') {
            matchesStatus = p.status === 'running';
        } else if (state.procStatusFilter === 'suspended') {
            matchesStatus = p.status === 'suspended' || p.status === 'sleeping' || p.status === 'stopped';
        }
        
        return matchesSearch && matchesStatus;
    });
    
    // Sort
    const col = state.procSortCol;
    const desc = state.procSortDesc;
    filtered.sort((a, b) => {
        let valA = a[col];
        let valB = b[col];
        
        // Case insensitive string compare
        if (typeof valA === 'string') {
            valA = valA.toLowerCase();
            valB = valB.toLowerCase();
        }
        
        if (valA < valB) return desc ? 1 : -1;
        if (valA > valB) return desc ? -1 : 1;
        return 0;
    });
    
    // Total Badge
    document.getElementById('process-count').textContent = filtered.length;
    
    // Pagination slicing
    const totalItems = filtered.length;
    const maxPage = Math.max(1, Math.ceil(totalItems / state.procPageSize));
    if (state.procPage > maxPage) state.procPage = maxPage;
    
    const startIndex = (state.procPage - 1) * state.procPageSize;
    const paginated = filtered.slice(startIndex, startIndex + state.procPageSize);
    
    // Button updates
    document.getElementById('proc-prev-page').disabled = state.procPage === 1;
    document.getElementById('proc-next-page').disabled = state.procPage === maxPage;
    document.getElementById('proc-page-info').textContent = `Page ${state.procPage} of ${maxPage}`;
    
    if (paginated.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="loading-cell">No active processes matched criteria.</td></tr>`;
        return;
    }
    
    tbody.innerHTML = paginated.map(p => {
        const badgeClass = p.status === 'running' ? 'running' : 'suspended';
        return `
            <tr>
                <td><strong>${escapeHtml(p.name)}</strong></td>
                <td><span class="text-secondary">${p.pid}</span></td>
                <td><strong>${p.cpu_usage.toFixed(1)}%</strong></td>
                <td>${p.memory_mb.toFixed(1)} MB</td>
                <td>${p.threads}</td>
                <td><span class="status-badge ${badgeClass}">${escapeHtml(p.status)}</span></td>
                <td class="text-secondary font-mini" title="${escapeHtml(p.path)}">${escapeHtml(p.path)}</td>
            </tr>
        `;
    }).join('');
}

// Fetch Static Hardware specs
async function fetchHardwareSpecs() {
    try {
        const res = await fetch('/api/static-info');
        const data = await res.json();
        
        // System Information
        document.getElementById('spec-pc-name').textContent = data.computer_name || 'N/A';
        document.getElementById('spec-os-name').textContent = `${data.os_name} ${data.os_release}` || 'N/A';
        document.getElementById('spec-os-version').textContent = data.os_version || 'N/A';
        document.getElementById('spec-motherboard').textContent = `${data.motherboard_mfg} ${data.motherboard_product}` || 'N/A';
        document.getElementById('spec-bios').textContent = `${data.bios_name} (v${data.bios_version})` || 'N/A';
        
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
        document.getElementById('cpu-cores').textContent = data.cpu_cores_logical;
        document.getElementById('ram-usage-desc').textContent = `0 / ${data.total_ram_gb.toFixed(0)} GB`;
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
        const res = await fetch('/api/software');
        const data = await res.json();
        state.apps = data;
        renderInstalledApps();
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="4" class="loading-cell">Error reading Installed Software from Windows registry: ${e}</td></tr>`;
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
