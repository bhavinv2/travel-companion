import { useState } from 'react';
import Icon from './Icon';
import { useReveal } from '../hooks/useReveal';
import { site } from '../data/site';

type Pair = readonly [string, string];

/** Two independent stacks — a shared grid row would leave a hole in one column
 *  whenever the answer in the other column opened. Split per render now, because the
 *  questions come from the server and their number is not known at build time. */
function columnsOf(faqs: readonly Pair[]) {
  const split = Math.ceil(faqs.length / 2);
  return [
    faqs.slice(0, split).map((f, i) => [f, i] as const),
    faqs.slice(split).map((f, i) => [f, i + split] as const),
  ];
}

export default function FAQ() {
  const reveal = useReveal<HTMLDivElement>();
  const [openIndex, setOpenIndex] = useState(-1);

  // Admin -> Travel Insurance -> Help & FAQ, and nowhere else. This component used to fall back
  // to five answers baked into the build, which meant the page could show text that appeared on
  // no screen anybody could edit. Those answers are shipped defaults in the help centre now --
  // visible, editable, deletable. Delete them all and the section goes, which is the honest
  // outcome: the server's JSON-LD drops its FAQPage in the same breath.
  const faqs: Pair[] = (site.faqs || []).map((f) => [f.question, f.answer] as Pair);
  const columns = columnsOf(faqs);

  if (!faqs.length) return null;

  return (
    <section className="sec faq-sec" id="faq">
      <span className="faq-blob" aria-hidden="true" />
      <span className="faq-blob two" aria-hidden="true" />
      <div className={`wrap z1 ${reveal.className}`} ref={reveal.ref as any}>
        <div className="center">
          <span className="kick">FAQs</span>
          <h2 className="h2" style={{ marginTop: 12, maxWidth: 820 }}>Frequently Asked Questions About Travel Insurance</h2>
          <span className="script-tag" style={{ fontSize: 22, color: 'var(--blue)' }}>Answers, made simple.</span>
        </div>
        <div className="faq">
          {columns.map((column, ci) => (
            <div className="faq-col" key={ci}>
              {column.map(([[q, a], i]) => {
                const isOpen = openIndex === i;
                return (
                  <div className={`fq${isOpen ? ' open' : ''}`} key={q}>
                    <button
                      className="fq-b"
                      type="button"
                      aria-expanded={isOpen}
                      onClick={() => setOpenIndex(isOpen ? -1 : i)}
                    >
                      <span className="fq-q"><Icon name="i-sparkle" className="ico s xs fq-spark" />{q}</span>
                      <span className="fq-i"><Icon name={isOpen ? 'i-minus' : 'i-plus'} className="ico xs" /></span>
                    </button>
                    <div className="fq-wrap" aria-hidden={!isOpen}>
                      <div><div className="fq-a"><p className="small">{a}</p></div></div>
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
