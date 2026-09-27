/**
 * ObserveX — API Client
 * Centralized HTTP client with JWT auth, error handling, and auto-refresh.
 */
const API = (() => {
    const BASE = '';  // Same origin

    function _headers() {
        const h = { 'Content-Type': 'application/json' };
        const token = localStorage.getItem('ox_token');
        if (token) h['Authorization'] = `Bearer ${token}`;
        return h;
    }

    async function _request(method, path, body = null) {
        const opts = { method, headers: _headers() };
        if (body) opts.body = JSON.stringify(body);

        const resp = await fetch(`${BASE}${path}`, opts);

        if (resp.status === 401) {
            // Token expired or invalid — force logout
            Auth.logout();
            throw new Error('Session expired. Please sign in again.');
        }

        if (!resp.ok) {
            let detail = `HTTP ${resp.status}`;
            try {
                const err = await resp.json();
                detail = err.detail || JSON.stringify(err);
            } catch (_) {}
            throw new Error(detail);
        }

        if (resp.status === 204) return null;
        return resp.json();
    }

    return {
        get:    (path)       => _request('GET', path),
        post:   (path, body) => _request('POST', path, body),
        put:    (path, body) => _request('PUT', path, body),
        patch:  (path, body) => _request('PATCH', path, body),
        delete: (path)       => _request('DELETE', path),

        // ── Auth ──
        login:                (data) => _request('POST', '/api/v1/auth/login', data),
        createEnv:            (data) => _request('POST', '/api/v1/auth/create-environment', data),
        sendVerificationCode: (email) => _request('POST', '/api/v1/auth/send-verification-code', { email }),
        verifyCode:           (email, code) => _request('POST', '/api/v1/auth/verify-code', { email, code }),
        forgotPassword:       (email) => _request('POST', '/api/v1/auth/forgot-password', { email }),
        resetPassword:        (data) => _request('POST', '/api/v1/auth/reset-password', data),
        me:                   ()     => _request('GET', '/api/v1/auth/me'),

        // ── Enrollment ──
        listCodes:      ()     => _request('GET', '/api/v1/enrollment/codes'),
        createCode:     (data) => _request('POST', '/api/v1/enrollment/codes', data),
        deleteCode:     (id)   => _request('DELETE', `/api/v1/enrollment/codes/${id}`),
        deleteCodePermanent: (id) => _request('DELETE', `/api/v1/enrollment/codes/${id}/permanent`),

        // ── Admin ──
        overview:       ()     => _request('GET', '/api/v1/admin/overview'),
        listUsers:      ()     => _request('GET', '/api/v1/admin/users'),
        createUser:     (data) => _request('POST', '/api/v1/admin/users', data),
        deleteUser:     (id)   => _request('DELETE', `/api/v1/admin/users/${id}`),

        // ── Devices ──
        listDevices:    ()     => _request('GET', '/api/v1/devices'),
        getDevice:      (id)   => _request('GET', `/api/v1/devices/${id}`),
        deleteDevice:   (id)   => _request('DELETE', `/api/v1/devices/${id}`),
        deviceStatus:   (id)   => _request('GET', `/api/v1/devices/${id}/status`),

        // ── Telemetry ──
        liveMetrics:    (id)   => _request('GET', `/api/v1/telemetry/${id}/live`),
        processes:      (id)   => _request('GET', `/api/v1/telemetry/${id}/processes`),
        events:         (id)   => _request('GET', `/api/v1/telemetry/${id}/events`),

        // ── Alerts ──
        listAlerts:     (q='') => _request('GET', `/api/v1/alerts${q}`),
        listAlertRules: ()     => _request('GET', '/api/v1/alerts/rules'),
        createAlertRule:(data) => _request('POST', '/api/v1/alerts/rules', data),
        deleteAlertRule:(id)   => _request('DELETE', `/api/v1/alerts/rules/${id}`),

        // ── Assignments ──
        listAssignments:   ()     => _request('GET', '/api/v1/admin/assignments'),
        createAssignment:  (data) => _request('POST', '/api/v1/admin/assignments', data),
        deleteAssignment:  (id)   => _request('DELETE', `/api/v1/admin/assignments/${id}`),

        // ── Commands ──
        dispatchCommand: (data) => _request('POST', '/api/v1/commands', data),
        listCommands:    (q='') => _request('GET', `/api/v1/commands${q}`),

        // ── AIOps ──
        anomalies:  (id) => _request('GET', `/api/v1/aiops/${id}/anomalies`),
        forecast:   (id) => _request('GET', `/api/v1/aiops/${id}/forecast`),
        rootCause:  (id) => _request('GET', `/api/v1/aiops/${id}/root-cause`),
        insights:   (id) => _request('GET', `/api/v1/aiops/${id}/insights`),

        // ── Health ──
        health:     ()   => _request('GET', '/api/v1/health'),

        // ── Downloads ──
        downloadAgentUrl: '/api/v1/downloads/agent',
    };
})();
