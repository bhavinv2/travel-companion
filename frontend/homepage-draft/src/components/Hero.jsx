import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import { site, talk, TALK } from '../data/site.js';
import { reduceMotion, useReveal } from '../hooks.js';
import parentCare from '../assets/photos/hero-parent-care.jpg';
import travel from '../assets/photos/tc-l2.jpg';
import insurance from '../assets/photos/ins-hero-banner.jpg';
import health from '../assets/photos/health-hero.jpg';
import pickCompanion from '../assets/photos/ins-story-families.jpg';
import pickInsurance from '../assets/photos/ins-world-map.jpg';
import pickSahayak from '../assets/photos/sah-finder-care.jpg';
import logoMark from '../assets/logo-mark.png';

const AUTOPLAY_MS = 6000;           // long enough to read a headline before it changes

const SLIDES = [
  {
    key: 'care', full: true, img: parentCare, pos: 'center 30%',
    alt: 'A Sahayak smiling beside an elderly mother at her home in India',
    tagline: 'Miles apart, never out of reach.', pill: 'Parent Care in India',
    title: 'Your Parents Are in India. Their Care Is With Us.',
    text: 'A registered nurse at their door, help at every hospital visit, and updates for you wherever you are.',
    cta: 'Explore Sahayak', href: '#sahayak',
  },
  {
    key: 'travel', full: true, img: travel, pos: '62% center',
    alt: 'An elderly Indian couple with their luggage at the airport at sunset, ready to fly',
    tagline: 'Safer journeys, together.', pill: 'Travel Companion',
    title: 'When Your Parents Travel, They Don’t Have to Travel Alone.',
    text: 'A fellow traveller on the same flight, who speaks their language, from check-in to arrival.',
    cta: 'Explore Travel Companion', href: '#companion',
  },
  {
    key: 'insurance', full: true, img: insurance, pos: '70% center',
    alt: 'An Indian family with their luggage at the airport, about to travel',
    tagline: 'Covered every corner.', pill: 'Travel Insurance',
    title: 'When Parents Fly Out to See You, Keep Them Covered.',
    text: 'Compare 65+ A-rated visitor insurance plans, with help choosing the right one for them.',
    cta: 'Explore Travel Insurance', href: '#insurance',
  },
  {
    key: 'health', full: true, img: health, pos: '100% center',
    alt: 'A Sahayak checking an elderly father’s blood pressure at home in India',
    tagline: 'Care that keeps them well.', pill: 'Health & Wellness',
    title: 'Because Their Health Matters, Wherever You Are.',
    text: 'Doctor consultations, health checks and pre-travel assessments, arranged from abroad.',
    cta: 'Explore Health & Wellness', href: '#health',
  },
];

/* Under the hero, one card per service with its own photo and its own first step -- the way the
 * travel-insurance and companion pages open with their quote and search cards. */
const PICKS = [
  { key: 'companion', img: pickCompanion, title: 'Travel Companion', href: site.companionUrl, cta: 'Find a Companion',
    text: 'Someone beside them on the flight, who speaks their language.' },
  { key: 'insurance', img: pickInsurance, title: 'Travel Insurance', href: site.insuranceUrl, cta: 'Get a Free Quote',
    text: 'Visitor insurance for parents coming to see you.', price: () => site.prices.insurance },
  { key: 'sahayak', img: pickSahayak, title: 'Sahayak', href: site.sahayakUrl, cta: 'Book a Sahayak',
    text: 'A registered nurse with them for checkups, tests and hospital visits.',
    price: () => site.prices.sahayak && `From ${site.prices.sahayak}` },
];

export function Picks() {
  const ref = useReveal(0.1);
  return (
    <div className="picks-wrap">
      <div className="wrap">
        <div className="picks rv-stagger" ref={ref}>
          {PICKS.map((p, i) => {
            const price = p.price && p.price();
            return (
              <a className={`pick pick-${p.key}`} href={p.href} key={p.key} style={{ '--d': `${i * 90}ms` }}>
                <img src={p.img} alt="" loading="eager" decoding="async" />
                <span className="pick-b">
                  <b>{p.title}</b>
                  <small>{p.text}</small>
                  <span className="pick-go">{p.cta}{price && <em>{price}</em>}</span>
                </span>
              </a>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* Splits a headline into words so each can rise in on its own delay. */
function Words({ text }) {
  return text.split(' ').map((w, i) => (
    <Fragment key={i}><span className="w" style={{ '--d': `${120 + i * 55}ms` }}><span>{w}</span></span>{' '}</Fragment>
  ));
}

export default function Hero() {
  const [cur, setCur] = useState(0);
  const [paused, setPaused] = useState(false);
  const timer = useRef(null);
  const touch = useRef(null);

  const go = useCallback((i) => setCur((i + SLIDES.length) % SLIDES.length), []);

  // Advances on its own and keeps going under the mouse; it only holds while a keyboard user
  // has focus on one of the slide's buttons, so the button doesn't slide away mid-Tab.
  useEffect(() => {
    if (reduceMotion() || paused) return;
    timer.current = setTimeout(() => { if (!document.hidden) go(cur + 1); }, AUTOPLAY_MS);
    return () => clearTimeout(timer.current);
  }, [cur, paused, go]);

  return (
    <section
      className="hero" id="hero" aria-roledescription="carousel" aria-label="Featured services"
      onFocus={() => setPaused(true)} onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setPaused(false); }}
      onKeyDown={(e) => {
        if (e.key === 'ArrowLeft') go(cur - 1);
        if (e.key === 'ArrowRight') go(cur + 1);
      }}
      onTouchStart={(e) => { touch.current = [e.touches[0].clientX, e.touches[0].clientY]; }}
      onTouchEnd={(e) => {
        if (!touch.current) return;
        const dx = e.changedTouches[0].clientX - touch.current[0];
        const dy = e.changedTouches[0].clientY - touch.current[1];
        if (Math.abs(dx) > 45 && Math.abs(dx) > Math.abs(dy)) go(cur + (dx < 0 ? 1 : -1));
        touch.current = null;
      }}
    >
      <div className="slides">
        {SLIDES.map((s, n) => {
          const on = n === cur;
          // the first slide's headline is the page's heading -- what it says, it is about
          const Head = n === 0 ? 'h1' : 'p';
          return (
            <div key={s.key} className={`slide${s.full ? ' full' : ''}${on ? ' on' : ''}`} aria-hidden={!on} role="group"
              aria-roledescription="slide" aria-label={`${n + 1} of ${SLIDES.length}`}>
              <div className={`bg${s.narrow ? ' narrow' : ''}`}>
                <img src={s.img} alt={s.alt} style={{ objectPosition: s.pos }} decoding="async"
                  loading="eager" />
              </div>
              <div className="wrap">
                <div className="copy">
                  <span className="tagline">{s.tagline}</span>
                  <span className="pill">{s.pill}</span>
                  <Head className="hx">{on ? <Words text={s.title} /> : s.title}</Head>
                  <p className="s-p">{s.text}</p>
                  {/* the page's one main action first, the same on every slide; the slide's
                      own service second */}
                  <div className="s-ctas">
                    <a className="btn btn-hero" href={site.contactUrl} onClick={talk} tabIndex={on ? 0 : -1}>
                      {TALK}
                    </a>
                    <a className="btn btn-ghost" href={s.href} tabIndex={on ? 0 : -1}>{s.cta}</a>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* the travel-insurance banner's brand badge, same mark and lockup */}
      <div className="hero-badge" aria-hidden="true">
        <img src={logoMark} alt="" width={200} height={161} />
        <span className="hero-badge-tx">
          <b>NRI</b>
          <b className="hb-blue">Parent Service</b>
          <span>Your Parents, Our Priority</span>
        </span>
      </div>

    </section>
  );
}
