/**
 * ObserveX — UI Component Helpers
 * Reusable functions for toasts, modals, badges, tables, and stat cards.
 */
const UI = (() => {
    // ── Toast Notifications ──
    function toast(message, type = 'info', duration = 4000) {
        const container = document.getElementById('toast-container');
        const el = document.createElement('div');
        el.className = `toast ${type}`;
        el.textContent = message;
        container.appendChild(el);
        setTimeout(() => {
            el.style.animation = 'slideOut 0.3s ease-in forwards';
            setTimeout(() => el.remove(), 300);
        }, duration);
    }

    // ── Modal ──
    function showModal(title, contentHTML, actions = []) {
        closeModal();
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.id = 'modal-overlay';
        overlay.innerHTML = `
            <div class="modal">
                <h3 class="modal-title">${title}</h3>
                <div class="modal-body">${contentHTML}</div>
                <div class="modal-actions" id="modal-actions"></div>
            </div>
        `;
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) closeModal();
        });
        document.body.appendChild(overlay);

        const actionsEl = document.getElementById('modal-actions');
        actions.forEach(({ label, cls, onClick }) => {
            const btn = document.createElement('button');
            btn.className = `btn ${cls || 'btn-secondary'}`;
            btn.textContent = label;
            btn.addEventListener('click', onClick);
            actionsEl.appendChild(btn);
        });
    }

    function closeModal() {
        document.getElementById('modal-overlay')?.remove();
    }

    // ── Badges ──
    function statusBadge(status) {
        const map = {
            active: 'badge-online', online: 'badge-online',
            offline: 'badge-offline', pending: 'badge-pending',
            stale: 'badge-stale',
        };
        const dot = status === 'active' || status === 'online' ? 'online' : status === 'stale' ? 'stale' : 'offline';
        return `<span class="badge ${map[status] || 'badge-offline'}"><span class="status-dot ${dot}"></span>${status}</span>`;
    }

    function roleBadge(role) {
        return `<span class="badge ${role === 'admin' ? 'badge-admin' : 'badge-user'}">${role}</span>`;
    }

    function severityBadge(severity) {
        const map = { critical: 'badge-critical', warning: 'badge-warning', info: 'badge-info' };
        return `<span class="badge ${map[severity] || 'badge-info'}">${severity}</span>`;
    }

    // ── Stat Card ──
    function statCard(value, label, color = 'purple', iconSVG = '') {
        return `
            <div class="stat-card">
                <div class="stat-icon ${color}">${iconSVG}</div>
                <div>
                    <div class="stat-value">${value}</div>
                    <div class="stat-label">${label}</div>
                </div>
            </div>
        `;
    }

    // ── Table ──
    function table(headers, rows, emptyMessage = 'No data') {
        if (!rows.length) {
            return `<div class="empty-state"><div class="empty-state-title">${emptyMessage}</div></div>`;
        }
        const ths = headers.map(h => `<th>${h}</th>`).join('');
        const trs = rows.map(cells => `<tr>${cells.map(c => `<td>${c}</td>`).join('')}</tr>`).join('');
        return `<div class="table-container"><table><thead><tr>${ths}</tr></thead><tbody>${trs}</tbody></table></div>`;
    }

    // ── Loading ──
    function loading() {
        return '<div class="loading-state"><div class="loading-spinner"></div><span>Loading...</span></div>';
    }

    // ── Metric Bar ──
    function metricBar(pct) {
        const cls = pct > 90 ? 'danger' : pct > 75 ? 'warning' : '';
        return `<div class="metric-bar"><div class="metric-bar-fill ${cls}" style="width:${Math.min(100, pct)}%"></div></div>`;
    }

    // ── Time formatting ──
    function timeAgo(dateStr) {
        if (!dateStr) return 'Never';
        const diff = (Date.now() - new Date(dateStr).getTime()) / 1000;
        if (diff < 60) return `${Math.floor(diff)}s ago`;
        if (diff < 3600) return `${Math.floor(diff/60)}m ago`;
        if (diff < 86400) return `${Math.floor(diff/3600)}h ago`;
        return `${Math.floor(diff/86400)}d ago`;
    }

    function formatDate(dateStr) {
        if (!dateStr) return '—';
        return new Date(dateStr).toLocaleString();
    }

    return { toast, showModal, closeModal, statusBadge, roleBadge, severityBadge, statCard, table, loading, metricBar, timeAgo, formatDate };
})();
