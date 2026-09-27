/**
 * ObserveX — Page Renderers
 * Each page exports a render(container) function called by the router.
 */
const Pages = (() => {
    let _refreshTimer = null;
    let _activeWsCleanup = null;

    function _clearRefresh() {
        if (_refreshTimer) { clearInterval(_refreshTimer); _refreshTimer = null; }
        if (_activeWsCleanup) { _activeWsCleanup(); _activeWsCleanup = null; }
    }

    // ═══════════════════════════════════════════
    //  Dashboard
    // ═══════════════════════════════════════════
    async function renderDashboard(el) {
        el.innerHTML = UI.loading();
        try {
            const ov = await API.overview();
            el.innerHTML = `
                <div class="stats-grid">
                    ${UI.statCard(ov.total_devices, 'Total Devices', 'purple',
                        '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>')}
                    ${UI.statCard(ov.online_devices, 'Online', 'green',
                        '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>')}
                    ${UI.statCard(ov.offline_devices, 'Offline', 'red',
                        '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>')}
                    ${UI.statCard(ov.total_users, 'Users', 'blue',
                        '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg>')}
                </div>

                <div class="section-header" style="margin-top:var(--space-xl)">
                    <h3 class="section-title">Recent Alerts</h3>
                </div>
                <div id="dashboard-alerts">${UI.loading()}</div>

                <div class="section-header" style="margin-top:var(--space-xl)">
                    <h3 class="section-title">Device Fleet</h3>
                </div>
                <div id="dashboard-devices">${UI.loading()}</div>
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
                el.innerHTML = '<div class="empty-state"><div class="empty-state-title">No alerts</div></div>';
                return;
            }
            el.innerHTML = UI.table(
                ['Severity', 'Device', 'Type', 'Message', 'Time'],
                alerts.map(a => [
                    UI.severityBadge(a.severity),
                    a.device_id,
                    a.alert_type || '—',
                    a.message || '—',
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
            el.innerHTML = UI.table(
                ['Hostname', 'OS', 'Status', 'Last Seen'],
                devices.map(d => [
                    `<a href="#" onclick="Router.navigate('device-detail',{id:${d.id}});return false" style="font-weight:600">${d.hostname}</a>`,
                    `${d.os_name || '?'} ${d.os_version || ''}`,
                    UI.statusBadge(d.is_online ? 'active' : d.status),
                    UI.timeAgo(d.last_seen),
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
                    container.innerHTML = '<div class="empty-state"><div class="empty-state-title">No live metrics</div><p>The agent may not be connected yet.</p></div>';
                    return;
                }
                const m = data.metrics?.payload || data.metrics || {};
                _renderMetricsContent(container, m);
            } else if (tab === 'processes') {
                const data = await API.processes(deviceId);
                if (!data.processes.length) {
                    container.innerHTML = '<div class="empty-state"><div class="empty-state-title">No process data</div></div>';
                    return;
                }
                container.innerHTML = UI.table(
                    ['PID', 'Name', 'CPU %', 'Memory MB', 'Status'],
                    data.processes.slice(0, 50).map(p => [
                        p.pid, p.name,
                        (p.cpu_percent || 0).toFixed(1),
                        (p.memory_mb || 0).toFixed(1),
                        p.status || '—',
                    ]),
                );
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
                <div class="section-header">
                    <h3 class="section-title">Enrollment Codes</h3>
                    <div style="display:flex;gap:var(--space-sm)">
                        <a href="${API.downloadAgentUrl}" class="btn btn-secondary btn-sm" download>
                            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                            Download Agent
                        </a>
                        <button class="btn btn-primary btn-sm" onclick="Pages.showCreateCodeModal()">+ Generate Code</button>
                    </div>
                </div>
                <p style="color:var(--text-secondary);font-size:0.85rem;margin-bottom:var(--space-lg)">Share these codes with devices to enroll them into your organization.</p>
                ${codes.length ? UI.table(
                    ['Code', 'Uses', 'Max Uses', 'Expires', 'Status', 'Actions'],
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
                            `<span class="code-display" style="font-size:0.9rem;padding:0.3rem 0.6rem">${c.code}</span>`,
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
        renderAlerts, renderUsers, renderEnrollment, renderAssignments,
        // Exposed modal actions (called from onclick handlers)
        showCreateUserModal, showCreateCodeModal, showCreateAssignmentModal, showCreateAlertRuleModal,
        confirmDeleteDevice, deleteUser, revokeCode, deleteCodePermanent, confirmRevokeAssignment, deleteAssignment, deleteAlertRule,
        clearRefresh: _clearRefresh,
    };
})();
