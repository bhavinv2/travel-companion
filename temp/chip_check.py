"""Measure the chip row on a phone: labels, widths, icons, and that the row fits."""
import os, sys, threading
os.chdir(r"E:/OS/webscrapping/Travel-companion/travel-companion"); sys.path.insert(0, os.path.abspath("."))
from werkzeug.serving import make_server
from app import create_app, db
from app.models import User
app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False, 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                  'MAIL_PASSWORD': None, 'UPLOAD_FOLDER': '/tmp/u', 'PRIVATE_UPLOAD_FOLDER': '/tmp/p'})
with app.app_context():
    db.create_all()
    u = User(email='b@t.com', username='bob', first_name='Bob'); u.set_password('pw12345678')
    db.session.add(u); db.session.commit()
srv = make_server('127.0.0.1', 8160, app); threading.Thread(target=srv.serve_forever, daemon=True).start()
from playwright.sync_api import sync_playwright
SHOT = r'C:/Users/durga/AppData/Local/Temp/claude/e--OS-webscrapping/40052e21-de68-469c-ad83-083632083264/scratchpad/'

PROBE = """(sel) => {
  const tabs = [...document.querySelectorAll(sel)];
  return tabs.map(t => {
    const r = t.getBoundingClientRect();
    const label = t.querySelector('.wtab-label') || t.querySelector('.txt > span');
    const lr = label ? label.getBoundingClientRect() : null;
    const orb = t.querySelector('.wtab-orb, .orb');
    const orbR = orb ? orb.getBoundingClientRect() : null;
    return {
      on: t.classList.contains('active'),
      w: Math.round(r.width),
      label: label ? label.textContent.trim() : null,
      labelVisible: !!(lr && lr.width > 1),
      iconVisible: !!(orbR && orbR.width > 1),
      text: t.innerText.replace(/\s+/g, ' ').trim(),
    };
  });
}"""

with sync_playwright() as pw:
    b = pw.chromium.launch()
    for label, url, sel, needs_login in [
            ('logged-out landing', 'http://127.0.0.1:8160/', '.wtab', False),
            ('signed-in home', 'http://127.0.0.1:8160/', '.qs-tab', True)]:
        p = b.new_page(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        if needs_login:
            p.goto('http://127.0.0.1:8160/auth/login')
            p.fill('input[name=email]', 'b@t.com'); p.fill('input[name=password]', 'pw12345678')
            p.click('button[type=submit]'); p.wait_for_timeout(600)
        p.goto(url, wait_until='domcontentloaded'); p.wait_for_timeout(900)
        if not p.query_selector(sel):
            print('%s: %s not on this page' % (label, sel)); p.close(); continue
        print('\n=== %s (%s) at 390px ===' % (label, sel))
        n = len(p.query_selector_all(sel))
        for i in range(n):
            p.eval_on_selector_all(sel, "(els, i) => els.forEach((e, j) => e.classList.toggle('active', j === i))", i)
            p.wait_for_timeout(450)
            rows = p.evaluate(PROBE, sel)
            total = sum(r['w'] for r in rows)
            desc = ' | '.join('%s%s %dpx' % ('[ON] ' if r['on'] else '', r['text'] or '(icon)', r['w']) for r in rows)
            icons = all(r['iconVisible'] for r in rows)
            print('  select %d -> %s   (row %dpx of 390, icons on every chip: %s)' % (i + 1, desc, total, icons))
            if i == 0:
                p.screenshot(path=SHOT + ('chips_%s.png' % sel.strip('.')))
        p.close()
    b.close()
srv.shutdown()
