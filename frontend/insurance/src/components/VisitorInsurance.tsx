import Icon from './Icon';
 import { photo } from '../data/site';
import SideDecor from './SideDecor';
import { useQuote } from '../context/QuoteContext';
import { useReveal } from '../hooks/useReveal';

const CARDS: Array<{ icon: string; title: string; desc: string; accent?: boolean }> = [
  { icon: 'i-heart', title: 'Medical Emergency Coverage', desc: 'Eligible treatment and hospital costs.' },
  { icon: 'i-headset', title: 'Emergency Assistance', desc: 'A helpline when something goes wrong.' },
  { icon: 'i-steth', title: 'Hospital & Doctor Support', desc: 'Guidance to find care nearby.' },
  { icon: 'i-shield', title: 'Travel Protection', desc: 'Cover for eligible trip disruptions.', accent: true },
];

export default function VisitorInsurance() {
  const { openQuote } = useQuote();
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section className="sec" id="visitor" style={{ background: 'var(--cloud)' }}>
      <SideDecor icons={[
        { name: 'i-heart', side: 'left', top: '18%', size: 30, rotate: -8, opacity: 0.14 },
        { name: 'i-plane', side: 'left', top: '70%', size: 100, rotate: -18, opacity: 0.06 },
        { name: 'i-passport', side: 'right', top: '62%', size: 32, rotate: 6, opacity: 0.14 },
        { name: 'i-globe', side: 'right', top: '10%', size: 90, rotate: 10, opacity: 0.06 },
      ]} />
      <div className={`wrap split z1 ${reveal.className}`} ref={reveal.ref as any}>
        <div className="vcluster">
          <span className="vglow" aria-hidden="true" />
          <span className="script-tag" style={{ position: 'absolute', left: -8, top: -30, fontSize: 26, color: 'var(--blue)', zIndex: 2 }}>Together, always.</span>
          <div className="vmain">
            <img src={photo('visitor-main.jpg')} alt="Family spending time together at home during a visit abroad" loading="lazy" />
          </div>
          <div className="vinset">
            <img src={photo('visitor-inset.jpg')} alt="World map symbolising international travel" loading="lazy" />
          </div>
          <div className="vexp">
            <span className="vexp-num">30</span>
            <span className="vexp-txt">Years of<br />experience</span>
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
          <div className="g2" style={{ marginTop: 24 }}>
            {CARDS.map((c) => (
              <div className="card lift" style={{ padding: 20 }} key={c.title}>
                <div className={`tile${c.accent ? ' g' : ''}`}><Icon name={c.icon} className={c.accent ? 'ico g' : 'ico'} /></div>
                <h3 className="t3" style={{ marginTop: 12, fontSize: 18 }}>{c.title}</h3>
                <p className="small">{c.desc}</p>
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
