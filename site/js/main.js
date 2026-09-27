// Whisper Transcriber Suite — page interactions (no third-party requests).
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const root = document.documentElement;
  const hasIO = 'IntersectionObserver' in window;
  const canHover = matchMedia('(hover: hover)').matches;
  // 'on' = full motion, 'calm' = slow ambient motion only (OS asked to reduce), 'off' = still.
  const motion = () => root.dataset.motion || 'on';
  const listeners = new Set();
  const onMotionChange = (fn) => listeners.add(fn);

  /* Motion toggle: stored per browser, falls back to the OS preference. */
  const toggle = $('[data-motion-toggle]');
  const syncToggle = () => {
    if (!toggle) return;
    const off = motion() === 'off';
    toggle.setAttribute('aria-pressed', String(off));
    const label = off ? 'Play animations' : 'Pause animations';
    toggle.title = label;
    const sr = $('[data-motion-label]', toggle);
    if (sr) sr.textContent = label;
  };
  if (toggle) {
    toggle.addEventListener('click', () => {
      const next = motion() === 'off' ? 'on' : 'off';
      root.dataset.motion = next;
      try { localStorage.setItem('wts-motion', next); } catch (e) { /* storage unavailable */ }
      syncToggle();
      listeners.forEach((fn) => fn(next));
    });
  }
  syncToggle();

  /* Header: glass once the page moves; highlight the section in view. */
  const header = $('[data-header]');
  const onScroll = () => header && header.classList.toggle('is-scrolled', scrollY > 24);
  addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  if (hasIO) {
    const links = new Map($$('.site-nav a').map((a) => [a.getAttribute('href').slice(1), a]));
    const spy = new IntersectionObserver((entries) => {
      for (const e of entries) {
        const link = links.get(e.target.id);
        if (link) link.classList.toggle('is-current', e.isIntersecting);
      }
    }, { rootMargin: '-45% 0px -50% 0px' });
    links.forEach((_, id) => { const el = document.getElementById(id); if (el) spy.observe(el); });
  }

  /* Platform-aware primary download. */
  const platform = (() => {
    const p = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || '';
    const ua = navigator.userAgent || '';
    if (/android|iphone|ipad|ipod/i.test(ua) || /android|ios/i.test(p)) return 'mobile';
    if (/mac/i.test(p) || /mac os x/i.test(ua)) return 'mac';
    if (/linux|x11|cros/i.test(p) || /linux|cros/i.test(ua)) return 'linux';
    return 'windows';
  })();
  const cta = $('[data-os-cta]');
  const ctaLabel = $('[data-os-label]');
  if (cta && ctaLabel) {
    // The CTA links straight to the Windows installer; send everyone else to the cards.
    if (platform === 'mac') { ctaLabel.textContent = 'Install on macOS'; cta.href = '#mac-install'; cta.removeAttribute('rel'); }
    if (platform === 'linux') { ctaLabel.textContent = 'Get it for Linux'; cta.href = '#download'; cta.removeAttribute('rel'); }
    if (platform === 'mobile') { ctaLabel.textContent = 'Get it for your computer'; cta.href = '#download'; cta.removeAttribute('rel'); }
  }
  const recCard = $(`.dl-card[data-os="${platform === 'mobile' ? 'windows' : platform}"]`);
  if (recCard && platform !== 'mobile') {
    recCard.classList.add('is-recommended');
    const badge = $('[data-rec-badge]', recCard);
    if (badge) badge.hidden = false;
  }

  /* Copy buttons (the macOS one-line install). */
  $$('[data-copy]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const src = $(btn.dataset.copy);
      if (!src) return;
      try {
        await navigator.clipboard.writeText(src.textContent.trim());
      } catch (e) {
        const r = document.createRange(); r.selectNodeContents(src);
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
        return;
      }
      btn.textContent = 'Copied'; btn.classList.add('is-done');
      setTimeout(() => { btn.textContent = 'Copy'; btn.classList.remove('is-done'); }, 1800);
    });
  });

  /* Scroll reveals, staggered within each batch that enters together. */
  const srEls = $$('.sr');
  if (!hasIO) {
    srEls.forEach((el) => el.classList.add('in'));
  } else {
    const io = new IntersectionObserver((entries) => {
      let i = 0;
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        e.target.style.setProperty('--sr-delay', `${Math.min(i++ * 90, 450)}ms`);
        e.target.classList.add('in');
        io.unobserve(e.target);
      }
    }, { rootMargin: '0px 0px -6% 0px', threshold: 0.06 });
    srEls.forEach((el) => io.observe(el));
  }

  /* Feature visuals only animate while on screen. */
  const liveEls = $$('[data-live]');
  if (hasIO) {
    const liveIO = new IntersectionObserver((entries) => {
      for (const e of entries) {
        e.target.classList.toggle('is-live', e.isIntersecting);
        e.target.dispatchEvent(new CustomEvent(e.isIntersecting ? 'live:on' : 'live:off'));
      }
    }, { threshold: 0.2 });
    liveEls.forEach((el) => liveIO.observe(el));
  } else {
    liveEls.forEach((el) => el.classList.add('is-live'));
  }

  /* Cursor spotlight + gentle 3D tilt on cards. */
  const bento = $('[data-spotlight]');
  if (bento && canHover) {
    bento.addEventListener('pointermove', (ev) => {
      for (const cell of bento.children) {
        const r = cell.getBoundingClientRect();
        cell.style.setProperty('--mx', `${ev.clientX - r.left}px`);
        cell.style.setProperty('--my', `${ev.clientY - r.top}px`);
      }
    }, { passive: true });
  }
  if (canHover) {
    $$('[data-tilt-card]').forEach((card) => {
      card.addEventListener('pointermove', (ev) => {
        if (motion() === 'off') return;
        const r = card.getBoundingClientRect();
        const k = motion() === 'calm' ? 2 : 5;
        card.style.setProperty('--tx', `${((0.5 - (ev.clientY - r.top) / r.height) * k).toFixed(2)}deg`);
        card.style.setProperty('--ty', `${(((ev.clientX - r.left) / r.width - 0.5) * k).toFixed(2)}deg`);
      }, { passive: true });
      card.addEventListener('pointerleave', () => { card.style.setProperty('--tx', '0deg'); card.style.setProperty('--ty', '0deg'); });
    });
  }

  /* Typers (feature card + hero caption). */
  const makeTyper = (el, phrases, host) => {
    if (!el) return;
    let timer = 0; let running = false; let p = 0; let c = phrases[0].length; let dir = -1;
    const tick = () => {
      if (!running) return;
      if (motion() === 'off') { el.textContent = phrases[0]; running = false; return; }
      const phrase = phrases[p];
      c += dir;
      el.textContent = phrase.slice(0, Math.max(0, c));
      const slow = motion() === 'calm' ? 1.8 : 1;
      let wait = (dir > 0 ? 42 + Math.random() * 50 : 16) * slow;
      if (dir > 0 && c >= phrase.length) { dir = -1; wait = 2000 * slow; }
      else if (dir < 0 && c <= 0) { dir = 1; p = (p + 1) % phrases.length; wait = 380; }
      timer = setTimeout(tick, wait);
    };
    const start = () => { if (!running && motion() !== 'off') { running = true; timer = setTimeout(tick, 1400); } };
    const stop = () => { running = false; clearTimeout(timer); };
    if (host) { host.addEventListener('live:on', start); host.addEventListener('live:off', stop); } else { start(); }
    onMotionChange((m) => { stop(); el.textContent = phrases[p]; c = phrases[p].length; dir = -1; if (m !== 'off') start(); });
  };
  const typer = $('[data-typer]');
  makeTyper(typer, ['so the words appear as you speak', 'cuts land on natural pauses', 'and no word is ever split in two'], typer && typer.closest('[data-live]'));
  makeTyper($('[data-hero-typer]'), ['Your audio stays on your computer.', 'No cloud. No account. No upload.', 'Whisper runs on your own computer.', 'Fourteen formats, one click.']);

  /* Denoise before/after waveforms (deterministic, so the art never changes between visits). */
  const noisy = $('[data-wave="noisy"]');
  const clean = $('[data-wave="clean"]');
  if (noisy && clean) {
    let seed = 7;
    const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
    const N = 300; const W = 600; const H = 120; const mid = H / 2;
    const bursts = [[30, 70], [95, 150], [175, 205], [230, 290]];
    const env = (i) => {
      let e = 0;
      for (const [a, b] of bursts) {
        if (i >= a && i <= b) { const t = (i - a) / (b - a); e = Math.max(e, Math.sin(Math.PI * t) ** 0.6); }
      }
      return e;
    };
    let dClean = ''; let dNoisy = '';
    for (let i = 0; i <= N; i++) {
      const x = (i / N) * W;
      const e = env(i);
      const carrier = Math.sin(i * 1.7) * (0.55 + 0.45 * Math.sin(i * 0.31));
      const yc = mid - carrier * e * 46;
      const yn = yc + (rnd() - 0.5) * (10 + 16 * (1 - e)) + Math.sin(i * 2.9) * 3;
      dClean += `${i ? 'L' : 'M'}${x.toFixed(1)} ${yc.toFixed(1)}`;
      dNoisy += `${i ? 'L' : 'M'}${x.toFixed(1)} ${yn.toFixed(1)}`;
    }
    clean.setAttribute('d', dClean);
    noisy.setAttribute('d', dNoisy);
  }

  /* Hero background: flowing sound ribbons on a 2D canvas. */
  const canvas = $('[data-waves]');
  if (canvas && canvas.getContext) {
    const ctx = canvas.getContext('2d');
    const ribbons = [
      { c: [12, 157, 149], a: 0.16, f: 1.6, s: 0.00035, amp: 0.12, y: 0.62, w: 2.2 },
      { c: [79, 124, 242], a: 0.13, f: 2.3, s: -0.00028, amp: 0.09, y: 0.66, w: 1.8 },
      { c: [106, 92, 240], a: 0.14, f: 1.2, s: 0.00022, amp: 0.15, y: 0.7, w: 2.6 },
      { c: [242, 96, 76], a: 0.11, f: 2.9, s: 0.00041, amp: 0.07, y: 0.68, w: 1.6 },
    ];
    let w = 0; let h = 0; let dpr = 1; let raf = 0; let visible = true; let t0 = performance.now();
    const resize = () => {
      dpr = Math.min(devicePixelRatio || 1, 2);
      w = canvas.clientWidth; h = canvas.clientHeight;
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      draw(performance.now());
    };
    const draw = (now) => {
      const speed = motion() === 'calm' ? 0.35 : 1;
      const t = (now - t0) * speed;
      ctx.clearRect(0, 0, w, h);
      for (const r of ribbons) {
        for (let k = 0; k < 7; k++) {
          ctx.beginPath();
          const off = k * 0.012;
          for (let x = 0; x <= w; x += 8) {
            const u = x / w;
            const env = Math.sin(Math.PI * u) ** 1.4;
            const y = h * (r.y + off) + Math.sin(u * Math.PI * 2 * r.f + t * r.s * 6 + k * 0.35) * h * r.amp * env
              + Math.sin(u * 17 + t * r.s * 9) * 6 * env;
            if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
          }
          ctx.strokeStyle = `rgba(${r.c[0]},${r.c[1]},${r.c[2]},${r.a * (1 - k / 8)})`;
          ctx.lineWidth = r.w;
          ctx.stroke();
        }
      }
    };
    const loop = (now) => { raf = 0; draw(now); if (visible && motion() !== 'off') raf = requestAnimationFrame(loop); };
    const kick = () => { if (!raf && visible && motion() !== 'off') raf = requestAnimationFrame(loop); };
    addEventListener('resize', resize, { passive: true });
    if (hasIO) new IntersectionObserver((es) => { visible = es[0].isIntersecting; kick(); }).observe(canvas);
    document.addEventListener('visibilitychange', () => { visible = !document.hidden; kick(); });
    onMotionChange(kick);
    resize();
    kick();
  }

  /* Hero 3D scene: follows the pointer and the scroll position. */
  const scene = $('[data-scene]');
  const rig = $('[data-rig]');
  if (scene && rig) {
    let px = 0; let py = 0; let raf = 0;
    const apply = () => {
      raf = 0;
      if (motion() === 'off') { rig.style.setProperty('--rx', '0deg'); rig.style.setProperty('--ry', '0deg'); return; }
      const k = motion() === 'calm' ? 0.4 : 1;
      const sy = Math.min(scrollY / innerHeight, 1);
      rig.style.setProperty('--rx', `${((-py * 8) + sy * 10) * k}deg`);
      rig.style.setProperty('--ry', `${(px * 14 - sy * 8) * k}deg`);
    };
    const req = () => { if (!raf) raf = requestAnimationFrame(apply); };
    if (canHover) {
      addEventListener('pointermove', (ev) => {
        px = ev.clientX / innerWidth - 0.5; py = ev.clientY / innerHeight - 0.5; req();
      }, { passive: true });
    }
    addEventListener('scroll', req, { passive: true });
    onMotionChange(req);
  }

  /* Showreel: 3D carousel ring. */
  const reel = $('[data-reel]');
  if (reel) {
    const ring = $('[data-reel-ring]', reel);
    const viewport = $('[data-reel-viewport]', reel);
    const cards = $$('.reel-card', ring);
    const titleEl = $('[data-reel-title]', reel);
    const capEl = $('[data-reel-caption]', reel);
    const dotsEl = $('[data-reel-dots]', reel);
    const n = cards.length; const step = 360 / n;
    let angle = 0; let target = 0; let raf = 0; let current = -1;
    let inView = false; let hover = false; let userTook = 0; let auto = 0;

    cards.forEach((c, i) => c.style.setProperty('--a', `${i * step}deg`));
    const dots = cards.map((c, i) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.setAttribute('aria-label', `Show ${c.dataset.title}`);
      b.addEventListener('click', () => { takeOver(); goTo(i); });
      dotsEl.appendChild(b);
      return b;
    });

    const indexOf = (a) => ((Math.round(-a / step) % n) + n) % n;
    const render = () => {
      ring.style.setProperty('--angle', `${angle}deg`);
      cards.forEach((c, i) => {
        let d = ((i * step + angle) % 360 + 540) % 360 - 180; // -180..180, 0 = front
        const f = Math.max(0, 1 - Math.abs(d) / (step * 1.2));
        c.style.setProperty('--b', (0.45 + 0.55 * Math.max(0, Math.cos(d * Math.PI / 180))).toFixed(3));
        c.style.setProperty('--front', f.toFixed(3));
      });
      const idx = indexOf(angle);
      if (idx !== current) {
        current = idx;
        titleEl.textContent = cards[idx].dataset.title;
        capEl.textContent = cards[idx].dataset.caption;
        dots.forEach((d, i) => d.setAttribute('aria-current', String(i === idx)));
      }
    };
    const tick = () => {
      raf = 0;
      const diff = target - angle;
      const ease = motion() === 'off' ? 1 : motion() === 'calm' ? 0.06 : 0.09;
      angle = Math.abs(diff) < 0.05 ? target : angle + diff * ease;
      render();
      if (angle !== target) raf = requestAnimationFrame(tick);
    };
    const kick = () => { if (!raf) raf = requestAnimationFrame(tick); };
    const goTo = (i) => {
      const base = Math.round(-target / step);
      let delta = ((i - ((base % n) + n) % n) % n + n) % n;
      if (delta > n / 2) delta -= n;
      target = -(base + delta) * step;
      kick();
    };
    const next = () => { target = (Math.round(target / step) - 1) * step; kick(); };
    const prev = () => { target = (Math.round(target / step) + 1) * step; kick(); };
    const takeOver = () => { userTook = Date.now(); };

    const schedule = () => {
      clearTimeout(auto);
      if (motion() === 'off' || !inView || hover) return;
      const wait = motion() === 'calm' ? 7000 : 3600;
      auto = setTimeout(() => { if (Date.now() - userTook > 9000) next(); schedule(); }, wait);
    };

    $('[data-reel-next]', reel).addEventListener('click', () => { takeOver(); next(); });
    $('[data-reel-prev]', reel).addEventListener('click', () => { takeOver(); prev(); });
    reel.addEventListener('keydown', (ev) => {
      if (ev.key === 'ArrowRight') { takeOver(); next(); ev.preventDefault(); }
      if (ev.key === 'ArrowLeft') { takeOver(); prev(); ev.preventDefault(); }
    });
    viewport.addEventListener('pointerenter', () => { hover = true; schedule(); });
    viewport.addEventListener('pointerleave', () => { hover = false; schedule(); });

    // Drag / swipe to spin; releases snap to the nearest card.
    let dragX = null; let dragStart = 0; let moved = false;
    viewport.addEventListener('pointerdown', (ev) => { dragX = ev.clientX; dragStart = target; moved = false; viewport.setPointerCapture(ev.pointerId); takeOver(); });
    viewport.addEventListener('pointermove', (ev) => {
      if (dragX === null) return;
      const dx = ev.clientX - dragX;
      if (Math.abs(dx) > 4) moved = true;
      target = dragStart + dx * (step / (viewport.clientWidth * 0.35));
      angle = target; render();
    });
    const release = () => {
      if (dragX === null) return;
      dragX = null;
      target = Math.round(target / step) * step;
      kick();
    };
    viewport.addEventListener('pointerup', release);
    viewport.addEventListener('pointercancel', release);
    // A plain click on a side card brings it to the front.
    cards.forEach((c, i) => c.addEventListener('click', () => { if (!moved) { takeOver(); goTo(i); } }));

    if (hasIO) new IntersectionObserver((es) => { inView = es[0].isIntersecting; schedule(); }, { threshold: 0.3 }).observe(viewport);
    onMotionChange(() => { schedule(); kick(); });
    render();
  }
})();
