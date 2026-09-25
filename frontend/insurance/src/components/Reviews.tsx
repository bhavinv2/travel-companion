import Icon from './Icon';
import SideDecor from './SideDecor';
import { useReveal } from '../hooks/useReveal';
import { photo, site } from '../data/site';

const REVIEWS = [
  {
    tone: 'amber', tag: 'Easy quote process',
    quote: 'The quote took a few minutes and the plan terms were easy to follow.',
    name: 'S. Krishnan', place: 'Canada', avatar: photo('avatar-1.jpg'),
  },
  {
    tone: 'blue', tag: '24/7 support',
    quote: 'Having one number to call while abroad made the whole trip calmer.',
    name: 'R. Fernandes', place: 'United Kingdom', avatar: photo('avatar-2.jpg'),
  },
  {
    tone: 'green', tag: 'Digital claims',
    quote: 'I uploaded my documents from my phone and could track every step.',
    name: 'A. Menon', place: 'Singapore', avatar: photo('avatar-3.jpg'),
  },
];

/** The colour rotation the shipped three use, continued for however many are saved. */
const TONES = ['amber', 'blue', 'green'];

export default function Reviews() {
  const reveal = useReveal<HTMLDivElement>();

  // Testimonials are entered in Admin -> Insurance page. Unlike the FAQs there is no falling back
  // to the shipped three once the server has spoken: they are invented, and three invented
  // customers on an insurance page costs more trust than no section at all. The server sends the
  // samples to staff only, so the section can still be previewed before it is filled.
  const injected = Array.isArray(site.reviews);
  const reviews = injected
    ? site.reviews!.map((r, i) => ({
        tone: TONES[i % TONES.length],
        tag: r.tag || '',
        quote: r.quote,
        name: r.name,
        place: r.place || '',
        avatar: r.photo || photo(`avatar-${(i % 3) + 1}.jpg`),
      }))
    : REVIEWS;
  const areSamples = injected ? !!site.reviewsAreSamples : true;

  if (!reviews.length) return null;

  return (
    <section className="sec rev-sec">
      <span className="rev-glow" aria-hidden="true" />
      <SideDecor icons={[
        { name: 'i-star', side: 'left', top: '26%', size: 28, rotate: -12, opacity: 0.14 },
        { name: 'i-users', side: 'left', top: '66%', size: 95, rotate: 10, opacity: 0.06 },
        { name: 'i-heart', side: 'right', top: '58%', size: 30, rotate: 8, opacity: 0.14 },
        { name: 'i-checkc', side: 'right', top: '12%', size: 80, rotate: -8, opacity: 0.06 },
      ]} />
      <div className={`wrap z1 ${reveal.className}`} ref={reveal.ref as any}>
        <div className="center">
          <span className="kick rev-kick">Reviews</span>
          <h2 className="h2" style={{ marginTop: 12 }}>What Travellers Say</h2>
          <span className="script-tag" style={{ fontSize: 22, color: 'var(--marigold)' }}>Real trips. Real peace of mind.</span>
          <p className="lead" style={{ marginTop: 12, maxWidth: 520 }}>
            What families tell us after insuring a trip with our team.
          </p>
          {areSamples && (
            <p className="tiny" style={{ marginTop: 10 }}>
              Sample reviews &middot; add real ones in Admin &rarr; Insurance page
            </p>
          )}
        </div>
        <div className="rev-grid">
          {reviews.map((r) => (
            <figure className={`rev t-${r.tone}`} key={r.name}>
              <span className="rev-mark" aria-hidden="true">&rdquo;</span>
              <span className="stars" aria-label="5 out of 5 stars">
                {Array.from({ length: 5 }, (_, i) => <Icon key={i} name="i-star" className="star" />)}
              </span>
              <blockquote>{r.quote}</blockquote>
              <figcaption>
                <span className="rev-av">
                  <img src={r.avatar} alt="" width={46} height={46} loading="lazy" decoding="async" />
                </span>
                <span className="rev-who">
                  <b>{r.name}</b>
                  <span>{r.place}</span>
                </span>
              </figcaption>
              <span className="rev-tag">{r.tag}</span>
            </figure>
          ))}
        </div>
      </div>
    </section>
  );
}
