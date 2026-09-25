import Icon from './Icon';
 import { photo } from '../data/site';
import { useReveal } from '../hooks/useReveal';

export default function Hero() {
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section className="hero" id="top">
      <img className="hero-bg" src={photo('hero-banner.jpg')} alt="Senior couple at the airport at sunset, ready for a protected journey" loading="eager" />
      <div className="wrap hero-in" ref={reveal.ref as any}>
        <div className="hero-copy reveal in">
          <span className="script-tag hero-script">Explore. Dream. Discover.</span>
          <span className="chip">
            <Icon name="i-globe" className="ico xs" />
            International travel &amp; visitor insurance
          </span>
          <h1 className="h1" style={{ marginTop: 22 }}>Travel Further. Stay Protected.</h1>
          <p className="lead" style={{ marginTop: 20, maxWidth: 520 }}>
            Travel insurance for every journey &mdash; designed for unexpected medical emergencies, trip disruptions and travel-related expenses.
          </p>
          <p className="small" style={{ marginTop: 12, maxWidth: 520 }}>
            Quote and compare international travel insurance and travel medical insurance online, and buy in minutes — brought to you by NRI Parent Service.
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 28 }}>
            <a className="btn btn-ow btn-lg" href="#benefits">Explore Coverage</a>
          </div>
          <div className="hero-trust">
            <span><Icon name="i-check" className="ico g sm" />65+ A-rated plans</span>
            <span><Icon name="i-check" className="ico g sm" />Claims guidance</span>
            <span><Icon name="i-check" className="ico g sm" />Help across time zones</span>
          </div>
          <div className="hero-stats">
            <div className="hero-stat">
              <span className="tile" style={{ width: 36, height: 36, borderRadius: 10, background: 'rgba(255,255,255,.18)' }}>
                <Icon name="i-users" className="ico w sm" />
              </span>
              <span><b>12,000+</b><span>Travellers protected</span></span>
            </div>
            <div className="hero-stat">
              <span className="tile" style={{ width: 36, height: 36, borderRadius: 10, background: 'rgba(255,255,255,.18)' }}>
                <Icon name="i-star" className="ico w sm" />
              </span>
              <span><b>4.8 / 5</b><span>Average rating</span></span>
            </div>
            <div className="hero-stat">
              <span className="tile" style={{ width: 36, height: 36, borderRadius: 10, background: 'rgba(255,255,255,.18)' }}>
                <Icon name="i-headset" className="ico w sm" />
              </span>
              <span><b>24/7</b><span>Global support</span></span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
