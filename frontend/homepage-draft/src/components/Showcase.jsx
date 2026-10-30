import Bg from './Bg.jsx';
import { Doodles, Note, Snap, Trail } from './Deco.jsx';
import Rail from './Rail.jsx';
import { site, talk, TALK } from '../data/site.js';
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
// Health: the hospitals on the About page
import hBg from '../assets/photos/sah-svc-demo.jpg';
import pApollo from '../assets/about/partner-apollo.png';
import pHealthcare from '../assets/about/partner-healthcare.png';
import pManipal from '../assets/about/partner-manipal.png';
import pMax from '../assets/about/partner-max.png';
import pStari from '../assets/about/partner-stari.png';
import pIcici from '../assets/about/partner-icicrelom.png';
// snapshots for the empty spaces (Deco.jsx)
import snapSydney from '../assets/photos/tc-l7.jpg';
import snapUpdate from '../assets/photos/why-updates.jpg';
import snapWell from '../assets/photos/sah-svc-wellness.jpg';
import snapWalk from '../assets/photos/ins-story-senior.jpg';

/* After the journey has walked through all six services, a band for each with what the journey
 * does not show: the routes companions fly, what visitor insurance covers and who writes it, what
 * a Sahayak handles, and the hospitals we work with. Each on a photo edge to edge, in its own
 * page's colours and words. */

function Head({ kick, id, title, accent, script, lede }) {
  const ref = useReveal();
  return (
    <div className="sc-head center rv-up" ref={ref}>
      <span className="kick">{kick}</span>
      <h2 className="h2" id={id}>{title} <em>{accent}</em></h2>
      {script && <span className="script-tag">{script}</span>}
      {lede && <p className="lede">{lede}</p>}
    </div>
  );
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

// flanking the heading, outside the content (Deco.jsx hides them on narrow screens)
const LEFT = 'max(18px, calc(50% - 660px))';

// ------------------------------------------------------------------------------------------- companion
const ROUTES = [
  { to: 'USA', img: rUsa, pos: 'center 60%' },
  { to: 'Canada', img: rCanada, pos: 'center' },
  { to: 'UK', img: rUk, pos: 'center' },
  { to: 'Australia', img: rAustralia, pos: 'center 60%' },
  { to: 'Germany', img: rGermany, pos: 'center 30%' },
];

export function Companion() {
  const routes = useReveal(0.1);
  return (
    <section className="sc sc-dark sc-tc sc-band" id="companion" aria-labelledby="tc-h">
      <Bg src={tcBg} pos="center 35%" />
      <Snap src={tcPlane} caption="Same flight, same language" pos="center 40%" at={{ top: '64px', left: LEFT }} rotate={-6} width={160} tone="amber" />
      <Note at={{ top: '96px', right: LEFT }} rotate={5} icon="plane">Safer journeys, together</Note>
      <Trail at={{ top: '150px', right: 'max(40px, calc(50% - 600px))' }} width={170} tone="amber" flip />
      <Doodles items={[['globe', { top: '58%', left: '2%', size: 30, rotate: 8, opacity: 0.18 }],
        ['pin', { top: '70%', right: '2.5%', size: 28, rotate: 10, opacity: 0.2 }]]} />
      <div className="wrap">
        <Head kick="Travel Companion" id="tc-h" title="Popular Routes for" accent="Parents Flying Out"
          lede="A fellow traveller on the same flight, who speaks their language, on the routes families ask for most." />
        <div className="routes rv-stagger" ref={routes}>
          {ROUTES.map((r, i) => (
            <a className="route" href={site.companionUrl} key={r.to} style={{ '--d': `${i * 80}ms` }}>
              <img src={r.img} alt="" loading="lazy" decoding="async" style={{ objectPosition: r.pos }} />
              <span><small>India to</small><b>{r.to}</b></span>
            </a>
          ))}
        </div>
        <div className="sc-ctas center">
          <a className="btn btn-amber" href={site.companionUrl}>Find a Companion</a>
          <a className="btn btn-w" href={site.companionUrl}>Post a Trip for Your Parents</a>
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
  return (
    <section className="sc sc-light sc-band sc-ins" id="insurance" aria-labelledby="ins-h">
      <Bg src={insBg} pos="70% center" />
      <Snap src={snapSydney} caption="Protected every mile." at={{ top: '64px', left: LEFT }} rotate={-6} width={160} />
      <Note at={{ top: '100px', right: LEFT }} rotate={-5} icon="plane" tone="blue">Insured before takeoff</Note>
      <Doodles items={[['shield', { top: '54%', left: '2.5%', size: 32, rotate: -8, opacity: 0.18 }],
        ['globe', { top: '24%', right: '3%', size: 30, rotate: 10, opacity: 0.18 }]]} />
      <div className="wrap">
        <Head kick="Travel Insurance" id="ins-h" title="What Visitor Insurance" accent="Covers"
          script="Covered every corner." />
        <ul className="chips row">
          {['No medical exam required', 'Instant e-policy by email', 'Claims support in your language'].map((t) => <li key={t}>{t}</li>)}
        </ul>
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
        <div className="sc-ctas center">
          <a className="btn btn-p" href={site.insuranceUrl}>Get a Free Quote</a>
          <a className="btn btn-o" href={site.insuranceUrl}>Compare 65+ A-rated plans</a>
        </div>
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
  return (
    <section className="sc sc-soft sc-band sc-sah" id="sahayak" aria-labelledby="sah-h">
      <Bg src={sahBg} pos="20% center" />
      <Snap src={sVitals} caption="Vitals checked, 10:12" pos="100% 50%" at={{ top: '64px', left: LEFT }} rotate={-6} width={160} />
      <Snap src={snapUpdate} caption="Update shared with you" pos="center 30%" at={{ top: '80px', right: LEFT }} rotate={5} width={155} tone="amber" />
      <Doodles items={[['steth', { top: '56%', left: '2.5%', size: 32, rotate: 10, opacity: 0.2 }],
        ['heart', { top: '64%', right: '3%', size: 28, rotate: -10, opacity: 0.22 }]]} />
      <div className="wrap">
        <Head kick="Sahayak" id="sah-h" title="What a Sahayak" accent="Handles for Them"
          script="Someone qualified, and a record you can read." />
        <ul className="chips row">
          {['Registered, verified nurses', 'Care at home, no clinic queues', 'You stay informed', 'One-time or ongoing care'].map((t) => <li key={t}>{t}</li>)}
        </ul>
        <div className="tiles four rv-stagger" ref={grid}>
          {SERVICES.map((s, i) => (
            <a className="tile short" href={site.sahayakUrl} key={s.title} style={{ '--d': `${i * 60}ms` }}>
              <img src={s.img} alt="" loading="lazy" decoding="async" style={{ objectPosition: s.pos }} />
              <span className="tile-b"><b>{s.title}</b></span>
            </a>
          ))}
        </div>
        <div className="sc-ctas center">
          <a className="btn btn-p" href={site.sahayakUrl}>Book a Sahayak</a>
          <a className="btn btn-o" href={site.sahayakUrl}>Explore Sahayak Services</a>
        </div>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------------------------------- health
// the About page's partners, under the names it gives them
const HOSPITALS = [['Apollo', pApollo], ['Health Care', pHealthcare], ['Manipal Hospitals', pManipal],
  ['MAX Health Care', pMax], ['STARI Health Insurance', pStari], ['ICICRELom', pIcici]].map(([name, src]) => ({ name, src }));

export function Health() {
  return (
    <section className="sc sc-dark sc-band sc-health" id="health" aria-labelledby="hl-h">
      <Bg src={hBg} pos="center 30%" />
      <Snap src={snapWell} caption="Feeling well" pos="30% 50%" at={{ top: '56px', left: LEFT }} rotate={-6} width={150} />
      <Snap src={snapWalk} caption="Out and about" pos="center 35%" at={{ top: '72px', right: LEFT }} rotate={5} width={140} />
      <Doodles items={[['steth', { top: '62%', left: '2.5%', size: 32, rotate: -10, opacity: 0.2 }],
        ['heart', { top: '66%', right: '2.5%', size: 28, rotate: 8, opacity: 0.2 }]]} />
      <div className="wrap">
        <Head kick="Health & Wellness" id="hl-h" title="Our Healthcare" accent="Partners"
          script="Care that keeps them well."
          lede="Doctor consultations, health checks and pre-travel assessments for your parents in India, with the hospitals and health partners we work with." />
        <Logos label="healthcare partners" logos={HOSPITALS} />
        <div className="sc-ctas center">
          <a className="btn btn-amber" href={site.contactUrl} onClick={talk}>{TALK}</a>
        </div>
      </div>
    </section>
  );
}
