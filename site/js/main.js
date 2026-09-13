// Whisper Transcriber Suite — page interactions (no third-party requests).
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const hasIO = 'IntersectionObserver' in window;

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
    if (platform === 'mac') ctaLabel.textContent = 'Download for macOS';
    if (platform === 'linux') { ctaLabel.textContent = 'Get it for Linux'; cta.href = '#download'; cta.removeAttribute('rel'); }
    if (platform === 'mobile') { ctaLabel.textContent = 'Get it for your computer'; cta.href = '#download'; cta.removeAttribute('rel'); }
  }
  const recCard = $(`.dl-card[data-os="${platform === 'mobile' ? 'windows' : platform}"]`);
  if (recCard && platform !== 'mobile') {
    recCard.classList.add('is-recommended');
    const badge = $('[data-rec-badge]', recCard);
    if (badge) badge.hidden = false;
  }

  /* Scroll reveals, staggered within each batch that enters together. */
  const srEls = $$('.sr');
  if (!hasIO || reduceMotion) {
    srEls.forEach((el) => el.classList.add('in'));
  } else {
    const io = new IntersectionObserver((entries) => {
      let i = 0;
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        e.target.style.setProperty('--sr-delay', `${Math.min(i++ * 80, 400)}ms`);
        e.target.classList.add('in');
        io.unobserve(e.target);
      }
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    srEls.forEach((el) => io.observe(el));
  }

  /* Feature visuals only animate while on screen. */
  const liveEls = $$('[data-live]');
  if (hasIO) {
    const liveIO = new IntersectionObserver((entries) => {
      for (const e of entries) {
        e.target.classList.toggle('is-live', e.isIntersecting && !reduceMotion);
        e.target.dispatchEvent(new CustomEvent(e.isIntersecting ? 'live:on' : 'live:off'));
      }
    }, { threshold: 0.2 });
    liveEls.forEach((el) => liveIO.observe(el));
  } else if (!reduceMotion) {
    liveEls.forEach((el) => el.classList.add('is-live'));
  }

  /* Cursor spotlight across the bento. */
  const bento = $('[data-spotlight]');
  if (bento && matchMedia('(hover: hover)').matches) {
    bento.addEventListener('pointermove', (ev) => {
      for (const cell of bento.children) {
        const r = cell.getBoundingClientRect();
        cell.style.setProperty('--mx', `${ev.clientX - r.left}px`);
        cell.style.setProperty('--my', `${ev.clientY - r.top}px`);
      }
    }, { passive: true });
  }

  /* Live-transcription typer. */
  const typer = $('[data-typer]');
  const liveCell = typer && typer.closest('[data-live]');
  if (typer && liveCell && !reduceMotion) {
    const phrases = ['so the words appear as you speak', 'cuts land on natural pauses', 'and no word is ever split in two'];
    let timer = 0; let running = false; let p = 0; let c = phrases[0].length; let dir = -1;
    const tick = () => {
      if (!running) return;
      const phrase = phrases[p];
      c += dir;
      typer.textContent = phrase.slice(0, Math.max(0, c));
      let wait = dir > 0 ? 42 + Math.random() * 50 : 16;
      if (dir > 0 && c >= phrase.length) { dir = -1; wait = 1800; }
      else if (dir < 0 && c <= 0) { dir = 1; p = (p + 1) % phrases.length; wait = 380; }
      timer = setTimeout(tick, wait);
    };
    liveCell.addEventListener('live:on', () => { if (!running) { running = true; timer = setTimeout(tick, 900); } });
    liveCell.addEventListener('live:off', () => { running = false; clearTimeout(timer); });
  }

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

  /* Product tour: accessible tabs, autoplay while visible, gentle 3D tilt. */
  const tablist = $('.tour-tabs');
  if (tablist) {
    const tabs = $$('[role="tab"]', tablist);
    const shots = $$('.app-shots img');
    const panel = $('#tour-panel');
    const caption = $('[data-tour-caption]');
    const stage = $('.tour-stage');
    const captions = [
      'A drop target, engine and language pickers, speaker-label and word-timestamp options.',
      'Batch jobs with live progress — pause, resume, cancel, re-run or remove any row.',
      'Pick a format, clip a time range, pull subtitles, optionally transcribe as soon as the download finishes.',
      'One button turns this machine into a transcription page for other devices on the network.',
      'Play one live stream as a full-screen grid, optionally across several monitors.',
    ];
    const DURATION = 5600;
    let current = 0; let userTook = false; let inView = false; let hovering = false; let autoTimer = 0; let progressAnim = null;

    const select = (i, focus = false) => {
      current = (i + tabs.length) % tabs.length;
      tabs.forEach((t, k) => {
        const on = k === current;
        t.setAttribute('aria-selected', String(on));
        t.tabIndex = on ? 0 : -1;
        const bar = t.querySelector('.tab-progress');
        if (bar) bar.remove();
      });
      shots.forEach((img, k) => img.classList.toggle('is-active', k === current));
      if (panel) panel.setAttribute('aria-labelledby', tabs[current].id);
      if (caption) caption.textContent = captions[current];
      if (focus) tabs[current].focus();
      schedule();
    };

    const schedule = () => {
      clearTimeout(autoTimer);
      if (progressAnim) { progressAnim.cancel(); progressAnim = null; }
      if (userTook || !inView || hovering || reduceMotion) return;
      const bar = document.createElement('span');
      bar.className = 'tab-progress';
      tabs[current].appendChild(bar);
      if (bar.animate) progressAnim = bar.animate([{ transform: 'scaleX(0)' }, { transform: 'scaleX(1)' }], { duration: DURATION, easing: 'linear', fill: 'forwards' });
      autoTimer = setTimeout(() => select(current + 1), DURATION);
    };

    const takeOver = () => { userTook = true; clearTimeout(autoTimer); if (progressAnim) progressAnim.cancel(); $$('.tab-progress', tablist).forEach((b) => b.remove()); };

    tabs.forEach((t, k) => t.addEventListener('click', () => { takeOver(); select(k); }));
    tablist.addEventListener('keydown', (ev) => {
      const keys = { ArrowRight: current + 1, ArrowLeft: current - 1, Home: 0, End: tabs.length - 1 };
      if (!(ev.key in keys)) return;
      ev.preventDefault();
      takeOver();
      select(keys[ev.key], true);
    });

    if (hasIO && stage) {
      new IntersectionObserver((entries) => {
        for (const e of entries) {
          inView = e.isIntersecting;
          stage.classList.toggle('in-view', e.isIntersecting || stage.classList.contains('in-view'));
          schedule();
        }
      }, { threshold: 0.35 }).observe(stage);
    } else if (stage) {
      stage.classList.add('in-view');
    }

    if (stage && matchMedia('(hover: hover)').matches && !reduceMotion) {
      const win = $('.app-window', stage);
      let raf = 0; let tx = 0; let ty = 0;
      stage.addEventListener('pointerenter', () => { hovering = true; stage.classList.add('is-tilting'); schedule(); });
      stage.addEventListener('pointerleave', () => {
        hovering = false; stage.classList.remove('is-tilting');
        win.style.setProperty('--tx', '0deg'); win.style.setProperty('--ty', '0deg');
        schedule();
      });
      stage.addEventListener('pointermove', (ev) => {
        const r = stage.getBoundingClientRect();
        tx = (0.5 - (ev.clientY - r.top) / r.height) * 5;
        ty = ((ev.clientX - r.left) / r.width - 0.5) * 7;
        if (!raf) raf = requestAnimationFrame(() => { raf = 0; win.style.setProperty('--tx', `${tx.toFixed(2)}deg`); win.style.setProperty('--ty', `${ty.toFixed(2)}deg`); });
      }, { passive: true });
    }
  }
})();
