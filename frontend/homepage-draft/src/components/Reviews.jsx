import { Star } from './Icon.jsx';
import Rail from './Rail.jsx';
import { useReveal } from '../hooks.js';

/* Placeholder copy carried over from the static page, shown without a "Sample" label. Replace
 * each with a real, permission-cleared review (and a real name) before this page goes live. */
const REVIEWS = [
  { svc: 'Sahayak', av: 'S', where: 'London, UK · Parents in Hyderabad',
    text: 'My father had a cataract surgery in Hyderabad while I was in London. The Sahayak picked him up, stayed through the procedure and sent me photos and updates on WhatsApp. I could finally sleep that night.' },
  { svc: 'Travel Companion', av: 'T', where: 'Toronto, Canada · Parents in Chennai',
    text: 'My parents were flying to Toronto for the first time. Their companion helped them through check-in, immigration and the transit. They arrived calm and smiling, not exhausted.' },
  { svc: 'Virtual Doctor', av: 'V', where: 'Dubai, UAE · Parents in Pune',
    text: 'Amma’s BP readings were worrying us. We set up a video consultation and I joined the call from Dubai. Hearing the doctor’s advice myself made all the difference.' },
  { svc: 'Gift Health', av: 'G', where: 'Sydney, Australia · Parents in Kochi',
    text: 'I gifted my parents a health checkup for their anniversary. It was arranged at a time that suited them and the reports came straight to me.' },
  { svc: 'Fit2Fly', av: 'F', where: 'New Jersey, USA · Parents in Ahmedabad',
    text: 'Before Papa’s flight to the US, the Fit2Fly check gave us a doctor’s go-ahead and a clear list of what to carry. No last-minute panic at the airport.' },
  { svc: 'Travel Insurance', av: 'T', where: 'Singapore · Parents in Bengaluru',
    text: 'Choosing visitor insurance for my in-laws was confusing. The team explained the options simply and we bought the plan online the same day.' },
];

export default function Reviews() {
  const head = useReveal();
  return (
    <section className="sec reviews" id="reviews" aria-labelledby="test-h">
      <div className="wrap">
        <div className="p2-head rv-up" ref={head}>
          <span className="kick">Testimonials</span>
          <h2 className="h2" id="test-h">What Families Say</h2>
          <span className="script-tag st-amber">Peace of mind, shared.</span>
          <p className="lede">Real experiences from families who trust us with their parents’ care.</p>
        </div>
        <Rail label="reviews" className="rv-rail">
          {REVIEWS.map((r, i) => (
            <figure className="rv" key={i}>
              <div className="rv-top"><span className="rv-svc">{r.svc}</span></div>
              <div className="rv-stars" aria-label="5 out of 5 stars">{[0, 1, 2, 3, 4].map((k) => <Star key={k} />)}</div>
              <blockquote><p>{r.text}</p></blockquote>
              <figcaption><span className="av">{r.av}</span><span><b>[Customer name]</b><small>{r.where}</small></span></figcaption>
            </figure>
          ))}
        </Rail>
      </div>
    </section>
  );
}
