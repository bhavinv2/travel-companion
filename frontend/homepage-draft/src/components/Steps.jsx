import Icon from './Icon.jsx';
import { site, talk, TALK } from '../data/site.js';
import { useReveal } from '../hooks.js';

/* "How it works": the three steps from a first message to the updates, and the prices the
 * service pages publish (routes/homepage_draft.py _prices) -- each shown only once it is known. */
const STEPS = [
  { icon: 'chat', title: 'Tell us what they need',
    text: 'Chat with us here, message us on WhatsApp or call. Tell us about your parents, their city and what they need.' },
  { icon: 'calendar', title: 'We arrange it',
    text: 'A Sahayak, a travel companion, a video consultation with a doctor or the right insurance plan, booked for your parents.' },
  { icon: 'heart', title: 'You stay in the loop',
    text: 'Updates on WhatsApp at every step, so you know how they are, wherever you are.' },
];

export default function Steps() {
  const head = useReveal();
  const list = useReveal(0.15);
  const { sahayak, insurance } = site.prices;
  return (
    <section className="sec how" id="how" aria-labelledby="how-h">
      <div className="wrap">
        <div className="p2-head rv-up" ref={head}>
          <span className="kick">How it works</span>
          <h2 className="h2" id="how-h">Care for Your Parents in <em>Three Steps</em></h2>
        </div>
        <ol className="how-steps rv-stagger" ref={list}>
          {STEPS.map((s, i) => (
            <li className="how-step" key={s.title} style={{ '--d': `${i * 120}ms` }}>
              <span className="how-n" aria-hidden="true">{i + 1}</span>
              <span className="how-ic" aria-hidden="true"><Icon name={s.icon} /></span>
              <h3>{s.title}</h3>
              <p>{s.text}</p>
            </li>
          ))}
        </ol>
        <div className="how-foot">
          {(sahayak || insurance) && (
            <p className="how-prices">
              {sahayak && <span><Icon name="home" />Sahayak visits from <b>{sahayak}</b></span>}
              {insurance && <span><Icon name="shield" />Travel insurance: <b>{insurance}</b></span>}
            </p>
          )}
          <a className="btn btn-p" href={site.contactUrl} onClick={talk}>{TALK}<Icon name="arrow" /></a>
        </div>
      </div>
    </section>
  );
}
