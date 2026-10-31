import { useEffect, useRef, useState } from 'react';
import { Doodles, Side, Trail } from './Deco.jsx';
import Icon from './Icon.jsx';
import { away, site, talk, TALK } from '../data/site.js';
import { MARK } from '../data/services.js';
import { reduceMotion } from '../hooks.js';
import parents from '../assets/photos/parents-centre.jpg';
import imgCompanion from '../assets/photos/why-travel.jpg';
import imgInsurance from '../assets/photos/hero-travel.jpg';
import imgDoctor from '../assets/photos/doctor-consultation.jpg';
import imgSahayak from '../assets/photos/why-local.jpg';
import imgGift from '../assets/photos/cta-care.jpg';
import imgFit from '../assets/photos/health-hero.jpg';
import landmarks from '../assets/photos/landmarks.webp';

/* The hero: light and calm, no photo behind it. On the left, the promise -- "Your Parents Are in
 * India. Their Care Is With Us." -- one line about what we do, the two buttons and the six services'
 * marks in a row. On the right, the
 * care circle: the six services turning slowly around the parents, two small status cards
 * floating in its top corners (the names hang under the photos, so the bottom ones stay clear), and under it a card about the service in front. That one moves on by itself
 * every few seconds; pointing at a photo in the circle brings it forward at once and holds it while
 * the pointer rests on the circle or the card (a tap or the keyboard picks too). Nothing moves for
 * anybody whose device asks for less motion. */

const NEXT_MS = 4500;

const SERVICES = [
  { ...MARK.companion, img: imgCompanion, pos: '55% 35%', group: 'Travel',
    text: 'Trusted assistance for elderly parents who need support before, during or after their journey.',
    cta: 'Explore Travel Companion', href: site.companionUrl },
  { ...MARK.insurance, img: imgInsurance, pos: '50% 35%', group: 'Travel',
    text: 'Protect your parents with travel insurance designed to support them throughout their journey.',
    cta: 'Explore Travel Insurance', href: site.insuranceUrl },
  { ...MARK.doctor, img: imgDoctor, pos: '33% 30%', group: 'Care',
    text: 'Video consultations with a doctor from home. You can join the call from abroad.',
    cta: 'Book a Consultation', href: site.doctorUrl },
  { ...MARK.sahayak, img: imgSahayak, pos: '45% 35%', group: 'Care',
    text: 'A trusted helping hand for hospital visits, doctor appointments, healthcare needs and everyday assistance.',
    cta: 'Book a Sahayak', href: site.sahayakUrl },
  { ...MARK.gift, img: imgGift, pos: '30% 40%', group: 'Health',
    text: 'Give your parents the gift of better health, care and proactive support — even from miles away.',
    cta: 'Explore Gift Health', href: site.giftUrl },
  { ...MARK.fit, img: imgFit, pos: '62% 40%', group: 'Health',
    text: 'Prepare your parents for safe and confident travel with the right health assessment before their journey.',
    cta: 'Explore Fit2Fly', href: site.fitUrl },
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

  return (
    <section className="hero4" id="hero" aria-labelledby="hero-h">
      <Side img={landmarks} shape="art" top="26%" icons={[['plane', MARK.companion.color], ['heart', '#E4613F'],
        ['home', MARK.sahayak.color], ['video', MARK.doctor.color]]} />
      <Doodles items={[
        ['heart', { bottom: '10%', left: '44%', size: 22, rotate: -10, opacity: 0.2 }],
        ['pin', { bottom: '6%', right: '2%', size: 26, rotate: 10, opacity: 0.18 }]]} />
      <Trail at={{ bottom: '24px', left: 'max(40px, calc(50% - 580px))' }} width={170} tone="amber" />

      <div className="wrap hero4-grid">
        <div className="hero4-copy">
          <span className="tagline">Miles apart, never out of reach.</span>
          <h1 className="h4x" id="hero-h">Your Parents Are in India. <em>Their Care Is With Us.</em></h1>
          <p className="h4-lede">A companion on their flight, cover for the unexpected, a doctor on video and a trusted
            helping hand at their door, all arranged from wherever you are.</p>
          <div className="s-ctas">
            <a className="btn btn-p" href={site.contactUrl} onClick={talk}>{TALK}</a>
            <a className="btn btn-o" href="#services">See How We Help</a>
          </div>
          <div className="h4-trust">
            <span className="h4-marks" aria-hidden="true">
              {SERVICES.map((sv) => <i key={sv.key} style={{ '--c': sv.color }}><Icon name={sv.icon} /></i>)}
            </span>
            <span><b>Six services, one team</b><small>Updates on WhatsApp at every step</small></span>
          </div>
        </div>

        <div className="hero4-art" {...hold}>
          <div className="h4-stage">
            <span className="h4-chip c1" aria-hidden="true"><i><Icon name="check" stroke={3} className="" /></i>
              <span><b>Sahayak reached home</b><small>Today, 10:30 AM</small></span></span>
            <span className="h4-chip c2" aria-hidden="true"><i><Icon name="video" stroke={2.2} className="" /></i>
              <span><b>Doctor's video call</b><small>You can join from abroad</small></span></span>

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
                <img src={parents} alt="An elderly Indian couple smiling at home" decoding="async" />
                <span className="orb-label"><Icon name="heart" />Your Parents</span>
              </div>
            </div>
          </div>

          <a className="h4-card" id="hero-svc" href={s.href} key={s.key} style={{ '--c': s.color }} {...away(s.href)}>
            <img src={s.img} alt="" style={{ objectPosition: s.pos }} />
            <span className="h4-card-b">
              <small><Icon name={s.icon} />{s.group}</small>
              <b>{s.title}<span className="h4-card-go" title={s.cta}><Icon name="arrow" /></span></b>
              <span>{s.text}</span>
            </span>
            <span className="h4-bar" aria-hidden="true"><i className={moving ? 'run' : ''} /></span>
          </a>
        </div>
      </div>
    </section>
  );
}
