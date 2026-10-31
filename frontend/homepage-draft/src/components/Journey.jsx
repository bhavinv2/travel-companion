import { useEffect, useRef } from 'react';
import Icon from './Icon.jsx';
import { away, site } from '../data/site.js';
import { MARK, MARKS } from '../data/services.js';
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
import { Doodles, Note, Side, Snap, Trail } from './Deco.jsx';
import sideTravel from '../assets/photos/tc-l2.jpg';
import sideCare from '../assets/photos/sahayak-photo.jpg';
import sideHealth from '../assets/photos/sah-family.jpg';

/* "Our services" as on the static page: a path drawn by scroll, stops alternating sides, each
 * with a 3D object that tilts as it passes. Each stop's service icon sits on the path at its
 * stop and lights up in the service's colour when the line reaches it; the line takes on each
 * service's colour as it goes, and only its glowing tip moves with the page. */

const PLANE = 'M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z';

// the line's colour after the last stop, on the way to "Arrived"
const ARRIVED = '#E4613F';
const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const mix = (a, b, t) => { const A = rgb(a), B = rgb(b); return `rgb(${A.map((v, i) => Math.round(v + (B[i] - v) * t)).join(',')})`; };
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

function Stop({ rev, n, mark, title, text, link, primary, objClass = '', children }) {
  const hid = `s${n}-h`;
  const txt = useReveal(0.25);
  return (
    <article className={`stop${rev ? ' rev' : ''}`} aria-labelledby={hid}>
      <span className="node" data-pt style={{ '--c': mark.color }}><Icon name={mark.icon} stroke={2} className="" /></span>
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

// How fast the line's tip and the 3D objects catch up with the scroll: the share of the gap
// closed per 60 fps frame. A mouse wheel moves the page 100+ px at once; this turns that jump
// into a short glide instead of a hop.
const EASE = 0.2;

/* The static page's script, scoped to this section -- with the line, its tip and the objects
 * easing toward where the scroll says they should be, instead of jumping there. */
function useJourney(sectionRef) {
  useEffect(() => {
    const sec = sectionRef.current;
    const body = sec.querySelector('.jr-body');
    const svg = body.querySelector('.jr-path');
    const trail = svg.querySelector('.trail');
    const drawn = svg.querySelector('.drawn');
    const ink = svg.querySelector('linearGradient');
    const head = body.querySelector('.jr-tip');
    const pts = Array.from(body.querySelectorAll('[data-pt]'));
    const lamps = pts.filter((el) => el.classList.contains('node') || el.classList.contains('pin-pt'));
    const objs = Array.from(body.querySelectorAll('.obj'));
    const stubs = Array.from(body.querySelectorAll('.stub-wrap'));
    const chaps = Array.from(sec.querySelectorAll('.chap'));
    const ind = sec.querySelector('.chap-ind');
    const reduce = reduceMotion();
    let samples = [], total = 0, raf = 0, running = false, last = 0;
    let lampY = [];                               // where each stop's icon (and the pin) sits on the path
    let inks = [];                                // [y, colour]: the line's colour down the page
    let cur = null;                               // where the tip is, as a length along the path
    let chap = -1;
    const eased = new Map();                      // each object's own {q, pr}, easing like the tip

    function build() {
      const br = body.getBoundingClientRect();
      const W = body.clientWidth, H = body.scrollHeight;
      const mobile = window.innerWidth <= 760;
      const cx = mobile ? 21 : W / 2;
      const ptY = [];
      svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
      const P = [[cx, 0]];
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
      // the line's colours: each stop's own where its icon sits, blending from one stop to the next
      lampY = lamps.map((el) => ptY[pts.indexOf(el)]);
      const cols = lamps.map((el) => el.style.getPropertyValue('--c').trim() || ARRIVED);
      inks = [[0, cols[0]], ...lampY.map((y, i) => [y, cols[i]])];
      ink.setAttribute('y2', String(H));
      ink.replaceChildren(...inks.map(([y, c]) => {
        const s = document.createElementNS('http://www.w3.org/2000/svg', 'stop');
        s.setAttribute('offset', String(clamp(y / H, 0, 1)));
        s.setAttribute('stop-color', c);
        return s;
      }));
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

    // the line's colour at height y: between two stops, part the one and part the next
    function inkAt(y) {
      for (let i = 1; i < inks.length; i++) {
        if (y <= inks[i][0]) {
          const [ya, ca] = inks[i - 1], [yb, cb] = inks[i];
          return mix(ca, cb, yb === ya ? 1 : clamp((y - ya) / (yb - ya), 0, 1));
        }
      }
      return inks.length ? inks[inks.length - 1][1] : ARRIVED;
    }

    // the line drawn down to length L, its tip there in the line's colour there, and every stop
    // the tip has reached lit up (the tip slips under a stop's icon as it lights)
    function draw(L) {
      drawn.style.strokeDashoffset = total - L;
      const p = drawn.getPointAtLength(L);
      head.style.transform = `translate3d(${p.x}px,${p.y}px,0)`;
      head.style.setProperty('--c', inkAt(p.y));
      lamps.forEach((el, i) => el.classList.toggle('lit', lampY[i] <= p.y + 1));
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
      <Side img={sideTravel} shape="arch" top="15%" tint={MARK.companion.color} pos="center 40%"
        icons={[['plane', MARK.companion.color], ['shield', MARK.insurance.color], ['pin', '#E4613F'], ['globe', '#0F9D8C']]} />
      <Side img={sideCare} shape="blob" top="45%" tint={MARK.sahayak.color} pos="center 30%"
        icons={[['steth', MARK.doctor.color], ['home', MARK.sahayak.color], ['video', '#2446B8'], ['heart', '#E4613F']]} />
      <Side img={sideHealth} shape="circle" top="74%" tint={MARK.fit.color}
        icons={[['gift', MARK.gift.color], ['clip', MARK.fit.color], ['health', '#E4613F'], ['calendar', '#2446B8']]} />
      <Doodles items={[
        ['globe', { top: '5%', right: '4%', size: 38, rotate: 8, opacity: 0.12 }],
        ['heart', { top: '38%', right: '3%', size: 28, rotate: 10 }],
        ['steth', { top: '66%', right: '3.5%', size: 32, rotate: -10 }],
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
          <svg className="jr-path" aria-hidden="true">
            <defs><linearGradient id="jr-ink" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="1" /></defs>
            <path className="trail" d="" /><path className="drawn" d="" stroke="url(#jr-ink)" />
          </svg>
          <span className="jr-tip" aria-hidden="true" style={{ '--c': MARKS[0].color }} />

          <Stub id="ch-travel" n="01" word="one" title="Travel" text="Safer, calmer journeys for your parents." tone="travel"
            img={chTravel} services={['Travel Companion', 'Travel Insurance']}>
            <Snap src={readyToFly} caption="Ready to fly!" at={{ top: '-18px', left: '1%' }} rotate={-6} />
            <Note at={{ top: '34px', right: '0%' }} rotate={5} icon="plane">Safer journeys, together</Note>
            <Trail at={{ top: '86px', right: '6%' }} width={170} flip />
          </Stub>

          <Stop n={1} mark={MARK.companion} title="Travel Companion" link={['Explore Travel Companion', site.companionUrl]}
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

          <Stop rev n={2} mark={MARK.insurance} title="Travel Insurance" link={['Explore Travel Insurance', site.insuranceUrl]}
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

          <Stop n={3} mark={MARK.doctor} title="Virtual Doctor Consultation" link={['Book a Consultation', site.doctorUrl]}
            text="Video consultations with a doctor from home. You can join the call from abroad.">
            {/* the Call-ON-Doc page's own pictures: its hero, and its call screen in front of it */}
            <div className="o3 vd3">
              <div className="vd-photo"><img src={docHero} alt="" loading="lazy" decoding="async" /></div>
              <div className="vd-phone"><img src={docScreen} alt="" loading="lazy" decoding="async" /></div>
              <Chip cls="c1" title="Prescription shared" sub="Sent to you on WhatsApp" />
            </div>
          </Stop>

          <Stop rev n={4} mark={MARK.sahayak} title="Sahayak" primary link={['Book a Sahayak', site.sahayakUrl]}
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

          <Stop n={5} mark={MARK.gift} title="Gift Health" link={['Explore Gift Health', site.giftUrl]} objClass="tall"
            text="Give your parents the gift of better health, care and proactive support — even from miles away.">
            <div className="o3 gb3">
              <div className="cube"><div className="in" /><div className="face b" /><div className="face l" /><div className="face r" /><div className="face f" /></div>
              <div className="voucher"><span>Gift Health</span><b>A health checkup for Amma</b><small>With love, from Toronto</small></div>
              <div className="lid"><div className="top" /><div className="face b" /><div className="face l" /><div className="face r" /><div className="face f" /><div className="bow" /></div>
              <Chip cls="c1" icon="heart" stroke={2.4} title="Sent from abroad" sub="Received at home in India" />
            </div>
          </Stop>

          <Stop rev n={6} mark={MARK.fit} title="Fit2Fly" link={['Explore Fit2Fly', site.fitUrl]} objClass="tall"
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
            <span className="pin-pt" data-pt style={{ '--c': ARRIVED }}><Icon name="pin" className="" />Arrived <small>· Your parents, cared for</small></span>
          </div>
        </div>
      </div>
    </section>
  );
}
