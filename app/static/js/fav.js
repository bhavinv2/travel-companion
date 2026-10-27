/* The header's star, "This page" (base.html, routes/favourites.py): opens and closes its panel. Everything in it is
 * a plain form that comes back to this page, so this only does the opening: one panel at a time, Escape or a click
 * elsewhere closes it, and focus goes to the name field. "Open it" on Leads and Contacts opens the page's own
 * Views menu instead (one home for those views). */
(function () {
  const dd = document.getElementById('favDD');
  if (!dd) return;
  const btn = dd.querySelector('[data-fav-toggle]');
  const pop = dd.querySelector('.fav-pop');

  function open(on) {
    pop.hidden = !on;
    dd.classList.toggle('open', on);
    btn.setAttribute('aria-expanded', on ? 'true' : 'false');
    if (on) {
      const first = pop.querySelector('[data-fav-label], input:not([type=hidden]), a, button');
      if (first) first.focus({ preventScroll: true });
    }
  }
  btn.addEventListener('click', function (e) {
    e.stopPropagation();
    open(pop.hidden);
  });
  document.addEventListener('click', function (e) {
    if (!pop.hidden && !dd.contains(e.target)) open(false);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !pop.hidden) {
      open(false);
      btn.focus();
    }
  });
  const views = pop.querySelector('[data-fav-open-views]');
  if (views) {
    views.addEventListener('click', function () {
      const menu = document.querySelector('.vw-menu');
      open(false);
      if (!menu) return;
      menu.open = true;
      menu.scrollIntoView({ block: 'center', behavior: 'smooth' });
      const s = menu.querySelector('summary');
      if (s) s.focus({ preventScroll: true });
    });
  }
  window.FavStar = { open: open };
})();
