import Icon from './Icon';
import SideDecor from './SideDecor';
import { useReveal } from '../hooks/useReveal';
import { fromServer, photo, site } from '../data/site';

const REVIEWS = [
  {
    tag: 'Parents visiting children', quote: 'The quote took a few minutes and the plan terms were easy to follow.',
    name: 'S. Krishnan', place: 'Canada', cc: 'CA', avatar: photo('avatar-1.jpg'),
  },
  {
    tag: 'Family trip', quote: 'Having one number to call while abroad made the whole trip calmer.',
    name: 'R. Fernandes', place: 'United Kingdom', cc: 'GB', avatar: photo('avatar-2.jpg'),
  },
  {
    tag: 'Business travel', quote: 'I uploaded my documents from my phone and could track every step.',
    name: 'A. Menon', place: 'Singapore', cc: 'SG', avatar: photo('avatar-3.jpg'),
  },
];

export default function Reviews() {
  const reveal = useReveal<HTMLDivElement>();
  // Testimonials are managed in Admin -> Insurance page. REVIEWS below is what this build
  // shipped with and is only used when nothing was injected (the dev server).
  const reviews = fromServer(site.reviews, REVIEWS);
  const areSamples = site.reviews ? !!site.reviewsAreSamples : true;

  return (
    <section className="sec">
      <SideDecor icons={[
        { name: 'i-star', side: 'left', top: '26%', size: 28, rotate: -12, opacity: 0.14 },
        { name: 'i-users', side: 'left', top: '66%', size: 95, rotate: 10, opacity: 0.06 },
        { name: 'i-heart', side: 'right', top: '58%', size: 30, rotate: 8, opacity: 0.14 },
        { name: 'i-checkc', side: 'right', top: '12%', size: 80, rotate: -8, opacity: 0.06 },
      ]} />
      <div className={`wrap z1 ${reveal.className}`} ref={reveal.ref as any}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'flex-end', justifyContent: 'space-between' }}>
          <div>
            <span className="kick">Reviews</span>
            <h2 className="h2" style={{ marginTop: 12 }}>What Travellers Say</h2>
            <span className="script-tag" style={{ fontSize: 22, color: 'var(--blue)' }}>Real trips. Real peace of mind.</span>
          </div>
          {areSamples && (
            <span className="chip" style={{ background: 'var(--cloud)', color: 'var(--slate)', border: '1px solid var(--mist)', fontSize: 13 }}>
              <Icon name="i-info" className="ico s xs" />Sample reviews &middot; add real ones in Admin &rarr; Insurance page
            </span>
          )}
        </div>
        <div className="g3" style={{ marginTop: 36 }}>
          {reviews.map((r) => (
            <figure className="card lift rev" key={r.name}>
              <div className="rev-top">
                <span className="stars" aria-label="5 out of 5 stars">
                  {Array.from({ length: 5 }, (_, i) => <Icon key={i} name="i-star" className="star" />)}
                </span>
                <span className="chip" style={{ fontSize: 13, minHeight: 28 }}>{r.tag}</span>
              </div>
              <blockquote>&ldquo;{r.quote}&rdquo;</blockquote>
              <figcaption>
                <img
                  src={(r as { avatar?: string }).avatar || r.photo || photo('avatar-1.jpg')}
                  alt={r.name}
                  width={44}
                  height={44}
                  loading="lazy"
                  style={{ borderRadius: '50%', objectFit: 'cover', flexShrink: 0 }}
                />
                <span style={{ flex: 1 }}>
                  <span style={{ display: 'block', fontWeight: 600 }}>{r.name}</span>
                  <span className="tiny">{r.place}</span>
                </span>
                <span className="cc">{r.cc}</span>
              </figcaption>
            </figure>
          ))}
        </div>
      </div>
    </section>
  );
}
