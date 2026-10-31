document.querySelectorAll('[data-tour-load]').forEach((button) => {
  button.addEventListener('click', () => {
    const player = button.closest('[data-tour-player]');
    if (!player) return;
    const frame = document.createElement('iframe');
    frame.src = 'https://www.youtube-nocookie.com/embed/pfnjrinmayA?autoplay=1';
    frame.title = button.getAttribute('aria-label');
    frame.allow = 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share';
    frame.allowFullscreen = true;
    player.replaceChildren(frame);
    frame.focus();
  });
});
