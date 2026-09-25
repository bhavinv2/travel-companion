import Icon from './Icon';
 import { photo } from '../data/site';
import { useQuote } from '../context/QuoteContext';
import { useReveal } from '../hooks/useReveal';

export default function FinalCTA() {
  const { openQuote } = useQuote();
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section style={{ padding: '64px 0 80px' }}>
      <div className={`wrap ${reveal.className}`} ref={reveal.ref as any}>
        <div className="cta cta-final">
          <div className="cta-copy">
            <span className="script-tag" style={{ fontSize: 26, color: '#fff', opacity: 0.9 }}>Your next journey awaits.</span>
            <h2 style={{ fontSize: 'clamp(28px,3.4vw,48px)', lineHeight: 1.12, letterSpacing: '-.02em', color: '#fff', marginTop: 6 }}>
              Ready to Travel With More Confidence?
            </h2>
            <p className="lead" style={{ marginTop: 16, color: '#E6EEFF', maxWidth: 520 }}>
              Explore travel insurance options designed around your destination, travel dates and traveller needs.
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 28 }}>
              <button className="btn btn-w btn-lg" type="button" onClick={() => openQuote()}>Get Your Free Quote</button>
              <a className="btn btn-ow btn-lg" href="#contact">
                <Icon name="i-headset" className="ico w sm" />Talk to an Expert
              </a>
            </div>
          </div>
          <div className="cta-photo">
            <img src={photo('final-cta.jpg')} alt="Traveller looking out at a sunset landscape" loading="lazy" />
          </div>
        </div>
      </div>
    </section>
  );
}
