import Icon from './Icon';
import SideDecor from './SideDecor';
import { useQuote } from '../context/QuoteContext';
import { useReveal } from '../hooks/useReveal';
import { photo } from '../data/site';

const ITEMS = [
  { photo: 'destination', tone: 'blue', title: 'Destination', alt: 'Globe and landmark models on an old world map' },
  { photo: 'visa-type', tone: 'amber', title: 'Visa type', alt: 'Passport with entry stamps beside a medical check form' },
  { photo: 'immigration', tone: 'blue', title: 'Immigration', alt: 'Immigration officer stamping a passport on arrival' },
  { photo: 'schengen-rules', tone: 'indigo', title: 'Schengen rules', alt: 'Schengen visa insurance policy documents and an EU flag' },
  { photo: 'airline-trip', tone: 'rose', title: 'Airline & trip terms', alt: 'Airport departure board above waiting suitcases' },
  { photo: 'local-regulations', tone: 'teal', title: 'Local regulations', alt: 'Local regulations notice mounted on a stone wall' },
];

export default function Requirements() {
  const { openQuote } = useQuote();
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section className="sec req-sec">
      <span className="req-glow" aria-hidden="true" />
      <SideDecor icons={[
        { name: 'i-stamp', side: 'left', top: '20%', size: 30, rotate: -8, opacity: 0.14 },
        { name: 'i-landmark', side: 'left', top: '66%', size: 95, rotate: 6, opacity: 0.06 },
        { name: 'i-flag', side: 'right', top: '64%', size: 30, rotate: 6, opacity: 0.14 },
        { name: 'i-ticket', side: 'right', top: '14%', size: 85, rotate: -12, opacity: 0.06 },
      ]} />
      <div className={`wrap split z1 ${reveal.className}`} ref={reveal.ref as any}>
        <div>
          <span className="kick req-kick">Travel requirements</span>
          <h2 className="h2" style={{ marginTop: 12 }}>Is Travel Insurance Mandatory?</h2>
          <span className="script-tag" style={{ fontSize: 22, color: 'var(--blue)' }}>Know before you go.</span>
          <p className="lead" style={{ marginTop: 14 }}>It depends on where you're going and why. Requirements differ by destination, visa and trip.</p>
          <div className="req-note">
            <span className="req-note-ic"><Icon name="i-info" /></span>
            <span>
              <b>Check the requirements for your destination before travelling.</b>
              <span>Embassy and immigration sources have the final word.</span>
            </span>
          </div>
          <button className="btn btn-p full" type="button" style={{ marginTop: 22 }} onClick={() => openQuote()}>Get a Free Quote</button>
        </div>
        <div className="req-grid">
          {ITEMS.map((it) => (
            <div className={`req-card t-${it.tone}`} key={it.title}>
              <div className="req-img">
                <img src={photo(`requirements/${it.photo}.jpg`)} alt={it.alt} width={720} height={360} loading="lazy" decoding="async" />
                <span className="req-badge">{it.title}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
