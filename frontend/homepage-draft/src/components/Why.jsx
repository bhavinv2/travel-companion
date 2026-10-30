import Bg from './Bg.jsx';
import { Doodles, Note } from './Deco.jsx';
import { useReveal } from '../hooks.js';
import whyBg from '../assets/photos/ins-story-senior.jpg';
import local from '../assets/photos/why-local.jpg';
import health from '../assets/photos/why-health.jpg';
import travel from '../assets/photos/why-travel.jpg';
import updates from '../assets/photos/why-updates.jpg';

/* Four photo cards, the description opening on hover, on the insurance page's photo of an
 * elderly couple out walking. */
const CARDS = [
  { tag: 'Local support', title: 'Someone There for Them', text: 'Help in their own city, from people who turn up and speak their language.',
    img: local, pos: 'center 20%', alt: 'A Sahayak, her ID card on show, welcomed at the door by an elderly mother' },
  { tag: 'Healthcare', title: 'Healthcare Assistance', text: 'Help with doctor visits, hospitals and healthcare coordination.',
    img: health, pos: 'center 25%', alt: 'A Sahayak handing an elderly father’s file to a hospital receptionist' },
  { tag: 'Travel', title: 'Travel Support', text: 'Assistance for elderly parents before and during their journeys.',
    img: travel, pos: 'center 30%', alt: 'A Sahayak pushing the luggage trolley for an elderly couple at the airport' },
  { tag: 'Peace of mind', title: 'Regular Updates', text: 'Stay informed about the support your parents receive.',
    img: updates, pos: 'center 30%', alt: 'An elderly mother waving in a video update the Sahayak is recording for her family' },
];

export default function Why() {
  const head = useReveal();
  const grid = useReveal(0.1);
  return (
    <section className="sc sc-dark why" id="why" aria-labelledby="why-h">
      <Bg src={whyBg} pos="center 35%" />
      <Note at={{ top: '84px', left: 'max(24px, calc(50% - 640px))' }} rotate={-6} icon="heart">Families first</Note>
      <Doodles items={[['users', { top: '12%', right: '4%', size: 34, rotate: 8, opacity: 0.22 }], ['shield', { top: '58%', left: '2.5%', size: 30, rotate: -8, opacity: 0.2 }],
        ['heart', { top: '70%', right: '3%', size: 26, rotate: 10, opacity: 0.22 }]]} />
      <div className="wrap">
        <div className="sc-head center rv-up" ref={head}>
          <span className="kick">Why families choose us</span>
          <h2 className="h2" id="why-h">Why Choose <em>NRI Parent Service?</em></h2>
          <span className="script-tag">Care you can count on.</span>
          <p className="lede">Because caring for your parents from abroad should feel simpler, safer and more reassuring.</p>
        </div>
        <div className="wgrid rv-stagger" ref={grid}>
          {CARDS.map((c, i) => (
            <article className="wcard" key={c.title} style={{ '--d': `${i * 100}ms` }} tabIndex={0}>
              <img src={c.img} alt={c.alt} style={{ objectPosition: c.pos }} loading="lazy" decoding="async" />
              <span className="wtag">{c.tag}</span>
              <div className="wbody"><h3>{c.title}</h3><p>{c.text}</p></div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
