import { useState } from 'react';
import Icon from './Icon';
import SideDecor from './SideDecor';
import { useReveal } from '../hooks/useReveal';
import { fromServer, site } from '../data/site';

const FAQS = [
  ['What is travel insurance?', 'A policy that can help cover eligible costs from unexpected events on a trip, such as medical emergencies, delays or lost baggage.'],
  ['What does travel insurance cover?', 'It varies by plan. Common benefits include emergency medical expenses, evacuation, trip interruption and baggage. Always check the policy wording.'],
  ['Is travel insurance mandatory?', 'For some destinations and visa types, yes, for example many Schengen visa applications. Check official sources for your trip.'],
  ['What is visitor insurance?', 'Travel medical cover for people visiting another country, such as parents staying with family abroad or tourists.'],
  ['Can I buy travel insurance online?', 'Yes. Get a quote, compare 65+ A-rated plans and buy online. Your policy documents are sent digitally.'],
] as const;

export default function FAQ() {
  const reveal = useReveal<HTMLDivElement>();
  const [openIndex, setOpenIndex] = useState(0);
  // Managed on the ordinary Admin -> Help & FAQ screen, under the travel-insurance category.
  const faqs = fromServer(
    site.faqs?.map((f) => [f.question, f.answer] as const),
    FAQS as unknown as (readonly [string, string])[],
  );

  return (
    <section className="sec" id="faq" style={{ background: 'var(--cloud)' }}>
      <SideDecor icons={[
        { name: 'i-info', side: 'left', top: '24%', size: 28, rotate: -8, opacity: 0.14 },
        { name: 'i-file', side: 'left', top: '64%', size: 90, rotate: 10, opacity: 0.06 },
        { name: 'i-checkc', side: 'right', top: '60%', size: 30, rotate: 8, opacity: 0.14 },
        { name: 'i-shield', side: 'right', top: '10%', size: 85, rotate: -10, opacity: 0.06 },
      ]} />
      <div className={`wrap z1 ${reveal.className}`} ref={reveal.ref as any}>
        <div className="center">
          <span className="kick">FAQs</span>
          <h2 className="h2" style={{ marginTop: 12, maxWidth: 820 }}>Frequently Asked Questions About Travel Insurance</h2>
          <span className="script-tag" style={{ fontSize: 22, color: 'var(--green)' }}>Answers, made simple.</span>
        </div>
        <div className="faq">
          {faqs.map(([q, a], i) => {
            const isOpen = openIndex === i;
            return (
              <div className={`fq${isOpen ? ' open' : ''}`} key={q}>
                <button
                  className="fq-b"
                  type="button"
                  aria-expanded={isOpen}
                  onClick={() => setOpenIndex(isOpen ? -1 : i)}
                >
                  <span>{q}</span>
                  <span className="fq-i"><Icon name={isOpen ? 'i-minus' : 'i-plus'} className="ico xs" /></span>
                </button>
                {isOpen && <div className="fq-a"><p className="small">{a}</p></div>}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
