import { Doodles, Note, Snap } from './Deco.jsx';
import helpPhoto from '../assets/photos/support-agent.webp';
import { site } from '../data/site.js';
import { useReveal } from '../hooks.js';

/* A few questions from each service's Help centre page (routes/homepage_draft.py _faqs), edited
 * where the Help centre is; the rest are one click away. None published: no section. */
export default function Faq() {
  const head = useReveal();
  const list = useReveal(0.1);
  if (!site.faqs.length) return null;
  return (
    <section className="sc sc-light hfaq" id="faq" aria-labelledby="faq-h">
      <Doodles items={[['chat', { top: '10%', right: '4%', size: 30, rotate: 8 }], ['pin', { top: '84%', right: '8%', size: 26, rotate: -10 }]]} />
      <div className="wrap hfaq-in">
        <div className="hfaq-head rv-up" ref={head}>
          <span className="kick">Questions</span>
          <h2 className="h2" id="faq-h">Questions Families <em>Ask Us</em></h2>
          <p className="lede">Short answers to what families ask before they start.</p>
          <span className="script-tag">Answers, before you ask.</span>
          <a className="lnk" href={site.helpUrl}>More answers in our Help centre</a>
          <span className="hfaq-deco" aria-hidden="true">
            <Snap src={helpPhoto} caption="Ask us anything" pos="center 20%" at={{ top: '0', left: '4%' }} rotate={-5} width={160} tone="help" />
            <Note at={{ top: '64px', left: '50%' }} rotate={4} icon="chat" tone="blue">We are here to help</Note>
          </span>
        </div>
        <div className="hfaq-list rv-stagger" ref={list}>
          {site.faqs.map((f, i) => (
            <details className="hfaq-q" key={i} style={{ '--d': `${i * 60}ms` }}>
              <summary>
                <span className="hfaq-qt">{f.service && <small>{f.service}</small>}{f.question}</span>
                <span className="hfaq-pm" aria-hidden="true" />
              </summary>
              <p>{f.answer}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}
