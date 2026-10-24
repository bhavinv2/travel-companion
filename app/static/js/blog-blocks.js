/* The blocks of a blog post beyond text (admin/blog_edit.html, loaded before blog-studio.js): two or three columns, a
   picture beside text, a picture carousel and a content slider, a video, YouTube and Vimeo, the post's own
   HTML / CSS / JS, and space -- and, for every block, its settings in the Block tab: space above and below, padding,
   background, width and text alignment, and what each kind has of its own. The post's layout (Post › Layout) is
   shown on the editor as it is chosen.

   What a block is lives in its class (blog_engine keeps exactly these: _DIVS, _CLASSES, _STYLE_RE). The public
   page draws the players, the sandboxed code and the carousels; here a block shows a preview, in a <bs-live>
   element, which blog-studio.js takes out of everything it saves or copies (and the server drops). */
window.BlogBlocks = (function () {
  'use strict';
  let S = null;                                    // window.BlogStudio, once the editor is up (init)
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const icon = i => (i.startsWith('fa-brands') ? i : 'fa-solid ' + i);

  const items = [
    { key: 'cols2', label: 'Two columns', icon: 'fa-table-columns', hint: 'Side by side: text, pictures, lists', words: 'columns layout grid side by side' },
    { key: 'cols3', label: 'Three columns', icon: 'fa-table-cells-large', hint: 'Three side by side', words: 'columns layout grid' },
    { key: 'mt', label: 'Picture and text', icon: 'fa-object-group', hint: 'A picture on the left or right, text beside it', words: 'media text image split side left right' },
    { key: 'carousel', label: 'Picture carousel', icon: 'fa-images', hint: 'Pictures one after another, with arrows', words: 'gallery slider slideshow images carousel' },
    { key: 'slider', label: 'Content slider', icon: 'fa-layer-group', hint: 'Cards of text that slide', words: 'carousel slides cards testimonials quotes' },
    { key: 'video', label: 'Video', icon: 'fa-video', hint: 'Upload an MP4, or link one', words: 'movie clip mp4 upload film' },
    { key: 'youtube', label: 'YouTube or Vimeo', icon: 'fa-brands fa-youtube', hint: 'Paste its link: it plays in the post', words: 'embed video youtube vimeo' },
    { key: 'code', label: 'Custom HTML / CSS / JS', icon: 'fa-code', hint: 'Your own code, run apart from the site', words: 'html css javascript embed widget script code iframe' },
    { key: 'spacer', label: 'Space', icon: 'fa-arrows-up-down', hint: 'Empty space between blocks', words: 'spacer gap margin blank' },
  ];
  const NAMES = { cols: 'Columns', mt: 'Picture and text', carousel: 'Picture carousel', slider: 'Content slider',
                  video: 'Video', embed: 'YouTube or Vimeo', code: 'Custom code', spacer: 'Space' };
  const ICONS = { cols: 'fa-table-columns', mt: 'fa-object-group', carousel: 'fa-images', slider: 'fa-layer-group',
                  video: 'fa-video', embed: 'fa-brands fa-youtube', code: 'fa-code', spacer: 'fa-arrows-up-down' };

  function kindOf(b) {
    if (!b || b.nodeType !== 1) return null;
    const c = b.classList;
    if (b.tagName === 'DIV') {
      if (c.contains('blog-cols')) return 'cols';
      if (c.contains('blog-mt')) return 'mt';
      if (c.contains('blog-carousel')) return b.querySelector(':scope > div.blog-slide') ? 'slider' : 'carousel';
      if (c.contains('blog-code')) return 'code';
      if (c.contains('blog-spacer')) return 'spacer';
    }
    if (b.tagName === 'FIGURE') return c.contains('blog-embed') ? 'embed' : c.contains('blog-video') ? 'video' : 'picture';
    if (b.tagName === 'P' && c.contains('blog-cta-wrap')) return 'button';
    return 'text';
  }

  // a YouTube or Vimeo address -> {provider, id, start}: the same rules as blog_engine.embed_of
  function embedOf(url) {
    url = (url || '').trim();
    let m = url.match(/^(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?(?:.*&)?v=|shorts\/|embed\/|live\/)|youtu\.be\/)([A-Za-z0-9_-]{6,20})/);
    let provider = 'youtube';
    if (!m) { m = url.match(/^(?:https?:\/\/)?(?:www\.|player\.)?vimeo\.com\/(?:video\/)?(\d{5,12})/); provider = 'vimeo'; }
    if (!m) return null;
    const t = url.match(/[?&#](?:t|start)=(?:(\d+)h)?(?:(\d+)m)?(\d+)?s?/);
    const start = t ? (+(t[1] || 0)) * 3600 + (+(t[2] || 0)) * 60 + (+(t[3] || 0)) : 0;
    return { provider, id: m[1], start };
  }
  const isVideoFile = url => /^(https?:\/\/|\/(?!\/))\S+\.(mp4|webm)(\?\S*)?$/i.test(url || '');

  function make(html) { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; }

  // ---------------------------------------------------------------- adding
  const CODE_START = '<div class="hello">Hello from the post</div>\n<style>\n  .hello { padding: 24px; border-radius: 12px; background: #eaf3fe; font: 600 18px system-ui; }\n</style>\n<script>\n  document.querySelector(\'.hello\').addEventListener(\'click\', e => e.target.textContent = \'Clicked!\');\n</script>';
  function insert(key, target) {
    let node = null, focus = null, settings = false;
    if (key === 'cols2' || key === 'cols3') {
      const n = key === 'cols2' ? 2 : 3;
      node = make('<div class="blog-cols" data-cols="' + n + '">' + Array.from({ length: n }, (_, i) =>
        '<div class="blog-col"><h3>Column ' + (i + 1) + '</h3><p>Write here.</p></div>').join('') + '</div>');
      focus = node.querySelector('p');
    } else if (key === 'mt') {
      node = make('<div class="blog-mt" data-pos="left" data-ratio="50"><figure class="blog-mt-media"></figure>' +
        '<div class="blog-mt-body"><h3>A heading beside the picture</h3><p>Write here.</p></div></div>');
      settings = true;
    } else if (key === 'carousel') {
      node = make('<div class="blog-carousel" data-show="1" data-interval="5"></div>');
      settings = true;
    } else if (key === 'slider') {
      node = make('<div class="blog-carousel" data-show="2" data-interval="0">' + [1, 2, 3].map(i =>
        '<div class="blog-slide"><h3>Card ' + i + '</h3><p>Write here.</p></div>').join('') + '</div>');
      settings = true;
    } else if (key === 'video') { node = make('<figure class="blog-video"></figure>'); settings = true; }
    else if (key === 'youtube') { node = make('<figure class="blog-embed"></figure>'); settings = true; }
    else if (key === 'code') { node = make('<div class="blog-code" data-h="auto" data-title="Embedded content"><pre>' + esc(CODE_START) + '</pre></div>'); settings = true; }
    else if (key === 'spacer') { node = make('<div class="blog-spacer" data-h="48"></div>'); settings = true; }
    else return false;
    let line = null;
    S.structural(() => { S.place(node, target); line = S.after(node); });
    if (focus) S.caretIn(focus, true); else if (!settings && line) S.caretIn(line);
    S.setActive(node);
    if (settings) S.blockSettings(node);
    return true;
  }
  // a YouTube or Vimeo link, or a video file's address, pasted on an empty line: that video, not a link
  function pasteUrl(url, target) {
    if (!target || !S.isEmpty(target)) return false;
    const e = embedOf(url);
    let node = null;
    if (e) node = make('<figure class="blog-embed" data-provider="' + e.provider + '" data-vid="' + esc(e.id) + '"' + (e.start ? ' data-start="' + e.start + '"' : '') + '></figure>');
    else if (isVideoFile(url)) node = make('<figure class="blog-video"><video src="' + esc(url) + '" controls preload="metadata"></video></figure>');
    if (!node) return false;
    S.structural(() => { S.place(node, target); S.after(node); });
    S.setActive(node);
    S.toast(e ? 'The video plays in the post. Its settings are in the Block tab.' : 'The video is in the post.', 'success');
    return true;
  }

  // ---------------------------------------------------------------- previews (never saved)
  function live(el, key, html, cls) {
    let p = el.querySelector(':scope > bs-live');
    if (p && p.dataset.key === key) return p;
    if (p) p.remove();
    p = document.createElement('bs-live');
    p.dataset.key = key;
    p.className = cls || '';
    p.setAttribute('contenteditable', 'false');
    p.innerHTML = html;
    el.prepend(p);
    return p;
  }
  const hash = s => { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return String(h); };
  const HEIGHT_JS = '<script>(function(){function h(){parent.postMessage({blogFrame:"edit",height:Math.ceil(document.documentElement.getBoundingClientRect().height)},"*")}addEventListener("load",h);if(window.ResizeObserver)new ResizeObserver(h).observe(document.documentElement);setTimeout(h,400)})()<\/script>';
  function decorate(root) {
    root.querySelectorAll('figure.blog-embed').forEach(f => {
      const id = f.dataset.vid, kind = f.dataset.provider;
      if (id && kind === 'youtube') live(f, 'yt' + id, '<img src="https://img.youtube.com/vi/' + esc(id) + '/hqdefault.jpg" alt=""><span class="bs-play"><i class="fa-brands fa-youtube"></i></span><small>YouTube · plays in the post, fullscreen too</small>', 'bs-embed-prev');
      else if (id) live(f, 'vm' + id, '<span class="bs-play vimeo"><i class="fa-brands fa-vimeo-v"></i></span><small>Vimeo video ' + esc(id) + ' · plays in the post</small>', 'bs-embed-prev is-vimeo');
      else live(f, 'none', '<span class="bs-empty"><i class="fa-brands fa-youtube"></i> Paste a YouTube or Vimeo link in the Block tab</span>', 'bs-embed-prev is-empty');
    });
    root.querySelectorAll('figure.blog-video').forEach(f => {
      const p = f.querySelector(':scope > bs-live');
      if (f.querySelector('video')) { if (p) p.remove(); return; }
      live(f, 'none', '<span class="bs-empty"><i class="fa-solid fa-video"></i> Upload a video, or paste its link, in the Block tab</span>', 'bs-placeholder');
    });
    root.querySelectorAll('figure.blog-mt-media').forEach(f => {
      const p = f.querySelector(':scope > bs-live');
      if (f.querySelector('img, video')) { if (p) p.remove(); return; }
      live(f, 'none', '<span class="bs-empty"><i class="fa-regular fa-image"></i> Choose a picture in the Block tab</span>', 'bs-placeholder');
    });
    root.querySelectorAll('div.blog-carousel').forEach(c => {
      const p = c.querySelector(':scope > bs-live');
      if (c.querySelector(':scope > .blog-slide')) { if (p) p.remove(); return; }
      live(c, 'none', '<span class="bs-empty"><i class="fa-solid fa-images"></i> Add pictures in the Block tab</span>', 'bs-placeholder');
    });
    root.querySelectorAll('div.blog-spacer').forEach(d => {
      const h = Math.min(+(d.dataset.h || 48) || 48, 400);
      d.style.height = h + 'px';
      live(d, 'h' + h, '<span>Space · ' + h + ' px</span>', 'bs-spacer-label');
    });
    root.querySelectorAll('div.blog-code').forEach(d => {
      const code = d.querySelector('pre') ? d.querySelector('pre').textContent : '';
      const key = hash(code + '|' + (d.dataset.h || 'auto'));
      const p = live(d, key, '<span class="bs-code-tag"><i class="fa-solid fa-code"></i> Your code, running apart from the site</span><iframe sandbox="allow-scripts allow-forms allow-modals" title="Preview of the code"></iframe>', 'bs-code-prev');
      const frame = p.querySelector('iframe');
      if (frame.dataset.done !== key) {
        frame.dataset.done = key;
        frame.style.height = (d.dataset.h && d.dataset.h !== 'auto' ? Math.min(+d.dataset.h, 4000) : 160) + 'px';
        frame.dataset.auto = d.dataset.h === 'auto' || !d.dataset.h ? '1' : '0';
        frame.srcdoc = '<!doctype html><html><head><meta charset="utf-8"><base target="_blank"><style>html,body{margin:0}</style></head><body>' + code + HEIGHT_JS + '</body></html>';
      }
    });
  }
  // the code's preview says how tall it is
  window.addEventListener('message', e => {
    if (!e.data || e.data.blogFrame !== 'edit') return;
    document.querySelectorAll('.bs-code-prev iframe').forEach(f => {
      if (f.contentWindow === e.source && f.dataset.auto === '1') f.style.height = Math.min(Math.max(+e.data.height || 0, 40), 4000) + 'px';
    });
  });

  // ---------------------------------------------------------------- names, for the bar and the list view
  function name(b) { const k = kindOf(b); return NAMES[k] || null; }
  function iconFor(b) { const k = kindOf(b); return ICONS[k] || null; }
  function text(b) {
    const k = kindOf(b);
    if (k === 'embed') return b.dataset.vid ? (b.dataset.provider === 'vimeo' ? 'Vimeo ' : 'YouTube ') + b.dataset.vid : 'no link yet';
    if (k === 'video') { const v = b.querySelector('video'); return v ? (v.getAttribute('src') || '').split('/').pop() : 'no video yet'; }
    if (k === 'code') { const t = (b.querySelector('pre') || {}).textContent || ''; return t.replace(/\s+/g, ' ').trim().slice(0, 50); }
    if (k === 'carousel') return S.plural(b.querySelectorAll(':scope > figure.blog-slide').length, 'picture');
    if (k === 'slider') return S.plural(b.querySelectorAll(':scope > div.blog-slide').length, 'card');
    if (k === 'spacer') return (b.dataset.h || 48) + ' px';
    if (k === 'cols' || k === 'mt') return b.innerText.replace(/\s+/g, ' ').trim().slice(0, 60) || 'empty';
    return null;
  }

  // ---------------------------------------------------------------- the Block tab
  const STYLE = [
    ['sp-t', 'Space above', [['', 'Standard'], ['0', 'None'], ['1', 'XS'], ['2', 'S'], ['3', 'M'], ['4', 'L'], ['5', 'XL']]],
    ['sp-b', 'Space below', [['', 'Standard'], ['0', 'None'], ['1', 'XS'], ['2', 'S'], ['3', 'M'], ['4', 'L'], ['5', 'XL']]],
    ['pd-', 'Padding', [['', 'None'], ['1', 'Small'], ['2', 'Medium'], ['3', 'Large']]],
    ['bg-', 'Background', [['', 'None'], ['soft', 'Grey'], ['blue', 'Blue'], ['warm', 'Warm'], ['dark', 'Dark']]],
    ['wd-', 'Width', [['', 'Standard'], ['wide', 'Wide'], ['full', 'Full width']]],
    ['ta-', 'Text', [['', 'Left'], ['center', 'Centre'], ['right', 'Right']]],
  ];
  const STYLE_RE = { 'sp-t': /^sp-t\d$/, 'sp-b': /^sp-b\d$/, 'pd-': /^pd-\d$/, 'bg-': /^bg-/, 'wd-': /^wd-/, 'ta-': /^ta-/ };
  const valueOf = (b, pre) => { const c = Array.from(b.classList).find(x => STYLE_RE[pre].test(x)); return c ? c.slice(pre.length) : ''; };
  function seg(attr, key, label, opts, cur) {
    return '<div class="ge-bk-row"><span>' + esc(label) + '</span><div class="ge-bk-seg" role="group" aria-label="' + esc(label) + '">' +
      opts.map(([v, w]) => '<button type="button" ' + attr + '="' + esc(key) + '" data-v="' + esc(v) + '" aria-pressed="' + (String(cur) === String(v)) + '">' + esc(w) + '</button>').join('') + '</div></div>';
  }
  const field = (label, html, hint) => '<label class="ge-bk-field"><span>' + esc(label) + '</span>' + html + (hint ? '<small>' + hint + '</small>' : '') + '</label>';
  const btn = (act, label, ic, cls) => '<button type="button" class="ge-btn' + (cls ? ' ' + cls : '') + '" data-bk="' + act + '"><i class="' + icon(ic) + '"></i> ' + esc(label) + '</button>';

  function own(k, b) {
    if (k === 'cols') return '<h4 class="ge-h">Columns</h4>' + seg('data-bk-set', 'cols', 'How many', [['2', 'Two'], ['3', 'Three']], b.dataset.cols || '2') +
      '<p class="ge-dim">Click in a column to write. Each column takes any blocks: headings, lists, pictures, buttons. On a phone they stack.</p>';
    if (k === 'mt') {
      const img = b.querySelector('figure.blog-mt-media img');
      return '<h4 class="ge-h">Picture and text</h4>' +
        seg('data-bk-set', 'pos', 'Picture on the', [['left', 'Left'], ['right', 'Right']], b.dataset.pos || 'left') +
        seg('data-bk-set', 'ratio', 'Picture takes', [['33', '⅓'], ['40', '40%'], ['50', 'Half'], ['60', '60%'], ['67', '⅔']], b.dataset.ratio || '50') +
        '<div class="ge-bk-btns">' + btn('mt-lib', 'Media library', 'fa-photo-film') + btn('mt-upload', 'Upload', 'fa-upload') + '</div>' +
        (img ? field('Description (what the picture shows)', '<input type="text" data-nodirty data-bk-in="mt-alt" maxlength="200" value="' + esc(img.alt) + '"/>') : '') +
        '<p class="ge-dim">The text beside it is written in the post. On a phone the picture goes on top.</p>';
    }
    if (k === 'carousel' || k === 'slider') {
      const pics = k === 'carousel';
      const slides = Array.from(b.querySelectorAll(':scope > .blog-slide'));
      return '<h4 class="ge-h">' + (pics ? 'Picture carousel' : 'Content slider') + '</h4>' +
        '<ol class="ge-bk-slides">' + slides.map((s, i) => '<li data-i="' + i + '">' +
          (s.tagName === 'FIGURE' && s.querySelector('img') ? '<img src="' + esc(s.querySelector('img').getAttribute('src')) + '" alt=""/>' : '<span class="ge-bk-card">' + esc((s.innerText || '').trim().slice(0, 40) || 'Empty card') + '</span>') +
          (s.tagName === 'FIGURE' ? '<input type="text" data-nodirty data-bk-in="cap" data-i="' + i + '" placeholder="Caption" value="' + esc((s.querySelector('figcaption') || {}).textContent || '') + '"/>' : '') +
          '<span class="ge-bk-sl-acts"><button type="button" data-bk="sl-left" data-i="' + i + '" aria-label="Earlier"' + (i ? '' : ' disabled') + '><i class="fa-solid fa-arrow-left"></i></button>' +
          '<button type="button" data-bk="sl-right" data-i="' + i + '" aria-label="Later"' + (i < slides.length - 1 ? '' : ' disabled') + '><i class="fa-solid fa-arrow-right"></i></button>' +
          '<button type="button" data-bk="sl-del" data-i="' + i + '" aria-label="Remove"><i class="fa-solid fa-xmark"></i></button></span></li>').join('') +
        (slides.length ? '' : '<li class="ge-dim">No ' + (pics ? 'pictures' : 'cards') + ' yet.</li>') + '</ol>' +
        '<div class="ge-bk-btns">' + (pics ? btn('sl-lib', 'Add from the library', 'fa-photo-film') + btn('sl-upload', 'Upload pictures', 'fa-upload')
          : btn('sl-card', 'Add a card', 'fa-plus')) + '</div>' +
        seg('data-bk-set', 'show', 'Shown at once', [['1', 'One'], ['2', 'Two'], ['3', 'Three']], b.dataset.show || '1') +
        seg('data-bk-set', 'interval', 'Moves by itself', [['0', 'No'], ['3', '3 s'], ['5', '5 s'], ['8', '8 s']], b.dataset.interval || '0') +
        (pics ? '' : '<p class="ge-dim">Write each card in the post: scroll the slider sideways.</p>');
    }
    if (k === 'video') {
      const v = b.querySelector('video');
      return '<h4 class="ge-h">Video</h4><div class="ge-bk-btns">' + btn('vid-upload', v ? 'Replace: upload' : 'Upload a video', 'fa-upload', 'ge-btn-primary') + '</div>' +
        '<p class="ge-dim">MP4 or WebM, up to 150 MB. Readers play it in the post, fullscreen too.</p>' +
        field('Or its address', '<input type="text" inputmode="url" data-nodirty data-bk-in="vid-src" placeholder="https://…/video.mp4" value="' + esc(v ? v.getAttribute('src') : '') + '"/>') +
        '<div class="ge-bk-btns">' + btn('vid-poster', 'Picture before it plays', 'fa-image') + (v && v.getAttribute('poster') ? btn('vid-noposter', 'No picture', 'fa-xmark') : '') + '</div>' +
        field('Caption', '<input type="text" data-nodirty data-bk-in="caption" maxlength="200" value="' + esc((b.querySelector('figcaption') || {}).textContent || '') + '"/>');
    }
    if (k === 'embed') {
      const url = b.dataset.vid ? (b.dataset.provider === 'vimeo' ? 'https://vimeo.com/' + b.dataset.vid : 'https://www.youtube.com/watch?v=' + b.dataset.vid) : '';
      return '<h4 class="ge-h">YouTube or Vimeo</h4>' +
        field('Its link', '<input type="text" inputmode="url" data-nodirty data-bk-in="embed-url" placeholder="https://youtu.be/… or https://vimeo.com/…" value="' + esc(url) + '"/>' +
                '<b class="ge-bk-err" data-bk-err="embed-url" hidden>Paste a YouTube or Vimeo link.</b>',
              'It plays in the post (fullscreen too), with a link to watch it on ' + (b.dataset.provider === 'vimeo' ? 'Vimeo' : 'YouTube') + ' in a new tab.') +
        field('Start at (seconds)', '<input type="text" inputmode="numeric" maxlength="5" data-nodirty data-bk-in="embed-start" value="' + esc(b.dataset.start || '') + '"/>') +
        field('Caption', '<input type="text" data-nodirty data-bk-in="caption" maxlength="200" value="' + esc((b.querySelector('figcaption') || {}).textContent || '') + '"/>');
    }
    if (k === 'code') {
      const code = (b.querySelector('pre') || {}).textContent || '';
      const h = b.dataset.h || 'auto';
      return '<h4 class="ge-h">Custom HTML / CSS / JS</h4>' +
        '<textarea class="ge-bk-code" rows="14" spellcheck="false" data-nodirty data-bk-in="code">' + esc(code) + '</textarea>' +
        '<div class="ge-bk-btns">' + btn('code-run', 'Run the preview', 'fa-play', 'ge-btn-primary') + '</div>' +
        seg('data-bk-set', 'h', 'Height', [['auto', 'Fits its content'], ['240', '240'], ['400', '400'], ['600', '600']], ['auto', '240', '400', '600'].includes(h) ? h : 'auto') +
        field('Name (for screen readers)', '<input type="text" data-nodirty data-bk-in="code-title" maxlength="120" value="' + esc(b.dataset.title || '') + '"/>') +
        '<p class="ge-dim"><i class="fa-solid fa-shield-halved"></i> It runs in a frame of its own, apart from the site: it cannot read the page, its cookies or who is signed in. Scripts, styles and links all work inside it; links open in a new tab.</p>';
    }
    if (k === 'spacer') return '<h4 class="ge-h">Space</h4>' + seg('data-bk-set', 'h', 'Height', [['16', '16'], ['32', '32'], ['48', '48'], ['72', '72'], ['96', '96'], ['144', '144']], b.dataset.h || '48');
    if (k === 'button') {
      const a = b.querySelector('a');
      return '<h4 class="ge-h">Button</h4>' +
        seg('data-bk-btn', 'look', 'Look', [['', 'Filled'], ['cta-outline', 'Outline']], a && a.classList.contains('cta-outline') ? 'cta-outline' : '') +
        seg('data-bk-btn', 'size', 'Size', [['', 'Standard'], ['cta-big', 'Big']], a && a.classList.contains('cta-big') ? 'cta-big' : '') +
        seg('data-bk-btn', 'tab', 'Opens', [['', 'Here'], ['_blank', 'In a new tab']], a && a.getAttribute('target') === '_blank' ? '_blank' : '') +
        '<p class="ge-dim">Click the button in the post to change its words or where it goes.</p>';
    }
    if (k === 'picture') return '<p class="ge-dim">Click the picture for its description, caption and to replace it.</p>';
    return '';
  }
  function pane(b) {
    const box = document.getElementById('geBlockPane');
    if (!box) return;
    if (!b || !S.editor.contains(b)) { box._block = null; box.innerHTML = '<p class="ge-dim">Click a block in the post to see its settings.</p>'; return; }
    const k = kindOf(b);
    box._block = b;
    const title = name(b) || ({ P: 'Paragraph', H2: 'Heading', H3: 'Sub-heading', UL: 'List', OL: 'Numbered list', BLOCKQUOTE: 'Quote', ASIDE: 'Tip box', TABLE: 'Table', HR: 'Line across', FIGURE: 'Picture' })[b.tagName] || 'Block';
    box.innerHTML = '<div class="ge-bk-head"><i class="' + icon(iconFor(b) || 'fa-square') + '"></i><b>' + esc(title) + '</b></div>' + own(k, b) +
      '<h4 class="ge-h">Look</h4>' + STYLE.filter(([pre]) => !(pre === 'ta-' && /^(code|spacer|embed|video|carousel)$/.test(k)) && !(pre === 'pd-' && k === 'spacer') && !(pre === 'bg-' && k === 'spacer'))
        .map(([pre, label, opts]) => seg('data-bk-style', pre, label, opts, valueOf(b, pre))).join('');
  }
  const block = () => { const box = document.getElementById('geBlockPane'); const b = box && box._block; return b && S.editor.contains(b) ? b : null; };
  const again = () => pane(block());

  // a change from the Block tab: one step of undo, then the tab drawn again
  function change(fn, redraw) {
    const b = block();
    if (!b) return;
    S.structural(() => fn(b));
    if (redraw !== false) again();
  }
  function styleSet(b, pre, v) {
    Array.from(b.classList).filter(c => STYLE_RE[pre].test(c)).forEach(c => b.classList.remove(c));
    if (v !== '') b.classList.add(pre + v);
    if (!b.className) b.removeAttribute('class');
  }
  function setOf(b, key, v) {
    const k = kindOf(b);
    if (key === 'cols') {
      const n = +v, cols = Array.from(b.querySelectorAll(':scope > .blog-col'));
      while (cols.length < n) { const c = make('<div class="blog-col"><p>Write here.</p></div>'); b.appendChild(c); cols.push(c); }
      while (cols.length > n) { const last = cols.pop(); const prev = cols[cols.length - 1]; while (last.firstChild) prev.appendChild(last.firstChild); last.remove(); }
      b.dataset.cols = v;
    } else if (key === 'h' && k === 'code') b.dataset.h = v;
    else b.dataset[key] = v;
  }

  // pictures for the picture beside text and the carousel: from the library (one at a time) or uploaded (several)
  function picture(m) { return '<img src="' + esc(m.src) + '" alt="' + esc(m.alt || '') + '" data-file="' + esc(m.name) + '" loading="lazy">'; }
  function setMtPicture(b, m) {
    const f = b.querySelector('figure.blog-mt-media');
    f.querySelectorAll('img, video, bs-live').forEach(x => x.remove());
    f.insertAdjacentHTML('afterbegin', picture(m));
  }
  function filePick(accept, multiple, then) {
    const inp = document.createElement('input');
    inp.type = 'file';
    inp.accept = accept;
    inp.multiple = !!multiple;
    inp.addEventListener('change', () => then(Array.from(inp.files || [])));
    inp.click();
  }
  async function uploadPictures(files, each) {
    files = files.filter(f => /\.(jpe?g|png|webp)$/i.test(f.name) || /^image\/(jpeg|png|webp)$/.test(f.type));
    if (!files.length) { S.toast('Use a JPG, PNG or WebP picture.', 'danger'); return; }
    for (const f of files) {
      try { const d = await S.upload(f, 'body'); each({ src: d.src, name: d.name, alt: '' }); } catch (err) { S.toast(err.message, 'danger'); }
    }
  }
  async function uploadVideo(file) {
    const b = block();
    if (!b || !file) return;
    if (!/\.(mp4|webm)$/i.test(file.name)) { S.toast('Use an MP4 or WebM video.', 'danger'); return; }
    if (file.size > 150 * 1024 * 1024) { S.toast('That video is larger than 150 MB: make it shorter or smaller first.', 'danger'); return; }
    const box = document.getElementById('geBlockPane');
    const say = box.querySelector('[data-bk=vid-upload]');
    if (say) { say.disabled = true; say.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Uploading ' + esc(file.name) + '…'; }
    const fd = new FormData();
    fd.append('file', file);
    try {
      const r = await fetch(S.form.dataset.videoUrl, { method: 'POST', headers: { 'X-CSRFToken': S.CSRF }, body: fd, credentials: 'same-origin' });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.url) throw new Error(d.error || 'The video could not be uploaded.');
      change(x => setVideo(x, d.src));
      S.toast('The video is in the post.', 'success');
    } catch (err) { S.toast(err.message, 'danger'); again(); }
  }
  function setVideo(b, src) {
    let v = b.querySelector('video');
    if (!src) { if (v) v.remove(); return; }
    if (!v) { v = document.createElement('video'); v.setAttribute('controls', ''); v.setAttribute('preload', 'metadata'); b.prepend(v); }
    v.setAttribute('src', src);
  }
  function caption(b, text) {
    let cap = b.querySelector(':scope > figcaption');
    if (!text.trim()) { if (cap) cap.remove(); return; }
    if (!cap) { cap = document.createElement('figcaption'); b.appendChild(cap); }
    cap.textContent = text;
  }

  function wire() {
    const box = document.getElementById('geBlockPane');
    if (!box) return;
    box.addEventListener('click', e => {
      const t = e.target.closest('button');
      if (!t || t.disabled) return;
      const b = block();
      if (!b) return;
      if (t.dataset.bkStyle != null) { change(x => styleSet(x, t.dataset.bkStyle, t.dataset.v)); return; }
      if (t.dataset.bkSet != null) { change(x => setOf(x, t.dataset.bkSet, t.dataset.v)); return; }
      if (t.dataset.bkBtn != null) {
        change(x => {
          const a = x.querySelector('a');
          if (!a) return;
          if (t.dataset.bkBtn === 'tab') { if (t.dataset.v) { a.setAttribute('target', '_blank'); a.setAttribute('rel', 'noopener noreferrer'); } else { a.removeAttribute('target'); a.removeAttribute('rel'); } }
          else { const cls = t.dataset.bkBtn === 'look' ? 'cta-outline' : 'cta-big'; a.classList.toggle(cls, !!t.dataset.v); }
        });
        return;
      }
      const act = t.dataset.bk, i = +t.dataset.i;
      if (act === 'mt-lib') S.openLib({ purpose: 'body', onPick: m => change(x => setMtPicture(x, m)) });
      else if (act === 'mt-upload') filePick('image/jpeg,image/png,image/webp', false, files => uploadPictures(files, m => change(x => setMtPicture(x, m))));
      else if (act === 'sl-lib') S.openLib({ purpose: 'body', onPick: m => change(x => x.insertAdjacentHTML('beforeend', '<figure class="blog-slide">' + picture(m) + '</figure>')) });
      else if (act === 'sl-upload') filePick('image/jpeg,image/png,image/webp', true, files => uploadPictures(files, m => change(x => x.insertAdjacentHTML('beforeend', '<figure class="blog-slide">' + picture(m) + '</figure>'))));
      else if (act === 'sl-card') change(x => x.insertAdjacentHTML('beforeend', '<div class="blog-slide"><h3>A new card</h3><p>Write here.</p></div>'));
      else if (act === 'sl-left' || act === 'sl-right' || act === 'sl-del') {
        change(x => {
          const slides = Array.from(x.querySelectorAll(':scope > .blog-slide')), s = slides[i];
          if (!s) return;
          if (act === 'sl-del') s.remove();
          else if (act === 'sl-left' && slides[i - 1]) slides[i - 1].before(s);
          else if (act === 'sl-right' && slides[i + 1]) slides[i + 1].after(s);
        });
      } else if (act === 'vid-upload') filePick('video/mp4,video/webm', false, files => uploadVideo(files[0]));
      else if (act === 'vid-poster') S.openLib({ purpose: 'body', onPick: m => change(x => { const v = x.querySelector('video'); if (v) v.setAttribute('poster', m.src); else S.toast('Add the video first.', 'warning'); }) });
      else if (act === 'vid-noposter') change(x => { const v = x.querySelector('video'); if (v) v.removeAttribute('poster'); });
      else if (act === 'code-run') runCode();
    });
    // typed fields: applied as they are typed (a step of undo after a pause), the tab not redrawn under the caret
    let typeT = null;
    box.addEventListener('input', e => {
      const t = e.target, b = block();
      if (!b || !t.dataset.bkIn) return;
      const k = t.dataset.bkIn;
      if (k === 'code') { clearTimeout(typeT); typeT = setTimeout(runCode, 900); return; }
      clearTimeout(typeT);
      typeT = setTimeout(() => {
        S.structural(() => {
          if (k === 'mt-alt') { const img = b.querySelector('figure.blog-mt-media img'); if (img) img.alt = t.value; }
          else if (k === 'cap') { const s = b.querySelectorAll(':scope > .blog-slide')[+t.dataset.i]; if (s) caption(s, t.value); }
          else if (k === 'caption') caption(b, t.value);
          else if (k === 'vid-src') { const v = t.value.trim(); if (!v || /^(https?:\/\/|\/(?!\/))/.test(v)) setVideo(b, v); }
          else if (k === 'embed-url') {
            const e2 = embedOf(t.value);
            if (e2) { b.dataset.provider = e2.provider; b.dataset.vid = e2.id; if (e2.start) b.dataset.start = e2.start; }
            else if (!t.value.trim()) { delete b.dataset.provider; delete b.dataset.vid; delete b.dataset.start; }
          } else if (k === 'embed-start') { const n = parseInt(t.value, 10); if (n > 0) b.dataset.start = Math.min(n, 99999); else delete b.dataset.start; }
          else if (k === 'code-title') b.dataset.title = t.value.replace(/[<>]/g, '').slice(0, 120) || 'Embedded content';
        });
        const err = box.querySelector('[data-bk-err=embed-url]');
        if (err && k === 'embed-url') err.hidden = !t.value.trim() || !!embedOf(t.value);
      }, 450);
    });
    function runCode() {
      const b = block(), ta = box.querySelector('[data-bk-in=code]');
      if (!b || !ta) return;
      S.structural(() => {
        let pre = b.querySelector('pre');
        if (!pre) { pre = document.createElement('pre'); b.appendChild(pre); }
        pre.textContent = ta.value;
      });
    }

    // the post's layout, on the editor as it is chosen (the form sends it; blog_posts.clean_layout)
    const CLASS = { width: 'lay-w-', size: 'lay-s-', spacing: 'lay-sp-' }, STANDARD = { width: 'normal', size: 'm', spacing: 'normal' };
    S.form.addEventListener('change', e => {
      const t = e.target;
      if (!t.dataset || !t.dataset.lay) return;
      const key = t.dataset.lay;
      Array.from(S.editor.classList).filter(c => c.startsWith(CLASS[key])).forEach(c => S.editor.classList.remove(c));
      if (t.value !== STANDARD[key]) S.editor.classList.add(CLASS[key] + t.value);
      S.changed();
      S.floating();
    });
  }

  function init(studio) {
    S = studio;
    wire();
  }

  return { items, insert, pasteUrl, decorate, name, icon: iconFor, text, pane, init, embedOf, kindOf };
})();
