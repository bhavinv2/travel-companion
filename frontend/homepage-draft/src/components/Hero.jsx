import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import Icon from './Icon.jsx';
import { site } from '../data/site.js';
import { reduceMotion } from '../hooks.js';
import parentCare from '../assets/photos/hero-parent-care.jpg';
import travel from '../assets/photos/hero-travel.jpg';
import health from '../assets/photos/health-hero.jpg';
import logoMark from '../assets/logo-mark.png';

const AUTOPLAY_MS = 3000;

const SLIDES = [
  {
    key: 'care', full: true, img: parentCare, pos: 'center 30%',
    alt: 'A Sahayak smiling beside an elderly mother at her home in India',
    tagline: 'Miles apart, never out of reach.', pill: 'Parent Care in India', icon: 'heart',
    title: 'Your Parents Are in India. Their Care Is With Us.',
    text: 'Trusted support for your parents, even when you’re miles away.',
    cta: 'Explore Parent Care', href: '#ch-care',
  },
  {
    key: 'travel', img: travel, pos: 'center 35%',
    alt: 'A smiling elderly Indian couple with their luggage at the airport, ready to travel',
    tagline: 'Worry-free travel for your loved ones.', pill: 'Travel Insurance & Travel Companion', icon: 'plane',
    title: 'When Your Parents Travel, They Don’t Have to Travel Alone.',
    text: 'From travel preparation to companionship, we help make every journey safer and more comfortable.',
    cta: 'Explore Travel Support', href: '#ch-travel',
  },
  {
    key: 'health', full: true, img: health, pos: '100% center',
    alt: 'A Sahayak checking an elderly father’s blood pressure at home in India',
    tagline: 'Care that keeps them well.', pill: 'Health & Wellness', icon: 'health',
    title: 'Because Their Health Matters, Wherever You Are.',
    text: 'Reliable health, wellness and everyday support for your parents in India.',
    cta: 'Explore Health & Wellness', href: '#ch-health',
  },
];

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
      <h1 className="sr">Trusted Parent Care Services for NRIs in India</h1>
      <div className="slides">
        {SLIDES.map((s, n) => {
          const on = n === cur;
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
                  <span className="pill"><Icon name={s.icon} />{s.pill}</span>
                  <p className="hx">{on ? <Words text={s.title} /> : s.title}</p>
                  <p className="s-p">{s.text}</p>
                  <div className="s-ctas">
                    <a className="btn btn-hero" href={s.href} tabIndex={on ? 0 : -1}>
                      {s.cta}<Icon name="arrow" />
                    </a>
                    <a className="btn btn-ghost" href={site.contactUrl} tabIndex={on ? 0 : -1}>Talk to Us</a>
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
