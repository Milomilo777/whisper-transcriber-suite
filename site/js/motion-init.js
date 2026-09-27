// Runs before first paint (loaded synchronously in <head>).
// Motion preference: a stored choice wins; otherwise follow the OS
// ("calm" = slow ambient motion only when the OS asks to reduce motion).
(function () {
  var d = document.documentElement, m = null;
  d.classList.add('js');
  try { m = localStorage.getItem('wts-motion'); } catch (e) {}
  var q = /[?&]motion=(on|off|calm)\b/.exec(location.search); if (q) m = q[1]; // QA/capture override, not stored
  if (m !== 'on' && m !== 'off') m = matchMedia('(prefers-reduced-motion: reduce)').matches ? 'calm' : 'on';
  d.dataset.motion = m;
})();
