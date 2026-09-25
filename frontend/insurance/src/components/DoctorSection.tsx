import Icon from './Icon';
 import { photo } from '../data/site';
import { useQuote } from '../context/QuoteContext';
import { useReveal } from '../hooks/useReveal';

export default function DoctorSection() {
  const { openConsult } = useQuote();
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section className="sec dark">
      <svg className="pat" aria-hidden="true">
        <defs>
          <pattern id="hearts" width="84" height="76" patternUnits="userSpaceOnUse">
            <path d="M42 58C24 45 17 37 17 29a11 11 0 0 1 25-5 11 11 0 0 1 25 5c0 8-7 16-25 29z" fill="none" stroke="#fff" strokeOpacity=".07" strokeWidth="2" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#hearts)" />
      </svg>
      <div className={`wrap split ${reveal.className}`} ref={reveal.ref as any}>
        <div>
          <span className="chip" style={{ background: 'var(--green)', color: '#fff' }}>Free for our travel insurance customers</span>
          <span className="script-tag" style={{ display: 'block', fontSize: 24, marginTop: 10, color: 'var(--horizon)' }}>Care that travels with you.</span>
          <h2 className="h2" style={{ marginTop: 10 }}>Free Virtual Doctor Consultation While You're Abroad</h2>
          <p className="lead" style={{ marginTop: 14, color: '#C9D6F2' }}>
            Every traveller insured with us can speak to a doctor by video or phone from wherever they are staying, at no extra cost.
          </p>
          <div className="feat-row">
            <span><Icon name="i-video" className="ico h sm" />Video or audio call</span>
            <span><Icon name="i-lock" className="ico h sm" />Private &amp; secure</span>
            <span><Icon name="i-clock" className="ico h sm" />Any time zone</span>
          </div>
          <button className="btn btn-w btn-lg full" type="button" style={{ marginTop: 28 }} onClick={openConsult}>
            Book Your Free Consultation
          </button>
          <div className="note">
            <Icon name="i-info" className="ico h xs" />
            <p className="tiny" style={{ color: '#A9B8DB' }}>
              Available to insured travellers. Availability and consultation terms may vary, and services are subject to applicable policy terms.
            </p>
          </div>
        </div>
        <div>
          <div className="vc">
            <div className="vc-top">
              <span>Virtual doctor consultation</span>
              <span className="status"><Icon name="i-lock" className="ico g xs" />Secure connection</span>
            </div>
            <div className="vc-body">
              <div className="vc-stage">
                <img src={photo('doctor-section.jpg')} alt="Doctor available for a video consultation" loading="lazy" />
                <span className="vc-name">Dr. Anita Rao &middot; General physician</span>
                <span className="vc-self">
                  <img src={photo('avatar-2.jpg')} alt="Traveller on the call" loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                </span>
              </div>
              <div className="vc-ctrl">
                <button className="rbtn" type="button" aria-label="Mute microphone"><Icon name="i-mic" className="ico n sm" /></button>
                <button className="rbtn" type="button" aria-label="Turn camera off"><Icon name="i-video" className="ico n sm" /></button>
                <button className="btn" type="button" style={{ minHeight: 48, borderRadius: 999, background: 'var(--navy)', color: '#fff', fontSize: 15 }}>End call</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
