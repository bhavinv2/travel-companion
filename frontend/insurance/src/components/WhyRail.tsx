import Icon from './Icon';
import SideDecor from './SideDecor';
import { useReveal } from '../hooks/useReveal';
import { useDragRail } from '../hooks/useDragRail';
import { photo } from '../data/site';

const CARDS = [
  {
    tag: 'Medical cover', title: 'Emergency Medical Expenses',
    desc: 'Eligible treatment costs abroad, within plan limits.',
    photo: photo('benefit-medical.jpg'), alt: 'Doctor ready to treat a travelling patient',
  },
  {
    tag: 'Hospital cover', title: 'Hospitalisation Support',
    desc: 'Help arranging admission, with direct billing where available.',
    photo: photo('benefit-hospitalisation.jpg'), alt: 'Clean hospital reception desk',
  },
  {
    tag: 'Evacuation', title: 'Emergency Evacuation',
    desc: 'Transfer to suitable care when medically necessary.',
    photo: photo('benefit-evacuation.jpg'), alt: 'Hospital building with an emergency entrance sign',
  },
  {
    tag: 'Trip cover', title: 'Trip Interruption',
    desc: 'Eligible costs if you must cut a trip short.',
    photo: photo('benefit-interruption.jpg'), alt: 'City street at dusk',
  },
  {
    tag: 'Delay cover', title: 'Trip Delay',
    desc: 'Support for covered delays beyond set hours.',
    photo: photo('benefit-delay.jpg'), alt: 'Hand holding a small clock',
  },
  {
    tag: 'Baggage cover', title: 'Baggage Protection',
    desc: 'Cover for eligible lost or delayed checked bags.',
    photo: photo('benefit-baggage.jpg'), alt: 'Travel backpack packed and ready',
  },
  {
    tag: '24/7 cover', title: '24/7 Assistance',
    desc: 'A helpline for emergencies, in any time zone.',
    photo: photo('benefit-support-247.jpg'), alt: 'Two people shaking hands over paperwork',
  },
  {
    tag: 'Support cover', title: 'Travel Support',
    desc: 'Guidance on documents, clinics and next steps.',
    photo: photo('benefit-support-docs.jpg'), alt: 'Hand signing travel paperwork',
  },
];

export default function WhyRail() {
  const reveal = useReveal<HTMLDivElement>();
  const { railProps, scrollRail, canScrollLeft, canScrollRight } = useDragRail();

  return (
    <section className="sec" id="benefits">
      <SideDecor icons={[
        { name: 'i-route', side: 'left', top: '22%', size: 30, rotate: -10, opacity: 0.14 },
        { name: 'i-bag', side: 'left', top: '64%', size: 100, rotate: 12, opacity: 0.06 },
        { name: 'i-wallet', side: 'right', top: '58%', size: 30, rotate: 8, opacity: 0.14 },
        { name: 'i-clock', side: 'right', top: '12%', size: 80, rotate: -8, opacity: 0.06 },
      ]} />
      <div className={`wrap z1 ${reveal.className}`} ref={reveal.ref as any}>
        <div className="rail-hd">
          <div>
            <span className="kick">Why it matters</span>
            <h2 className="h2" style={{ marginTop: 12 }}>Why You Need Travel Insurance</h2>
            <span className="script-tag" style={{ fontSize: 22, color: 'var(--marigold)' }}>Prevent medical bills from disrupting your trip.</span>
            <p className="lead" style={{ marginTop: 10 }}>Because unexpected moments shouldn't become unexpected expenses.</p>
          </div>
        </div>

        <div className="rail-wrap-box">
          <button
            className="rnav-side left"
            type="button"
            aria-label="Previous cards"
            disabled={!canScrollLeft}
            onClick={() => scrollRail('prev')}
          >
            <Icon name="i-back" className="ico sm" />
          </button>

          <div
            className="rail"
            tabIndex={0}
            role="group"
            aria-label="Reasons to buy travel insurance — drag or use arrows"
            {...railProps}
          >
            {CARDS.map((c) => (
              <article className="wtile" key={c.title}>
                <img src={c.photo} alt={c.alt} loading="lazy" decoding="async" draggable={false} />
                <span className="wtile-scrim" aria-hidden="true" />
                <span className="wtile-tag">{c.tag}</span>
                <div className="wtile-body">
                  <h3>{c.title}</h3>
                  {/* The reveal carries the explanation, nothing more. There used to be a
                      quote button in every one of these cards -- eight identical buttons at one
                      scroll position, with the section's own CTAs already above and below it. */}
                  <div className="wtile-reveal">
                    <div>
                      <p>{c.desc}</p>
                    </div>
                  </div>
                </div>
              </article>
            ))}
          </div>

          <button
            className="rnav-side right"
            type="button"
            aria-label="Next cards"
            disabled={!canScrollRight}
            onClick={() => scrollRail('next')}
          >
            <Icon name="i-arrow" className="ico sm" />
          </button>
        </div>
      </div>
    </section>
  );
}
