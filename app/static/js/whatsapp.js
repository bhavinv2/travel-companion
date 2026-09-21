/* Team chooser for the WhatsApp buttons (templates/_whatsapp.html). Any [data-wa-open] button opens
   the one #waChooser on the page. The browser time zone pre-highlights the likely team; it is a
   hint, never a decision: an NRI in Dallas arranging a trip from Hyderabad may well want India. */
(function () {
  const chooser = document.getElementById('waChooser'), overlay = document.getElementById('waChooserOverlay');
  if (!chooser || !overlay) return;
  const likelyRegion = () => {
    let tz = '';
    try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (e) {}
    return /^America\//.test(tz) ? 'us' : 'in';
  };
  function open(e) {
    e.preventDefault();
    const likely = likelyRegion();
    chooser.querySelectorAll('.wa-opt').forEach(o => o.classList.toggle('is-likely', o.dataset.region === likely));
    overlay.hidden = false; chooser.hidden = false;
    requestAnimationFrame(() => { overlay.classList.add('open'); chooser.classList.add('open'); });
    setTimeout(() => chooser.querySelector('.wa-opt.is-likely')?.focus(), 200);
  }
  function close() {
    overlay.classList.remove('open'); chooser.classList.remove('open');
    setTimeout(() => { overlay.hidden = true; chooser.hidden = true; }, 220);
  }
  document.addEventListener('click', e => { if (e.target.closest('[data-wa-open]')) open(e); });
  chooser.querySelectorAll('.wa-opt').forEach(o => o.addEventListener('click', () => setTimeout(close, 80)));
  document.getElementById('waChooserClose').addEventListener('click', close);
  overlay.addEventListener('click', close);
  // Capture phase + stopPropagation: the chooser is the top layer, so Esc must close only it and
  // never the sign-up prompt / contact modal / drawer that may be open underneath.
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !chooser.hidden) { e.stopPropagation(); close(); }
  }, true);
})();
