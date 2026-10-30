import { useReveal } from '../hooks.js';
import local from '../assets/photos/why-local.jpg';
import health from '../assets/photos/why-health.jpg';
import travel from '../assets/photos/why-travel.jpg';
import updates from '../assets/photos/why-updates.jpg';

/* As on the static page: four photo cards, the description opening on hover. */
const CARDS = [
  { tag: 'Local support', title: 'Trusted Local Support', text: 'Reliable, verified assistance for your parents in India.',
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
    <section className="sec why" id="why" aria-labelledby="why-h">
      <div className="wrap">
        <div className="sec-h rv-up" ref={head}>
          <div>
            <span className="kick">Why families choose us</span>
            <h2 className="h2" id="why-h">Why Choose NRI Parent Service?</h2>
            <p className="lede">Because caring for your parents from abroad should feel simpler, safer and more reassuring.</p>
          </div>
        </div>
        <div className="wgrid rv-stagger" ref={grid}>
          {CARDS.map((c, i) => (
            <article className="wcard" key={c.title} style={{ '--d': `${i * 100}ms` }} tabIndex={0}>
              <img src={c.img} alt={c.alt} style={{ objectPosition: c.pos }} decoding="async" />
              <span className="wtag">{c.tag}</span>
              <div className="wbody"><h3>{c.title}</h3><p>{c.text}</p></div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
