import Icon from './Icon';
import { useReveal } from '../hooks/useReveal';

const ITEMS = [
  { icon: 'i-lock', label: 'Secure online experience' },
  { icon: 'i-headset', label: 'Expert support' },
  { icon: 'i-list', label: 'Simple quote process' },
  { icon: 'i-file', label: 'Claims assistance' },
  { icon: 'i-globe', label: 'International traveller support' },
];

export default function TrustRow() {
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section style={{ background: 'var(--sky)', padding: '56px 0' }}>
      <div
        className={`wrap ${reveal.className}`}
        ref={reveal.ref as any}
        style={{ display: 'grid', gridTemplateColumns: '4fr 8fr', gap: 28, alignItems: 'center' }}
      >
        <div>
          <span className="kick">Trust</span>
          <h2 className="h2" style={{ marginTop: 12 }}>Travel With Confidence</h2>
          <span className="script-tag" style={{ fontSize: 22, color: 'var(--blue)' }}>Trust, built in.</span>
          <p className="small" style={{ marginTop: 10, maxWidth: 340 }}>What every traveller gets, from quote to claim.</p>
        </div>
        <div className="card trust-row" style={{ borderColor: 'transparent' }}>
          {ITEMS.map((it) => (
            <div key={it.label}>
              <Icon name={it.icon} className="ico g" />
              <span>{it.label}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
