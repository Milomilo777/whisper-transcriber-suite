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
      // closing the notice keeps this language, so "/" does not redirect and ask again
      if (document.documentElement.lang) remember(document.documentElement.lang);
    }
  });
  document.addEventListener('keydown', (ev) => {
    const menu = document.querySelector('[data-lang-menu]');
    if (ev.key === 'Escape' && menu && menu.open) { menu.open = false; menu.querySelector('summary')?.focus(); }
  });

  // The one-line menu fits English down to 1240 px (styles.css); longer translations need more room.
  // While the header row overflows, drop the product name next to the logo first, then the menu.
  const row = document.querySelector('.site-header .header-row');
  if (row && 'ResizeObserver' in window) {
    const root = document.documentElement;
    const over = () => row.scrollWidth > row.clientWidth + 1;
    const fit = () => {
      root.classList.remove('hdr-no-name', 'hdr-no-nav');
      if (!over()) return;
      root.classList.add('hdr-no-name');
      if (over()) root.classList.add('hdr-no-nav');
    };
    new ResizeObserver(fit).observe(row);
    if (document.fonts) document.fonts.ready.then(fit);
  }

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
