import Icon from './Icon';
import SideDecor from './SideDecor';
import { useReveal } from '../hooks/useReveal';
import { useDragRail } from '../hooks/useDragRail';
import { asset } from '../data/site';

type Logo = { name: string; file: string; w: number; h: number };

const LOGOS: Logo[] = [
  { name: 'IMG', file: 'img.png', w: 149, h: 66 },
  { name: 'WorldTrips', file: 'worldtrips.png', w: 202, h: 47 },
  { name: 'Trawick International', file: 'trawick-international.png', w: 209, h: 52 },
  { name: 'Seven Corners', file: 'seven-corners.png', w: 197, h: 131 },
  { name: 'Global Underwriters', file: 'global-underwriters.png', w: 203, h: 50 },
  { name: 'Petersen International Underwriters', file: 'petersen-international-underwriters.png', w: 346, h: 81 },
  { name: 'Travel Insured International', file: 'travel-insured-international.png', w: 126, h: 109 },
  { name: 'TravelSafe Insurance', file: 'travelsafe-insurance.png', w: 102, h: 27 },
  { name: 'Travelex', file: 'travelex.png', w: 102, h: 33 },
  { name: 'BlueCross BlueShield Global Solutions', file: 'bluecross-blueshield-global-solutions.png', w: 455, h: 74 },
  { name: 'Cigna', file: 'cigna.png', w: 165, h: 67 },
  { name: 'battleface', file: 'battleface.png', w: 211, h: 35 },
  { name: 'HTH Worldwide', file: 'hth-worldwide.png', w: 99, h: 19 },
];

export default function Partners() {
  const reveal = useReveal<HTMLDivElement>();
  const { railProps, scrollRail, canScrollLeft, canScrollRight } = useDragRail();

  return (
    <section className="sec-sm pt-sec" aria-labelledby="partners-h">
      <span className="pt-glow" aria-hidden="true" />
      <SideDecor icons={[
        { name: 'i-globe', side: 'left', top: '30%', size: 30, rotate: -8, opacity: 0.14 },
        { name: 'i-checkc', side: 'left', top: '70%', size: 90, rotate: 8, opacity: 0.06 },
        { name: 'i-star', side: 'right', top: '55%', size: 30, rotate: 10, opacity: 0.14 },
        { name: 'i-shield', side: 'right', top: '12%', size: 85, rotate: -10, opacity: 0.06 },
      ]} />
      <div className={`wrap center z1 ${reveal.className}`} ref={reveal.ref as any}>
        <span className="kick pt-kick">Our insurance partners</span>
        <h2 className="h2" id="partners-h" style={{ marginTop: 12, maxWidth: 760 }}>
          Quote and Compare 65+ A-Rated Travel Insurance Plans
        </h2>
        <span className="script-tag" style={{ fontSize: 22, color: 'var(--marigold)' }}>Choice, made simple.</span>
        <p className="lead" style={{ marginTop: 12, maxWidth: 640 }}>
          Side-by-side quotes from leading travel and visitor insurance providers, in one place.
        </p>
        <ul className="pt-points">
          <li className="t-blue"><Icon name="i-list" className="ico sm" />Compare side by side</li>
          <li className="t-green"><Icon name="i-file" className="ico sm" />Documents by email</li>
          <li className="t-amber"><Icon name="i-clock" className="ico sm" />Buy online in minutes</li>
        </ul>
        <div className="rail-wrap-box">
          <button
            className="rnav-side left"
            type="button"
            aria-label="Previous partners"
            disabled={!canScrollLeft}
            onClick={() => scrollRail('prev')}
          >
            <Icon name="i-back" className="ico sm" />
          </button>

          <div
            className="rail logo-rail"
            tabIndex={0}
            role="group"
            aria-label="Insurance partners — drag or use arrows"
            {...railProps}
          >
            {LOGOS.map((logo) => (
              <div className="lgo" key={logo.file}>
                <img
                  src={asset(`logos/${logo.file}`)}
                  alt={logo.name}
                  width={logo.w}
                  height={logo.h}
                  loading="lazy"
                  decoding="async"
                  draggable={false}
                />
              </div>
            ))}
          </div>

          <button
            className="rnav-side right"
            type="button"
            aria-label="Next partners"
            disabled={!canScrollRight}
            onClick={() => scrollRail('next')}
          >
            <Icon name="i-arrow" className="ico sm" />
          </button>
        </div>
        <p className="tiny" style={{ marginTop: 18 }}>Plan availability depends on your destination, age, citizenship and trip dates.</p>
      </div>
    </section>
  );
}
