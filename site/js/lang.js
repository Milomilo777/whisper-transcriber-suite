// Language menu and first-visit notice (no third-party requests).
// A picked language is kept in the wts_lang cookie, which functions/index.js reads before it
// sends a visitor of "/" to a language by country. ?auto=1 marks such a redirect; ?lang=en is
// the "View in English" link. Both are removed from the address bar after use.
(() => {
  const remember = (code) => {
    document.cookie = `wts_lang=${encodeURIComponent(code)}; Path=/; Max-Age=31536000; SameSite=Lax; Secure`;
  };
  document.addEventListener('click', (ev) => {
    const pick = ev.target.closest && ev.target.closest('[data-lang-pick]');
    if (pick) remember(pick.dataset.langPick);
    const menu = document.querySelector('[data-lang-menu]');
    if (menu && menu.open && !menu.contains(ev.target)) menu.open = false;
    if (ev.target.closest && ev.target.closest('[data-lang-notice-close]')) {
      const note = document.querySelector('[data-lang-notice]');
      if (note) note.hidden = true;
    }
  });
  document.addEventListener('keydown', (ev) => {
    const menu = document.querySelector('[data-lang-menu]');
    if (ev.key === 'Escape' && menu && menu.open) { menu.open = false; menu.querySelector('summary').focus(); }
  });

  const q = new URLSearchParams(location.search);
  if (!q.has('auto') && !q.has('lang')) return;
  if (q.get('lang') === 'en') remember('en');
  const note = document.querySelector('[data-lang-notice]');
  if (note && q.has('auto')) note.hidden = false;
  q.delete('auto');
  q.delete('lang');
  const rest = q.toString();
  history.replaceState(null, '', location.pathname + (rest ? `?${rest}` : '') + location.hash);
})();
