import Icon from './Icon';
import { useQuote } from '../context/QuoteContext';
import { useReveal } from '../hooks/useReveal';
import { photo } from '../data/site';

export default function FinalCTA() {
  const { openQuote } = useQuote();
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section className="sec fcta-sec">
      <div className={`wrap ${reveal.className}`} ref={reveal.ref as any}>
        <div className="fcta">
          <img
            className="fcta-bg"
            src={photo('cta-parents.jpg')}
            alt="Grandparents holding their grandchild at sunset as a plane passes overhead"
            loading="lazy"
            decoding="async"
          />
          <span className="fcta-scrim" aria-hidden="true" />

          {/* dashed flight path arcing across the top, as in the reference */}
          <svg className="fcta-path" viewBox="0 0 760 90" preserveAspectRatio="none" aria-hidden="true">
            <path d="M8 74 C 170 28, 330 14, 470 26" fill="none" stroke="#6B9BFF" strokeWidth="2.5"
                  strokeLinecap="round" strokeDasharray="2 12" />
          </svg>
          <Icon name="i-plane" className="fcta-plane" />
          <Icon name="i-pin" className="fcta-pin" />

          <span className="script-tag fcta-script">Their journey,<br />our cover</span>

          <div className="fcta-copy">
            <h2 className="fcta-h">Ready to Travel With More Confidence?</h2>
            <p className="fcta-lead">
              Compare 65+ A-rated plans for your parents&apos; visit &mdash; free quotes in under two minutes.
            </p>
            <div className="fcta-btns">
              <button className="btn fcta-a" type="button" onClick={() => openQuote()}>
                Get Your Free Quote
              </button>
              <a className="btn fcta-b" href="#contact">Talk to an Expert</a>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
