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
  // While the header row overflows, drop the product name next to the logo first, then the language name next to
  // the globe (shown above 1500 px), then the menu, and last the GitHub icon (phones with the "English" button).
  const row = document.querySelector('.site-header .header-row');
  if (row && 'ResizeObserver' in window) {
    const root = document.documentElement;
    const over = () => row.scrollWidth > row.clientWidth + 1;
    let lastWidth = -1;
    const fit = (force) => {
      // only a new row width (or late fonts) can change the answer; height changes from our own classes do not
      if (force !== true && row.clientWidth === lastWidth) return;
      lastWidth = row.clientWidth;
      root.classList.remove('hdr-no-name', 'hdr-no-lang', 'hdr-no-nav', 'hdr-no-gh');
      for (const step of ['hdr-no-name', 'hdr-no-lang', 'hdr-no-nav', 'hdr-no-gh']) {
        if (!over()) return;
        root.classList.add(step);
      }
    };
    new ResizeObserver(() => fit()).observe(row);
    if (document.fonts) document.fonts.ready.then(() => fit(true));
  }

  const q = new URLSearchParams(location.search);
  if (!q.has('auto') && !q.has('lang')) return;
  if (q.get('lang') === 'en') remember('en');
  const note = document.querySelector('[data-lang-notice]');
  if (note && q.has('auto')) note.hidden = false;
  // a visitor who stays on the language "/" chose for them keeps it (the notice and the English button
  // switch away), so the next visit of "/" neither redirects again nor repeats the notice
  if (q.has('auto') && document.documentElement.lang) remember(document.documentElement.lang);
  q.delete('auto');
  q.delete('lang');
  const rest = q.toString();
  history.replaceState(null, '', location.pathname + (rest ? `?${rest}` : '') + location.hash);
})();
