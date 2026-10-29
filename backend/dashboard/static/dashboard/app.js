const sidebar = document.querySelector('[data-sidebar]');
const overlay = document.querySelector('[data-sidebar-overlay]');
const toggle = document.querySelector('[data-sidebar-toggle]');

function closeSidebar() {
    document.body.classList.remove('sidebar-open');
}

if (toggle) {
    toggle.addEventListener('click', () => document.body.classList.toggle('sidebar-open'));
}
if (overlay) {
    overlay.addEventListener('click', closeSidebar);
}

document.querySelectorAll('[data-dismiss-message]').forEach((button) => {
    button.addEventListener('click', () => button.closest('.message').remove());
});

document.querySelectorAll('tr[data-href]').forEach((row) => {
    row.addEventListener('click', (event) => {
        if (!event.target.closest('a, button, input, select')) {
            window.location.href = row.dataset.href;
        }
    });
    row.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
            window.location.href = row.dataset.href;
        }
    });
});
