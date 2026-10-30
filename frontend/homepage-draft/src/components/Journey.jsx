import { useEffect, useRef } from 'react';
import Icon from './Icon.jsx';
import { away, site } from '../data/site.js';
import { reduceMotion, useReveal } from '../hooks.js';
import companionStub from '../assets/photos/companion-stub.jpg';
import tileParent from '../assets/photos/tile-parent.jpg';
import docHero from '../assets/photos/call-on-doc-hero.webp';
import docScreen from '../assets/photos/call-on-doc-screen.webp';
import sahHero from '../assets/photos/sah-hero-ecosystem.jpg';
import readyToFly from '../assets/photos/ins-story-parents.jpg';
import checkedPhoto from '../assets/photos/sah-svc-lab.jpg';
import chTravel from '../assets/photos/tc-l3.jpg';
import chCare from '../assets/photos/sah-finder-care.jpg';
import chHealth from '../assets/photos/hero-parent-care.jpg';
import { Doodles, Note, Snap, Trail } from './Deco.jsx';

/* "Our services" as on the static page: a flight path drawn by scroll, stops alternating
 * sides, each with a 3D object that turns as it passes, and the traveller on the path
 * changing with the chapter. */

const PLANE = 'M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z';
const Check = ({ w = 3 }) => <Icon name="check" stroke={w} className="" />;

function Chip({ cls, icon = 'check', stroke = 3, title, sub }) {
  return (
    <div className={`float-chip ${cls}`}>
      <span className="ck"><Icon name={icon} stroke={stroke} className="" /></span>
      <span>{title}<small>{sub}</small></span>
    </div>
  );
}

/* A chapter's card on the path: its whole photo, framed in its own shape and ringed in the chapter's
 * colour, with its number on a badge,
 * "Chapter one" and its name, its line, and the services it covers. `children` are the snapshots
 * and notes in the space beside it. */
function Stub({ id, n, word, title, text, tone, img, services, children }) {
  return (
    <div className="stub-wrap" id={id}>
      {children}
      <div className={`stub ${tone}`} data-pt>
        <span className="stub-ph"><img src={img} alt="" loading="lazy" decoding="async" /><b>{n}</b></span>
        <span className="stub-tx"><small>Chapter {word}</small><strong>{title}</strong><span>{text}</span></span>
        <span className="stub-svcs">{services.map((sv) => <i key={sv}>{sv}</i>)}</span>
      </div>
    </div>
  );
}

function Stop({ rev, n, title, text, link, primary, objClass = '', children }) {
  const hid = `s${n}-h`;
  const txt = useReveal(0.25);
  return (
    <article className={`stop${rev ? ' rev' : ''}`} aria-labelledby={hid}>
      <span className="node" data-pt />
      <div className="stop-txt rv-up" ref={txt}>
        <span className="stop-n">0{n}</span>
        <h3 id={hid}>{title}</h3>
        <p>{text}</p>
        <a className={primary ? 'btn btn-a' : 'lnk'} href={link[1]} {...away(link[1])}>{link[0]}<Icon name="arrow" /></a>
      </div>
      <div className={`obj ${objClass}`} aria-hidden="true">{children}</div>
    </article>
  );
}

function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }

// How fast the traveller and the 3D objects catch up with the scroll: the share of the gap
// closed per 60 fps frame. A mouse wheel moves the page 100+ px at once; this turns that jump
// into a glide of a few hundred milliseconds.
const EASE = 0.14;

/* The static page's script, scoped to this section -- with the traveller, the drawn path and
 * the objects easing toward where the scroll says they should be, instead of jumping there. */
function useJourney(sectionRef) {
  useEffect(() => {
    const sec = sectionRef.current;
    const body = sec.querySelector('.jr-body');
    const svg = body.querySelector('.jr-path');
    const trail = svg.querySelector('.trail');
    const drawn = svg.querySelector('.drawn');
    const plane = body.querySelector('.plane');
    const rot = plane.querySelector('.rot');
    const pts = Array.from(body.querySelectorAll('[data-pt]'));
    const objs = Array.from(body.querySelectorAll('.obj'));
    const stubs = Array.from(body.querySelectorAll('.stub-wrap'));
    const chaps = Array.from(sec.querySelectorAll('.chap'));
    const ind = sec.querySelector('.chap-ind');
    const reduce = reduceMotion();
    let samples = [], total = 0, ptY = [], raf = 0, running = false, last = 0;
    let cur = null;                               // where the traveller is, as a length along the path
    let chap = -1;
    const eased = new Map();                      // each object's own {q, pr}, easing like the traveller

    function build() {
      const br = body.getBoundingClientRect();
      const W = body.clientWidth, H = body.scrollHeight;
      const mobile = window.innerWidth <= 760;
      const cx = mobile ? 21 : W / 2;
      svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
      const P = [[cx, 0]];
      ptY = [];
      pts.forEach((el) => {
        const r = el.getBoundingClientRect();
        let y = r.top - br.top + r.height / 2;
        if (el.classList.contains('pin-pt')) y = r.top - br.top - 36;
        P.push([cx, y]);
        ptY.push(y);
      });
      const bulge = mobile ? 0 : Math.min(W * 0.05, 70);
      let d = `M${P[0][0]} ${P[0][1]}`;
      for (let i = 1; i < P.length; i++) {
        const a = P[i - 1], b = P[i], s = i % 2 ? 1 : -1, dy = b[1] - a[1];
        d += ` C${a[0] + s * bulge} ${a[1] + dy * 0.35} ${b[0] + s * bulge} ${a[1] + dy * 0.65} ${b[0]} ${b[1]}`;
      }
      trail.setAttribute('d', d);
      drawn.setAttribute('d', d);
      total = drawn.getTotalLength();
      drawn.style.strokeDasharray = `${total} ${total}`;
      samples = [];
      const N = 600;
      for (let k = 0; k <= N; k++) {
        const L = (total * k) / N;
        samples.push([L, drawn.getPointAtLength(L).y]);
      }
      cur = null;                                 // a new path: start where the scroll is, no glide
      moveMarker();
      kick();
    }

    function lenAtY(y) {
      if (!samples.length || y <= samples[0][1]) return 0;
      for (let i = 1; i < samples.length; i++) {
        if (samples[i][1] >= y) {
          const a = samples[i - 1], b = samples[i];
          const t = b[1] === a[1] ? 0 : (y - a[1]) / (b[1] - a[1]);
          return a[0] + (b[0] - a[0]) * t;
        }
      }
      return total;
    }

    // the traveller at length L: the path drawn up to it, its icon turned along the path, the
    // stops it has passed lit, and its icon for the chapter it is in -- all from where it IS, so
    // the icon changes exactly as it passes a stop
    function draw(L) {
      drawn.style.strokeDashoffset = total - L;
      const p1 = drawn.getPointAtLength(Math.max(0, L - 1));
      const p2 = drawn.getPointAtLength(Math.min(total, L + 1));
      const p = drawn.getPointAtLength(L);
      let ang = (Math.atan2(p2.y - p1.y, p2.x - p1.x) * 180) / Math.PI + 90;
      if (!isFinite(ang) || (p1.x === p2.x && p1.y === p2.y)) ang = 180;
      plane.style.transform = `translate3d(${p.x}px,${p.y}px,0)`;
      rot.style.transform = `rotate(${ang}deg)`;
      const y = p.y;
      // points: stub, stop, stop, stub, stop, stop, stub, stop, stop, pin
      let mode = 'plane';
      if (ptY.length >= 10) {
        if (y >= (ptY[7] + ptY[8]) / 2) mode = 'fly';
        else if (y >= ptY[6]) mode = 'gift';
        else if (y >= (ptY[4] + ptY[5]) / 2) mode = 'help';
        else if (y >= ptY[3]) mode = 'doc';
      }
      if (plane.getAttribute('data-mode') !== mode) {
        plane.setAttribute('data-mode', mode);
        plane.classList.remove('swap');
        void plane.offsetWidth;
        plane.classList.add('swap');
      }
      pts.forEach((el, i) => {
        if (el.classList.contains('node')) el.classList.toggle('passed', ptY[i] <= y + 1);
      });
    }

    // each 3D object turns and opens with the scroll, easing like the traveller; false once all
    // have arrived
    function objects(k, vh) {
      let moving = false;
      objs.forEach((o) => {
        const r = o.getBoundingClientRect();
        if (r.bottom < -200 || r.top > vh + 200) { eased.delete(o); return; }
        const q = reduce ? 0 : clamp((r.top + r.height / 2 - vh / 2) / (vh * 0.75), -1, 1);
        const pr = reduce ? 1 : clamp((vh * 0.92 - r.top) / (vh * 0.55), 0, 1);
        let e = eased.get(o);
        if (!e) { e = { q, pr }; eased.set(o, e); }
        e.q += (q - e.q) * k;
        e.pr += (pr - e.pr) * k;
        if (Math.abs(q - e.q) < 0.002 && Math.abs(pr - e.pr) < 0.002) { e.q = q; e.pr = pr; } else moving = true;
        o.style.setProperty('--q', e.q.toFixed(4));
        o.style.setProperty('--pr', e.pr.toFixed(4));
      });
      return moving;
    }

    // the chapter bar's marker slides under the chapter being read
    function moveMarker() {
      const c = chaps[Math.max(chap, 0)];
      if (!ind || !c) return;
      ind.style.width = `${c.offsetWidth}px`;
      ind.style.transform = `translateX(${c.offsetLeft}px)`;
    }
    function chapters(vh) {
      let now = 0;
      stubs.forEach((s, i) => { if (s.getBoundingClientRect().top < vh * 0.5) now = i; });
      if (now === chap) return;
      chap = now;
      chaps.forEach((c, i) => {
        c.classList.toggle('on', i === now);
        if (i === now) c.setAttribute('aria-current', 'step'); else c.removeAttribute('aria-current');
      });
      moveMarker();
    }

    function frame(t) {
      running = false;
      if (!total) return;
      const dt = last ? Math.min(t - last, 64) : 16.7;
      last = t;
      const k = reduce ? 1 : 1 - Math.pow(1 - EASE, dt / 16.7);
      const vh = window.innerHeight;
      const goal = lenAtY(vh * 0.55 - body.getBoundingClientRect().top);
      cur = cur === null ? goal : cur + (goal - cur) * k;
      if (Math.abs(goal - cur) < 0.4) cur = goal;
      draw(cur);
      const moving = objects(k, vh);
      chapters(vh);
      if (cur !== goal || moving) kick(); else last = 0;
    }
    function kick() {
      if (running) return;
      running = true;
      raf = requestAnimationFrame(frame);
    }

    const onScroll = kick;
    const rebuild = () => { cancelAnimationFrame(raf); running = false; raf = requestAnimationFrame(build); };
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', rebuild);
    window.addEventListener('load', rebuild);
    const ro = window.ResizeObserver ? new ResizeObserver(rebuild) : null;
    if (ro) ro.observe(body);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(rebuild);
    build();
    return () => {
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', rebuild);
      window.removeEventListener('load', rebuild);
      if (ro) ro.disconnect();
      cancelAnimationFrame(raf);
    };
  }, [sectionRef]);
}

export default function Journey() {
  const ref = useRef(null);
  const head = useReveal();
  useJourney(ref);

  return (
    <section className="jr" id="services" aria-labelledby="jr-h" ref={ref}>
      <Doodles items={[
        ['plane', { top: '2%', left: '3%', size: 34, rotate: -14, opacity: 0.14 }],
        ['globe', { top: '5%', right: '4%', size: 38, rotate: 8, opacity: 0.12 }],
        ['pin', { top: '24%', left: '2.5%', size: 26, rotate: -6 }],
        ['heart', { top: '38%', right: '3%', size: 28, rotate: 10 }],
        ['home', { top: '52%', left: '3%', size: 30, rotate: 6, opacity: 0.12 }],
        ['steth', { top: '66%', right: '3.5%', size: 32, rotate: -10 }],
        ['gift', { top: '80%', left: '3%', size: 30, rotate: -8 }],
        ['shield', { top: '92%', right: '4%', size: 30, rotate: 6, opacity: 0.12 }],
      ]} />
      <div className="wrap">
        <div className="jr-head rv-up" ref={head}>
          <span className="kick">Our services</span>
          <h2 className="h2" id="jr-h">Every Step of Their Journey, <em>Taken Care Of</em></h2>
          <p className="lede">From the airport to their front door, here is how we support your parents in India.</p>
        </div>

        <nav className="chapnav" aria-label="Service chapters">
          <div className="chapnav-in">
            <span className="chap-ind" aria-hidden="true" />
            <a className="chap on" href="#ch-travel"><Icon name="plane" className="" /><b>01</b>Travel</a>
            <a className="chap" href="#ch-care"><Icon name="home" className="" /><b>02</b>Care</a>
            <a className="chap" href="#ch-health"><Icon name="health" className="" /><b>03</b>Health</a>
          </div>
        </nav>

        <div className="jr-body">
          <svg className="jr-path" aria-hidden="true"><path className="trail" d="" /><path className="drawn" d="" /></svg>
          <div className="plane" data-mode="plane" aria-hidden="true">
            <span className="ring" />
            <span className="rot">
              <span className="pi pi-plane"><svg viewBox="0 0 24 24" fill="currentColor"><path d={PLANE} /></svg></span>
              <span className="pi pi-fly"><svg viewBox="0 0 24 24" fill="currentColor"><path d={PLANE} /></svg></span>
            </span>
            <span className="pi pi-doc"><Icon name="steth" className="" /></span>
            <span className="pi pi-help">
              <svg viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="9.5" cy="6.5" r="2.6" /><path d="M10 9.6c-.6 3-.9 5.4-.5 8.4" /><path d="M9.5 18 7.5 27M9.5 18l2.5 9" /><path d="M9.8 12 6 14.5" /><path d="M6 14.5 4.8 27" /><circle cx="22" cy="5.5" r="2.6" /><path d="M22 8.6V18" /><path d="M22 18l-2 9M22 18l2 9" /><path d="M22 11.5 13 12.6" />
              </svg>
            </span>
            <span className="pi pi-gift"><Icon name="gift" className="" /></span>
            <span className="badge-ok"><Check w={3.4} /></span>
          </div>

          <Stub id="ch-travel" n="01" word="one" title="Travel" text="Safer, calmer journeys for your parents." tone="travel"
            img={chTravel} services={['Travel Companion', 'Travel Insurance']}>
            <Snap src={readyToFly} caption="Ready to fly!" at={{ top: '-18px', left: '1%' }} rotate={-6} />
            <Note at={{ top: '34px', right: '0%' }} rotate={5} icon="plane">Safer journeys, together</Note>
            <Trail at={{ top: '86px', right: '6%' }} width={170} flip />
          </Stub>

          <Stop n={1} title="Travel Companion" link={['Explore Travel Companion', site.companionUrl]}
            text="Trusted assistance for elderly parents who need support before, during or after their journey.">
            <div className="o3 bp3">
              <div className="bp-card">
                <div className="bp-main">
                  <div className="bp-top"><span>Boarding pass · Travel Companion</span><Icon name="heart" className="" /></div>
                  <div className="bp-route">
                    <div><b>HYD</b><small>Hyderabad</small></div>
                    <div className="fly"><i /><svg viewBox="0 0 24 24" fill="currentColor"><path d={PLANE} transform="rotate(90 12 12)" /></svg><i /></div>
                    <div style={{ textAlign: 'right' }}><b>LHR</b><small>London</small></div>
                  </div>
                  <div className="bp-meta3">
                    <div><span>Passengers</span><b>Amma &amp; Papa</b></div>
                    <div><span>Companion</span><b>Sahayak</b></div>
                    <div><span>Assistance</span><b>Door to door</b></div>
                  </div>
                </div>
                <div className="bp-stub"><img src={companionStub} alt="" /><span>Travelling<br />together</span><i className="bar" /></div>
              </div>
              <Chip cls="c1" title="Companion assigned" sub="You get updates at every step" />
            </div>
          </Stop>

          <Stop rev n={2} title="Travel Insurance" link={['Explore Travel Insurance', site.insuranceUrl]}
            text="Protect your parents with travel insurance designed to support them throughout their journey.">
            <div className="o3 ic3">
              <div className="ic-front">
                <div className="ic-hd"><span className="mk"><span><Icon name="heart" className="" /></span>NRI Parent Service</span><em>Travel Medical</em></div>
                <div className="ic-body">
                  <div className="ic-l">
                    <div><span>Member name</span><b>Lakshmi Rao</b></div>
                    <div><span>Effective date</span><b>On the day they fly</b></div>
                    <div><span>Certificate #</span><b>XXXXXXXXX</b></div>
                    <span className="fine">Sample card for illustration</span>
                  </div>
                  <div className="ic-r">
                    <div><span>Member ID</span><b>•••• •••• ••••</b></div>
                    <div><span>Plan</span><b>International Travel</b></div>
                    <div><span>Group</span><b>NRI Parent Service</b></div>
                    <div><span>Purchase via</span><b>Preventia360</b></div>
                  </div>
                </div>
              </div>
              <Chip cls="c1" icon="shield" stroke={2.6} title="Eligible medical emergencies" sub="Covered as per plan terms" />
            </div>
          </Stop>

          <Stub id="ch-care" n="02" word="two" title="Care" text="Doctors and a helping hand, wherever you are." tone="care"
            img={chCare} services={['Virtual Doctor', 'Sahayak']}>
            <Note at={{ top: '30px', left: '0%' }} rotate={-5} tone="blue">A helping hand at home</Note>
            <Trail at={{ top: '82px', left: '5%' }} width={170} />
            <Snap src={tileParent} caption="Amma, at home" at={{ top: '-22px', right: '1%' }} rotate={5} width={140} />
          </Stub>

          <Stop n={3} title="Virtual Doctor Consultation" link={['Book a Consultation', site.doctorUrl]}
            text="Video consultations with a doctor from home. You can join the call from abroad.">
            {/* the Call-ON-Doc page's own pictures: its hero, and its call screen in front of it */}
            <div className="o3 vd3">
              <div className="vd-photo"><img src={docHero} alt="" loading="lazy" decoding="async" /></div>
              <div className="vd-phone"><img src={docScreen} alt="" loading="lazy" decoding="async" /></div>
              <Chip cls="c1" title="Prescription shared" sub="Sent to you on WhatsApp" />
            </div>
          </Stop>

          <Stop rev n={4} title="Sahayak" primary link={['Book a Sahayak', site.sahayakUrl]}
            text="A trusted helping hand for hospital visits, doctor appointments, healthcare needs and everyday assistance.">
            {/* the Sahayak page's hero picture, whole, framed as that page frames it */}
            <div className="o3 sh3">
              <div className="lay sh-bk" />
              <div className="sh-card"><img src={sahHero} alt="" loading="lazy" decoding="async" /></div>
              <Chip cls="c1" icon="calendar" stroke={2.4} title="Hospital visit" sub="Today, 10:30 AM" />
            </div>
          </Stop>

          <Stub id="ch-health" n="03" word="three" title="Health" text="Proactive health support, arranged from abroad." tone="health"
            img={chHealth} services={['Gift Health', 'Fit2Fly']}>
            <Note at={{ top: '40px', left: '0%' }} rotate={-4} icon="health" tone="blue">Their health, looked after</Note>
            <Snap src={checkedPhoto} caption="Tests done at home" at={{ top: '-20px', right: '1%' }} rotate={5} />
          </Stub>

          <Stop n={5} title="Gift Health" link={['Explore Gift Health', site.giftUrl]} objClass="tall"
            text="Give your parents the gift of better health, care and proactive support — even from miles away.">
            <div className="o3 gb3">
              <div className="cube"><div className="in" /><div className="face b" /><div className="face l" /><div className="face r" /><div className="face f" /></div>
              <div className="voucher"><span>Gift Health</span><b>A health checkup for Amma</b><small>With love, from Toronto</small></div>
              <div className="lid"><div className="top" /><div className="face b" /><div className="face l" /><div className="face r" /><div className="face f" /><div className="bow" /></div>
              <Chip cls="c1" icon="heart" stroke={2.4} title="Sent from abroad" sub="Received at home in India" />
            </div>
          </Stop>

          <Stop rev n={6} title="Fit2Fly" link={['Explore Fit2Fly', site.fitUrl]} objClass="tall"
            text="Prepare your parents for safe and confident travel with the right health assessment before their journey.">
            <div className="o3 ff3">
              <div className="clip" />
              <div className="paper">
                <span className="t">Fit2Fly · Assessment</span>
                <h4>Pre-travel health check</h4>
                <div className="who2"><span>Passenger <b>Papa</b></span><span>Route <b>HYD → LHR</b></span></div>
                {['Vitals reviewed', 'Doctor consultation', 'Travel medicines', 'Ready for the journey'].map((r) => (
                  <div className="row" key={r}>{r}<i><Check w={3.4} /></i></div>
                ))}
              </div>
              <div className="clip-top" />
              <div className="stamp">Ready<br />to fly</div>
            </div>
          </Stop>

          <div className="jr-end">
            <span className="pin-pt" data-pt><Icon name="pin" className="" />Arrived <small>· Your parents, cared for</small></span>
          </div>
        </div>
      </div>
    </section>
  );
}
