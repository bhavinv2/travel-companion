import Icon from './Icon';
import SideDecor from './SideDecor';
import { useQuote } from '../context/QuoteContext';
import { useReveal } from '../hooks/useReveal';
import { useInView } from '../hooks/useInView';

const STEPS = [
  {
    icon: 'i-pin', tone: 'amber', title: 'Tell Us About Your Trip',
    desc: 'Destination, dates and travellers.', chip: 'Takes two minutes',
  },
  {
    icon: 'i-list', tone: 'blue', title: 'Compare Your Options',
    desc: '65+ A-rated plans, side by side.', chip: 'No payment to compare',
  },
  {
    icon: 'i-shield', tone: 'green', title: 'Choose Your Coverage',
    desc: 'Pick the plan that fits and buy online.', chip: 'Policy issued instantly',
  },
  {
    icon: 'i-plane', tone: 'rose', title: 'Travel With Confidence',
    desc: 'Your policy and help, on your phone.', chip: '24/7 assistance',
  },
];

export default function HowItWorks() {
  const { openQuote } = useQuote();
  const reveal = useReveal<HTMLDivElement>();
  const track = useInView<HTMLDivElement>();

  return (
    <section className="sec how-sec" id="how">
      <SideDecor icons={[
        { name: 'i-pin', side: 'left', top: '28%', size: 28, rotate: -10, opacity: 0.14 },
        { name: 'i-route', side: 'left', top: '68%', size: 95, rotate: 14, opacity: 0.06 },
        { name: 'i-plane', side: 'right', top: '50%', size: 32, rotate: 12, opacity: 0.14 },
        { name: 'i-list', side: 'right', top: '10%', size: 80, rotate: -10, opacity: 0.06 },
      ]} />
      <div className={`wrap z1 ${reveal.className}`} ref={reveal.ref as any}>
        <div className="center">
          <span className="kick how-kick">Simple steps, real protection</span>
          <h2 className="h2" style={{ marginTop: 12, maxWidth: 720 }}>Travel Insurance Made Simple</h2>
          <span className="script-tag" style={{ fontSize: 22, color: 'var(--horizon)' }}>Steps, made simple.</span>
          <p className="lead" style={{ marginTop: 12, maxWidth: 560 }}>
            Getting your parents covered takes just a few minutes, start to finish.
          </p>
        </div>

        <div className={`how${track.inView ? ' in' : ''}`} ref={track.ref as any}>
          <span className="how-rail" aria-hidden="true">
            <i />
            <Icon name="i-plane" className="how-rail-plane" />
          </span>
          <div className="how-grid">
            {STEPS.map((s, i) => (
              <div className={`how-card t-${s.tone}`} key={s.title}>
                <span className="how-num">{i + 1}</span>
                <span className="how-ic"><Icon name={s.icon} /></span>
                <b>{s.title}</b>
                <p className="small">{s.desc}</p>
                <span className="how-chip">{s.chip}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="how-cta">
          <button className="btn btn-p btn-lg" type="button" onClick={() => openQuote()}>
            Get a Free Quote
            <Icon name="i-arrow" className="ico w sm" />
          </button>
          <p className="how-note">
            <Icon name="i-check" className="ico sm" />
            Free to compare — no payment needed to see prices
          </p>
        </div>
      </div>
    </section>
  );
}
