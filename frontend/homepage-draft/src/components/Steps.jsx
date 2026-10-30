import { Doodles, Snap, Trail } from './Deco.jsx';
import { site, talk, TALK } from '../data/site.js';
import { useReveal } from '../hooks.js';
import askPhoto from '../assets/photos/support-agent.webp';
import arrangePhoto from '../assets/photos/sah-svc-demo.jpg';
import updatePhoto from '../assets/photos/why-updates.jpg';
import youAbroad from '../assets/photos/tc-l4.jpg';
import themAtHome from '../assets/photos/hero-parent-care.jpg';

/* "How it works": the three steps from a first message to the updates, each with its own photo. */
const STEPS = [
  { img: askPhoto, pos: 'center 20%', tone: 'ask', title: 'Tell us what they need',
    text: 'Chat with us here, message us on WhatsApp or call. Tell us about your parents, their city and what they need.' },
  { img: arrangePhoto, pos: '30% 40%', title: 'We arrange it',
    text: 'A Sahayak, a travel companion, a video consultation with a doctor or the right insurance plan, booked for your parents.' },
  { img: updatePhoto, pos: 'center 30%', title: 'You stay in the loop',
    text: 'Updates on WhatsApp at every step, so you know how they are, wherever you are.' },
];

export default function Steps() {
  const head = useReveal();
  const list = useReveal(0.15);
  return (
    <section className="sc sc-light how" id="how" aria-labelledby="how-h">
      <Snap src={youAbroad} caption="You, abroad" pos="center 60%" at={{ top: '64px', left: 'max(18px, calc(50% - 660px))' }} rotate={-6} width={150} />
      <Trail at={{ top: '96px', left: 'max(180px, calc(50% - 500px))' }} width={150} />
      <Trail at={{ top: '96px', right: 'max(180px, calc(50% - 500px))' }} width={150} flip />
      <Snap src={themAtHome} caption="Them, at home" pos="70% 30%" at={{ top: '64px', right: 'max(18px, calc(50% - 660px))' }} rotate={5} width={150} tone="amber" />
      <Doodles items={[['chat', { top: '58%', left: '2.5%', size: 30, rotate: -8 }], ['calendar', { top: '62%', right: '2.5%', size: 30, rotate: 8 }],
        ['heart', { top: '90%', left: '6%', size: 26, rotate: 10 }]]} />
      <div className="wrap">
        <div className="sc-head center rv-up" ref={head}>
          <span className="kick">How it works</span>
          <h2 className="h2" id="how-h">Care for Your Parents in <em>Three Steps</em></h2>
          <span className="script-tag">From your message to their door.</span>
        </div>
        <ol className="how-steps rv-stagger" ref={list}>
          {STEPS.map((s, i) => (
            <li className="how-step" key={s.title} style={{ '--d': `${i * 120}ms` }}>
              <span className={`how-ph${s.tone ? ' ' + s.tone : ''}`}>
                <img src={s.img} alt="" loading="lazy" decoding="async" style={{ objectPosition: s.pos }} />
                <span className="how-n" aria-hidden="true">{i + 1}</span>
              </span>
              <h3>{s.title}</h3>
              <p>{s.text}</p>
            </li>
          ))}
        </ol>
        <div className="how-foot">
          <a className="btn btn-p" href={site.contactUrl} onClick={talk}>{TALK}</a>
        </div>
      </div>
    </section>
  );
}
