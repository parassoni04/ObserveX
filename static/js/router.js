/**
 * ObserveX — Client-Side Router
 * Simple hash-based SPA router that maps pages to render functions.
 */
const Router = (() => {
    const _routes = {
        'dashboard':     { title: 'Dashboard',     subtitle: 'Organization overview',     render: Pages.renderDashboard },
        'devices':       { title: 'Devices',       subtitle: 'Monitored device fleet',    render: Pages.renderDevices },
        'device-detail': { title: 'Device Detail',  subtitle: 'Device monitoring & AIOps', render: Pages.renderDeviceDetail },
        'alerts':        { title: 'Alerts',         subtitle: 'Alert rules & history',     render: Pages.renderAlerts },
        'users':         { title: 'Users',          subtitle: 'Organization members',      render: Pages.renderUsers, admin: true },
        'enrollment':    { title: 'Enrollment',     subtitle: 'Device enrollment codes',   render: Pages.renderEnrollment, admin: true },
        'assignments':   { title: 'Assignments',    subtitle: 'Device-user mappings',      render: Pages.renderAssignments, admin: true },
    };

    let _currentPage = null;
    let _currentParams = null;

    function navigate(page, params = {}) {
        _currentPage = page;
        _currentParams = params;

        Pages.clearRefresh();

        const route = _routes[page];
        if (!route) { navigate('dashboard'); return; }

        // Update header
        document.getElementById('page-title').textContent = route.title;
        document.getElementById('page-subtitle').textContent = route.subtitle;
        document.getElementById('page-actions').innerHTML = '';

        // Update active nav
        document.querySelectorAll('.nav-item').forEach(el => {
            el.classList.toggle('active', el.dataset.page === page);
        });

        // Render page
        const container = document.getElementById('page-content');
        route.render(container, params);
    }

    function refresh() {
        if (_currentPage) navigate(_currentPage, _currentParams);
    }

    function init() {
        // Nav click handlers
        document.querySelectorAll('.nav-item').forEach(el => {
            el.addEventListener('click', (e) => {
                e.preventDefault();
                navigate(el.dataset.page);
            });
        });

        // Default page
        navigate('dashboard');
    }

    return { navigate, refresh, init };
})();
