/**
 * PyFusion Minimal UI Shell Helper (web/assets/app.js)
 * All component state, database CRUD, and studio actions now run directly in Python (.fusion SFCs).
 * This file only handles client-side tab switching, theme toggling, and toast notifications.
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
        showToast(`Healthy! ${data.components.length} SFCs mounted • HMR Active`);
    } catch (err) {
        if (dot) dot.className = 'w-2 h-2 rounded-full bg-rose-500';
        if (text) text.textContent = 'Server Offline';
        showToast('Could not reach /api/health', 'error');
    }
}

// CSP-safe event delegation (no inline onclick handlers required)
document.addEventListener('click', (e) => {
    const tabEl = e.target.closest('[data-tab]');
    if (tabEl) {
        if (tabEl.tagName === 'A') e.preventDefault();
        switchTab(tabEl.getAttribute('data-tab'));
        return;
    }
    const actionEl = e.target.closest('[data-action]');
    if (actionEl) {
        const action = actionEl.getAttribute('data-action');
        if (action === 'health') checkServerHealth();
        else if (action === 'toggle-theme') toggleTheme();
        return;
    }
    const copyEl = e.target.closest('[data-copy]');
    if (copyEl) {
        copyCommand(copyEl.getAttribute('data-copy'));
    }
});

if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
}
