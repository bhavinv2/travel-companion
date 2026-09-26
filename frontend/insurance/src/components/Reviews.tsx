import Icon from './Icon';
import SideDecor from './SideDecor';
import { useReveal } from '../hooks/useReveal';
import { site } from '../data/site';

/** The colour rotation the design uses, continued for however many reviews are published. */
const TONES = ['amber', 'blue', 'green'];

export default function Reviews() {
  const reveal = useReveal<HTMLDivElement>();

  // Reviews are written by people who used the service and published once an admin approves
  // them -- the same pipeline the rest of the site uses. There is deliberately nothing to fall
  // back to: this component used to ship three invented customers, and three invented customers
  // on an insurance page cost more trust than an absent section does. No reviews, no section.
  const reviews = (site.reviews || []).map((r, i) => ({
    key: r.id || String(i),
    tone: TONES[i % TONES.length],
    tag: r.tag || '',
    quote: r.quote,
    name: r.name,
    place: r.place || '',
    rating: Math.min(Math.max(r.rating || 5, 1), 5),
    // Their own picture or their initial -- never a stock portrait. This used to fall back to
    // one of three photos from the design, which next to a real name and a real review reads as
    // a photograph of the person who wrote it.
    photo: r.photo || '',
    initial: (r.name || '?').trim().charAt(0).toUpperCase() || '?',
  }));

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
          {site.reviewsUrl && (
            <p className="tiny" style={{ marginTop: 10 }}>
              <a href={site.reviewsUrl}>Read them all, or leave your own</a>
            </p>
          )}
        </div>
        {/* few reviews should sit in the middle rather than hugging the left edge of a
            three-column grid that is mostly empty */}
        <div className={`rev-grid${reviews.length < 3 ? ' few' : ''}`}>
          {reviews.map((r) => (
            <figure className={`rev t-${r.tone}`} key={r.key}>
              <span className="rev-mark" aria-hidden="true">&rdquo;</span>
              {/* the rating they actually gave, not five painted on every card */}
              <span className="stars" aria-label={`${r.rating} out of 5 stars`}>
                {Array.from({ length: r.rating }, (_, i) => <Icon key={i} name="i-star" className="star" />)}
              </span>
              <blockquote>{r.quote}</blockquote>
              <figcaption>
                <span className="rev-av">
                  {r.photo
                    ? <img src={r.photo} alt="" width={46} height={46} loading="lazy" decoding="async" />
                    : <span className="rev-initial" aria-hidden="true">{r.initial}</span>}
                </span>
                <span className="rev-who">
                  <b>{r.name}</b>
                  <span>{r.place}</span>
                </span>
              </figcaption>
              {r.tag && <span className="rev-tag">{r.tag}</span>}
            </figure>
          ))}
        </div>
      </div>
    </section>
  );
}
