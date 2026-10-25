'use strict';
const progress = document.querySelector('[data-status-url]');
if (progress) {
  let stopped = false;
  const message = document.querySelector('#poll-message');
  const check = async () => {
    if (stopped) return;
    try {
      const response = await fetch(progress.dataset.statusUrl, {redirect: 'error'});
      if (!response.ok) throw new Error('Unable to check status');
      const run = await response.json();
      if (run.status !== progress.dataset.status) {
        stopped = true;
        location.reload();
        return;
      }
      message.textContent = 'Checking status every 5 seconds.';
    } catch (_) {
      message.textContent = 'Connection interrupted or session expired. Refresh to check again.';
    }
    setTimeout(check, 5000);
  };
  setTimeout(check, 5000);
}
document.querySelectorAll('form').forEach(form => {
  form.addEventListener('submit', () => {
    const button = form.querySelector('button[type="submit"]');
    if (button) { button.disabled = true; button.textContent = 'Working…'; }
  });
});
