import Icon from './Icon';
import SideDecor from './SideDecor';
import { useQuote } from '../context/QuoteContext';
import { useReveal } from '../hooks/useReveal';
import { photo } from '../data/site';

const FEATURES = [
  { icon: 'i-video', label: 'Video or audio call' },
  { icon: 'i-lock', label: 'Private & secure' },
  { icon: 'i-clock', label: 'Any time zone' },
];

export default function DoctorSection() {
  const { openConsult } = useQuote();
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section className="sec vcon-sec">
      <span className="vcon-glow" aria-hidden="true" />
      <SideDecor icons={[
        { name: 'i-video', side: 'left', top: '24%', size: 28, rotate: -8, opacity: 0.14 },
        { name: 'i-heart', side: 'left', top: '70%', size: 92, rotate: 8, opacity: 0.06 },
        { name: 'i-clock', side: 'right', top: '64%', size: 30, rotate: 8, opacity: 0.14 },
        { name: 'i-shield', side: 'right', top: '12%', size: 86, rotate: -10, opacity: 0.06 },
      ]} />
      <div className={`wrap split z1 ${reveal.className}`} ref={reveal.ref as any}>
        <div>
          <span className="chip g">
            <Icon name="i-check" className="ico g xs" />
            Free for our travel insurance customers
          </span>
          <h2 className="h2" style={{ marginTop: 16 }}>Free Virtual Doctor Consultation While You&apos;re Abroad</h2>
          <span className="script-tag" style={{ display: 'block', fontSize: 22, marginTop: 8, color: 'var(--blue)' }}>
            Care that travels with you.
          </span>
          <p className="lead" style={{ marginTop: 14, maxWidth: 520 }}>
            Every traveller insured with us can speak to a doctor by video or phone from wherever they are staying, at no extra cost.
          </p>

          <ul className="vcon-feats">
            {FEATURES.map((f) => (
              <li key={f.label}><Icon name={f.icon} className="ico sm" />{f.label}</li>
            ))}
          </ul>

          <button className="btn btn-p btn-lg" type="button" style={{ marginTop: 26 }} onClick={openConsult}>
            Book Your Free Consultation
            <Icon name="i-arrow" className="ico w sm" />
          </button>

          <p className="vcon-note">
            <Icon name="i-info" className="ico sm" />
            <span className="tiny">
              Available to insured travellers, in partnership with{' '}
              <a href="https://preventia360.com/" target="_blank" rel="noopener noreferrer" className="preventia-link">Preventia360</a>.
              {' '}Availability and consultation terms may vary, and services are subject to applicable policy terms.
            </span>
          </p>
        </div>

        <div>
          <div className="vc">
            <div className="vc-top">
              <span>Virtual doctor consultation</span>
              <span className="status"><Icon name="i-lock" className="ico g xs" />Secure connection</span>
            </div>
            <div className="vc-body">
              <div className="vc-stage">
                <img src={photo('doctor-consultation.jpg')} alt="Preventia360 telehealth app: a physician on a live video call with two travellers on a tablet, and the care-booking screen on a phone" loading="lazy" />
              </div>
              <div className="vc-ctrl">
                <button className="rbtn" type="button" aria-label="Mute microphone"><Icon name="i-mic" className="ico n sm" /></button>
                <button className="rbtn" type="button" aria-label="Turn camera off"><Icon name="i-video" className="ico n sm" /></button>
                <button className="btn vc-end" type="button">End call</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
