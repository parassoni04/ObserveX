/**
 * ObserveX — Auth Module
 * Handles login, logout, token storage, and session state.
 */
const Auth = (() => {
    let _user = null;

    function _storeSession(token, user) {
        localStorage.setItem('ox_token', token);
        localStorage.setItem('ox_user', JSON.stringify(user));
        _user = user;
    }

    function _clearSession() {
        localStorage.removeItem('ox_token');
        localStorage.removeItem('ox_user');
        _user = null;
    }

    return {
        get user() {
            if (!_user) {
                try { _user = JSON.parse(localStorage.getItem('ox_user')); } catch (_) {}
            }
            return _user;
        },

        get isLoggedIn() {
            return !!localStorage.getItem('ox_token');
        },

        get isAdmin() {
            return this.user?.role === 'admin';
        },

        get token() {
            return localStorage.getItem('ox_token');
        },

        async login(usernameOrEmail, password) {
            const data = await API.login({
                username_or_email: usernameOrEmail,
                password: password,
            });
            _storeSession(data.access_token, data.user);
            return data;
        },

        async createEnvironment(formData) {
            const data = await API.createEnv(formData);
            _storeSession(data.access_token, data.user);
            return data;
        },

        async refreshUser() {
            try {
                const user = await API.me();
                localStorage.setItem('ox_user', JSON.stringify(user));
                _user = user;
                return user;
            } catch (e) {
                this.logout();
                throw e;
            }
        },

        logout() {
            _clearSession();
            WS.disconnect();
            document.getElementById('app-screen').classList.remove('active');
            document.getElementById('app-screen').classList.add('hidden');
            document.getElementById('auth-screen').classList.add('active');
            document.getElementById('auth-screen').classList.remove('hidden');
            // Show login form, hide create-env
            document.getElementById('login-form').classList.remove('hidden');
            document.getElementById('create-env-form').classList.add('hidden');
        },

        updateUI() {
            const user = this.user;
            if (!user) return;

            const avatar = document.getElementById('user-avatar');
            const name = document.getElementById('user-display-name');
            const role = document.getElementById('user-display-role');

            if (avatar) avatar.textContent = (user.full_name || user.username || 'U')[0].toUpperCase();
            if (name) name.textContent = user.full_name || user.username;
            if (role) role.textContent = user.role;

            // Show/hide admin-only nav items
            document.querySelectorAll('.admin-only').forEach(el => {
                el.style.display = this.isAdmin ? '' : 'none';
            });
        },
    };
})();
