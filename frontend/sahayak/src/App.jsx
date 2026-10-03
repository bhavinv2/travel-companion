import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Icon, { Underline } from './components/Icon.jsx';
import { cx } from './components/ui.jsx';
import NeedMode from './components/NeedMode.jsx';
import BecomeMode from './components/BecomeMode.jsx';
import BookingModal from './components/BookingModal.jsx';
import { BecomeHeroCard, NeedHeroCard } from './components/HeroCard.jsx';
import { scrollToId } from './hooks.js';
import { site } from './data/site.js';
import heroNeed from './assets/hero-need.jpg';
import heroBecome from './assets/hero-become.jpg';
import logoMark from './assets/logo-mark.png';

// What each journey calls itself.
const JOURNEY = {
  need: { label: 'Book a Sahayak', short: 'Book', sub: 'A professional with your parents',
          icon: 'homeHeart' },
  become: { label: 'Join as a Sahayak', short: 'Join', sub: 'For health professionals',
            icon: 'userPlus' },
};
// The switch button always advertises the *other* journey, in that journey's colour.
const SWITCH = {
  need: { to: 'become', ...JOURNEY.become },
  become: { to: 'need', ...JOURNEY.need },
};

function SwitchCta({ mode, onClick, className }) {
  const s = SWITCH[mode];
  return (
    <button type="button" className={cx('sw-cta', `to-${s.to}`, className)} onClick={onClick}>
      <span className="sw-cta-tx">
        <b>{s.label}</b>
        <small>{s.sub}</small>
      </span>
      <span className="sw-cta-arr"><Icon name="arrow" sw={2.2} /></span>
    </button>
  );
}

/* The journey switcher as it appears in the site header, beside the product switcher.
 *
 * It borrows that switcher's classes rather than bringing its own, so the two chips on the
 * brand's second line are the same control twice over -- same type, same caret, same menu --
 * and a change to the header's look reaches both. Those classes live in the site stylesheet,
 * which is loaded by the page this is portalled into, not by this bundle.
 *
 * Opening and closing is handled here instead of by the site's delegated handler, because
 * that one is written for the single #svcSw in the header and a second switcher has to come
 * with its own.
 */
function JourneySwitch({ mode, onPick }) {
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  const here = JOURNEY[mode];

  useEffect(() => {
    if (!open) return;
    const away = (e) => { if (!box.current || !box.current.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('click', away);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('click', away);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);

  return (
    <div className={cx('svc-sw', open && 'open')} ref={box}>
      <button type="button" className="svc-sw-btn" aria-haspopup="menu" aria-expanded={open}
              title="Switch journey" onClick={() => setOpen((o) => !o)}>
        {/* Two labels, one shown at a time by the stylesheet: on a narrow phone the full one
            wraps and takes the header with it. */}
        <span className="logo-sub">
          <span className="jn-long">{here.label}</span>
          <span className="jn-short">{here.short}</span>
        </span>
        <i className="fa-solid fa-chevron-down svc-sw-caret" aria-hidden="true"></i>
      </button>
      <div className="svc-sw-menu" role="menu" aria-label="Sahayak journeys">
        <div className="svc-sw-head">Sahayak is for</div>
        {['need', 'become'].map((m) => (
          <button key={m} type="button" role="menuitem"
                  className={cx('svc-sw-item', m === mode && 'on')}
                  onClick={() => { setOpen(false); onPick(m); }}>
            <Icon name={JOURNEY[m].icon} className="svc-sw-ico" sw={2} />
            <span><b>{JOURNEY[m].label}</b><small>{JOURNEY[m].sub}</small></span>
            {m === mode && <Icon name="check" className="svc-sw-tick" sw={3} />}
          </button>
        ))}
      </div>
    </div>
  );
}

const NAV_LINKS = {
  need: [['#services', 'Services'], ['#how', 'How it works'], ['#price', 'Pricing'], ['#request', 'Request care']],
  become: [['#roles', 'Who can join'], ['#role', 'Your role'], ['#path', 'The path'], ['#apply', 'Apply']],
};

function BrandLockup({ className = 'brand-tx' }) {
  return (
    <span className={className}>
      <b>NRI</b>
      <b className="hb-blue">Parent Service</b>
      <small>Your Parents, Our Priority</small>
    </span>
  );
}

function Nav({ mode, onToggle }) {
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);
  const links = NAV_LINKS[mode];
  return (
    <header className={cx('nav', open && 'open')}>
      <div className="wrap nav-in">
        <a className="brand" href="#top" onClick={close}>
          <img className="brand-logo" src={logoMark} alt="" width="200" height="161" />
          <BrandLockup />
        </a>
        <nav className="links" aria-label="Main">
          {links.map(([href, label]) => <a key={href} href={href}>{label}</a>)}
        </nav>
        <SwitchCta mode={mode} onClick={onToggle} className="nav-switch" />
        <button
          type="button"
          className="nav-burger"
          aria-label={open ? 'Close menu' : 'Open menu'}
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          <span></span><span></span><span></span>
        </button>
      </div>
      <div className="nav-panel" hidden={!open}>
        <nav aria-label="Mobile">
          {links.map(([href, label]) => (
            <a key={href} href={href} onClick={close}>{label}<Icon name="arrow" sw={2} /></a>
          ))}
        </nav>
      </div>
    </header>
  );
}

function Footer({ mode, onSwitch }) {
  return (
    <footer className="ftr">
      <div className="wrap">
        <div className="ftr-grid">
          <div className="ftr-brand">
            <a className="ftr-logo" href="#top">
              <img src={logoMark} alt="" width="200" height="161" />
              <BrandLockup className="ftr-logo-tx" />
            </a>
            <p>Qualified health professionals who take each step with your parents at home, and a record of it that reaches you — so you can be there, even from miles away.</p>
          </div>
          <div>
            <h4>For families</h4>
            <ul>
              {NAV_LINKS.need.map(([href, label]) => (
                <li key={href}><a href={href} onClick={(e) => { if (mode !== 'need') { e.preventDefault(); onSwitch('need', href); } }}>{label}</a></li>
              ))}
            </ul>
          </div>
          <div>
            <h4>For professionals</h4>
            <ul>
              {NAV_LINKS.become.map(([href, label]) => (
                <li key={href}><a href={href} onClick={(e) => { if (mode !== 'become') { e.preventDefault(); onSwitch('become', href); } }}>{label}</a></li>
              ))}
            </ul>
          </div>
          <div>
            <h4>Contact</h4>
            <ul className="ftr-contact">
              <li><Icon name="phone" />[YOUR HELPLINE NUMBER]</li>
              <li><Icon name="chat" />[YOUR SUPPORT EMAIL]</li>
            </ul>
          </div>
        </div>
        <div className="ftr-bottom">
          <span>© {new Date().getFullYear()} NRI Parent Service. All rights reserved.</span>
          <span>Made with ❤️ for Desi parents and the families who love them</span>
        </div>
      </div>
    </footer>
  );
}

function HeroBadge() {
  return (
    <div className="hero-badge rise d6">
      <img src={logoMark} alt="" width="200" height="161" />
      <span className="hero-badge-tx">
        <b>NRI</b>
        <b className="hb-blue">Parent Service</b>
        <span>Your Parents, Our Priority</span>
      </span>
    </div>
  );
}

function Heroes({ openBook, onApply }) {
  return (
    <div id="top">
      <div className="m-need">
        <section className="bh">
          <img className="bh-blur" src={heroNeed} alt="" aria-hidden="true" />
          <img className="bh-bg" src={heroNeed} alt="A Sahayak in uniform smiling with an elderly mother at her home" />
          <div className="wrap bh-in">
            <div className="bh-copy">
              <div className="rise"><span className="hero-script">Someone qualified beside them — even from miles away.</span></div>
              <span className="eyebrow rise d1"><i></i>Sahayak · Professional health assistance</span>
              <h1 className="bh-h">
                <span className="ln"><span className="l1">Health Assistance,</span></span>
                <span className="ln"><span className="l2"><span className="t">At Every</span> <span className="b">Step<Underline /></span><span className="dt">.</span></span></span>
              </h1>
              <p className="lead rise d3">A qualified health professional takes each step with your parents — the check, the test, the appointment, the medicines — and every step is logged as it happens, so you see it without having to ask.</p>
            </div>
          </div>
          <HeroBadge />
        </section>
        <NeedHeroCard openBook={openBook} />
      </div>
      <div className="m-become">
        <section className="bh bj">
          <img className="bh-blur" src={heroBecome} alt="" aria-hidden="true" />
          <img className="bh-bg" src={heroBecome} alt="A smiling Sahayak in uniform carrying a care bag on her way to a home visit" />
          <div className="wrap bh-in">
            <div className="bh-copy">
              <div className="rise"><span className="hero-script">Your training, where it is actually needed.</span></div>
              <span className="eyebrow rise d1"><i></i>Sahayak · For health professionals</span>
              <h1 className="bh-h">
                <span className="ln"><span className="l1">Your Health Training</span></span>
                <span className="ln"><span className="l1 l1b">Belongs Beside a Family</span></span>
                <span className="ln"><span className="l2"><span className="t">at</span> <span className="b">Home<Underline /></span><span className="dt">.</span></span></span>
              </h1>
              <p className="lead rise d3">Join Sahayak as a health professional. Take assignments you are qualified for, close to home, with the app guiding each step and a doctor reviewing the record.</p>
            </div>
          </div>
          <HeroBadge />
        </section>
        <BecomeHeroCard onApply={onApply} />
      </div>
    </div>
  );
}

export default function App() {
  const [mode, setMode] = useState('need');
  const [booking, setBooking] = useState({ open: false, prefill: null });
  const [applyAs, setApplyAs] = useState(null);
  const onApply = useCallback((info) => { setApplyAs({ ...info, nonce: Date.now() }); scrollToId('apply'); }, []);

  const openBook = useCallback((prefill = null) => setBooking({ open: true, prefill }), []);
  const closeBook = useCallback(() => setBooking((b) => ({ ...b, open: false })), []);

  const switchTo = (m) => {
    setMode(m);
    scrollToId('top');
  };
  const toggleMode = () => switchTo(mode === 'need' ? 'become' : 'need');

  /* Served inside the site's own header and footer (base.html), so the bundle must not draw
     a second set -- standalone (`npm run dev`) it still draws both, which is how the page is
     worked on. Embedded, the journey switcher goes into the site header instead, beside the
     product switcher: it belongs in the chrome, not in a strip pushed under it. */
  const chrome = site.chrome !== false;
  const [slot, setSlot] = useState(null);
  useEffect(() => { setSlot(document.getElementById('sahayakJourney')); }, []);

  return (
    <div className={cx('page', mode, !chrome && 'embedded')} id="page" style={{ width: '100%', minHeight: '100%' }}>
      {chrome && <Nav mode={mode} onToggle={toggleMode} />}
      {chrome && <div className="mob-switch"><SwitchCta mode={mode} onClick={toggleMode} className="block" /></div>}
      {!chrome && slot && createPortal(<JourneySwitch mode={mode} onPick={switchTo} />, slot)}
      <Heroes openBook={openBook} onApply={onApply} />
      <NeedMode openBook={openBook} />
      <BecomeMode mode={mode} applyAs={applyAs} onApplyAs={(bg) => setApplyAs({ bg, nonce: Date.now() })} />
      {chrome && (
        <Footer
          mode={mode}
          onSwitch={(m, href) => {
            setMode(m);
            scrollToId(href.slice(1));
          }}
        />
      )}
      <BookingModal open={booking.open} prefill={booking.prefill} onClose={closeBook} />
    </div>
  );
}
