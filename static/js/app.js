/**
 * ObserveX — App Bootstrap
 * Entry point — handles auth forms, session restore, and app initialization.
 */
(function() {
    'use strict';

    // ── Auth Form Handlers ──
    const loginForm = document.getElementById('login-form-element');
    const createEnvForm = document.getElementById('create-env-form-element');

    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const btn = document.getElementById('login-btn');
        const errEl = document.getElementById('login-error');
        errEl.classList.add('hidden');

        btn.querySelector('.btn-text').textContent = 'Signing in...';
        btn.querySelector('.btn-loader').classList.remove('hidden');
        btn.disabled = true;

        try {
            await Auth.login(
                document.getElementById('login-input').value,
                document.getElementById('login-password').value,
            );
            _enterApp();
        } catch (err) {
            errEl.textContent = err.message;
            errEl.classList.remove('hidden');
        } finally {
            btn.querySelector('.btn-text').textContent = 'Sign In';
            btn.querySelector('.btn-loader').classList.add('hidden');
            btn.disabled = false;
        }
    });

    let _verificationToken = null;
    let _verifiedEmail = null;

    function _resetVerificationUI() {
        _verificationToken = null;
        _verifiedEmail = null;
        const otpSection = document.getElementById('email-verification-section');
        const fieldsSection = document.getElementById('create-env-fields');
        const btnText = document.getElementById('create-env-btn-text');
        const devBanner = document.getElementById('dev-code-banner');
        if (otpSection) otpSection.classList.add('hidden');
        if (fieldsSection) fieldsSection.classList.remove('hidden');
        if (btnText) btnText.textContent = 'Verify Email & Create Environment';
        const otpInput = document.getElementById('env-otp-code');
        if (otpInput) otpInput.value = '';
        if (devBanner) devBanner.classList.add('hidden');
    }

    createEnvForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const btn = document.getElementById('create-env-btn');
        const btnText = document.getElementById('create-env-btn-text');
        const errEl = document.getElementById('create-env-error');
        errEl.classList.add('hidden');

        const orgName = document.getElementById('env-org-name').value.trim();
        const username = document.getElementById('env-username').value.trim();
        const email = document.getElementById('env-email').value.trim().toLowerCase();
        const password = document.getElementById('env-password').value;
        const confirmPassword = document.getElementById('env-confirm-password').value;
        const fullname = document.getElementById('env-fullname').value.trim();

        // Validate passwords
        if (password !== confirmPassword) {
            errEl.textContent = 'Passwords do not match. Please re-enter.';
            errEl.classList.remove('hidden');
            document.getElementById('env-confirm-password').focus();
            return;
        }
        if (password.length < 8) {
            errEl.textContent = 'Password must be at least 8 characters long.';
            errEl.classList.remove('hidden');
            document.getElementById('env-password').focus();
            return;
        }

        // Validate email format
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(email)) {
            errEl.textContent = 'Please enter a valid email address.';
            errEl.classList.remove('hidden');
            document.getElementById('env-email').focus();
            return;
        }

        const otpSection = document.getElementById('email-verification-section');
        const isOtpVisible = otpSection && !otpSection.classList.contains('hidden');

        // Step 1: Send verification code if not yet sent or email changed
        if (!isOtpVisible && (_verifiedEmail !== email || !_verificationToken)) {
            btnText.textContent = 'Sending Code...';
            btn.querySelector('.btn-loader').classList.remove('hidden');
            btn.disabled = true;

            try {
                const res = await API.sendVerificationCode(email);
                document.getElementById('verification-target-email').textContent = email;
                otpSection.classList.remove('hidden');
                document.getElementById('create-env-fields').classList.add('hidden');
                btnText.textContent = 'Confirm Code & Create Environment';

                if (res.dev_code) {
                    document.getElementById('dev-code-text').textContent = res.dev_code;
                    document.getElementById('dev-code-banner').classList.remove('hidden');
                }
                document.getElementById('env-otp-code').focus();
                UI.toast(`Verification code sent to ${email}`, 'info');
            } catch (err) {
                errEl.textContent = err.message;
                errEl.classList.remove('hidden');
                btnText.textContent = 'Verify Email & Create Environment';
            } finally {
                btn.querySelector('.btn-loader').classList.add('hidden');
                btn.disabled = false;
            }
            return;
        }

        // Step 2: Verify code if entered
        if (isOtpVisible && (_verifiedEmail !== email || !_verificationToken)) {
            const code = document.getElementById('env-otp-code').value.trim();
            if (!code || code.length !== 6) {
                errEl.textContent = 'Please enter the 6-digit verification code.';
                errEl.classList.remove('hidden');
                document.getElementById('env-otp-code').focus();
                return;
            }

            btnText.textContent = 'Verifying...';
            btn.querySelector('.btn-loader').classList.remove('hidden');
            btn.disabled = true;

            try {
                const vRes = await API.verifyCode(email, code);
                _verificationToken = vRes.verification_token;
                _verifiedEmail = email;
            } catch (err) {
                errEl.textContent = err.message;
                errEl.classList.remove('hidden');
                btnText.textContent = 'Confirm Code & Create Environment';
                btn.querySelector('.btn-loader').classList.add('hidden');
                btn.disabled = false;
                return;
            }
        }

        // Step 3: Create Environment
        btnText.textContent = 'Creating Environment...';
        btn.querySelector('.btn-loader').classList.remove('hidden');
        btn.disabled = true;

        try {
            await Auth.createEnvironment({
                organization_name: orgName,
                admin_username: username,
                admin_email: email,
                admin_password: password,
                confirm_password: confirmPassword,
                admin_full_name: fullname || undefined,
                verification_token: _verificationToken,
            });
            _resetVerificationUI();
            _enterApp();
            UI.toast('Environment created! Welcome to ObserveX.', 'success');
        } catch (err) {
            errEl.textContent = err.message;
            errEl.classList.remove('hidden');
        } finally {
            btnText.textContent = 'Verify Email & Create Environment';
            btn.querySelector('.btn-loader').classList.add('hidden');
            btn.disabled = false;
        }
    });

    // Resend OTP button
    document.getElementById('resend-otp-btn')?.addEventListener('click', async () => {
        const email = document.getElementById('env-email').value.trim().toLowerCase();
        const errEl = document.getElementById('create-env-error');
        errEl.classList.add('hidden');
        try {
            const res = await API.sendVerificationCode(email);
            if (res.dev_code) {
                document.getElementById('dev-code-text').textContent = res.dev_code;
                document.getElementById('dev-code-banner').classList.remove('hidden');
            }
            UI.toast('New verification code sent!', 'info');
        } catch (err) {
            errEl.textContent = err.message;
            errEl.classList.remove('hidden');
        }
    });

    // Edit details button (back to fields)
    document.getElementById('change-details-btn')?.addEventListener('click', () => {
        _resetVerificationUI();
    });

    // Click dev code banner to auto-fill
    document.getElementById('dev-code-banner')?.addEventListener('click', () => {
        const code = document.getElementById('dev-code-text').textContent.trim();
        if (code) {
            const otpInput = document.getElementById('env-otp-code');
            otpInput.value = code;
            otpInput.focus();
        }
    });

    // Toggle between login and create-env forms
    document.getElementById('show-create-env').addEventListener('click', () => {
        document.getElementById('login-form').classList.add('hidden');
        document.getElementById('create-env-form').classList.remove('hidden');
        _resetVerificationUI();
    });
    document.getElementById('show-login').addEventListener('click', () => {
        document.getElementById('create-env-form').classList.add('hidden');
        document.getElementById('login-form').classList.remove('hidden');
        _resetVerificationUI();
    });

    // Logout
    document.getElementById('logout-btn').addEventListener('click', () => {
        Auth.logout();
        UI.toast('Signed out', 'info');
    });

    // ── Enter App ──
    function _enterApp() {
        document.getElementById('auth-screen').classList.remove('active');
        document.getElementById('auth-screen').classList.add('hidden');
        document.getElementById('app-screen').classList.add('active');
        document.getElementById('app-screen').classList.remove('hidden');

        Auth.updateUI();
        Router.init();
        WS.connect();

        // Listen for real-time updates
        WS.on('device_update', () => {
            // If on dashboard or devices page, soft refresh
            // (Don't do it on device-detail — the timer handles that)
        });
        WS.on('alert_triggered', (msg) => {
            UI.toast(`Alert: ${msg.message || 'New alert triggered'}`, 'warning');
        });
    }

    // ── Session Restore ──
    if (Auth.isLoggedIn) {
        // Validate token by calling /me
        Auth.refreshUser()
            .then(() => _enterApp())
            .catch(() => {
                // Token invalid — show login
                Auth.logout();
            });
    }
})();
