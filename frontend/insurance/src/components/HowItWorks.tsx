import Icon from './Icon';
import SideDecor from './SideDecor';
import { useReveal } from '../hooks/useReveal';
import { useInView } from '../hooks/useInView';

const STEPS = [
  { icon: 'i-pin', title: 'Tell Us About Your Trip', desc: 'Destination, dates and travellers.' },
  { icon: 'i-list', title: 'Compare Your Options', desc: '65+ plans, side by side.' },
  { icon: 'i-shield', title: 'Choose Your Coverage', desc: 'Pick the plan that fits, buy online.' },
  { icon: 'i-plane', title: 'Travel With Confidence', desc: 'Your policy and help, on your phone.' },
];

export default function HowItWorks() {
  const reveal = useReveal<HTMLDivElement>();
  const track = useInView<HTMLDivElement>();

  return (
    <section className="sec">
      <SideDecor icons={[
        { name: 'i-pin', side: 'left', top: '28%', size: 28, rotate: -10, opacity: 0.14 },
        { name: 'i-route', side: 'left', top: '68%', size: 95, rotate: 14, opacity: 0.06 },
        { name: 'i-plane', side: 'right', top: '50%', size: 32, rotate: 12, opacity: 0.14 },
        { name: 'i-list', side: 'right', top: '10%', size: 80, rotate: -10, opacity: 0.06 },
      ]} />
      <div className={`wrap z1 ${reveal.className}`} ref={reveal.ref as any}>
        <div className="center">
          <span className="kick">How it works</span>
          <h2 className="h2" style={{ marginTop: 12 }}>Travel Insurance Made Simple</h2>
          <span className="script-tag" style={{ fontSize: 22, color: 'var(--horizon)' }}>Simple, by design.</span>
        </div>
        <div className={`how${track.inView ? ' in' : ''}`} ref={track.ref as any}>
          <span className="how-track" aria-hidden="true"><i /></span>
          <div className="g4">
            {STEPS.map((s) => (
              <div className="how-step" key={s.title}>
                <span className="how-num"><Icon name={s.icon} /></span>
                <b>{s.title}</b>
                <p className="small">{s.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
