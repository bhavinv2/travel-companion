import { useEffect, useState } from 'react';
import Icon from './Icon';
import SideDecor from './SideDecor';
import { useQuote } from '../context/QuoteContext';
import { useReveal } from '../hooks/useReveal';
import { photo } from '../data/site';

const CARDS: Array<{ title: string; desc: string; tone: string }> = [
  { title: 'Medical Emergency Coverage', desc: 'Eligible treatment and hospital costs.', tone: 'blue' },
  { title: 'Emergency Assistance', desc: 'A helpline when something goes wrong.', tone: 'green' },
  { title: 'Hospital & Doctor Support', desc: 'Guidance to find care nearby.', tone: 'amber' },
  { title: 'Travel Protection', desc: 'Cover for eligible trip disruptions.', tone: 'rose' },
];

// Add more photos here later — the carousel and dots activate automatically once there's more than one.
const VISITOR_SLIDES = [
  { src: photo('visitor-main.jpg'), alt: 'Family spending time together at home during a visit abroad' },
  { src: photo('visitor-2.png'), alt: 'Indian parents sharing tea with their daughter at home, luggage packed by the door' },
  { src: photo('visitor-3.png'), alt: 'Indian grandparents walking with their granddaughter beside the Thames in London' },
];

const MAP_PINS = [
  { name: 'USA', left: '19%', top: '46%' },
  { name: 'Canada', left: '21%', top: '25%' },
  { name: 'India', left: '68%', top: '54%' },
  { name: 'Schengen', left: '46%', top: '37%' },
];

export default function VisitorInsurance() {
  const { openQuote } = useQuote();
  const reveal = useReveal<HTMLDivElement>();
  const [slide, setSlide] = useState(0);

  useEffect(() => {
    if (VISITOR_SLIDES.length < 2) return;
    const t = setInterval(() => setSlide((s) => (s + 1) % VISITOR_SLIDES.length), 4000);
    return () => clearInterval(t);
  }, []);

  return (
    <section className="sec" id="visitor" style={{ background: 'var(--cloud)' }}>
      <SideDecor icons={[
        { name: 'i-heart', side: 'left', top: '18%', size: 30, rotate: -8, opacity: 0.14 },
        { name: 'i-plane', side: 'left', top: '70%', size: 100, rotate: -18, opacity: 0.06 },
        { name: 'i-passport', side: 'right', top: '62%', size: 32, rotate: 6, opacity: 0.14 },
        { name: 'i-globe', side: 'right', top: '10%', size: 90, rotate: 10, opacity: 0.06 },
      ]} />
      <div className={`wrap split vsplit z1 ${reveal.className}`} ref={reveal.ref as any}>
        <div className="vcluster">
          <span className="vglow" aria-hidden="true" />
          <span className="script-tag" style={{ position: 'absolute', left: -8, top: -30, fontSize: 24, color: 'var(--blue)', zIndex: 2 }}>Welcoming parents home with peace of mind.</span>
          <div className="vmain">
            {VISITOR_SLIDES.map((s, i) => (
              <img key={s.src} src={s.src} alt={s.alt} loading={i === 0 ? 'eager' : 'lazy'} className={i === slide ? 'on' : ''} />
            ))}
            {VISITOR_SLIDES.length > 1 && (
              <span className="vdots" role="tablist" aria-label="Visitor insurance photos">
                {VISITOR_SLIDES.map((s, i) => (
                  <button
                    key={s.src}
                    type="button"
                    role="tab"
                    aria-label={`Show photo ${i + 1}`}
                    aria-selected={i === slide}
                    className={i === slide ? 'on' : ''}
                    onClick={() => setSlide(i)}
                  />
                ))}
              </span>
            )}
          </div>
          <div className="vinset">
            <span className="vinset-img">
              <img src={photo('visitor-inset.jpg')} alt="World map highlighting India, the USA, Canada and the Schengen area" loading="lazy" />
            </span>
            {MAP_PINS.map((p) => (
              <span key={p.name} className="vpin" style={{ left: p.left, top: p.top }}>
                <i />
                <b>{p.name}</b>
              </span>
            ))}
          </div>
        </div>
        <div>
          <span className="kick">Visitor insurance</span>
          <h2 className="h2" style={{ marginTop: 12 }}>Visitor Insurance for Travellers</h2>
          <p className="lead" style={{ marginTop: 14 }}>
            Visiting family, exploring a new country or travelling internationally? International visitor insurance helps protect you from unexpected medical expenses and travel emergencies.
          </p>
          <div className="v-checklist">
            <span><Icon name="i-check" className="ico g sm" />No medical exam required</span>
            <span><Icon name="i-check" className="ico g sm" />Instant e-policy by email</span>
            <span><Icon name="i-check" className="ico g sm" />Claims support in your language</span>
          </div>
          <div className="vben">
            {CARDS.map((c) => (
              <div className={`vben-card t-${c.tone}`} key={c.title}>
                <h3>{c.title}</h3>
                <p>{c.desc}</p>
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '14px 24px', marginTop: 28 }}>
            <button className="btn btn-p full" type="button" onClick={() => openQuote()}>Get a Free Quote</button>
            <a href="#benefits" style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
              Compare visitors insurance
              <Icon name="i-arrow" className="ico sm" />
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
