import { Star } from './Icon.jsx';
import Rail from './Rail.jsx';
import { site } from '../data/site.js';
import { useReveal } from '../hooks.js';

/* Reviews real customers left and staff approved (routes/homepage_draft.py _reviews), the ones
 * picked for the home page first. None approved yet: no section -- the sample stories this page
 * was drafted with are gone, because a page about caring for parents trades on being believed. */
export default function Reviews() {
  const head = useReveal();
  const rail = useReveal(0.1);
  if (!site.reviews.length) return null;
  return (
    <section className="sec reviews" id="reviews" aria-labelledby="test-h">
      <div className="wrap">
        <div className="p2-head rv-up" ref={head}>
          <span className="kick">Testimonials</span>
          <h2 className="h2" id="test-h">What Families Say</h2>
          <p className="lede">In their own words: families who use NRI Parent Service.</p>
        </div>
        <div className="rv-zoom" ref={rail}>
          <Rail label="reviews" className="rv-rail">
            {site.reviews.map((r, i) => (
              <figure className="rv" key={i}>
                {r.service && <div className="rv-top"><span className="rv-svc">{r.service}</span></div>}
                <div className="rv-stars" aria-label={`${r.rating} out of 5 stars`}>
                  {[1, 2, 3, 4, 5].map((k) => <span key={k} className={k <= r.rating ? '' : 'off'}><Star /></span>)}
                </div>
                <blockquote><p>{r.quote}</p></blockquote>
                <figcaption>
                  {r.photo ? <img className="av" src={r.photo} alt="" loading="lazy" /> : <span className="av">{(r.name || '?').charAt(0).toUpperCase()}</span>}
                  <span><b>{r.name}</b></span>
                </figcaption>
              </figure>
            ))}
          </Rail>
        </div>
      </div>
    </section>
  );
}
