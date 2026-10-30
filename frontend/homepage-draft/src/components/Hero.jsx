import { Fragment, useEffect, useRef, useState } from 'react';
import Bg from './Bg.jsx';
import { Doodles, Note, Trail } from './Deco.jsx';
import Icon from './Icon.jsx';
import { site, talk, TALK } from '../data/site.js';
import { reduceMotion } from '../hooks.js';
import heroBg from '../assets/photos/tc-l2.jpg';
import parents from '../assets/photos/parents-centre.jpg';
import imgCompanion from '../assets/photos/why-travel.jpg';
import imgInsurance from '../assets/photos/hero-travel.jpg';
import imgDoctor from '../assets/photos/doctor-consultation.jpg';
import imgSahayak from '../assets/photos/why-local.jpg';
import imgGift from '../assets/photos/cta-care.jpg';
import imgFit from '../assets/photos/health-hero.jpg';

/* The hero is the care circle, with the words of nri-parent-service-homepage.html's hero beside it:
 * the six services turn slowly around the parents on the right; on the left, the original hero's
 * three messages -- Parent Care, Travel, Health & Wellness, each with its handwritten line, label,
 * headline and text -- follow the service in front, whose photo, words and button sit under them.
 * The service in front moves on by itself every few seconds; a pointer on a service picks it at
 * once (and holds it while it rests on the circle or the details), as does a tap, the keyboard,
 * the original hero's labelled buttons or its arrows. Pause stops the moving on for good, and
 * nothing moves for anybody whose device asks for less motion. */

const NEXT_MS = 5000;

// the original hero's three slides, word for word; `first` is the service its button jumps to
const GROUPS = {
  Care: { label: 'Parent Care', first: 3, tagline: 'Miles apart, never out of reach.', pill: 'Parent Care in India',
          title: 'Your Parents Are in India. Their Care Is With Us.',
          text: 'Trusted support for your parents, even when you’re miles away.' },
  Travel: { label: 'Travel', first: 0, tagline: 'Worry-free travel for your loved ones.', pill: 'Travel Insurance & Travel Companion',
            title: 'When Your Parents Travel, They Don’t Have to Travel Alone.',
            text: 'From travel preparation to companionship, we help make every journey safer and more comfortable.' },
  Health: { label: 'Health & Wellness', first: 4, tagline: 'Care that keeps them well.', pill: 'Health & Wellness',
            title: 'Because Their Health Matters, Wherever You Are.',
            text: 'Reliable health, wellness and everyday support for your parents in India.' },
};
const GROUP_ORDER = ['Care', 'Travel', 'Health'];

/* the headline's words rise in one after another, as on the original hero */
function Words({ text }) {
  return text.split(' ').map((w, i) => (
    <Fragment key={i}><span className="w" style={{ '--d': `${120 + i * 55}ms` }}><span>{w}</span></span>{' '}</Fragment>
  ));
}

const SERVICES = [
  { key: 'companion', color: '#2446B8', icon: 'plane', img: imgCompanion, pos: '55% 35%', title: 'Travel Companion', group: 'Travel',
    text: 'Trusted assistance for elderly parents who need support before, during or after their journey.',
    cta: 'Explore Travel Companion', href: site.companionUrl },
  { key: 'insurance', color: '#0F9D8C', icon: 'shield', img: imgInsurance, pos: '50% 35%', title: 'Travel Insurance', group: 'Travel',
    text: 'Protect your parents with travel insurance designed to support them throughout their journey.',
    cta: 'Explore Travel Insurance', href: site.insuranceUrl },
  { key: 'doctor', color: '#5B4BD6', icon: 'steth', img: imgDoctor, pos: '33% 30%', title: 'Virtual Doctor', group: 'Care',
    text: 'Video consultations with a doctor from home. You can join the call from abroad.',
    cta: 'Book a Consultation', href: site.contactUrl },
  { key: 'sahayak', color: '#E4613F', icon: 'home', img: imgSahayak, pos: '45% 35%', title: 'Sahayak', group: 'Care',
    text: 'A trusted helping hand for hospital visits, doctor appointments, healthcare needs and everyday assistance.',
    cta: 'Book a Sahayak', href: site.sahayakUrl },
  { key: 'gift', color: '#C98A12', icon: 'gift', img: imgGift, pos: '30% 40%', title: 'Gift Health', group: 'Health',
    text: 'Give your parents the gift of better health, care and proactive support — even from miles away.',
    cta: 'Ask about Gift Health', href: site.contactUrl },
  { key: 'fit', color: '#14946E', icon: 'clip', img: imgFit, pos: '62% 40%', title: 'Fit2Fly', group: 'Health',
    text: 'Prepare your parents for safe and confident travel with the right health assessment before their journey.',
    cta: 'Ask about Fit2Fly', href: site.contactUrl },
];

export default function Hero() {
  const [cur, setCur] = useState(GROUPS.Care.first);       // it opens on Parent Care, as the original did
  const [held, setHeld] = useState(false);          // a pointer or the keyboard is on the circle or the details
  const [stopped, setStopped] = useState(false);    // the pause button
  const timer = useRef(null);
  const s = SERVICES[cur];
  const g = GROUPS[s.group];
  const step = 360 / SERVICES.length;
  const go = (i) => setCur((i + SERVICES.length) % SERVICES.length);
  const moving = !held && !stopped && !reduceMotion();

  useEffect(() => {
    if (!moving) return undefined;
    timer.current = setTimeout(() => { if (!document.hidden) setCur((c) => (c + 1) % SERVICES.length); }, NEXT_MS);
    return () => clearTimeout(timer.current);
  }, [cur, moving]);

  const hold = {
    onMouseEnter: () => setHeld(true),
    onMouseLeave: () => setHeld(false),
    onFocus: () => setHeld(true),
    onBlur: (e) => { if (!e.currentTarget.contains(e.relatedTarget)) setHeld(false); },
  };

  return (
    <section className="hero2" id="hero" aria-label="Featured services">
      <h1 className="sr">Trusted Parent Care Services for NRIs in India</h1>
      <Bg src={heroBg} pos="62% center" eager />
      <Trail at={{ top: '40px', left: 'calc(50% - 60px)' }} width={200} tone="amber" />
      <Doodles items={[['plane', { top: '12%', left: '2.5%', size: 26, rotate: -14, opacity: 0.3 }],
        ['heart', { bottom: '16%', left: '46%', size: 22, rotate: -10, opacity: 0.3 }],
        ['globe', { top: '10%', right: '3%', size: 28, rotate: 8, opacity: 0.3 }]]} />
      <Note at={{ bottom: '30px', left: 'max(40px, calc(50% - 580px))' }} rotate={-3} icon="heart">Safer journeys, together</Note>

      <div className="wrap hero2-grid">
        <div className="hero2-copy">
          <div className="hmsg" key={s.group}>
            <span className="tagline">{g.tagline}</span>
            <span className="pill hpill">{g.pill}</span>
            <p className="hx">{reduceMotion() ? g.title : <Words text={g.title} />}</p>
            <p className="s-p">{g.text}</p>
          </div>

          <article className="hsvc" id="hero-svc" style={{ '--c': s.color }} key={s.key} {...hold}>
            <div className="hsvc-ph"><img src={s.img} alt="" style={{ objectPosition: s.pos }} /></div>
            <div className="hsvc-b">
              <span className="pill"><Icon name={s.icon} />{s.group}</span>
              <h2>{s.title}</h2>
              <p>{s.text}</p>
            </div>
            <span className="hsvc-bar" aria-hidden="true"><i className={moving ? 'run' : ''} /></span>
          </article>

          <div className="s-ctas">
            <a className="btn btn-hero" href={site.contactUrl} onClick={talk}>{TALK}</a>
            <a className="btn btn-ghost" href={s.href}>{s.cta}</a>
          </div>
          {/* the original hero's controls: a labelled button per message, and arrows */}
          <div className="hctrl">
            <div className="hdots">
              {GROUP_ORDER.map((k) => (
                <button type="button" key={k} className={s.group === k ? 'on' : ''} aria-current={s.group === k}
                  aria-label={`Show ${GROUPS[k].label}`} onClick={() => setCur(GROUPS[k].first)}>
                  <i /><span>{GROUPS[k].label}</span>
                </button>
              ))}
            </div>
            <div className="harrows">
              <button type="button" className="harr" aria-label="Previous service" onClick={() => go(cur - 1)}><Icon name="left" /></button>
              <button type="button" className="harr" aria-label="Next service" onClick={() => go(cur + 1)}><Icon name="right" /></button>
              <button type="button" className="hsvc-stop" onClick={() => setStopped((v) => !v)} aria-pressed={stopped}>
                {stopped ? 'Play' : 'Pause'}
              </button>
            </div>
          </div>
        </div>

        <div className="orbit" role="group" aria-label="Our services — point at one to read about it" {...hold}>
          <div className="orb-ring">
            <svg className="orb-lines" viewBox="-300 -300 600 600" aria-hidden="true">
              <circle r="210" className="orb-track" />
              <g className="orb-spin">
                {SERVICES.map((sv, i) => {
                  const a = (i * step * Math.PI) / 180;
                  return <line key={sv.key} x1="0" y1="0" x2={210 * Math.sin(a)} y2={-210 * Math.cos(a)}
                    className={i === cur ? 'on' : ''} style={{ stroke: i === cur ? sv.color : undefined }} />;
                })}
              </g>
            </svg>
            {SERVICES.map((sv, i) => (
              <div className="orb-slot" key={sv.key} style={{ '--a': `${i * step}deg` }}>
                <button type="button" className={`orb-item${i === cur ? ' on' : ''}`} style={{ '--c': sv.color }}
                  aria-pressed={i === cur} aria-controls="hero-svc" onClick={() => setCur(i)}
                  onMouseEnter={() => setCur(i)} onFocus={() => setCur(i)}>
                  <span className="orb-ph"><img src={sv.img} alt="" style={{ objectPosition: sv.pos }} decoding="async" /></span>
                  <span className="orb-ic"><Icon name={sv.icon} /></span>
                  <span className="orb-name">{sv.title}</span>
                </button>
              </div>
            ))}
          </div>
          <div className="orb-centre">
            <span className="orb-pulse" aria-hidden="true" />
            <img src={parents} alt="" decoding="async" />
            <span className="orb-label"><Icon name="heart" />Your Parents</span>
          </div>
        </div>
      </div>
    </section>
  );
}
