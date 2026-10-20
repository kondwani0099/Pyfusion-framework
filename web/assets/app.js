/**
 * PyFusion Frontend Controller (web/assets/app.js)
 * Coordinates tab navigation, SQLite ORM table CRUD, Project Studio actions, and Theme switching.
 */

const TABS = ['overview', 'playground', 'form', 'security'];

function switchTab(tabName) {
    if (!TABS.includes(tabName)) return;

    TABS.forEach((t) => {
        const sec = document.getElementById(`section-${t}`);
        const btmBtn = document.getElementById(`btm-nav-${t}`);
        const topBtn = document.getElementById(`top-nav-${t}`);

        if (sec) sec.classList.toggle('hidden', t !== tabName);
        if (btmBtn) {
            btmBtn.classList.toggle('active', t === tabName);
            btmBtn.classList.toggle('text-emerald-500', t === tabName);
        }
        if (topBtn) {
            topBtn.classList.toggle('btn-active', t === tabName);
        }
    });

    if (tabName === 'form') {
        loadDatabaseRecords();
    }

    if (document.activeElement && document.activeElement.blur) {
        document.activeElement.blur();
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    const alertClass = type === 'error' ? 'alert-error' : 'alert-success';
    toast.className = `alert ${alertClass} shadow-lg py-2 px-4 text-sm font-medium`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

function copyCommand(cmdText) {
    navigator.clipboard.writeText(cmdText).then(() => {
        showToast(`Copied: ${cmdText}`);
    });
}

function toggleTheme() {
    const html = document.documentElement;
    const current = html.getAttribute('data-theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    showToast(`Theme switched to ${next} mode`);
}

async function checkServerHealth() {
    const dot = document.getElementById('health-dot');
    const text = document.getElementById('health-text');
    try {
        const res = await fetch('/api/health');
        const data = await res.json();
        if (dot) dot.className = 'w-2 h-2 rounded-full bg-emerald-400';
        if (text) text.textContent = `DB: ${data.database_connected ? 'Connected' : 'Off'} • OWASP Safe`;
        showToast(`Healthy! Components: ${(data.components || []).length}, DB Connected: ${data.database_connected}`);
    } catch (err) {
        if (dot) dot.className = 'w-2 h-2 rounded-full bg-rose-500';
        if (text) text.textContent = 'Server Offline';
        showToast('Could not reach /api/health', 'error');
    }
}

async function loadDatabaseRecords() {
    const tbody = document.getElementById('db-records-tbody');
    if (!tbody) return;
    try {
        const res = await fetch('/api/submissions');
        const data = await res.json();
        const rows = data.submissions || [];
        if (rows.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center opacity-60 py-4">No records in pyfusion.db yet. Submit the form above to insert one!</td></tr>';
            return;
        }
        tbody.innerHTML = '';
        rows.forEach((rec) => {
            const tr = document.createElement('tr');
            const tdId = document.createElement('td');
            tdId.className = 'font-bold text-emerald-400';
            tdId.textContent = `#${rec.id}`;

            const tdUser = document.createElement('td');
            tdUser.className = 'font-medium';
            tdUser.textContent = rec.username;

            const tdHash = document.createElement('td');
            tdHash.className = 'font-mono text-xs opacity-70 max-w-xs truncate';
            tdHash.title = rec.password_hash;
            tdHash.textContent = rec.password_hash;

            const tdIp = document.createElement('td');
            tdIp.className = 'text-xs opacity-75';
            tdIp.textContent = rec.ip_address;

            const tdDate = document.createElement('td');
            tdDate.className = 'text-xs opacity-75';
            tdDate.textContent = rec.created_at;

            const tdAct = document.createElement('td');
            const delBtn = document.createElement('button');
            delBtn.className = 'btn btn-xs btn-ghost text-rose-400';
            delBtn.textContent = 'Delete';
            delBtn.onclick = () => deleteRecord(rec.id);
            tdAct.appendChild(delBtn);

            tr.append(tdId, tdUser, tdHash, tdIp, tdDate, tdAct);
            tbody.appendChild(tr);
        });
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-rose-400 py-4">Failed to load records.</td></tr>';
    }
}

async function deleteRecord(id) {
    try {
        await fetch(`/api/submissions/${id}`, { method: 'DELETE' });
        showToast(`Deleted record #${id} from pyfusion.db`);
        loadDatabaseRecords();
    } catch (e) {
        showToast('Failed to delete record', 'error');
    }
}

async function handleFormSubmit(event) {
    const ajaxMode = document.getElementById('ajax-mode-toggle').checked;
    if (!ajaxMode) {
        return true;
    }
    event.preventDefault();

    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;
    const statusBadge = document.getElementById('form-status-badge');
    const responseBox = document.getElementById('form-response-box');

    statusBadge.className = 'badge badge-info';
    statusBadge.textContent = 'Saving to SQLite...';

    try {
        const body = new URLSearchParams({ username, password }).toString();
        const res = await fetch('/submit_form', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/json'
            },
            body
        });
        const data = await res.json();
        statusBadge.className = 'badge badge-success';
        statusBadge.textContent = `Saved Record #${data.record ? data.record.id : ''}`;
        responseBox.textContent = JSON.stringify(data, null, 2);
        showToast(`Saved "${username}" to SQLite database!`);
        loadDatabaseRecords();
    } catch (err) {
        statusBadge.className = 'badge badge-error';
        statusBadge.textContent = 'Error';
        responseBox.textContent = String(err);
        showToast('Form submission failed', 'error');
    }
}

async function loadProjectSettings() {
    try {
        const res = await fetch('/api/project/config');
        const data = await res.json();
        if (data && data.config) {
            const c = data.config;
            const pEl = document.getElementById('cfg-project-name');
            const tEl = document.getElementById('cfg-app-title');
            const iEl = document.getElementById('cfg-icon-path');
            if (pEl && c.project_name) pEl.value = c.project_name;
            if (tEl && c.app_title) tEl.value = c.app_title;
            if (iEl && c.icon) iEl.value = c.icon;
        }
    } catch (_) {}
}

async function saveProjectSettings() {
    const project_name = document.getElementById('cfg-project-name').value;
    const app_title = document.getElementById('cfg-app-title').value;
    const icon = document.getElementById('cfg-icon-path').value;
    const badge = document.getElementById('project-cfg-badge');
    try {
        const res = await fetch('/api/project/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_name, app_title, icon })
        });
        const data = await res.json();
        badge.textContent = `✓ Saved (${data.config.project_name})`;
        document.title = data.config.app_title;
        showToast(`Saved project "${project_name}" and generated icon.ico!`);
    } catch (e) {
        showToast('Failed to save project settings', 'error');
    }
}

async function saveDesktopShortcutFromWeb() {
    const project_name = document.getElementById('cfg-project-name').value;
    const app_title = document.getElementById('cfg-app-title').value;
    const icon = document.getElementById('cfg-icon-path').value;
    const badge = document.getElementById('project-cfg-badge');
    try {
        const res = await fetch('/api/project/save-desktop', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_name, app_title, icon })
        });
        const data = await res.json();
        const info = data.shortcut_info || {};
        badge.textContent = `✓ Desktop Shortcut Created!`;
        showToast(`Created Desktop App Shortcut for "${info.app_title}"!`);
    } catch (e) {
        showToast('Failed to save desktop shortcut', 'error');
    }
}

async function buildAndroidFromWeb(format = 'both') {
    const project_name = document.getElementById('cfg-project-name').value;
    const app_title = document.getElementById('cfg-app-title').value;
    const icon = document.getElementById('cfg-icon-path').value;
    const badge = document.getElementById('project-cfg-badge');
    try {
        const res = await fetch('/api/project/build-android', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_name, app_title, icon, format })
        });
        const data = await res.json();
        const info = data.android_info || {};
        badge.textContent = `✓ Android .${format.toUpperCase()} Ready (${info.package_name})`;
        showToast(`Configured Android .${format.toUpperCase()} in mobile/buildozer.spec & GitHub Actions CI!`);
    } catch (e) {
        showToast('Failed to generate Android project', 'error');
    }
}

async function launchMobileFromWeb() {
    try {
        const res = await fetch('/api/project/launch-mobile', { method: 'POST' });
        const data = await res.json();
        showToast(`Launched Android Simulator Window (PID: ${data.pid})!`);
    } catch (e) {
        showToast('Failed to launch Android Simulator', 'error');
    }
}

if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
}

document.addEventListener('DOMContentLoaded', () => {
    loadProjectSettings();
});
