import Icon from './Icon';
 import { photo } from '../data/site';
import SideDecor from './SideDecor';
import { useQuote } from '../context/QuoteContext';
import { useReveal } from '../hooks/useReveal';

const CARDS = [
  {
    icon: 'i-heart', title: 'Emergency Medical Expenses', desc: 'Eligible treatment costs abroad, within plan limits.',
    photo: photo('benefit-medical.jpg'), alt: 'Doctor ready to treat a travelling patient',
  },
  {
    icon: 'i-hospital', title: 'Hospitalisation Support', desc: 'Help arranging admission, with direct billing where available.',
    photo: photo('benefit-hospitalisation.jpg'), alt: 'Clean hospital reception desk',
  },
  {
    icon: 'i-ambulance', title: 'Emergency Evacuation', desc: 'Transfer to suitable care when medically necessary.',
    photo: photo('benefit-evacuation.jpg'), alt: 'Hospital building with an emergency entrance sign',
  },
  {
    icon: 'i-route', title: 'Trip Interruption', desc: 'Eligible costs if you must cut a trip short.',
    photo: photo('benefit-interruption.jpg'), alt: 'City street at dusk',
  },
  {
    icon: 'i-clock', title: 'Trip Delay', desc: 'Support for covered delays beyond set hours.',
    photo: photo('benefit-delay.jpg'), alt: 'Hand holding a small clock',
  },
  {
    icon: 'i-bag', title: 'Baggage Protection', desc: 'Cover for eligible lost or delayed checked bags.',
    photo: photo('benefit-baggage.jpg'), alt: 'Travel backpack packed and ready',
  },
  {
    icon: 'i-phone', title: '24/7 Assistance', desc: 'A helpline for emergencies, in any time zone.',
    photo: photo('benefit-support-247.jpg'), alt: 'Two people shaking hands over paperwork',
  },
  {
    icon: 'i-globe', title: 'Travel Support', desc: 'Guidance on documents, clinics and next steps.',
    photo: photo('benefit-support-docs.jpg'), alt: 'Hand signing travel paperwork',
  },
];

export default function Benefits() {
  const { openQuote } = useQuote();
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section className="sec" id="benefits" style={{ background: 'var(--cloud)' }}>
      <SideDecor icons={[
        { name: 'i-checkc', side: 'left', top: '24%', size: 30, rotate: -6, opacity: 0.14 },
        { name: 'i-shield', side: 'left', top: '68%', size: 105, rotate: 10, opacity: 0.06 },
        { name: 'i-list', side: 'right', top: '60%', size: 30, rotate: 8, opacity: 0.14 },
        { name: 'i-hospital', side: 'right', top: '10%', size: 90, rotate: -8, opacity: 0.06 },
      ]} />
      <div className={`wrap z1 ${reveal.className}`} ref={reveal.ref as any}>
        <div className="center">
          <span className="kick">Benefits</span>
          <h2 className="h2" style={{ marginTop: 12, maxWidth: 820 }}>Benefits of Travel Insurance</h2>
          <span className="script-tag" style={{ fontSize: 24, color: 'var(--green)' }}>Every detail, protected.</span>
          <p className="lead" style={{ marginTop: 12, maxWidth: 660 }}>
            Explore the protection a single travel insurance plan can bring &mdash; from eligible medical costs to trip disruptions and support when you need it.
          </p>
        </div>
        <div className="bgrid4">
          {CARDS.map((c) => (
            <article className="bcard2" key={c.title}>
              <img className="bcard-img" src={c.photo} alt={c.alt} loading="lazy" />
              <div className="bcard-ov">
                <span className="bcard-ic"><Icon name={c.icon} className="ico w sm" /></span>
                <h3 className="bcard-t2">{c.title}</h3>
                <p className="bcard-d2">{c.desc}</p>
              </div>
            </article>
          ))}
        </div>
        <div className="center" style={{ marginTop: 44 }}>
          <button className="btn btn-p btn-lg" type="button" onClick={() => openQuote()}>
            Explore Travel Insurance Options
            <Icon name="i-arrow" className="ico w sm" />
          </button>
        </div>
      </div>
    </section>
  );
}
