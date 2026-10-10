import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Icon, { Underline } from './components/Icon.jsx';
import { cx } from './components/ui.jsx';
import NeedMode from './components/NeedMode.jsx';
import BecomeMode from './components/BecomeMode.jsx';
import BookingModal from './components/BookingModal.jsx';
import FinderModal from './components/ServiceFinder.jsx';
import { BecomeHeroCard, NeedHeroCard } from './components/HeroCard.jsx';
import { scrollToId } from './hooks.js';
import { site } from './data/site.js';
import heroEco from './assets/hero-care-ecosystem.jpg';
import heroBecome from './assets/hero-become.jpg';
import logoMark from './assets/logo-mark.png';

// What each journey calls itself.
const JOURNEY = {
  need: {
    label: 'Book a Sahayak', short: 'Book', sub: 'A professional with your parents',
    icon: 'homeHeart', art: heroEco,
    say: 'A registered nurse takes each step with your parents — the check, the test, the '
       + 'appointment, the medicines — and every step is recorded for you to read.',
  },
  become: {
    label: 'Join as a Sahayak', short: 'Join', sub: 'For B.Sc Nursing, GNM & ANM nurses',
    icon: 'userPlus', art: heroBecome,
    say: 'Registered nurses take assignments matched to their qualification, close to home, '
       + 'with the app guiding every step and a doctor reviewing the record.',
  },
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
                  onClick={() => { setOpen(false); onPick(m, box.current); }}>
            <Icon name={JOURNEY[m].icon} className="svc-sw-ico" sw={2} />
            <span><b>{JOURNEY[m].label}</b><small>{JOURNEY[m].sub}</small></span>
            {m === mode && <Icon name="check" className="svc-sw-tick" sw={3} />}
          </button>
        ))}
      </div>
    </div>
  );
}

/* How long the move takes. Slow on purpose: the point is to be watched, and the previous
 * third of a second of shrink-and-blur read as a flicker rather than a transition. */
const VEIL_GROW = 620;
const VEIL_HOLD = 1200;   // long enough to look at the picture and read the line under it
const VEIL_DRAIN = 700;

/* The journey switch, pinned to the top-right of the hero.
 *
 * Portalled to <body> rather than rendered inside the page. The transition folds the whole
 * page into this control and opens the other one back out of it, which means the control
 * cannot be part of what is folding -- and the animation needs one fixed point to aim at.
 *
 * It steps aside once the hero has scrolled past: from there the switcher in the site header
 * is the one in view, and two of the same control on screen is one too many.
 */
function HeroSwitch({ mode, onSwitch }) {
  const [host] = useState(() =>
    (typeof document === 'undefined' ? null : document.createElement('div')));
  const [past, setPast] = useState(false);

  useEffect(() => {
    if (!host) return undefined;
    document.body.appendChild(host);
    return () => { document.body.removeChild(host); };
  }, [host]);

  useEffect(() => {
    const onScroll = () => setPast(window.scrollY > 420);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  if (!host) return null;
  const s = SWITCH[mode];
  return createPortal(
    <button type="button" className={cx('sah-switch', mode, past && 'gone')}
            title={'Switch to ' + s.label}
            onClick={(e) => onSwitch(s.to, e.currentTarget)}>
      <span className="sah-switch-ico" aria-hidden="true"><Icon name={s.icon} sw={2} /></span>
      <span className="sah-switch-tx"><small>Switch to</small><b>{s.label}</b></span>
      <span className="sah-switch-arr" aria-hidden="true"><Icon name="arrow" sw={2.4} /></span>
    </button>,
    host);
}

/* The disc that carries you across. Grows out of the pressed control in the colour of the
 * journey you are going to, says where you are going, then drains back into it. Portalled to
 * <body> and pointer-events:none -- it is scenery, not a dialog.
 */
function Veil({ veil }) {
  if (!veil || typeof document === 'undefined') return null;
  const j = JOURNEY[veil.to];
  return createPortal(
    <div className={cx('jv', 'to-' + veil.to, veil.phase)} aria-hidden="true"
         style={{ '--jx': veil.x + 'px', '--jy': veil.y + 'px', '--jr': veil.r + 'px' }}>
      <span className="jv-ink"></span>
      <span className="jv-tx">
        <span className="jv-art">
          <img src={j.art} alt="" />
          <span className="jv-ico"><Icon name={j.icon} sw={1.9} /></span>
        </span>
        <b>{j.label}</b>
        <small>{j.sub}</small>
        <p>{j.say}</p>
      </span>
    </div>,
    document.body);
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
            <p>Registered nurses who take each step with your parents at home, and a record of it that reaches you — so you can be there, even from miles away.</p>
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
        {/* The care-ecosystem picture is a whole story -- the nurse at the centre, and around her
            the video consultation, the hospital, the readings, the lab, the medicines, the ride --
            so it is shown whole, framed beside the copy, rather than as a backdrop the copy and
            its fade would cover half of. */}
        <section className="bh bh-eco">
          <img className="bh-blur" src={heroEco} alt="" aria-hidden="true" />
          <div className="wrap bh-in">
            <div className="bh-copy">
              <div className="rise"><span className="hero-script">Someone qualified beside them — even from miles away.</span></div>
              <span className="eyebrow rise d1"><i></i>Sahayak · Registered nurses at home</span>
              <h1 className="bh-h">
                <span className="ln"><span className="l1">Health Assistance,</span></span>
                <span className="ln"><span className="l2"><span className="t">At Every</span> <span className="b">Step<Underline /></span><span className="dt">.</span></span></span>
              </h1>
              <p className="lead rise d3">A registered nurse takes each step with your parents — the check, the test, the appointment, the medicines — and every step is logged as it happens, so you see it without having to ask.</p>
            </div>
            <figure className="bh-eco-art rise d4">
              <img src={heroEco} width="1672" height="941"
                   alt="A Sahayak nurse with an elderly mother, surrounded by what a Sahayak handles: video consultations, hospital visits, vitals, lab samples, medicines and rides to appointments" />
            </figure>
          </div>
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
              <span className="eyebrow rise d1"><i></i>Sahayak · For B.Sc Nursing, GNM &amp; ANM nurses</span>
              <h1 className="bh-h">
                <span className="ln"><span className="l1">Your Nursing Training</span></span>
                <span className="ln"><span className="l1 l1b">Belongs Beside a Family</span></span>
                <span className="ln"><span className="l2"><span className="t">at</span> <span className="b">Home<Underline /></span><span className="dt">.</span></span></span>
              </h1>
              <p className="lead rise d3">Join Sahayak if you hold a B.Sc Nursing, GNM or ANM qualification. Take assignments matched to your training, close to home, with the app guiding each step and a doctor reviewing the record.</p>
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

  /* Switching journeys folds the page into whichever control was pressed and opens the other
     journey back out of the same point, so the two halves of the site feel like one thing
     seen from two sides rather than two pages swapped behind your back.
     The origin is measured from the control itself, so it is right whether the press came
     from the hero, the site header or the nav. */
  const [swap, setSwap] = useState('');
  const [veil, setVeil] = useState(null);
  const timers = useRef([]);
  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  const switchTo = useCallback((m, origin) => {
    if (m === mode || veil) return;        // one move at a time
    const page = document.getElementById('page');
    const still = window.matchMedia
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!page || !origin || still) {        // no animation: just be where they asked to be
      setMode(m);
      scrollToId('top');
      return;
    }
    /* The veil is fixed, so it works in screen coordinates and the control it grows out of
       does not move under it -- every control that can start this is fixed or sticky. The
       radius is the distance to the furthest corner of the viewport, so the disc always
       covers whatever is behind it however near the edge the control sits. */
    const b = origin.getBoundingClientRect();
    const x = b.left + b.width / 2;
    const y = b.top + b.height / 2;
    setVeil({
      to: m,
      x,
      y,
      r: Math.ceil(Math.hypot(Math.max(x, window.innerWidth - x),
                              Math.max(y, window.innerHeight - y))) + 40,
      phase: 'grow',
    });
    setSwap('out');
    // Swap underneath while the colour is covering everything, then drain it away.
    timers.current.push(setTimeout(() => {
      window.scrollTo(0, 0);
      setMode(m);
      setSwap('in');
      setVeil((v) => (v ? { ...v, phase: 'drain' } : v));
    }, VEIL_GROW + VEIL_HOLD));
    timers.current.push(setTimeout(() => {
      setVeil(null);
      setSwap('');
    }, VEIL_GROW + VEIL_HOLD + VEIL_DRAIN));
  }, [mode, veil]);

  const toggleMode = (e) =>
    switchTo(mode === 'need' ? 'become' : 'need', e && e.currentTarget);

  /* Served inside the site's own header and footer (base.html), so the bundle must not draw
     a second set -- standalone (`npm run dev`) it still draws both, which is how the page is
     worked on. Embedded, the journey switcher goes into the site header instead, beside the
     product switcher: it belongs in the chrome, not in a strip pushed under it. */
  const chrome = site.chrome !== false;
  const [slot, setSlot] = useState(null);
  useEffect(() => { setSlot(document.getElementById('sahayakJourney')); }, []);

  return (
    <div className={cx('page', mode, !chrome && 'embedded', swap && 'swap-' + swap)} id="page" style={{ width: '100%', minHeight: '100%' }}>
      {chrome && <Nav mode={mode} onToggle={toggleMode} />}
      {chrome && <div className="mob-switch"><SwitchCta mode={mode} onClick={toggleMode} className="block" /></div>}
      {!chrome && slot && createPortal(<JourneySwitch mode={mode} onPick={switchTo} />, slot)}
      <HeroSwitch mode={mode} onSwitch={switchTo} />
      <Veil veil={veil} />
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
      <FinderModal mode={mode} openBook={openBook} />
    </div>
  );
}
