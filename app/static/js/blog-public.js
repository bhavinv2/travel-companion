/* The public blog (pages/blog.html, pages/blog_post.html): the pictures that swipe on each card; share, WhatsApp
   and save; the list that goes on as it is scrolled; the "Saved" round at the top; the reading bar on a post.
   Saved posts live in this browser only (localStorage 'blog.saved'): readers have no accounts on the blog. */
(function () {
  const KEY = 'blog.saved';
  const SAVED_MAX = 60;                     // as many as the list page asks for (routes/blog.py)
  const read = () => { try { return JSON.parse(localStorage.getItem(KEY) || '[]').filter(s => typeof s === 'string'); } catch (e) { return []; } };
  const write = list => { try { localStorage.setItem(KEY, JSON.stringify(list.slice(0, SAVED_MAX))); } catch (e) { /* private mode */ } };

  function toast(msg) {
    let t = document.querySelector('.bj-toast');
    if (!t) {
      t = document.createElement('div');
      t.className = 'bj-toast';
      t.setAttribute('role', 'status');
      document.body.appendChild(t);
    }
    t.textContent = msg;
    t.classList.add('on');
    clearTimeout(t.hideT);
    t.hideT = setTimeout(() => t.classList.remove('on'), 2400);
  }

  // ---------------------------------------------------------------- the pictures on a card swipe
  function slides(media) {
    if (media.dataset.ready) return;
    media.dataset.ready = '1';
    const box = media.querySelector('.bp-slides');
    const dots = Array.from(media.querySelectorAll('.bp-dots i'));
    const count = media.querySelector('.bp-count');
    const prev = media.querySelector('.bp-prev'), next = media.querySelector('.bp-next');
    const n = box.children.length;
    let raf = 0;
    function paint() {
      const i = Math.min(n - 1, Math.max(0, Math.round(box.scrollLeft / Math.max(1, box.clientWidth))));
      dots.forEach((d, j) => d.classList.toggle('on', j === i));
      if (count) count.textContent = (i + 1) + '/' + n;
      if (prev) prev.hidden = i === 0;
      if (next) next.hidden = i === n - 1;
      Array.from(box.children).forEach((a, j) => {           // only the picture in view is a stop for the keyboard
        a.tabIndex = j === i ? 0 : -1;
        a.setAttribute('aria-hidden', j === i ? 'false' : 'true');
      });
    }
    box.addEventListener('scroll', () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(paint); }, { passive: true });
    const go = step => box.scrollBy({ left: step * box.clientWidth, behavior: 'smooth' });
    if (prev) prev.addEventListener('click', () => go(-1));
    if (next) next.addEventListener('click', () => go(1));
  }

  // ---------------------------------------------------------------- saved for later
  function paintSaved(root) {
    const list = read();
    (root || document).querySelectorAll('[data-act=save]').forEach(b => {
      const holder = b.closest('[data-slug]');
      const on = !!holder && list.includes(holder.dataset.slug);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      b.title = on ? 'Saved: tap to take it off' : 'Save for later';
      const i = b.querySelector('i');
      if (i) i.className = (on ? 'fa-solid' : 'fa-regular') + ' fa-bookmark';
    });
    const story = document.getElementById('bjSaved');
    if (story) {
      story.hidden = !list.length && !story.classList.contains('on');
      const u = new URL(document.getElementById('bjStories').dataset.savedUrl, location.href);
      u.searchParams.set('saved', list.join(','));
      story.href = u.pathname + u.search;
      story.querySelector('[data-saved-n]').textContent = list.length ? '(' + list.length + ')' : '';
    }
  }

  // ---------------------------------------------------------------- share, WhatsApp, save
  document.addEventListener('click', async e => {
    const b = e.target.closest('[data-act]');
    const holder = b && b.closest('[data-slug]');
    if (!holder) return;
    const title = holder.dataset.title || document.title;
    const url = holder.dataset.url ? new URL(holder.dataset.url, location.href).href : location.href;
    const act = b.dataset.act;
    if (act === 'wa') {
      window.open('https://wa.me/?text=' + encodeURIComponent(title + '\n' + url), '_blank', 'noopener');
    } else if (act === 'share') {
      if (navigator.share) {
        try { await navigator.share({ title, url }); } catch (err) { /* closed */ }
        return;
      }
      try { await navigator.clipboard.writeText(url); toast('Link copied: paste it anywhere'); }
      catch (err) { window.prompt('Copy this link', url); }
    } else if (act === 'save') {
      const slug = holder.dataset.slug;
      if (!slug) { toast('A post can be saved once it is published.'); return; }
      const on = !read().includes(slug);
      write(on ? [slug].concat(read()) : read().filter(s => s !== slug));
      paintSaved();
      b.classList.remove('is-pop');
      void b.offsetWidth;                        // start the pop again
      b.classList.add('is-pop');
      toast(on ? 'Saved: find it under “Saved” at the top of the blog' : 'Taken off your saved posts');
    }
  });

  // ---------------------------------------------------------------- the list goes on as it is scrolled
  const feed = document.getElementById('bjFeed');
  const end = document.getElementById('bjEnd');
  let busy = false, stopped = false;
  async function more() {
    const a = document.getElementById('bjMore');
    if (!a || busy) return;
    busy = true;
    a.classList.add('is-busy');
    a.textContent = 'Loading…';
    try {
      const u = new URL(a.href, location.href);
      u.searchParams.set('chunk', '1');
      const r = await fetch(u, { credentials: 'same-origin' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const box = document.createElement('div');
      box.innerHTML = await r.text();
      const cards = Array.from(box.querySelectorAll('.bp'));
      cards.forEach(c => {
        feed.appendChild(c);
        const m = c.querySelector('.bp-media.is-multi');
        if (m) slides(m);
      });
      paintSaved(feed);
      const nxt = r.headers.get('X-Next');
      if (nxt) {
        a.href = nxt;
        a.classList.remove('is-busy');
        a.textContent = 'Load more stories';
      } else {
        end.innerHTML = '<p class="bj-done"><i class="fa-regular fa-circle-check"></i> You’re all caught up</p>';
      }
    } catch (err) {
      stopped = true;                            // the button still works; scrolling stops asking
      a.classList.remove('is-busy');
      a.textContent = 'Load more stories';
    }
    busy = false;
    requestAnimationFrame(near);                 // a short page: the end may still be in sight
  }
  function near() {
    if (!stopped && end.getBoundingClientRect().top < window.innerHeight + 900) more();
  }
  if (feed && end) {
    end.addEventListener('click', e => { if (e.target.closest('#bjMore')) { e.preventDefault(); stopped = false; more(); } });
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(es => { if (es.some(x => x.isIntersecting)) near(); }, { rootMargin: '900px 0px' }).observe(end);
    }
  }

  // ---------------------------------------------------------------- the reading bar on a post
  const bar = document.getElementById('bjProgress');
  if (bar) {
    let raf = 0;
    const paint = () => {
      const room = document.documentElement.scrollHeight - window.innerHeight;
      bar.style.width = (room > 0 ? Math.min(100, 100 * window.scrollY / room) : 0) + '%';
    };
    window.addEventListener('scroll', () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(paint); }, { passive: true });
    paint();
  }

  document.querySelectorAll('.bp-media.is-multi').forEach(slides);
  paintSaved();

  /* ---------------------------------------------------------------- the blocks inside a post (blog-blocks.css) */
  // a carousel or slider: arrows, dots, and moving by itself every N seconds (data-interval) -- not while it is
  // pointed at, touched or focused, and never when the reader asked for less motion
  const still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  document.querySelectorAll('.bj-content .blog-carousel').forEach(track => {
    const slidesOf = () => Array.from(track.querySelectorAll(':scope > .blog-slide'));
    if (slidesOf().length < 2) return;
    const wrap = document.createElement('div');
    wrap.className = 'bc-wrap';
    track.before(wrap);
    wrap.appendChild(track);
    const btn = (cls, label, icon) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'bc-btn ' + cls;
      b.setAttribute('aria-label', label);
      b.innerHTML = '<i class="fa-solid ' + icon + '" aria-hidden="true"></i>';
      wrap.appendChild(b);
      return b;
    };
    const prev = btn('bc-prev', 'Earlier', 'fa-chevron-left'), next = btn('bc-next', 'Later', 'fa-chevron-right');
    const dots = document.createElement('div');
    dots.className = 'bc-dots';
    wrap.appendChild(dots);
    const step = () => (slidesOf()[0] ? slidesOf()[0].getBoundingClientRect().width + 16 : track.clientWidth);
    const at = () => Math.round(track.scrollLeft / step());
    const pages = () => Math.max(1, slidesOf().length - Math.round(track.clientWidth / step()) + 1);
    const go = i => track.scrollTo({ left: Math.max(0, Math.min(i, pages() - 1)) * step(), behavior: 'smooth' });
    function paintDots() {
      const n = pages(), i = Math.min(at(), n - 1);
      if (dots.children.length !== n) {
        dots.innerHTML = '';
        for (let k = 0; k < n; k++) {
          const d = document.createElement('button');
          d.type = 'button';
          d.setAttribute('aria-label', 'Go to ' + (k + 1) + ' of ' + n);
          d.addEventListener('click', () => go(k));
          dots.appendChild(d);
        }
      }
      Array.from(dots.children).forEach((d, k) => d.setAttribute('aria-current', k === i ? 'true' : 'false'));
      prev.disabled = i <= 0;
      next.disabled = i >= n - 1;
    }
    prev.addEventListener('click', () => go(at() - 1));
    next.addEventListener('click', () => go(at() + 1));
    let t = null;
    track.addEventListener('scroll', () => { clearTimeout(t); t = setTimeout(paintDots, 80); }, { passive: true });
    window.addEventListener('resize', paintDots);
    paintDots();
    const every = +(track.dataset.interval || 0);
    if (every > 0 && !still) {
      let held = false;
      ['mouseenter', 'focusin', 'touchstart'].forEach(ev => wrap.addEventListener(ev, () => { held = true; }, { passive: true }));
      ['mouseleave', 'focusout'].forEach(ev => wrap.addEventListener(ev, () => { held = false; }));
      setInterval(() => { if (!held && !document.hidden) go(at() >= pages() - 1 ? 0 : at() + 1); }, every * 1000);
    }
  });
  // space of the height chosen in the editor
  document.querySelectorAll('.bj-content .blog-spacer').forEach(d => {
    const h = Math.min(+(d.dataset.h || 48) || 48, 400);
    d.style.height = h + 'px';
  });
  // the post's own code, in its sandboxed frame, says how tall it is (only a frame of this page is believed)
  window.addEventListener('message', e => {
    if (!e.data || typeof e.data.blogFrame !== 'number') return;
    document.querySelectorAll('.bj-content iframe.blog-code-frame[data-auto="1"]').forEach(f => {
      if (f.contentWindow === e.source) f.style.height = Math.min(Math.max(+e.data.height || 0, 40), 4000) + 'px';
    });
  });
})();
