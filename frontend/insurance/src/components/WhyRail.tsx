import { useRef } from 'react';
import Icon from './Icon';
 import { photo } from '../data/site';
import SideDecor from './SideDecor';
import { useQuote } from '../context/QuoteContext';
import { useReveal } from '../hooks/useReveal';

const CARDS = [
  {
    icon: 'i-heart', tag: 'Medical cover', title: 'Medical Emergencies',
    desc: 'Treatment abroad can cost far more than at home.',
    photo: photo('why-medical.jpg'), alt: 'Doctor in scrubs ready to treat a travelling patient',
  },
  {
    icon: 'i-route', tag: 'Trip cover', title: 'Trip Interruptions',
    desc: 'Plans change when something happens at home.',
    photo: photo('why-interruption.jpg'), alt: 'City street at dusk, a trip cut short',
  },
  {
    icon: 'i-bag', tag: 'Baggage cover', title: 'Lost or Delayed Baggage',
    desc: 'Essentials to tide you over until bags arrive.',
    photo: photo('why-baggage.jpg'), alt: 'Travel backpack packed and ready',
  },
  {
    icon: 'i-clock', tag: 'Delay cover', title: 'Flight Delays',
    desc: 'Long waits mean meals, transfers and extra nights.',
    photo: photo('why-delay.jpg'), alt: 'Hand holding a small clock, marking time lost to a delay',
  },
  {
    icon: 'i-ambulance', tag: 'Evacuation', title: 'Emergency Evacuation',
    desc: 'Transport to suitable care when it is needed.',
    photo: photo('why-evacuation.jpg'), alt: 'Hospital building with an emergency entrance sign',
  },
  {
    icon: 'i-wallet', tag: 'Trip costs', title: 'Unexpected Expenses',
    desc: "Rebookings, extra stays and costs you didn't plan for.",
    photo: photo('why-expenses.jpg'), alt: 'Foreign currency notes spread out, representing trip costs',
  },
];

export default function WhyRail() {
  const { openQuote } = useQuote();
  const reveal = useReveal<HTMLDivElement>();
  const railRef = useRef<HTMLDivElement>(null);
  const drag = useRef({ down: false, sx: 0, sl: 0, moved: 0 });

  function onPointerDown(e: React.PointerEvent) {
    if ((e.target as HTMLElement).closest('button')) return;
    const rail = railRef.current;
    if (!rail) return;
    drag.current = { down: true, sx: e.clientX, sl: rail.scrollLeft, moved: 0 };
    rail.classList.add('drag');
    rail.setPointerCapture(e.pointerId);
  }
  function onPointerMove(e: React.PointerEvent) {
    if (!drag.current.down) return;
    const rail = railRef.current;
    if (!rail) return;
    const dx = e.clientX - drag.current.sx;
    drag.current.moved = Math.abs(dx);
    rail.scrollLeft = drag.current.sl - dx;
  }
  function endDrag() {
    drag.current.down = false;
    railRef.current?.classList.remove('drag');
  }
  function scrollRail(dir: 'prev' | 'next') {
    const rail = railRef.current;
    if (!rail) return;
    const w = (rail.firstElementChild as HTMLElement)?.offsetWidth ?? 300;
    rail.scrollBy({ left: dir === 'next' ? w + 20 : -(w + 20), behavior: 'smooth' });
  }

  return (
    <section className="sec">
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
            <span className="script-tag" style={{ fontSize: 22, color: 'var(--marigold)' }}>Expect the unexpected.</span>
            <p className="lead" style={{ marginTop: 10 }}>Because unexpected moments shouldn't become unexpected expenses.</p>
          </div>
          <div className="rail-nav">
            <button className="rnav" type="button" aria-label="Previous cards" onClick={() => scrollRail('prev')}>
              <Icon name="i-back" className="ico n sm" />
            </button>
            <button className="rnav" type="button" aria-label="Next cards" onClick={() => scrollRail('next')}>
              <Icon name="i-arrow" className="ico n sm" />
            </button>
          </div>
        </div>
        <div
          className="rail"
          ref={railRef}
          tabIndex={0}
          role="group"
          aria-label="Reasons to buy travel insurance — drag or use arrows"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
        >
          {CARDS.map((c) => (
            <article className="wcard" key={c.title}>
              <div className="tile"><Icon name={c.icon} /></div>
              <h3 className="t3" style={{ marginTop: 14 }}>{c.title}</h3>
              <p className="small">{c.desc}</p>
              <div className="wcard-img">
                <span className="tag">{c.tag}</span>
                <img src={c.photo} alt={c.alt} loading="lazy" />
                <button className="btn btn-p wcta" type="button" onClick={() => openQuote()}>Get Quotes</button>
              </div>
            </article>
          ))}
        </div>
        <p className="rail-hint tiny"><Icon name="i-arrow" className="ico s xs" />Drag or swipe to see more reasons</p>
      </div>
    </section>
  );
}
