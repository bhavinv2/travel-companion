/* Blog studio editor (admin/blog_edit.html).

   The post is edited in place, in the public page's own styles. Pictures are objects, not text:
   one click opens their panel (description, caption, upload, remove) -- which is also how a
   picture the Word import could not find gets uploaded. The checks beside the post come from the
   server (blog_engine.checks), so the rules live in one place; this file only asks for them.
   Whatever the editor produces, the server cleans it again on save. */
(function () {
  const form = document.getElementById('bsForm');
  if (!form) return;
  const editor = document.getElementById('bsEditor');
  const hidden = form.querySelector('textarea[name=content]');
  const fileInput = document.getElementById('bsFile');
  const panel = document.getElementById('bsFigPanel');
  const CSRF = document.querySelector('meta[name="csrf-token"]')?.content || '';
  let dirty = false, saved = null, picking = null, current = null;

  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const toast = (m, t) => (window.showToast ? window.showToast(m, t) : alert(m));

  // ---------------------------------------------------------------- the content
  function lockFigures() {
    editor.querySelectorAll('figure').forEach(f => f.setAttribute('contenteditable', 'false'));
  }
  function serialise() {
    const c = editor.cloneNode(true);
    c.querySelectorAll('[contenteditable]').forEach(e => e.removeAttribute('contenteditable'));
    c.querySelectorAll('.is-picked').forEach(e => e.classList.remove('is-picked'));
    hidden.value = c.innerHTML.trim();
  }
  function changed() {
    dirty = true;
    document.getElementById('bsDirty').textContent = 'Unsaved changes';
    scheduleCheck();
  }
  lockFigures();

  // ---------------------------------------------------------------- selection
  function keep() {
    const s = window.getSelection();
    if (s.rangeCount && editor.contains(s.anchorNode)) saved = s.getRangeAt(0).cloneRange();
  }
  function restore() {
    editor.focus();
    if (!saved) return;
    const s = window.getSelection();
    s.removeAllRanges();
    s.addRange(saved);
  }
  function currentBlock() {
    const s = window.getSelection();
    let n = s.rangeCount ? s.anchorNode : null;
    while (n && n !== editor && !(n.nodeType === 1 && /^(P|H2|H3|BLOCKQUOTE|ASIDE|LI|DIV)$/.test(n.tagName))) n = n.parentNode;
    return n && n !== editor ? n : null;
  }
  function swapBlock(b, tag, cls) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    while (b.firstChild) n.appendChild(b.firstChild);
    b.replaceWith(n);
    const r = document.createRange();
    r.selectNodeContents(n);
    r.collapse(false);
    const s = window.getSelection();
    s.removeAllRanges();
    s.addRange(r);
  }
  function insertHTML(html) {
    restore();
    document.execCommand('insertHTML', false, html);
    lockFigures();
    changed();
  }

  // ---------------------------------------------------------------- toolbar
  const toolbar = document.getElementById('bsToolbar');
  toolbar.addEventListener('mousedown', e => { if (e.target.closest('button')) e.preventDefault(); });   // keep the selection
  toolbar.addEventListener('click', e => {
    const b = e.target.closest('button');
    if (!b) return;
    keep();
    editor.focus();
    const what = b.dataset.do;
    if (what === 'cmd') {
      document.execCommand(b.dataset.cmd, false, null);
    } else if (what === 'block') {
      const cur = currentBlock();
      if (cur && cur.tagName === 'ASIDE') swapBlock(cur, 'p');
      const tag = cur && cur.tagName.toLowerCase() === b.dataset.tag ? 'p' : b.dataset.tag;   // a second click undoes it
      document.execCommand('formatBlock', false, '<' + tag + '>');
    } else if (what === 'note') {
      const cur = currentBlock();
      if (!cur) return;
      if (cur.tagName === 'ASIDE') swapBlock(cur, 'p');
      else swapBlock(cur, 'aside', 'blog-note');
    } else if (what === 'link') {
      const url = (prompt('Link address: https://… or a page of this site like /travel-insurance') || '').trim();
      if (!url) return;
      if (!/^(https?:\/\/|mailto:|tel:|\/(?!\/))/i.test(url)) { toast('Use an https:// address or a site page starting with /', 'danger'); return; }
      restore();
      document.execCommand('createLink', false, url);
    } else if (what === 'image') {
      pick('body', null);
      return;
    } else if (what === 'cta') {
      const text = (prompt('Button text, e.g. Get a free quote') || '').trim();
      if (!text) return;
      const url = (prompt('Where the button goes: a site page like /travel-insurance, or https://…') || '').trim();
      if (!/^(https?:\/\/|\/(?!\/))/i.test(url)) { toast('Use an https:// address or a site page starting with /', 'danger'); return; }
      insertHTML('<p class="blog-cta-wrap"><a class="blog-cta" href="' + esc(url) + '">' + esc(text) + '</a></p><p><br></p>');
      return;
    } else if (what === 'clear') {
      document.execCommand('removeFormat', false, null);
      document.execCommand('formatBlock', false, '<p>');
    }
    changed();
  });

  // pasted text arrives as plain paragraphs: formatting from other sites is not this site's
  editor.addEventListener('paste', e => {
    const text = (e.clipboardData || window.clipboardData)?.getData('text/plain');
    if (text == null) return;
    e.preventDefault();
    const paras = text.replace(/\r/g, '').split(/\n{2,}/).map(p => p.trim()).filter(Boolean);
    if (paras.length <= 1) document.execCommand('insertText', false, text);
    else document.execCommand('insertHTML', false, paras.map(p => '<p>' + esc(p).replace(/\n/g, '<br>') + '</p>').join(''));
    changed();
  });
  editor.addEventListener('input', changed);
  editor.addEventListener('keyup', keep);
  editor.addEventListener('mouseup', keep);

  // ---------------------------------------------------------------- pictures
  async function upload(file, purpose) {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('purpose', purpose);
    const r = await fetch(form.dataset.imageUrl, { method: 'POST', headers: { 'X-CSRFToken': CSRF }, body: fd, credentials: 'same-origin' });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || !d.url) throw new Error(d.error || 'The picture could not be uploaded.');
    return d;
  }
  function pick(purpose, figure) {
    picking = { purpose, figure };
    fileInput.value = '';
    fileInput.click();
  }
  fileInput.addEventListener('change', async () => {
    const file = fileInput.files[0];
    if (!file || !picking) return;
    const { purpose, figure } = picking;
    picking = null;
    let d;
    try { d = await upload(file, purpose); } catch (err) { toast(err.message, 'danger'); return; }
    if (purpose === 'cover') return setCover(d.url, d.src);
    if (figure) {
      const alt = figure.querySelector('img')?.alt || figure.dataset.alt || '';
      const cap = figure.querySelector('figcaption');
      figure.className = 'blog-img';
      figure.removeAttribute('data-file');
      figure.removeAttribute('data-alt');
      figure.innerHTML = '<img src="' + esc(d.src) + '" alt="' + esc(alt) + '" data-file="' + esc(d.name) + '" loading="lazy">' + (cap ? cap.outerHTML : '');
      openPanel(figure);
      changed();
    } else {
      const alt = (prompt('Describe the picture (for Google and screen readers)') || '').trim();
      insertHTML('<figure class="blog-img"><img src="' + esc(d.src) + '" alt="' + esc(alt) + '" data-file="' + esc(d.name) + '" loading="lazy"></figure><p><br></p>');
    }
  });

  function openPanel(fig) {
    if (current) current.classList.remove('is-picked');
    current = fig;
    fig.classList.add('is-picked');
    const missing = fig.classList.contains('blog-img-missing');
    const img = fig.querySelector('img');
    panel.querySelector('.bs-fp-missing').hidden = !missing;
    panel.querySelector('.bs-fp-missing b').textContent = fig.dataset.file || '';
    panel.querySelector('[data-k=alt]').value = missing ? (fig.dataset.alt || '') : (img ? img.alt : '');
    panel.querySelector('[data-k=cap]').value = fig.querySelector('figcaption')?.textContent || '';
    panel.querySelector('[data-fp=replace] span').textContent = missing ? 'Upload ' + (fig.dataset.file || 'picture') : 'Replace picture';
    panel.style.top = (fig.offsetTop + fig.offsetHeight + 8) + 'px';
    panel.hidden = false;
  }
  function closePanel() {
    panel.hidden = true;
    if (current) current.classList.remove('is-picked');
    current = null;
  }
  editor.addEventListener('click', e => {
    const fig = e.target.closest('figure');
    if (fig && editor.contains(fig)) { e.preventDefault(); openPanel(fig); }
    else if (!panel.hidden) closePanel();
  });
  panel.addEventListener('input', e => {
    if (!current) return;
    const k = e.target.dataset.k;
    if (k === 'alt') {
      if (current.classList.contains('blog-img-missing')) current.dataset.alt = e.target.value;
      else if (current.querySelector('img')) current.querySelector('img').alt = e.target.value;
    } else if (k === 'cap') {
      let cap = current.querySelector('figcaption');
      if (!e.target.value.trim()) { if (cap) cap.remove(); }
      else { if (!cap) { cap = document.createElement('figcaption'); current.appendChild(cap); } cap.textContent = e.target.value; }
    }
    changed();
  });
  panel.addEventListener('click', e => {
    const b = e.target.closest('[data-fp]');
    if (!b || !current) return;
    if (b.dataset.fp === 'replace') pick('body', current);
    else if (b.dataset.fp === 'remove') { current.remove(); closePanel(); changed(); }
    else closePanel();
  });

  // ---------------------------------------------------------------- cover
  const coverInput = form.querySelector('input[name=cover_image_url]');
  const coverBox = document.getElementById('bsCover');
  function setCover(url, src) {
    coverInput.value = url || '';
    const img = coverBox.querySelector('img');
    img.hidden = !url;
    if (url) img.src = src || url; else img.removeAttribute('src');
    coverBox.querySelector('p').hidden = !!url;
    form.querySelector('[data-cover=remove]').hidden = !url;
    form.querySelector('[data-cover=upload]').lastChild.textContent = url ? ' Replace' : ' Upload';
    changed();
  }
  form.querySelectorAll('[data-cover]').forEach(b => b.addEventListener('click', () => {
    if (b.dataset.cover === 'upload') pick('cover', null); else setCover('', '');
  }));

  // ---------------------------------------------------------------- the other fields
  // the title is one line of text that wraps: as tall as it needs, and Enter does not add a line
  const title = form.querySelector('[name=title]');
  const fit = () => { title.style.height = 'auto'; title.style.height = title.scrollHeight + 'px'; };
  title.addEventListener('input', () => {
    if (/\n/.test(title.value)) title.value = title.value.replace(/\s*\n\s*/g, ' ');   // a pasted line break
    fit();
  });
  title.addEventListener('keydown', e => { if (e.key === 'Enter') e.preventDefault(); });
  fit();
  const summary = form.querySelector('[name=summary]');
  summary.addEventListener('input', () => { document.getElementById('bsSumCount').textContent = summary.value.trim().length; });
  const slug = form.querySelector('[name=slug]');
  slug.addEventListener('change', () => {
    slug.value = slug.value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80);
  });
  form.querySelectorAll('input[type=text], textarea[name=summary], textarea[name=title], input[type=checkbox]').forEach(i => i.addEventListener('input', changed));

  // ---------------------------------------------------------------- checks, from the server
  const ICON = { error: 'fa-circle-xmark', warn: 'fa-lightbulb', ok: 'fa-circle-check' };
  let timer = null, seq = 0;
  function scheduleCheck() { clearTimeout(timer); timer = setTimeout(check, 700); }
  async function check() {
    serialise();
    const mine = ++seq;
    let d;
    try {
      const r = await fetch(form.dataset.checkUrl, { method: 'POST', headers: { 'X-CSRFToken': CSRF }, body: new FormData(form), credentials: 'same-origin' });
      if (!r.ok) return;
      d = await r.json();
    } catch (err) { return; }
    if (mine !== seq) return;            // an older answer arriving late
    const box = document.getElementById('bsChecks');
    box.innerHTML = '';
    d.checks.forEach(c => {
      const li = document.createElement('li');
      li.className = 'bs-c-' + c.level;
      li.innerHTML = '<i class="fa-solid ' + ICON[c.level] + '"></i> ';
      li.appendChild(document.createTextNode(c.text));
      box.appendChild(li);
    });
    document.getElementById('bsBlocked').hidden = !d.checks.some(c => c.level === 'error');
    count(d.words);
  }
  function count(words) {
    if (words == null) words = (editor.innerText.trim().match(/\S+/g) || []).length;
    document.getElementById('bsCount').textContent = words + ' word' + (words === 1 ? '' : 's') + ' · ' + Math.max(1, Math.round(words / 200)) + ' min read';
  }
  count();

  // ---------------------------------------------------------------- saving
  form.addEventListener('submit', e => {
    const b = e.submitter;
    if (b && b.dataset.confirm && !confirm(b.dataset.confirm)) { e.preventDefault(); return; }
    serialise();
    if (b && b.getAttribute('formtarget') === '_blank') return;      // a preview: still unsaved here
    dirty = false;
  });
  window.addEventListener('beforeunload', e => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      (document.getElementById('bsSave') || document.getElementById('bsGoLive')).click();
    }
  });
})();
