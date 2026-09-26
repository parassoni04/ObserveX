/**
 * ObserveX — WebSocket Client
 * Maintains a persistent WS connection for real-time dashboard updates.
 */
const WS = (() => {
    let _ws = null;
    let _reconnectTimer = null;
    let _reconnectDelay = 1000;
    const _listeners = {};

    function _getUrl() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const token = Auth.token;
        return `${proto}//${location.host}/ws/v1/dashboard?token=${token}`;
    }

    function _emit(event, data) {
        (_listeners[event] || []).forEach(fn => {
            try { fn(data); } catch (e) { console.error('[WS] listener error:', e); }
        });
    }

    function _connect() {
        if (_ws) return;
        if (!Auth.isLoggedIn) return;

        const url = _getUrl();
        _ws = new WebSocket(url);

        _ws.onopen = () => {
            console.log('[WS] Connected');
            _reconnectDelay = 1000;
            _emit('connected', {});
        };

        _ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                const type = msg.type || 'unknown';
                _emit(type, msg);
                _emit('message', msg);
            } catch (e) {
                console.warn('[WS] Invalid message:', event.data);
            }
        };

        _ws.onclose = (event) => {
            console.log('[WS] Disconnected:', event.code, event.reason);
            _ws = null;
            _emit('disconnected', { code: event.code });
            // Auto-reconnect if still logged in
            if (Auth.isLoggedIn) {
                _reconnectTimer = setTimeout(() => {
                    _reconnectDelay = Math.min(_reconnectDelay * 1.5, 15000);
                    _connect();
                }, _reconnectDelay);
            }
        };

        _ws.onerror = (err) => {
            console.error('[WS] Error:', err);
            _ws?.close();
        };
    }

    return {
        connect() {
            clearTimeout(_reconnectTimer);
            _connect();
        },

        disconnect() {
            clearTimeout(_reconnectTimer);
            if (_ws) {
                _ws.close(1000, 'logout');
                _ws = null;
            }
        },

        send(data) {
            if (_ws?.readyState === WebSocket.OPEN) {
                _ws.send(JSON.stringify(data));
            }
        },

        on(event, fn) {
            if (!_listeners[event]) _listeners[event] = [];
            _listeners[event].push(fn);
        },

        off(event, fn) {
            if (_listeners[event]) {
                _listeners[event] = _listeners[event].filter(f => f !== fn);
            }
        },

        get isConnected() {
            return _ws?.readyState === WebSocket.OPEN;
        },
    };
})();
