/* Shared page behaviour: password toggles, confirm prompts, account menu, toasts and API calls. */
(function () {
  'use strict';

  const csrf = () => (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

  // Show / hide password fields
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-pw-toggle]');
    if (!btn) return;
    const input = btn.parentElement.querySelector('input');
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    btn.textContent = show ? 'Hide' : 'Show';
    btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  });

  // <form data-confirm="..."> asks before submitting (replaces inline onsubmit, which the CSP blocks)
  document.addEventListener('submit', (e) => {
    const msg = e.target.getAttribute('data-confirm');
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  // Close the account menu when clicking elsewhere or pressing Escape
  document.addEventListener('click', (e) => {
    document.querySelectorAll('details.usermenu[open]').forEach((d) => { if (!d.contains(e.target)) d.open = false; });
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') document.querySelectorAll('details.usermenu[open]').forEach((d) => { d.open = false; });
  });

  let toastTimer;
  function toast(text, opts) {
    opts = opts || {};
    let el = document.querySelector('.toast');
    if (!el) {
      el = document.createElement('div');
      el.className = 'toast';
      el.setAttribute('role', 'status');
      document.body.appendChild(el);
    }
    el.classList.toggle('error', !!opts.error);
    el.textContent = text;
    if (opts.link) {
      const a = document.createElement('a');
      a.href = opts.link.href;
      a.textContent = opts.link.text;
      el.appendChild(a);
    }
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, opts.ms || 3200);
  }

  async function api(method, url, body) {
    const res = await fetch(url, {
      method,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf() },
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (res.status === 401) { window.location.href = '/login?next=' + encodeURIComponent(location.pathname); }
    if (!res.ok) throw new Error((data && data.error) || 'Request failed (' + res.status + ').');
    return data;
  }

  window.ExciseUI = { toast, api };
})();
