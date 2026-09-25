import Icon from './Icon';
import SideDecor from './SideDecor';
import { useQuote } from '../context/QuoteContext';
import { useReveal } from '../hooks/useReveal';

const ITEMS = [
  { icon: 'i-pin', title: 'Destination', desc: 'Country and region rules' },
  { icon: 'i-passport', title: 'Visa type', desc: 'Some visas need proof of cover' },
  { icon: 'i-stamp', title: 'Immigration', desc: 'Entry conditions on arrival' },
  { icon: 'i-flag', title: 'Schengen rules', desc: 'Minimum medical cover applies' },
  { icon: 'i-ticket', title: 'Airline & trip terms', desc: 'Carrier or tour conditions' },
  { icon: 'i-landmark', title: 'Local regulations', desc: 'Rules can change, check first' },
];

export default function Requirements() {
  const { openQuote } = useQuote();
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section className="sec">
      <SideDecor icons={[
        { name: 'i-stamp', side: 'left', top: '20%', size: 30, rotate: -8, opacity: 0.14 },
        { name: 'i-landmark', side: 'left', top: '66%', size: 95, rotate: 6, opacity: 0.06 },
        { name: 'i-flag', side: 'right', top: '64%', size: 30, rotate: 6, opacity: 0.14 },
        { name: 'i-ticket', side: 'right', top: '14%', size: 85, rotate: -12, opacity: 0.06 },
      ]} />
      <div className={`wrap split z1 ${reveal.className}`} ref={reveal.ref as any}>
        <div>
          <span className="kick">Travel requirements</span>
          <h2 className="h2" style={{ marginTop: 12 }}>Is Travel Insurance Mandatory?</h2>
          <span className="script-tag" style={{ fontSize: 22, color: 'var(--blue)' }}>Know before you go.</span>
          <p className="lead" style={{ marginTop: 14 }}>It depends on where you're going and why. Requirements differ by destination, visa and trip.</p>
          <div style={{ marginTop: 22, background: 'var(--sky)', borderRadius: 20, padding: '20px 22px', display: 'flex', gap: 16, alignItems: 'flex-start' }}>
            <span className="tile" style={{ background: '#fff' }}><Icon name="i-info" /></span>
            <span>
              <span style={{ display: 'block', fontSize: 17, fontWeight: 600, lineHeight: 1.4 }}>Check the requirements for your destination before travelling.</span>
              <span className="small">Embassy and immigration sources have the final word.</span>
            </span>
          </div>
          <button className="btn btn-p full" type="button" style={{ marginTop: 22 }} onClick={() => openQuote()}>Check Your Coverage Options</button>
        </div>
        <div className="g2">
          {ITEMS.map((it) => (
            <div className="card lift" style={{ padding: 18, display: 'flex', gap: 14, alignItems: 'center' }} key={it.title}>
              <span className="tile"><Icon name={it.icon} /></span>
              <span>
                <span style={{ display: 'block', fontWeight: 600, fontSize: 17 }}>{it.title}</span>
                <span className="tiny">{it.desc}</span>
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
