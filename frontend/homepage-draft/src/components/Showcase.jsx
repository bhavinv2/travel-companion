import Bg from './Bg.jsx';
import Rail from './Rail.jsx';
import { site } from '../data/site.js';
import { useReveal } from '../hooks.js';
// Travel Companion: the companion page's own photos (static/img/landing)
import tcBg from '../assets/photos/ins-cta-parents.jpg';
import tcPlane from '../assets/photos/tc-l3.jpg';
import rUsa from '../assets/photos/tc-l4.jpg';
import rCanada from '../assets/photos/tc-l5.jpg';
import rUk from '../assets/photos/tc-l6.jpg';
import rAustralia from '../assets/photos/tc-l7.jpg';
import rGermany from '../assets/photos/tc-l8.jpg';
// Travel Insurance: the insurance page's own photos
import insBg from '../assets/photos/ins-story-parents.jpg';
import bMedical from '../assets/photos/ins-benefit-medical.jpg';
import bHospital from '../assets/photos/ins-benefit-hospitalisation.jpg';
import bEvacuation from '../assets/photos/ins-benefit-evacuation.jpg';
import bInterruption from '../assets/photos/ins-benefit-interruption.jpg';
import bDelay from '../assets/photos/ins-benefit-delay.jpg';
import bBaggage from '../assets/photos/ins-benefit-baggage.jpg';
import img from '../assets/logos/img.png';
import worldtrips from '../assets/logos/worldtrips.png';
import trawick from '../assets/logos/trawick-international.png';
import sevenCorners from '../assets/logos/seven-corners.png';
import globalUw from '../assets/logos/global-underwriters.png';
import petersen from '../assets/logos/petersen-international-underwriters.png';
import tii from '../assets/logos/travel-insured-international.png';
import travelsafe from '../assets/logos/travelsafe-insurance.png';
import travelex from '../assets/logos/travelex.png';
import bcbs from '../assets/logos/bluecross-blueshield-global-solutions.png';
import cigna from '../assets/logos/cigna.png';
import battleface from '../assets/logos/battleface.png';
import hth from '../assets/logos/hth-worldwide.png';
// Sahayak: the Sahayak page's own photos
import sahBg from '../assets/photos/sah-family.jpg';
import sWellness from '../assets/photos/sah-svc-wellness.jpg';
import sLab from '../assets/photos/sah-svc-lab.jpg';
import sVitals from '../assets/photos/sah-svc-vitals.jpg';
import sOutpatient from '../assets/photos/sah-svc-outpatient.jpg';
import sInpatient from '../assets/photos/sah-svc-inpatient.jpg';
import sPharmacy from '../assets/photos/sah-svc-pharmacy.jpg';
import sVirtual from '../assets/photos/sah-svc-virtual-consult.jpg';
import sOther from '../assets/photos/sah-svc-other.jpg';
// Health & wellness
import hBg from '../assets/photos/sah-svc-demo.jpg';
import hDoctor from '../assets/photos/doctor-consultation.jpg';
import hGift from '../assets/photos/cta-care.jpg';
import hFit from '../assets/photos/health-hero.jpg';
import pApollo from '../assets/about/partner-apollo.png';
import pHealthcare from '../assets/about/partner-healthcare.png';
import pManipal from '../assets/about/partner-manipal.png';
import pMax from '../assets/about/partner-max.png';
import pStari from '../assets/about/partner-stari.png';
import pIcici from '../assets/about/partner-icicrelom.png';

/* The home page's four services, each drawn the way its own page draws it -- the same photos, the
 * same words, the same colours -- on a photo that runs edge to edge behind the section. What each
 * says about itself is what its live page says. */

function Head({ kick, id, title, accent, script, lede, center }) {
  const ref = useReveal();
  return (
    <div className={`sc-head rv-up${center ? ' center' : ''}`} ref={ref}>
      <span className="kick">{kick}</span>
      <h2 className="h2" id={id}>{title} <em>{accent}</em></h2>
      {script && <span className="script-tag">{script}</span>}
      {lede && <p className="lede">{lede}</p>}
    </div>
  );
}

function Points({ items }) {
  return <ul className="sc-points">{items.map((t) => <li key={t}>{t}</li>)}</ul>;
}

function Logos({ label, logos }) {
  return (
    <Rail label={label} className="logo-rail">
      {logos.map((l) => (
        <div className="lgo" key={l.name}>
          <img src={l.src} alt={l.name} loading="lazy" decoding="async" draggable={false} />
        </div>
      ))}
    </Rail>
  );
}

// ------------------------------------------------------------------------------------------- companion
const ROUTES = [
  { to: 'USA', img: rUsa, pos: 'center 60%' },
  { to: 'Canada', img: rCanada, pos: 'center' },
  { to: 'UK', img: rUk, pos: 'center' },
  { to: 'Australia', img: rAustralia, pos: 'center 60%' },
  { to: 'Germany', img: rGermany, pos: 'center 30%' },
];

export function Companion() {
  const media = useReveal();
  const routes = useReveal(0.1);
  return (
    <section className="sc sc-dark sc-tc" id="companion" aria-labelledby="tc-h">
      <Bg src={tcBg} pos="center 35%" />
      <div className="wrap sc-grid">
        <div>
          <Head kick="Travel Companion" id="tc-h" title="Their Journey, Our Support —" accent="a Safer, Happier Trip."
            script="Safer journeys, together."
            lede="Send your parents across the world with someone beside them: a fellow traveller on the same flight, who speaks their language." />
          <Points items={['A companion on the same flight, in their language', 'Help at check-in, immigration and transit',
            'Visitor medical insurance for the unexpected', 'You stay the main contact, every step']} />
          <div className="sc-ctas">
            <a className="btn btn-amber" href={site.companionUrl}>Find a Companion</a>
            <a className="btn btn-w" href={site.companionUrl}>Post a Trip for Your Parents</a>
          </div>
        </div>
        <div className="sc-media rv-zoom" ref={media}>
          <img className="sc-photo" src={tcPlane} loading="lazy" decoding="async"
            alt="An elderly couple on a flight, chatting with the travel companion beside them" />
          <div className="bpass" aria-hidden="true">
            <span className="bp-k">Passenger</span><b>Your parents</b>
            <span className="bp-route">HYD <i /> LHR</span>
            <span className="bp-tag">Matched on the same flight</span>
          </div>
        </div>
      </div>
      <div className="wrap">
        <p className="sc-sub">Popular routes</p>
        <div className="routes rv-stagger" ref={routes}>
          {ROUTES.map((r, i) => (
            <a className="route" href={site.companionUrl} key={r.to} style={{ '--d': `${i * 80}ms` }}>
              <img src={r.img} alt="" loading="lazy" decoding="async" style={{ objectPosition: r.pos }} />
              <span><small>India to</small><b>{r.to}</b></span>
            </a>
          ))}
        </div>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------------------------------- insurance
const BENEFITS = [
  { title: 'Emergency Medical Expenses', text: 'Eligible treatment costs abroad, within plan limits.', img: bMedical },
  { title: 'Hospitalisation Support', text: 'Help arranging admission, with direct billing where available.', img: bHospital },
  { title: 'Emergency Evacuation', text: 'Transfer to suitable care when medically necessary.', img: bEvacuation },
  { title: 'Trip Interruption', text: 'Eligible costs if you must cut a trip short.', img: bInterruption },
  { title: 'Trip Delay', text: 'Cover for eligible delays beyond the plan’s minimum delay period.', img: bDelay },
  { title: 'Baggage Protection', text: 'Eligible expenses from lost or delayed checked baggage.', img: bBaggage },
];
const INSURERS = [
  ['IMG', img], ['WorldTrips', worldtrips], ['Trawick International', trawick], ['Seven Corners', sevenCorners],
  ['Global Underwriters', globalUw], ['Petersen International Underwriters', petersen],
  ['Travel Insured International', tii], ['TravelSafe Insurance', travelsafe], ['Travelex', travelex],
  ['BlueCross BlueShield Global Solutions', bcbs], ['Cigna', cigna], ['battleface', battleface], ['HTH Worldwide', hth],
].map(([name, src]) => ({ name, src }));

export function Insurance() {
  const tiles = useReveal(0.1);
  const price = site.prices.insurance;
  return (
    <section className="sc sc-light sc-ins" id="insurance" aria-labelledby="ins-h">
      <Bg src={insBg} pos="70% center" />
      <div className="wrap sc-grid">
        <div>
          <Head kick="Travel Insurance" id="ins-h" title="Visitor Insurance for" accent="Parents Visiting You"
            script="Covered every corner."
            lede="When your parents fly out to see you, visitor insurance helps protect them from unexpected medical expenses and travel emergencies." />
          <Points items={['No medical exam required', 'Instant e-policy by email', 'Claims support in your language']} />
          <div className="sc-ctas">
            <a className="btn btn-p" href={site.insuranceUrl}>Get a Free Quote</a>
            <a className="btn btn-o" href={site.insuranceUrl}>Compare 65+ A-rated plans</a>
          </div>
          {price && <p className="sc-price">Travel insurance: <b>{price}</b></p>}
        </div>
      </div>
      <div className="wrap">
        <div className="tiles six rv-stagger" ref={tiles}>
          {BENEFITS.map((b, i) => (
            <a className="tile" href={site.insuranceUrl} key={b.title} style={{ '--d': `${i * 70}ms` }}>
              <img src={b.img} alt="" loading="lazy" decoding="async" />
              <span className="tile-b"><b>{b.title}</b><small>{b.text}</small></span>
            </a>
          ))}
        </div>
        <p className="sc-sub center">Plans from leading insurers</p>
        <Logos label="insurers" logos={INSURERS} />
      </div>
    </section>
  );
}

// ------------------------------------------------------------------------------------------- sahayak
const SERVICES = [
  { title: 'Vitals Check', img: sVitals, pos: '100% 50%' },
  { title: 'Lab Work', img: sLab, pos: '100% 50%' },
  { title: 'Wellness Screen', img: sWellness, pos: '30% 50%' },
  { title: 'Out-Patient Visit', img: sOutpatient, pos: '56% 30%' },
  { title: 'In-Patient Visit', img: sInpatient, pos: 'center' },
  { title: 'Pharmacy Delivery', img: sPharmacy, pos: '52% 30%' },
  { title: 'Virtual Consultation Support', img: sVirtual, pos: '40% 30%' },
  { title: 'Other Support', img: sOther, pos: '45% 35%' },
];

export function Sahayak() {
  const grid = useReveal(0.1);
  const price = site.prices.sahayak;
  return (
    <section className="sc sc-soft sc-sah" id="sahayak" aria-labelledby="sah-h">
      <Bg src={sahBg} pos="20% center" />
      <div className="wrap sc-grid sc-flip">
        <div>
          <Head kick="Sahayak" id="sah-h" title="A Health Professional With Your Parents," accent="Every Step"
            script="Someone qualified, and a record you can read."
            lede="Book a registered nurse to take your parents through whatever the health need is — the check, the test, the appointment, the hospital, the medicines — with every step recorded as it is done." />
          <ul className="chips">
            {['Registered, verified nurses', 'Care at home, no clinic queues', 'You stay informed', 'One-time or ongoing care'].map((t) => <li key={t}>{t}</li>)}
          </ul>
          <div className="sc-ctas">
            <a className="btn btn-p" href={site.sahayakUrl}>Book a Sahayak</a>
            <a className="btn btn-o" href={site.sahayakUrl}>Explore Sahayak Services</a>
          </div>
          {price && <p className="sc-price">Sahayak visits from <b>{price}</b></p>}
        </div>
      </div>
      <div className="wrap">
        <div className="tiles four rv-stagger" ref={grid}>
          {SERVICES.map((s, i) => (
            <a className="tile short" href={site.sahayakUrl} key={s.title} style={{ '--d': `${i * 60}ms` }}>
              <img src={s.img} alt="" loading="lazy" decoding="async" style={{ objectPosition: s.pos }} />
              <span className="tile-b"><b>{s.title}</b></span>
            </a>
          ))}
        </div>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------------------------------- health
const HEALTH = [
  { title: 'Virtual Doctor Consultation', img: hDoctor, pos: '35% 30%',
    text: 'Video consultations with a doctor from home. You can join the call from abroad.', cta: 'Book a Consultation' },
  { title: 'Gift Health', img: hGift, pos: '30% 40%',
    text: 'Give your parents the gift of better health, care and proactive support — even from miles away.', cta: 'Ask about Gift Health' },
  { title: 'Fit2Fly', img: hFit, pos: '70% center',
    text: 'Prepare your parents for safe and confident travel with the right health assessment before their journey.', cta: 'Ask about Fit2Fly' },
];
// the About page's partners, under the names it gives them
const HOSPITALS = [['Apollo', pApollo], ['Health Care', pHealthcare], ['Manipal Hospitals', pManipal],
  ['MAX Health Care', pMax], ['STARI Health Insurance', pStari], ['ICICRELom', pIcici]].map(([name, src]) => ({ name, src }));

export function Health() {
  const cards = useReveal(0.1);
  return (
    <section className="sc sc-dark sc-health" id="health" aria-labelledby="hl-h">
      <Bg src={hBg} pos="center 30%" />
      <div className="wrap">
        <Head center kick="Health & Wellness" id="hl-h" title="Their Health," accent="Looked After From Abroad"
          script="Care that keeps them well."
          lede="Doctors, health checks and pre-travel assessments for your parents in India, arranged from wherever you are." />
        <div className="hcards rv-stagger" ref={cards}>
          {HEALTH.map((h, i) => (
            <article className="hcard" key={h.title} style={{ '--d': `${i * 100}ms` }}>
              <img src={h.img} alt="" loading="lazy" decoding="async" style={{ objectPosition: h.pos }} />
              <div className="hcard-b">
                <h3>{h.title}</h3>
                <p>{h.text}</p>
                <a className="lnk" href={site.contactUrl}>{h.cta}</a>
              </div>
            </article>
          ))}
        </div>
        <p className="sc-sub center">Our healthcare partners</p>
        <Logos label="healthcare partners" logos={HOSPITALS} />
      </div>
    </section>
  );
}
