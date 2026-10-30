import Icon from './Icon.jsx';
import Rail from './Rail.jsx';
import { useReveal } from '../hooks.js';
import { site } from '../data/site.js';
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

/* The same partner logos, in the same carousel, as the travel-insurance page
 * (frontend/insurance/src/components/Partners.tsx). */
const LOGOS = [
  { name: 'IMG', src: img, w: 149, h: 66 },
  { name: 'WorldTrips', src: worldtrips, w: 202, h: 47 },
  { name: 'Trawick International', src: trawick, w: 209, h: 52 },
  { name: 'Seven Corners', src: sevenCorners, w: 197, h: 131 },
  { name: 'Global Underwriters', src: globalUw, w: 203, h: 50 },
  { name: 'Petersen International Underwriters', src: petersen, w: 346, h: 81 },
  { name: 'Travel Insured International', src: tii, w: 126, h: 109 },
  { name: 'TravelSafe Insurance', src: travelsafe, w: 102, h: 27 },
  { name: 'Travelex', src: travelex, w: 102, h: 33 },
  { name: 'BlueCross BlueShield Global Solutions', src: bcbs, w: 455, h: 74 },
  { name: 'Cigna', src: cigna, w: 165, h: 67 },
  { name: 'battleface', src: battleface, w: 211, h: 35 },
  { name: 'HTH Worldwide', src: hth, w: 99, h: 19 },
];

export default function Partners() {
  const head = useReveal();
  return (
    <section className="partners2" id="partners" aria-labelledby="part-h">
      <div className="wrap">
        <div className="p2-head rv-up" ref={head}>
          <span className="kick">Our network</span>
          <h2 className="h2" id="part-h">Our Trusted Partners</h2>
          <span className="script-tag st-blue">Partners you can trust.</span>
          <p className="lede">Working with trusted healthcare, travel and insurance partners to support your parents better — including 65+ A-rated travel insurance plans to quote and compare.</p>
        </div>
        <Rail label="partners" className="logo-rail">
          {LOGOS.map((l) => (
            <div className="lgo" key={l.name}>
              <img src={l.src} alt={l.name} width={l.w} height={l.h} loading="lazy" decoding="async" draggable={false} />
            </div>
          ))}
        </Rail>
        <div className="p2-foot">
          <a className="lnk" href={site.insuranceUrl}>Compare travel insurance plans<Icon name="arrow" /></a>
        </div>
      </div>
    </section>
  );
}
