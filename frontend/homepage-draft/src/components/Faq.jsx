import Icon from './Icon.jsx';
import { site } from '../data/site.js';
import { useReveal } from '../hooks.js';

/* A few questions from each service's Help centre page (routes/homepage_draft.py _faqs), edited
 * where the Help centre is; the rest are one click away. None published: no section. */
export default function Faq() {
  const head = useReveal();
  const list = useReveal(0.1);
  if (!site.faqs.length) return null;
  return (
    <section className="sec hfaq" id="faq" aria-labelledby="faq-h">
      <div className="wrap hfaq-in">
        <div className="hfaq-head rv-up" ref={head}>
          <span className="kick">Questions</span>
          <h2 className="h2" id="faq-h">Questions Families <em>Ask Us</em></h2>
          <p className="lede">Short answers to what families ask before they start.</p>
          <a className="lnk" href={site.helpUrl}>More answers in our Help centre<Icon name="arrow" /></a>
        </div>
        <div className="hfaq-list rv-stagger" ref={list}>
          {site.faqs.map((f, i) => (
            <details className="hfaq-q" key={i} style={{ '--d': `${i * 60}ms` }}>
              <summary>{f.question}<span className="hfaq-pm" aria-hidden="true" /></summary>
              <p>{f.answer}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}
