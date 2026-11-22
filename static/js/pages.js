/**
 * ObserveX — Page Renderers
 * Each page exports a render(container) function called by the router.
 */
const Pages = (() => {
    let _refreshTimer = null;
    let _activeWsCleanup = null;

    // Process Sorting & Filtering State
    let _processSortCol = 'cpu';
    let _processSortDir = 'desc';
    let _processSearchQuery = '';
    let _cachedProcesses = [];
    let _activeDeviceId = null;

    function _clearRefresh() {
        if (_refreshTimer) { clearInterval(_refreshTimer); _refreshTimer = null; }
        if (_activeWsCleanup) { _activeWsCleanup(); _activeWsCleanup = null; }
    }

    function _escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    // ═══════════════════════════════════════════
    //  Dashboard
    // ═══════════════════════════════════════════
    async function renderDashboard(el) {
        el.innerHTML = UI.loading();
        try {
            const ov = await API.overview();
            el.innerHTML = `
                <!-- 4 Top Stat Cards -->
                <div class="stats-grid">
                    <div class="stat-card accent">
                        <div class="stat-icon accent">
                            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
                        </div>
                        <div class="stat-info">
                            <div class="stat-value">${ov.total_devices}</div>
                            <div class="stat-label">Total Devices</div>
                        </div>
                    </div>
                    <div class="stat-card green">
                        <div class="stat-icon green">
                            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                        </div>
                        <div class="stat-info">
                            <div class="stat-value">${ov.online_devices}</div>
                            <div class="stat-label">Online Nodes</div>
                        </div>
                    </div>
                    <div class="stat-card red">
                        <div class="stat-icon red">
                            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
                        </div>
                        <div class="stat-info">
                            <div class="stat-value">${ov.offline_devices}</div>
                            <div class="stat-label">Offline Nodes</div>
                        </div>
                    </div>
                    <div class="stat-card blue">
                        <div class="stat-icon blue">
                            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg>
                        </div>
                        <div class="stat-info">
                            <div class="stat-value">${ov.total_users}</div>
                            <div class="stat-label">Org Users</div>
                        </div>
                    </div>
                </div>

                <!-- Two-Column Operational Layout -->
                <div class="dashboard-layout">
                    <!-- Left Column: Alerts & Fleet Inventory -->
                    <div class="dashboard-main-col">
                        <!-- Recent Alerts Panel -->
                        <div class="panel-card">
                            <div class="panel-header">
                                <span class="panel-title">
                                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
                                    Recent Alerts
                                </span>
                                <a href="#" onclick="Router.navigate('alerts');return false" class="panel-action-link">View All Alerts →</a>
                            </div>
                            <div id="dashboard-alerts">${UI.loading()}</div>
                        </div>

                        <!-- Device Fleet Panel -->
                        <div class="panel-card">
                            <div class="panel-header">
                                <span class="panel-title">
                                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
                                    Device Fleet
                                </span>
                                <a href="#" onclick="Router.navigate('devices');return false" class="panel-action-link">Manage Devices →</a>
                            </div>
                            <div id="dashboard-devices">${UI.loading()}</div>
                        </div>
                    </div>

                    <!-- Right Column: Health Status, Telemetry & Quick Actions -->
                    <div class="dashboard-side-col">
                        <!-- Fleet Health Overview Card -->
                        <div class="panel-card">
                            <div class="panel-header">
                                <span class="panel-title">
                                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                                    Fleet Health Overview
                                </span>
                                <span style="font-size:0.72rem;font-weight:700;color:${ov.offline_devices > 0 ? 'var(--warning)' : 'var(--success)'}">
                                    ${ov.total_devices > 0 && ov.offline_devices === 0 ? '● 100% HEALTHY' : ov.total_devices === 0 ? 'NO DEVICES' : `● ${ov.offline_devices} OFFLINE`}
                                </span>
                            </div>
                            <div class="panel-body">
                                <div style="display:flex;flex-direction:column;gap:10px">
                                    <div style="display:flex;justify-content:space-between;font-size:0.82rem">
                                        <span style="color:var(--text-secondary)">Active Telemetry Stream</span>
                                        <strong style="color:var(--text-primary)">
                                            ${ov.total_devices > 0 ? Math.round((ov.online_devices / ov.total_devices) * 100) : 0}% Online
                                        </strong>
                                    </div>
                                    <div class="metric-bar" style="margin-top:0">
                                        <div class="metric-bar-fill" style="width:${ov.total_devices > 0 ? (ov.online_devices / ov.total_devices) * 100 : 0}%"></div>
                                    </div>
                                    <div style="display:flex;justify-content:space-between;font-size:0.78rem;color:var(--text-secondary);margin-top:2px">
                                        <span>Online Nodes: ${ov.online_devices}</span>
                                        <span>Offline Nodes: ${ov.offline_devices}</span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Platform Telemetry Specs -->
                        <div class="panel-card">
                            <div class="panel-header">
                                <span class="panel-title">
                                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
                                    Platform Observability
                                </span>
                                <span style="font-size:0.7rem;font-weight:700;color:var(--success)">ACTIVE</span>
                            </div>
                            <div class="panel-body">
                                <div class="platform-spec-list">
                                    <div class="platform-spec-item">
                                        <span class="platform-spec-name">Ingestion Stream</span>
                                        <span class="platform-spec-value">
                                            <span class="status-dot-pulse"></span>
                                            WebSockets v1
                                        </span>
                                    </div>
                                    <div class="platform-spec-item">
                                        <span class="platform-spec-name">Telemetry Interval</span>
                                        <span class="platform-spec-value">2.0 seconds</span>
                                    </div>
                                    <div class="platform-spec-item">
                                        <span class="platform-spec-name">Tenant Isolation</span>
                                        <span class="platform-spec-value" style="color:var(--accent-primary)">Database Partitioned</span>
                                    </div>
                                    <div class="platform-spec-item">
                                        <span class="platform-spec-name">Anomaly Engine</span>
                                        <span class="platform-spec-value">AIOps Baseline</span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Quick Actions -->
                        <div class="panel-card">
                            <div class="panel-header">
                                <span class="panel-title">
                                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
                                    Quick Actions
                                </span>
                            </div>
                            <div class="panel-body" style="display:flex;flex-direction:column;gap:8px">
                                <button class="btn btn-secondary btn-sm" onclick="Router.navigate('downloads')" style="justify-content:flex-start">
                                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                                    Agent Downloads Section
                                </button>
                                ${Auth.isAdmin ? `
                                    <button class="btn btn-secondary btn-sm" onclick="Pages.showCreateCodeModal()" style="justify-content:flex-start">
                                        + Generate Enrollment Code
                                    </button>
                                    <button class="btn btn-secondary btn-sm" onclick="Pages.showCreateUserModal()" style="justify-content:flex-start">
                                        + Add Organization User
                                    </button>
                                ` : ''}
                                <button class="btn btn-secondary btn-sm" onclick="Router.navigate('alerts')" style="justify-content:flex-start">
                                    Configure Alert Rules
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            _loadDashboardAlerts();
            _loadDashboardDevices();
        } catch (e) {
            el.innerHTML = `<div class="empty-state"><div class="empty-state-title">Failed to load dashboard</div><p>${e.message}</p></div>`;
        }
    }

    async function _loadDashboardAlerts() {
        const el = document.getElementById('dashboard-alerts');
        if (!el) return;
        try {
            const alerts = await API.listAlerts('?limit=5');
            if (!alerts.length) {
                el.innerHTML = `
                    <div class="empty-panel-state">
                        <div class="empty-panel-icon">
                            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                        </div>
                        <div class="empty-panel-title">All Systems Healthy</div>
                        <div class="empty-panel-desc">No active anomalies or threshold violations detected across your device fleet.</div>
                    </div>
                `;
                return;
            }
            el.innerHTML = UI.table(
                ['Severity', 'Device', 'Type', 'Message', 'Time'],
                alerts.map(a => [
                    UI.severityBadge(a.severity),
                    `<span style="font-family:var(--font-mono);font-size:0.8rem">${a.device_id}</span>`,
                    a.alert_type || '—',
                    `<span style="color:var(--text-primary);font-weight:500">${a.message || '—'}</span>`,
                    UI.timeAgo(a.timestamp),
                ]),
            );
        } catch (_) { el.innerHTML = ''; }
    }

    async function _loadDashboardDevices() {
        const el = document.getElementById('dashboard-devices');
        if (!el) return;
        try {
            const devices = await API.listDevices();
            if (!devices.length) {
                el.innerHTML = `
                    <div class="empty-panel-state">
                        <div class="empty-panel-icon" style="background:var(--accent-primary-dim);color:var(--accent-primary);border-color:var(--border-accent)">
                            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
                        </div>
                        <div class="empty-panel-title">No Enrolled Devices</div>
                        <div class="empty-panel-desc">Download ObserveXAgent.exe and run it with an enrollment code to register this device.</div>
                    </div>
                `;
                return;
            }
            el.innerHTML = UI.table(
                ['Hostname', 'Operating System', 'Status', 'Last Heartbeat', 'Action'],
                devices.map(d => [
                    `<a href="#" onclick="Router.navigate('device-detail',{id:${d.id}});return false" style="font-weight:700;color:var(--text-primary);text-decoration:none;display:flex;align-items:center;gap:6px">
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" style="color:var(--text-tertiary)"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
                        ${d.hostname}
                    </a>`,
                    `<span style="color:var(--text-secondary);font-size:0.8rem">${d.os_name || 'Windows'} ${d.os_version || ''}</span>`,
                    UI.statusBadge(d.is_online ? 'active' : d.status),
                    UI.timeAgo(d.last_seen),
                    `<a href="#" onclick="Router.navigate('device-detail',{id:${d.id}});return false" style="font-size:0.8rem;color:var(--accent-primary);font-weight:600">Inspect →</a>`,
                ]),
                'No devices enrolled yet',
            );
        } catch (_) { el.innerHTML = ''; }
    }

    // ═══════════════════════════════════════════
    //  Devices List
    // ═══════════════════════════════════════════
    async function renderDevices(el) {
        el.innerHTML = UI.loading();
        try {
            const devices = await API.listDevices();
            if (!devices.length) {
                el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📡</div><div class="empty-state-title">No devices enrolled</div><p>Create an enrollment code and install the agent on your devices.</p></div>';
                return;
            }
            el.innerHTML = `<div class="devices-grid">${devices.map(d => _deviceCard(d)).join('')}</div>`;
            el.querySelectorAll('.device-card').forEach(card => {
                card.addEventListener('click', () => {
                    Router.navigate('device-detail', { id: parseInt(card.dataset.id) });
                });
            });
        } catch (e) {
            el.innerHTML = `<div class="empty-state"><div class="empty-state-title">Error</div><p>${e.message}</p></div>`;
        }
    }

    function _deviceCard(d) {
        const statusClass = d.is_online ? 'online' : d.status === 'stale' ? 'stale' : 'offline';
        return `
            <div class="device-card" data-id="${d.id}">
                <div class="device-card-header">
                    <div class="device-hostname">
                        <span class="status-dot ${statusClass}"></span>
                        ${d.hostname}
                    </div>
                    ${UI.statusBadge(d.is_online ? 'active' : d.status)}
                </div>
                <div class="device-meta">
                    <div class="device-meta-row">OS: ${d.os_name || '—'} ${d.os_version || ''}</div>
                    <div class="device-meta-row">Agent: ${d.agent_version || '—'}</div>
                    <div class="device-meta-row">Last seen: ${UI.timeAgo(d.last_seen)}</div>
                </div>
            </div>
        `;
    }

    // ═══════════════════════════════════════════
    //  Device Detail
    // ═══════════════════════════════════════════
    async function renderDeviceDetail(el, params) {
        _clearRefresh();
        const id = params?.id;
        if (!id) { el.innerHTML = '<p>No device selected</p>'; return; }

        el.innerHTML = UI.loading();
        try {
            const device = await API.getDevice(id);
            el.innerHTML = `
                <div class="device-detail-header">
                    <div>
                        <button class="btn btn-ghost btn-sm" onclick="Router.navigate('devices')" style="margin-bottom:var(--space-sm)">← Back to Devices</button>
                        <div class="device-detail-info">
                            <h2>${device.hostname} ${UI.statusBadge(device.is_online ? 'active' : device.status)}</h2>
                            <p style="color:var(--text-secondary);font-size:0.85rem">UUID: ${device.device_uuid} · Registered: ${UI.formatDate(device.registered_at)}</p>
                        </div>
                    </div>
                    ${Auth.isAdmin ? `<button class="btn btn-danger btn-sm" onclick="Pages.confirmDeleteDevice(${id})">Delete Device</button>` : ''}
                </div>

                <div class="tabs">
                    <button class="tab active" data-tab="metrics">Live Metrics</button>
                    <button class="tab" data-tab="processes">Processes</button>
                    <button class="tab" data-tab="events">Events</button>
                    <button class="tab" data-tab="aiops">AIOps</button>
                </div>
                <div id="device-tab-content">${UI.loading()}</div>
            `;

            // Tab switching
            el.querySelectorAll('.tab').forEach(tab => {
                tab.addEventListener('click', () => {
                    el.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                    tab.classList.add('active');
                    _loadDeviceTab(id, tab.dataset.tab);
                });
            });

            _loadDeviceTab(id, 'metrics');

            // WebSocket real-time telemetry subscription
            const devIdNum = parseInt(id);
            if (WS.isConnected) {
                WS.send({ action: 'subscribe', device_id: devIdNum });
            }
            const onWsConnected = () => {
                WS.send({ action: 'subscribe', device_id: devIdNum });
            };
            const onWsTelemetry = (msg) => {
                if (msg.device_id === devIdNum && msg.payload) {
                    const activeTab = el.querySelector('.tab.active')?.dataset.tab;
                    if (activeTab === 'metrics') {
                        const tabContent = document.getElementById('device-tab-content');
                        if (tabContent) _renderMetricsContent(tabContent, msg.payload);
                    }
                }
            };
            WS.on('connected', onWsConnected);
            WS.on('telemetry', onWsTelemetry);

            _activeWsCleanup = () => {
                WS.off('connected', onWsConnected);
                WS.off('telemetry', onWsTelemetry);
                if (WS.isConnected) {
                    WS.send({ action: 'unsubscribe', device_id: devIdNum });
                }
            };

            // Periodic refresh fallback
            _refreshTimer = setInterval(() => {
                const activeTab = el.querySelector('.tab.active')?.dataset.tab;
                if (activeTab === 'metrics' && !WS.isConnected) {
                    _loadDeviceTab(id, 'metrics');
                } else if (activeTab === 'processes') {
                    _loadDeviceTab(id, 'processes');
                }
            }, 3000);
        } catch (e) {
            el.innerHTML = `<div class="empty-state"><div class="empty-state-title">Device not found</div><p>${e.message}</p></div>`;
        }
    }

    function _renderMetricsContent(container, m) {
        if (!container) return;
        const cpuPct = Number(m.cpu_usage ?? m.cpu_percent ?? 0);
        const ramPct = Number(m.ram_usage_percent ?? m.ram_percent ?? 0);
        const diskPct = Number(m.disk_usage_percent ?? m.disk_percent ?? 0);
        const gpuPct = Number(m.gpu_usage ?? m.gpu_percent ?? 0);

        function formatSpeed(bytesPerSec, mbps) {
            if (bytesPerSec != null && !isNaN(bytesPerSec) && Number(bytesPerSec) > 0) {
                const bps = Number(bytesPerSec);
                if (bps >= 1048576) return (bps / 1048576).toFixed(1) + ' MB/s';
                if (bps >= 1024) return (bps / 1024).toFixed(1) + ' KB/s';
                return bps.toFixed(0) + ' B/s';
            }
            if (mbps != null && !isNaN(mbps) && Number(mbps) > 0) return Number(mbps).toFixed(1) + ' Mbps';
            return '0.0 KB/s';
        }

        const cpuFreqStr = m.cpu_frequency || (m.cpu_freq_mhz ? `${Number(m.cpu_freq_mhz).toFixed(0)} MHz` : 'N/A');
        const ramUsedStr = m.ram_used_gb != null ? `${Number(m.ram_used_gb).toFixed(1)} GB` : (m.ram_used ? `${(Number(m.ram_used)/1024).toFixed(1)} GB` : 'N/A');
        const netSentStr = formatSpeed(m.net_upload_speed, m.net_sent_mbps);
        const netRecvStr = formatSpeed(m.net_download_speed, m.net_recv_mbps);
        const diskReadStr = formatSpeed(m.disk_read_speed, m.disk_read_mbps != null ? m.disk_read_mbps * 1048576 : null);
        const diskWriteStr = formatSpeed(m.disk_write_speed, m.disk_write_mbps != null ? m.disk_write_mbps * 1048576 : null);
        const uptimeStr = m.system_uptime || m.uptime_str || (m.uptime_seconds ? UI.formatUptime(m.uptime_seconds) : '—');
        const battStr = m.battery_percent != null ? `${m.battery_percent}%${m.battery_plugged ? ' (AC)' : ''}` : 'N/A';
        const gpuLabel = m.gpu_name && m.gpu_name !== 'N/A' ? ` (${m.gpu_name})` : '';

        container.innerHTML = `
            <div class="metrics-grid">
                <div class="metric-card">
                    <div class="metric-value">${cpuPct.toFixed(1)}%</div>
                    <div class="metric-label">CPU Usage</div>
                    ${UI.metricBar(cpuPct)}
                </div>
                <div class="metric-card">
                    <div class="metric-value">${ramPct.toFixed(1)}%</div>
                    <div class="metric-label">Memory Usage</div>
                    ${UI.metricBar(ramPct)}
                </div>
                <div class="metric-card">
                    <div class="metric-value">${diskPct.toFixed(1)}%</div>
                    <div class="metric-label">Disk Usage</div>
                    ${UI.metricBar(diskPct)}
                </div>
                <div class="metric-card">
                    <div class="metric-value">${gpuPct.toFixed(1)}%</div>
                    <div class="metric-label">GPU Usage${gpuLabel}</div>
                    ${UI.metricBar(gpuPct)}
                </div>
            </div>
            <div class="card" style="margin-top:var(--space-md)">
                <div class="card-title">Additional Metrics</div>
                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:var(--space-md);margin-top:var(--space-md);font-size:0.85rem;color:var(--text-secondary)">
                    <div>CPU Freq: <strong style="color:var(--text-primary)">${cpuFreqStr}</strong></div>
                    <div>RAM Used: <strong style="color:var(--text-primary)">${ramUsedStr}</strong></div>
                    <div>Net Sent: <strong style="color:var(--text-primary)">${netSentStr}</strong></div>
                    <div>Net Recv: <strong style="color:var(--text-primary)">${netRecvStr}</strong></div>
                    <div>Disk Read: <strong style="color:var(--text-primary)">${diskReadStr}</strong></div>
                    <div>Disk Write: <strong style="color:var(--text-primary)">${diskWriteStr}</strong></div>
                    <div>Battery: <strong style="color:var(--text-primary)">${battStr}</strong></div>
                    <div>Uptime: <strong style="color:var(--text-primary)">${uptimeStr}</strong></div>
                </div>
            </div>
        `;
    }

    async function _loadDeviceTab(deviceId, tab) {
        const container = document.getElementById('device-tab-content');
        if (!container) return;

        try {
            if (tab === 'metrics') {
                const data = await API.liveMetrics(deviceId);
                if (data.status === 'no_data') {
                    container.innerHTML = `
                        <div class="offline-device-guide">
                            <div class="offline-guide-header">
                                <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" style="color:var(--warning)"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                                <span class="offline-guide-title">Device Offline &mdash; Awaiting Telemetry Stream</span>
                            </div>
                            <p style="color:var(--text-secondary);font-size:0.88rem;line-height:1.5">
                                This device is registered with your organization but has not sent any active telemetry frames recently. When the ObserveX Windows Agent is running, real-time hardware gauges (CPU, RAM, Disks, Network, GPU) will render here automatically.
                            </p>
                            <div class="offline-guide-steps">
                                <div class="offline-step-item">
                                    <span class="offline-step-number">1</span>
                                    <div><strong>Download Windows Agent:</strong> Get <a href="/api/v1/downloads/agent" download="ObserveXAgent.exe" style="color:var(--accent-primary);text-decoration:underline">ObserveXAgent.exe</a> or the <a href="/api/v1/downloads/agent/zip" download="ObserveXAgent-Windows.zip" style="color:var(--accent-primary);text-decoration:underline">ZIP bundle</a>.</div>
                                </div>
                                <div class="offline-step-item">
                                    <span class="offline-step-number">2</span>
                                    <div><strong>Start the Agent:</strong> Double-click the executable or run it from PowerShell: <code style="font-family:var(--font-mono);background:rgba(0,0,0,0.4);padding:2px 6px;border-radius:4px;color:var(--accent-primary)">.\\ObserveXAgent.exe</code>.</div>
                                </div>
                                <div class="offline-step-item">
                                    <span class="offline-step-number">3</span>
                                    <div><strong>Live Stream:</strong> The agent automatically connects via secure WebSockets and streams metrics every 2.0s.</div>
                                </div>
                            </div>
                        </div>
                    `;
                    return;
                }
                const m = data.metrics?.payload || data.metrics || {};
                _renderMetricsContent(container, m);
            } else if (tab === 'processes') {
                _activeDeviceId = deviceId;
                const data = await API.processes(deviceId);
                _cachedProcesses = data.processes || [];
                _renderProcessTab(container);
            } else if (tab === 'events') {
                const data = await API.events(deviceId);
                if (!data.events.length) {
                    container.innerHTML = '<div class="empty-state"><div class="empty-state-title">No event logs</div></div>';
                    return;
                }
                container.innerHTML = UI.table(
                    ['Source', 'Event ID', 'Level', 'Message', 'Time'],
                    data.events.slice(0, 50).map(e => [
                        e.source || '—', e.event_id || '—',
                        e.level || e.type || '—',
                        `<span style="max-width:300px;display:inline-block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${e.message || '—'}</span>`,
                        e.time_generated || '—',
                    ]),
                );
            } else if (tab === 'aiops') {
                container.innerHTML = UI.loading();
                try {
                    const insights = await API.insights(deviceId);
                    const riskClass = insights.risk_level === 'critical' ? 'critical' : insights.risk_level === 'elevated' ? 'warning' : 'healthy';
                    const riskBadge = `<span class="risk-badge ${insights.risk_level || 'low'}">${(insights.risk_level || 'healthy').toUpperCase()}</span>`;

                    container.innerHTML = `
                        <div class="aiops-card ${riskClass}">
                            <div class="card-header">
                                <div class="card-title">Health Assessment</div>
                                ${riskBadge}
                            </div>
                            <div style="font-size:0.9rem;color:var(--text-secondary)">${insights.summary || 'Insufficient data for analysis.'}</div>
                        </div>
                        ${(insights.recommendations || []).map(r => `
                            <div class="aiops-card">
                                <div style="font-size:0.85rem;color:var(--text-primary)">💡 ${r}</div>
                            </div>
                        `).join('')}
                    `;
                } catch (e) {
                    container.innerHTML = '<div class="empty-state"><div class="empty-state-title">AIOps Analysis</div><p>Not enough telemetry data for analysis yet.</p></div>';
                }
            }
        } catch (e) {
            container.innerHTML = `<div class="empty-state"><p>${e.message}</p></div>`;
        }
    }

    // ── Process Tab Rendering with Interactive Sorting & Search ──
    function _renderProcessTab(container) {
        if (!container) return;
        if (!_cachedProcesses.length) {
            container.innerHTML = '<div class="empty-state"><div class="empty-state-title">No process data</div><p>Awaiting process metrics from the agent.</p></div>';
            return;
        }

        let filtered = _cachedProcesses;
        if (_processSearchQuery) {
            const q = _processSearchQuery.toLowerCase();
            filtered = filtered.filter(p => 
                (p.name && p.name.toLowerCase().includes(q)) ||
                (String(p.pid).includes(q)) ||
                (p.status && p.status.toLowerCase().includes(q))
            );
        }

        filtered = [...filtered].sort((a, b) => {
            let valA, valB;
            if (_processSortCol === 'cpu') {
                valA = Number(a.cpu_percent || 0);
                valB = Number(b.cpu_percent || 0);
            } else if (_processSortCol === 'memory') {
                valA = Number(a.memory_mb || 0);
                valB = Number(b.memory_mb || 0);
            } else if (_processSortCol === 'name') {
                valA = (a.name || '').toLowerCase();
                valB = (b.name || '').toLowerCase();
                return _processSortDir === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
            } else if (_processSortCol === 'pid') {
                valA = Number(a.pid || 0);
                valB = Number(b.pid || 0);
            } else {
                valA = Number(a.cpu_percent || 0);
                valB = Number(b.cpu_percent || 0);
            }
            return _processSortDir === 'asc' ? (valA - valB) : (valB - valA);
        });

        const sortIndicator = (col) => {
            if (_processSortCol !== col) return '';
            return `<span class="sort-indicator">${_processSortDir === 'desc' ? '▼' : '▲'}</span>`;
        };

        const totalCount = _cachedProcesses.length;
        const matchCount = filtered.length;

        const rowsHtml = filtered.slice(0, 100).map(p => `
            <tr>
                <td style="font-family:var(--font-mono);font-size:0.8rem;color:var(--text-tertiary)">${p.pid}</td>
                <td style="font-weight:600;color:var(--text-primary)">
                    ${_escapeHtml(p.name || '—')}
                </td>
                <td>
                    <span style="font-family:var(--font-mono);font-weight:600;color:${Number(p.cpu_percent) > 20 ? 'var(--danger)' : Number(p.cpu_percent) > 5 ? 'var(--warning)' : 'var(--text-primary)'}">
                        ${(Number(p.cpu_percent) || 0).toFixed(1)}%
                    </span>
                </td>
                <td>
                    <span style="font-family:var(--font-mono);color:var(--text-primary)">
                        ${(Number(p.memory_mb) || 0).toFixed(1)} MB
                    </span>
                </td>
                <td>
                    <span class="status-pill ${p.status === 'running' ? 'online' : 'offline'}">
                        ${_escapeHtml(p.status || 'running')}
                    </span>
                </td>
            </tr>
        `).join('');

        const existingTbody = container.querySelector('#process-table-body');
        const searchInput = document.getElementById('process-search-input');
        const isInputFocused = searchInput && searchInput === document.activeElement;

        if (existingTbody && isInputFocused) {
            existingTbody.innerHTML = rowsHtml;
            const countEl = container.querySelector('#process-count-badge');
            if (countEl) countEl.textContent = `${matchCount} of ${totalCount}`;
            return;
        }

        container.innerHTML = `
            <div class="process-toolbar">
                <div class="process-search-box">
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" style="color:var(--text-tertiary)"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                    <input type="text" id="process-search-input" class="process-search-input" placeholder="Search processes by name or PID..." value="${_escapeHtml(_processSearchQuery)}" oninput="Pages.filterProcesses(this.value)">
                    ${_processSearchQuery ? `<button onclick="Pages.filterProcesses('')" style="background:none;border:none;color:var(--text-tertiary);cursor:pointer;padding:0;font-size:1rem" title="Clear search">✕</button>` : ''}
                </div>
                <div class="process-sort-controls">
                    <span class="sort-label">Sort:</span>
                    <button class="sort-pill ${_processSortCol === 'cpu' ? 'active' : ''}" onclick="Pages.sortProcesses('cpu')">
                        CPU % ${_processSortCol === 'cpu' ? (_processSortDir === 'desc' ? '↓' : '↑') : ''}
                    </button>
                    <button class="sort-pill ${_processSortCol === 'memory' ? 'active' : ''}" onclick="Pages.sortProcesses('memory')">
                        Memory ${_processSortCol === 'memory' ? (_processSortDir === 'desc' ? '↓' : '↑') : ''}
                    </button>
                    <button class="sort-pill ${_processSortCol === 'name' ? 'active' : ''}" onclick="Pages.sortProcesses('name')">
                        Name ${_processSortCol === 'name' ? (_processSortDir === 'desc' ? 'Z-A' : 'A-Z') : ''}
                    </button>
                    <button class="sort-pill ${_processSortCol === 'pid' ? 'active' : ''}" onclick="Pages.sortProcesses('pid')">
                        PID ${_processSortCol === 'pid' ? (_processSortDir === 'desc' ? '↓' : '↑') : ''}
                    </button>
                    <span id="process-count-badge" style="font-size:0.75rem;color:var(--text-tertiary);margin-left:8px">
                        ${matchCount} of ${totalCount}
                    </span>
                </div>
            </div>

            <div class="data-table-container">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th class="sortable-th" onclick="Pages.sortProcesses('pid')" title="Click to sort by PID">PID ${sortIndicator('pid')}</th>
                            <th class="sortable-th" onclick="Pages.sortProcesses('name')" title="Click to sort by Process Name">Process Name ${sortIndicator('name')}</th>
                            <th class="sortable-th" onclick="Pages.sortProcesses('cpu')" title="Click to sort by CPU Usage">CPU % ${sortIndicator('cpu')}</th>
                            <th class="sortable-th" onclick="Pages.sortProcesses('memory')" title="Click to sort by Memory Usage">Memory (MB) ${sortIndicator('memory')}</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody id="process-table-body">
                        ${rowsHtml}
                    </tbody>
                </table>
            </div>
        `;
    }

    function sortProcesses(col) {
        if (_processSortCol === col) {
            _processSortDir = _processSortDir === 'desc' ? 'asc' : 'desc';
        } else {
            _processSortCol = col;
            _processSortDir = (col === 'name' || col === 'pid') ? 'asc' : 'desc';
        }
        const container = document.getElementById('device-tab-content');
        _renderProcessTab(container);
    }

    function filterProcesses(query) {
        _processSearchQuery = query;
        const container = document.getElementById('device-tab-content');
        _renderProcessTab(container);
        const input = document.getElementById('process-search-input');
        if (input) {
            input.focus();
            input.setSelectionRange(input.value.length, input.value.length);
        }
    }

    // ═══════════════════════════════════════════
    //  Agent Downloads (Dedicated Section)
    // ═══════════════════════════════════════════
    async function renderDownloads(el) {
        el.innerHTML = `
            <div class="downloads-container">
                <div class="downloads-hero">
                    <div class="downloads-hero-icon">
                        <svg viewBox="0 0 24 24" width="36" height="36" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                    </div>
                    <div class="downloads-hero-text">
                        <h2>ObserveX Windows Telemetry Agent</h2>
                        <p>
                            Download the official client binaries to stream real-time hardware telemetry (CPU, RAM, Disks, Network, GPU), running processes, and Windows event logs to your centralized ObserveX platform.
                        </p>
                    </div>
                </div>

                <div class="download-cards-grid">
                    <!-- Standalone EXE -->
                    <div class="download-card primary-card">
                        <span class="download-card-badge">RECOMMENDED</span>
                        <div class="download-card-header">
                            <div class="download-card-icon">
                                <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/></svg>
                            </div>
                            <div>
                                <h3>Standalone Executable (.exe)</h3>
                                <div class="download-file-meta">ObserveXAgent.exe · 18.5 MB · Native x64</div>
                            </div>
                        </div>
                        <p class="download-card-desc">
                            Single self-contained Windows executable. No Python installation, external runtime, or administrative dependencies needed. Runs out-of-the-box on Windows 10, 11, and Windows Server 2016+.
                        </p>
                        <div class="download-card-action">
                            <a href="/api/v1/downloads/agent" class="btn btn-primary btn-full" download="ObserveXAgent.exe">
                                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                                Download ObserveXAgent.exe
                            </a>
                        </div>
                    </div>

                    <!-- Full ZIP Bundle -->
                    <div class="download-card">
                        <span class="download-card-badge">PORTABLE ARCHIVE</span>
                        <div class="download-card-header">
                            <div class="download-card-icon">
                                <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="2"><polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/></svg>
                            </div>
                            <div>
                                <h3>Full Windows ZIP Bundle</h3>
                                <div class="download-file-meta">ObserveXAgent-Windows.zip · 18.2 MB</div>
                            </div>
                        </div>
                        <p class="download-card-desc">
                            Complete archive containing the executable, a 1-click double-click console launcher (<code>run_agent.bat</code>) with pause guards, and setup instructions.
                        </p>
                        <div class="download-card-action">
                            <a href="/api/v1/downloads/agent/zip" class="btn btn-secondary btn-full" download="ObserveXAgent-Windows.zip">
                                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                                Download ZIP Archive
                            </a>
                        </div>
                    </div>
                </div>

                <!-- Setup Guide -->
                <div class="downloads-guide-card">
                    <h3 class="guide-title">Quick Installation & Enrollment Instructions</h3>
                    <div class="guide-steps-grid">
                        <div class="guide-step">
                            <div class="step-num">1</div>
                            <div class="step-content">
                                <h4>Download Agent Binary</h4>
                                <p>Download <code>ObserveXAgent.exe</code> or the ZIP bundle above and save it to any directory on the target Windows device.</p>
                            </div>
                        </div>
                        <div class="guide-step">
                            <div class="step-num">2</div>
                            <div class="step-content">
                                <h4>Obtain Enrollment Code</h4>
                                <p>Go to the <a href="#" onclick="Router.navigate('enrollment');return false" style="color:var(--accent-primary);text-decoration:underline">Enrollment</a> section and generate an active onboarding code.</p>
                            </div>
                        </div>
                        <div class="guide-step">
                            <div class="step-num">3</div>
                            <div class="step-content">
                                <h4>Run First-Time Setup</h4>
                                <p>Double-click the agent. Enter your server URL and enrollment code when prompted. Credentials are encrypted and saved.</p>
                            </div>
                        </div>
                        <div class="guide-step">
                            <div class="step-num">4</div>
                            <div class="step-content">
                                <h4>Stream Telemetry</h4>
                                <p>The agent establishes an encrypted WebSocket link and streams system metrics every 2 seconds to your Dashboard.</p>
                            </div>
                        </div>
                    </div>

                    <div style="margin-top:var(--space-lg);border-top:1px solid var(--border-secondary);padding-top:var(--space-md)">
                        <h4 style="font-size:0.9rem;font-weight:600;margin-bottom:8px">Command-Line Flags Reference:</h4>
                        <div class="cli-reference-box">
                            <div class="cli-item">
                                <span class="cli-cmd">ObserveXAgent.exe</span>
                                <span class="cli-desc">Interactive first-run wizard (prompts for URL and code)</span>
                            </div>
                            <div class="cli-item">
                                <span class="cli-cmd">ObserveXAgent.exe --server &lt;URL&gt; --enroll &lt;CODE&gt;</span>
                                <span class="cli-desc">Non-interactive scripted device onboarding</span>
                            </div>
                            <div class="cli-item">
                                <span class="cli-cmd">ObserveXAgent.exe --interval 5.0</span>
                                <span class="cli-desc">Custom metrics collection interval (seconds)</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }


    // ═══════════════════════════════════════════
    //  Alerts
    // ═══════════════════════════════════════════
    async function renderAlerts(el) {
        el.innerHTML = UI.loading();
        try {
            const alerts = await API.listAlerts('?limit=100');
            el.innerHTML = `
                ${Auth.isAdmin ? '<div class="section-header"><h3 class="section-title">Alert Rules</h3><button class="btn btn-primary btn-sm" onclick="Pages.showCreateAlertRuleModal()">+ New Rule</button></div><div id="alert-rules-list">' + UI.loading() + '</div><hr style="border-color:var(--border-primary);margin:var(--space-xl) 0">' : ''}
                <div class="section-header"><h3 class="section-title">Alert History</h3></div>
                ${alerts.length ? UI.table(
                    ['Severity', 'Device', 'Type', 'Title', 'Message', 'Time'],
                    alerts.map(a => [
                        UI.severityBadge(a.severity),
                        a.device_id,
                        a.alert_type || '—',
                        a.title || '—',
                        `<span style="max-width:280px;display:inline-block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${a.message || '—'}</span>`,
                        UI.timeAgo(a.timestamp),
                    ]),
                ) : '<div class="empty-state"><div class="empty-state-title">No alerts</div></div>'}
            `;
            if (Auth.isAdmin) _loadAlertRules();
        } catch (e) {
            el.innerHTML = `<div class="empty-state"><p>${e.message}</p></div>`;
        }
    }

    async function _loadAlertRules() {
        const el = document.getElementById('alert-rules-list');
        if (!el) return;
        try {
            const rules = await API.listAlertRules();
            el.innerHTML = rules.length ? UI.table(
                ['Name', 'Metric', 'Condition', 'Severity', 'Enabled', 'Actions'],
                rules.map(r => [
                    r.name, r.metric_name,
                    `${r.operator} ${r.threshold_value}`,
                    UI.severityBadge(r.severity),
                    r.enabled ? '✓' : '✗',
                    `<button class="btn btn-danger btn-sm" onclick="Pages.deleteAlertRule(${r.id})">Delete</button>`,
                ]),
            ) : '<div class="empty-state"><div class="empty-state-title">No alert rules</div></div>';
        } catch (_) { el.innerHTML = ''; }
    }

    // ═══════════════════════════════════════════
    //  Users (Admin)
    // ═══════════════════════════════════════════
    async function renderUsers(el) {
        el.innerHTML = UI.loading();
        try {
            const users = await API.listUsers();
            el.innerHTML = `
                <div class="section-header">
                    <h3 class="section-title">Organization Users</h3>
                    <button class="btn btn-primary btn-sm" onclick="Pages.showCreateUserModal()">+ Add User</button>
                </div>
                ${UI.table(
                    ['Username', 'Email', 'Full Name', 'Role', 'Created', 'Actions'],
                    users.map(u => [
                        u.username, u.email, u.full_name || '—',
                        UI.roleBadge(u.role),
                        UI.formatDate(u.created_at),
                        u.role !== 'admin' ? `<button class="btn btn-danger btn-sm" onclick="Pages.deleteUser(${u.id})">Remove</button>` : '—',
                    ]),
                    'No users',
                )}
            `;
        } catch (e) {
            el.innerHTML = `<div class="empty-state"><p>${e.message}</p></div>`;
        }
    }

    // ═══════════════════════════════════════════
    //  Enrollment (Admin)
    // ═══════════════════════════════════════════
    async function renderEnrollment(el) {
        el.innerHTML = UI.loading();
        try {
            const codes = await API.listCodes();
            el.innerHTML = `
                <!-- Agent Distribution Hero Banner -->
                <div class="enrollment-hero-card">
                    <div class="enrollment-hero-left">
                        <h3>ObserveX Windows Agent Distribution</h3>
                        <p>
                            Deploy the lightweight native Windows monitoring agent to capture full-system metrics, running processes, and event logs. Run the agent with an active enrollment code to register the endpoint.
                        </p>
                    </div>
                    <div class="enrollment-hero-actions">
                        <a href="/api/v1/downloads/agent" class="btn btn-primary" download="ObserveXAgent.exe">
                            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                            Download Agent (.exe)
                        </a>
                        <a href="/api/v1/downloads/agent/zip" class="btn btn-secondary" download="ObserveXAgent-Windows.zip" title="Includes run_agent.bat launcher">
                            Download ZIP
                        </a>
                    </div>
                </div>

                <div class="section-header">
                    <h3 class="section-title">Enrollment Codes</h3>
                    <div style="display:flex;gap:var(--space-sm)">
                        <button class="btn btn-primary btn-sm" onclick="Pages.showCreateCodeModal()">+ Generate New Code</button>
                    </div>
                </div>
                <p style="color:var(--text-secondary);font-size:0.85rem;margin-bottom:var(--space-lg)">
                    Click any code to copy it directly to your clipboard for quick command-line enrollment.
                </p>
                ${codes.length ? UI.table(
                    ['Enrollment Code', 'Uses', 'Max Uses', 'Expires', 'Status', 'Actions'],
                    codes.map(c => {
                        const isUsable = !c.is_revoked && new Date(c.expires_at) > new Date() && (c.max_uses === 0 || c.usage_count < c.max_uses);
                        const statusLabel = c.is_revoked ? 'Revoked' : new Date(c.expires_at) <= new Date() ? 'Expired' : (c.max_uses > 0 && c.usage_count >= c.max_uses) ? 'Exhausted' : 'Active';
                        const statusColor = isUsable ? 'var(--success)' : 'var(--danger)';
                        let actions = '';
                        if (isUsable) {
                            actions += `<button class="btn btn-danger btn-sm" onclick="Pages.revokeCode(${c.id})" style="margin-right:4px">Revoke</button>`;
                        }
                        actions += `<button class="btn btn-ghost btn-sm" onclick="Pages.deleteCodePermanent(${c.id})" title="Delete from history" style="color:var(--danger)">
                            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>
                        </button>`;
                        return [
                            `<span class="code-badge-copyable" onclick="navigator.clipboard.writeText('${c.code}');UI.toast('Copied ${c.code} to clipboard!','info')" title="Click to copy code">
                                <span>${c.code}</span>
                                <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                            </span>`,
                            c.usage_count, c.max_uses || '∞',
                            UI.formatDate(c.expires_at),
                            `<span style="color:${statusColor};font-weight:600;font-size:0.8rem">${statusLabel}</span>`,
                            actions,
                        ];
                    }),
                ) : '<div class="empty-state"><div class="empty-state-title">No enrollment codes</div><p>Generate a code to start enrolling devices.</p></div>'}
            `;
        } catch (e) {
            el.innerHTML = `<div class="empty-state"><p>${e.message}</p></div>`;
        }
    }

    // ═══════════════════════════════════════════
    //  Assignments (Admin)
    // ═══════════════════════════════════════════
    async function renderAssignments(el) {
        el.innerHTML = UI.loading();
        try {
            const assignments = await API.listAssignments();
            el.innerHTML = `
                <div class="section-header">
                    <h3 class="section-title">Device ↔ User Assignments</h3>
                    <button class="btn btn-primary btn-sm" onclick="Pages.showCreateAssignmentModal()">+ Assign</button>
                </div>
                ${UI.table(
                    ['Device', 'User', 'Assigned By', 'Assigned At', 'Actions'],
                    assignments.map(a => [
                        a.device_hostname || `Device #${a.device_id}`,
                        a.username || `User #${a.user_id}`,
                        a.assigned_by || '—',
                        UI.formatDate(a.assigned_at),
                        `<button class="btn btn-danger btn-sm" onclick="Pages.confirmRevokeAssignment(${a.id}, '${(a.device_hostname || 'Device #' + a.device_id).replace(/'/g, "\\'")}')">Revoke</button>`,
                    ]),
                    'No assignments',
                )}
            `;
        } catch (e) {
            el.innerHTML = `<div class="empty-state"><p>${e.message}</p></div>`;
        }
    }

    // ═══════════════════════════════════════════
    //  Modal Actions
    // ═══════════════════════════════════════════
    function showCreateUserModal() {
        UI.showModal('Add User', `
            <div class="form-group"><label>Username</label><input type="text" id="modal-username" required></div>
            <div class="form-group"><label>Email</label><input type="email" id="modal-email" required></div>
            <div class="form-group"><label>Password</label><input type="password" id="modal-password" required></div>
            <div class="form-group"><label>Full Name</label><input type="text" id="modal-fullname"></div>
            <div class="form-group"><label>Role</label><select id="modal-role"><option value="user">User</option><option value="admin">Admin</option></select></div>
        `, [
            { label: 'Cancel', onClick: UI.closeModal },
            { label: 'Create', cls: 'btn-primary', onClick: async () => {
                try {
                    await API.createUser({
                        username: document.getElementById('modal-username').value,
                        email: document.getElementById('modal-email').value,
                        password: document.getElementById('modal-password').value,
                        full_name: document.getElementById('modal-fullname').value || undefined,
                        role: document.getElementById('modal-role').value,
                    });
                    UI.closeModal();
                    UI.toast('User created', 'success');
                    Router.refresh();
                } catch (e) { UI.toast(e.message, 'error'); }
            }},
        ]);
    }

    function showCreateCodeModal() {
        UI.showModal('Generate Enrollment Code', `
            <div class="form-group"><label>Max Uses</label><input type="number" id="modal-max-uses" value="10" min="1"></div>
            <div class="form-group"><label>Expires In (hours)</label><input type="number" id="modal-expires" value="24" min="1"></div>
        `, [
            { label: 'Cancel', onClick: UI.closeModal },
            { label: 'Generate', cls: 'btn-primary', onClick: async () => {
                try {
                    const result = await API.createCode({
                        max_uses: parseInt(document.getElementById('modal-max-uses').value),
                        expires_in_hours: parseInt(document.getElementById('modal-expires').value),
                    });
                    UI.closeModal();
                    UI.showModal('Enrollment Code', `
                        <p style="color:var(--text-secondary);margin-bottom:var(--space-md)">Share this code with the agent:</p>
                        <div class="code-display">${result.code}</div>
                        <p style="color:var(--text-tertiary);font-size:0.8rem;margin-top:var(--space-md)">Click the code to select it for copying.</p>
                    `, [{ label: 'Done', cls: 'btn-primary', onClick: () => { UI.closeModal(); Router.refresh(); }}]);
                } catch (e) { UI.toast(e.message, 'error'); }
            }},
        ]);
    }

    function showCreateAssignmentModal() {
        UI.showModal('Assign Device to User', `
            <div class="form-group"><label>Device ID</label><input type="number" id="modal-device-id" required></div>
            <div class="form-group"><label>User ID</label><input type="number" id="modal-user-id" required></div>
        `, [
            { label: 'Cancel', onClick: UI.closeModal },
            { label: 'Assign', cls: 'btn-primary', onClick: async () => {
                try {
                    await API.createAssignment({
                        device_id: parseInt(document.getElementById('modal-device-id').value),
                        user_id: parseInt(document.getElementById('modal-user-id').value),
                    });
                    UI.closeModal();
                    UI.toast('Device assigned', 'success');
                    Router.refresh();
                } catch (e) { UI.toast(e.message, 'error'); }
            }},
        ]);
    }

    function showCreateAlertRuleModal() {
        UI.showModal('Create Alert Rule', `
            <div class="form-group"><label>Rule Name</label><input type="text" id="modal-rule-name" required></div>
            <div class="form-group"><label>Metric</label><select id="modal-rule-metric">
                <option value="cpu_percent">CPU %</option><option value="ram_percent">RAM %</option>
                <option value="disk_percent">Disk %</option><option value="gpu_percent">GPU %</option>
            </select></div>
            <div class="form-row">
                <div class="form-group"><label>Operator</label><select id="modal-rule-op"><option value=">">></option><option value="<"><</option><option value=">=">>=</option><option value="<="><=</option></select></div>
                <div class="form-group"><label>Threshold</label><input type="number" id="modal-rule-threshold" value="90" step="0.1"></div>
            </div>
            <div class="form-group"><label>Severity</label><select id="modal-rule-severity"><option value="warning">Warning</option><option value="critical">Critical</option><option value="info">Info</option></select></div>
            <div class="form-group"><label>Device ID (optional, blank = all)</label><input type="number" id="modal-rule-device"></div>
        `, [
            { label: 'Cancel', onClick: UI.closeModal },
            { label: 'Create', cls: 'btn-primary', onClick: async () => {
                try {
                    await API.createAlertRule({
                        name: document.getElementById('modal-rule-name').value,
                        metric_name: document.getElementById('modal-rule-metric').value,
                        operator: document.getElementById('modal-rule-op').value,
                        threshold_value: parseFloat(document.getElementById('modal-rule-threshold').value),
                        severity: document.getElementById('modal-rule-severity').value,
                        device_id: document.getElementById('modal-rule-device').value ? parseInt(document.getElementById('modal-rule-device').value) : null,
                    });
                    UI.closeModal();
                    UI.toast('Alert rule created', 'success');
                    Router.refresh();
                } catch (e) { UI.toast(e.message, 'error'); }
            }},
        ]);
    }

    async function confirmDeleteDevice(id) {
        UI.showModal('Delete Device', '<p>Are you sure you want to delete this device? This cannot be undone.</p>', [
            { label: 'Cancel', onClick: UI.closeModal },
            { label: 'Delete', cls: 'btn-danger', onClick: async () => {
                try { await API.deleteDevice(id); UI.closeModal(); UI.toast('Device deleted', 'success'); Router.navigate('devices'); } catch (e) { UI.toast(e.message, 'error'); }
            }},
        ]);
    }

    async function deleteUser(id) {
        try { await API.deleteUser(id); UI.toast('User removed', 'success'); Router.refresh(); } catch (e) { UI.toast(e.message, 'error'); }
    }
    async function revokeCode(id) {
        UI.showModal('Revoke Enrollment Code', '<p>Are you sure you want to revoke this enrollment code? Devices will no longer be able to enroll with it.</p>', [
            { label: 'Cancel', onClick: UI.closeModal },
            { label: 'Revoke', cls: 'btn-danger', onClick: async () => {
                try { await API.deleteCode(id); UI.closeModal(); UI.toast('Code revoked', 'success'); Router.refresh(); } catch (e) { UI.toast(e.message, 'error'); }
            }},
        ]);
    }
    async function deleteCodePermanent(id) {
        UI.showModal('Delete Enrollment Code', '<p>Permanently delete this enrollment code from history? This cannot be undone.</p>', [
            { label: 'Cancel', onClick: UI.closeModal },
            { label: 'Delete', cls: 'btn-danger', onClick: async () => {
                try { await API.deleteCodePermanent(id); UI.closeModal(); UI.toast('Code deleted from history', 'success'); Router.refresh(); } catch (e) { UI.toast(e.message, 'error'); }
            }},
        ]);
    }
    async function confirmRevokeAssignment(id, deviceName) {
        UI.showModal('Revoke Assignment', `<p>Are you sure you want to revoke the assignment for <strong>${deviceName}</strong>? The user will lose access to this device.</p>`, [
            { label: 'Cancel', onClick: UI.closeModal },
            { label: 'Revoke', cls: 'btn-danger', onClick: async () => {
                try { await API.deleteAssignment(id); UI.closeModal(); UI.toast('Assignment revoked', 'success'); Router.refresh(); } catch (e) { UI.toast(e.message, 'error'); }
            }},
        ]);
    }
    async function deleteAssignment(id) {
        try { await API.deleteAssignment(id); UI.toast('Assignment removed', 'success'); Router.refresh(); } catch (e) { UI.toast(e.message, 'error'); }
    }
    async function deleteAlertRule(id) {
        try { await API.deleteAlertRule(id); UI.toast('Rule deleted', 'success'); Router.refresh(); } catch (e) { UI.toast(e.message, 'error'); }
    }

    return {
        renderDashboard, renderDevices, renderDeviceDetail,
        renderAlerts, renderUsers, renderEnrollment, renderAssignments, renderDownloads,
        // Exposed process sorting & filter actions
        sortProcesses, filterProcesses,
        // Exposed modal actions (called from onclick handlers)
        showCreateUserModal, showCreateCodeModal, showCreateAssignmentModal, showCreateAlertRuleModal,
        confirmDeleteDevice, deleteUser, revokeCode, deleteCodePermanent, confirmRevokeAssignment, deleteAssignment, deleteAlertRule,
        clearRefresh: _clearRefresh,
    };
})();
