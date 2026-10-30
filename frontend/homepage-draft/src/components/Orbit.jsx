import { useState } from 'react';
import Icon from './Icon.jsx';
import { site } from '../data/site.js';
import { useReveal } from '../hooks.js';
import parents from '../assets/photos/parents-centre.jpg';
import imgCompanion from '../assets/photos/why-travel.jpg';
import imgInsurance from '../assets/photos/hero-travel.jpg';
import imgDoctor from '../assets/photos/doctor-consultation.jpg';
import imgSahayak from '../assets/photos/why-local.jpg';
import imgGift from '../assets/photos/cta-care.jpg';
import imgFit from '../assets/photos/health-hero.jpg';

/* "Everything revolves around your parents": the six services, each in its own photo circle,
 * orbiting a centre circle of the parents. The ring turns slowly (CSS), each circle counter-
 * turns so it stays upright, and the orbit stops while a pointer or keyboard focus is on it.
 * Picking a service fills the card beside it.
 *
 * The photos are placeholders from the page's own set until the dedicated ones arrive; each is
 * one import to change. `pos` is where the subject sits in that photo, for the circle crop. */
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

export default function Orbit() {
  const head = useReveal();
  const body = useReveal(0.1);
  const [cur, setCur] = useState(0);
  const s = SERVICES[cur];
  const step = 360 / SERVICES.length;

  return (
    <section className="sec orb-sec" aria-labelledby="orb-h">
      <div className="wrap">
        <div className="p2-head rv-up" ref={head}>
          <span className="kick">Our care circle</span>
          <h2 className="h2" id="orb-h">Everything Revolves Around <em>Your Parents</em></h2>
          <span className="script-tag st-amber">Six ways we care.</span>
        </div>

        <div className="orb-body rv-up" ref={body}>
          <div className="orbit" role="group" aria-label="Our services — pick one to read about it">
            <div className="orb-ring">
              <svg className="orb-lines" viewBox="-300 -300 600 600" aria-hidden="true">
                <circle r="210" className="orb-track" />
                {SERVICES.map((sv, i) => {
                  const a = (i * step * Math.PI) / 180;
                  return <line key={sv.key} x1="0" y1="0" x2={210 * Math.sin(a)} y2={-210 * Math.cos(a)}
                    className={i === cur ? 'on' : ''} style={{ stroke: i === cur ? sv.color : undefined }} />;
                })}
              </svg>
              {SERVICES.map((sv, i) => (
                <div className="orb-slot" key={sv.key} style={{ '--a': `${i * step}deg` }}>
                  <button type="button" className={`orb-item${i === cur ? ' on' : ''}`} style={{ '--c': sv.color }}
                    aria-pressed={i === cur} aria-controls="orb-card" onClick={() => setCur(i)}
                    onMouseEnter={() => setCur(i)} onFocus={() => setCur(i)}>
                    <span className="orb-ph"><img src={sv.img} alt="" style={{ objectPosition: sv.pos }} loading="lazy" decoding="async" /></span>
                    <span className="orb-ic"><Icon name={sv.icon} /></span>
                    <span className="orb-name">{sv.title}</span>
                  </button>
                </div>
              ))}
            </div>
            <div className="orb-centre">
              <span className="orb-pulse" aria-hidden="true" />
              <img src={parents} alt="" loading="lazy" decoding="async" />
              <span className="orb-label"><Icon name="heart" />Your Parents</span>
            </div>
          </div>

          <article className="orb-card" id="orb-card" aria-live="polite" style={{ '--c': s.color }} key={s.key}>
            <div className="orb-card-ph"><img src={s.img} alt="" style={{ objectPosition: s.pos }} /></div>
            <div className="orb-card-b">
              <span className="orb-tag"><Icon name={s.icon} />{s.group}</span>
              <h3>{s.title}</h3>
              <p>{s.text}</p>
              <a className="btn orb-cta" href={s.href}>{s.cta}<Icon name="arrow" /></a>
              <div className="orb-dots" aria-hidden="true">
                {SERVICES.map((sv, i) => <i key={sv.key} className={i === cur ? 'on' : ''} style={{ '--c': sv.color }} />)}
              </div>
            </div>
          </article>
        </div>
      </div>
    </section>
  );
}
