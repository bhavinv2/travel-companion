import { useEffect, useRef, useState } from 'react';
import Bg from './Bg.jsx';
import { Doodles, Note, Trail } from './Deco.jsx';
import Icon from './Icon.jsx';
import { site, talk, TALK } from '../data/site.js';
import { reduceMotion } from '../hooks.js';
import mapBg from '../assets/photos/ins-world-map.jpg';
import parents from '../assets/photos/parents-centre.jpg';
import imgCompanion from '../assets/photos/why-travel.jpg';
import imgInsurance from '../assets/photos/hero-travel.jpg';
import imgDoctor from '../assets/photos/doctor-consultation.jpg';
import imgSahayak from '../assets/photos/why-local.jpg';
import imgGift from '../assets/photos/cta-care.jpg';
import imgFit from '../assets/photos/health-hero.jpg';

/* The hero is the care circle. On the left, one promise -- "Your Parents Are in India. Their Care
 * Is With Us." -- a short panel about the service in front, and the six services as a legend. On
 * the right, the six turning slowly around the parents, on a soft glow of the front one's colour.
 * The front service moves on by itself every few seconds; a pointer on its photo in the circle or
 * its name in the legend brings it forward at once and holds it there while the pointer rests on
 * the hero's circle, panel or legend (a tap or the keyboard picks too). Nothing moves for anybody
 * whose device asks for less motion. */

const NEXT_MS = 4500;

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
  const [cur, setCur] = useState(3);                 // it opens on Sahayak: care at their door
  const [held, setHeld] = useState(false);
  const timer = useRef(null);
  const s = SERVICES[cur];
  const step = 360 / SERVICES.length;
  const moving = !held && !reduceMotion();

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
  const pick = (i) => ({ onMouseEnter: () => setCur(i), onFocus: () => setCur(i), onClick: () => setCur(i) });

  return (
    <section className="hero3" id="hero" aria-labelledby="hero-h" style={{ '--c': s.color }}>
      <Bg src={mapBg} pos="center" eager />
      <span className="hero3-glow" aria-hidden="true" />
      <Trail at={{ top: '36px', left: 'calc(50% - 40px)' }} width={190} tone="amber" />
      <Doodles items={[['plane', { top: '10%', left: '2.5%', size: 26, rotate: -14, opacity: 0.3 }],
        ['heart', { bottom: '12%', left: '47%', size: 22, rotate: -10, opacity: 0.3 }],
        ['globe', { top: '8%', right: '3%', size: 28, rotate: 8, opacity: 0.3 }]]} />
      <Note at={{ bottom: '26px', left: 'max(40px, calc(50% - 580px))' }} rotate={-3} icon="heart">Safer journeys, together</Note>

      <div className="wrap hero3-grid" {...hold}>
        <div className="hero3-copy">
          <span className="tagline">Miles apart, never out of reach.</span>
          <h1 className="hx" id="hero-h">Your Parents Are in India. <em>Their Care Is With Us.</em></h1>

          <div className="hnow" key={s.key} aria-live="off">
            <span className="hnow-k"><Icon name={s.icon} />{s.group}</span>
            <b>{s.title}</b>
            <p>{s.text}</p>
            <span className="hnow-bar" aria-hidden="true"><i className={moving ? 'run' : ''} /></span>
          </div>

          <ul className="hlegend" aria-label="Our services">
            {SERVICES.map((sv, i) => (
              <li key={sv.key}>
                <button type="button" className={i === cur ? 'on' : ''} style={{ '--c': sv.color }}
                  aria-pressed={i === cur} {...pick(i)}>
                  <i aria-hidden="true" />{sv.title}
                </button>
              </li>
            ))}
          </ul>

          <div className="s-ctas">
            <a className="btn btn-hero" href={site.contactUrl} onClick={talk}>{TALK}</a>
            <a className="btn btn-ghost" href={s.href}>{s.cta}</a>
          </div>
        </div>

        <div className="hero3-circle">
          <div className="orbit" role="group" aria-label="Our services around your parents">
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
                    aria-pressed={i === cur} tabIndex={-1} {...pick(i)}>
                    <span className="orb-ph"><img src={sv.img} alt="" style={{ objectPosition: sv.pos }} decoding="async" /></span>
                    <span className="orb-ic"><Icon name={sv.icon} /></span>
                    <span className="orb-name">{sv.title}</span>
                  </button>
                </div>
              ))}
            </div>
            <div className="orb-centre">
              <span className="orb-pulse" aria-hidden="true" />
              <img src={parents} alt="An elderly Indian couple smiling at home" decoding="async" />
              <span className="orb-label"><Icon name="heart" />Your Parents</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
