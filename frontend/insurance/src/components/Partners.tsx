import Icon from './Icon';
import SideDecor from './SideDecor';
import { useReveal } from '../hooks/useReveal';

export default function Partners() {
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section className="sec-sm" aria-labelledby="partners-h" style={{ background: 'var(--cloud)' }}>
      <SideDecor icons={[
        { name: 'i-globe', side: 'left', top: '30%', size: 30, rotate: -8, opacity: 0.14 },
        { name: 'i-checkc', side: 'left', top: '70%', size: 90, rotate: 8, opacity: 0.06 },
        { name: 'i-star', side: 'right', top: '55%', size: 30, rotate: 10, opacity: 0.14 },
        { name: 'i-shield', side: 'right', top: '12%', size: 85, rotate: -10, opacity: 0.06 },
      ]} />
      <div className={`wrap center z1 ${reveal.className}`} ref={reveal.ref as any}>
        <span className="kick">Our insurance partners</span>
        <h2 className="h2" id="partners-h" style={{ marginTop: 12, maxWidth: 760 }}>
          Quote and Compare 65+ A-Rated Travel Insurance Plans
        </h2>
        <span className="script-tag" style={{ fontSize: 22, color: 'var(--marigold)' }}>Choice, made simple.</span>
        <p className="lead" style={{ marginTop: 12, maxWidth: 640 }}>
          Side-by-side quotes from leading travel and visitor insurance providers, in one place.
        </p>
        <div className="logos">
          <div className="lgo">
            <span className="tile" style={{ background: 'var(--sky)' }}><Icon name="i-shield" /></span>
            <b>Travel Insurance Services</b>
            <span>Provider logo</span>
          </div>
          <div className="lgo">
            <span className="tile" style={{ background: 'var(--sky)' }}><Icon name="i-hospital" /></span>
            <b>A-Rated Insurers</b>
            <span>Provider logo</span>
          </div>
          <div className="lgo">
            <span className="tile" style={{ background: 'var(--sky)' }}><Icon name="i-globe" /></span>
            <b>Global Assist Network</b>
            <span>Provider logo</span>
          </div>
          <div className="lgo">
            <span className="tile g"><Icon name="i-checkc" className="ico g" /></span>
            <b>Verified Underwriters</b>
            <span>Provider logo</span>
          </div>
          <div className="lgo lgo-more">
            <Icon name="i-list" className="ico" />
            <b>65+ plans</b>
            <span>Compare all</span>
          </div>
        </div>
        <p className="tiny" style={{ marginTop: 18 }}>Plan availability depends on your destination, age, citizenship and trip dates.</p>
      </div>
    </section>
  );
}
