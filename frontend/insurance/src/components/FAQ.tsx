import { useState } from 'react';
import Icon from './Icon';
import { useReveal } from '../hooks/useReveal';
import { fromServer, site } from '../data/site';

const FAQS = [
  ['What is travel insurance?', 'A policy that can help cover eligible costs from unexpected events on a trip, such as medical emergencies, delays or lost baggage.'],
  ['What does travel insurance cover?', 'It varies by plan. Common benefits include emergency medical expenses, evacuation, trip interruption and baggage. Always check the policy wording.'],
  ['Is travel insurance mandatory?', 'For some destinations and visa types, yes, for example many Schengen visa applications. Check official sources for your trip.'],
  ['What is visitor insurance?', 'Travel medical cover for people visiting another country, such as parents staying with family abroad or tourists.'],
  ['Can I buy travel insurance online?', 'Yes. Get a quote, compare 65+ A-rated plans and buy online. Your policy documents are sent digitally.'],
] as const;

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

  // Managed on the ordinary Admin -> Help & FAQ screen, under the travel-insurance category.
  // Falling back to the shipped set when none are entered is deliberate: these five answers are
  // generic and correct, and an empty FAQ section helps nobody.
  const faqs = fromServer(
    site.faqs?.map((f) => [f.question, f.answer] as Pair),
    FAQS as unknown as Pair[],
  );
  const columns = columnsOf(faqs);

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
