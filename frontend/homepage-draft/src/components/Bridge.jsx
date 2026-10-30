import Icon from './Icon.jsx';
import { useReveal } from '../hooks.js';
import callPhoto from '../assets/photos/doctor-consultation.jpg';

const POINTS = [
  ['calendar', 'Every appointment'],
  ['hospital', 'Every hospital visit'],
  ['plane', 'Every journey'],
  ['house', 'Every everyday need'],
];

export default function Bridge() {
  const vis = useReveal();
  const txt = useReveal();

  return (
    <section className="sec bridge-sec" aria-labelledby="dist-h">
      <div className="wrap bridge">
        <div className="br-vis rv-left" ref={vis}>
          {/* the travel-insurance page's virtual consultation card (DoctorSection.tsx .vc): the
              same picture in the same call window. Its controls are drawn, not buttons --
              there is no call to mute here, so nothing to focus or press. */}
          <div className="vc">
            <div className="vc-top">
              <span>Virtual doctor consultation</span>
              <span className="vc-status"><Icon name="lock" stroke={2} />Secure connection</span>
            </div>
            <div className="vc-body">
              <div className="vc-stage">
                <img src={callPhoto} loading="lazy" decoding="async" width={1600} height={874}
                  alt="Preventia360 telehealth app: a physician on a live video call with two parents on a tablet, and the care-booking screen on a phone" />
              </div>
              <div className="vc-ctrl" aria-hidden="true">
                <span className="rbtn"><Icon name="mic" /></span>
                <span className="rbtn"><Icon name="video" /></span>
                <span className="vc-end">End call</span>
              </div>
            </div>
          </div>
        </div>
        <div className="br-txt rv-up" ref={txt}>
          <span className="kick">Why we exist</span>
          <h2 className="h2" id="dist-h">Distance Shouldn’t Come Between You and <em>Your Parents’ Care</em></h2>
          <span className="script-tag st-amber">Close to them, wherever you are.</span>
          <p className="lede">Living abroad can make it difficult to be there for every appointment, hospital visit, journey or everyday need. NRI Parent Service helps bridge that distance by providing trusted support for your parents in India — so you can stay connected, informed and reassured.</p>
          <ul className="br-pts">
            {POINTS.map(([ic, t], i) => (
              <li key={t} style={{ '--d': `${200 + i * 90}ms` }}><span><Icon name={ic} /></span>{t}</li>
            ))}
          </ul>
          <a className="btn btn-p" href="#services">How We Help<Icon name="arrow" /></a>
        </div>
      </div>
    </section>
  );
}
