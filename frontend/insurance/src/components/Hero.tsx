import Icon from './Icon';
import { useReveal } from '../hooks/useReveal';
import { asset, photo } from '../data/site';

export default function Hero() {
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section className="hero" id="top">
      <img className="hero-bg" src={photo('hero-banner.jpg')} alt="Senior Indian couple with their suitcases by the departures gate windows at sunset" loading="eager" />
      <div className="wrap hero-in" ref={reveal.ref as any}>
        <div className="hero-copy reveal in">
          <span className="script-tag hero-script">Worry-free travel for you &amp; your loved ones.</span>
          <span className="chip">
            <Icon name="i-globe" className="ico xs" />
            International travel &amp; visitor insurance
          </span>
          <h1 className="h1" style={{ marginTop: 22 }}>Travel Further. Stay Protected.</h1>
          <p className="lead" style={{ marginTop: 20, maxWidth: 520 }}>
            Travel insurance for your journey, with cover for eligible medical emergencies, trip disruptions, and other travel-related expenses.
          </p>
          <p className="small" style={{ marginTop: 12, maxWidth: 520 }}>
            Get quotes and compare visitor insurance for the USA, super visa and visitor insurance for Canada, and Schengen visa cover online through NRI Parent Service.
          </p>
        </div>
      </div>
      <div className="hero-badge">
        <img src={asset('logo-mark.png')} alt="" width={200} height={161} />
        <span className="hero-badge-tx">
          <b>NRI</b>
          <b className="hb-blue">Parent Service</b>
          <span>Your Parents, Our Priority</span>
        </span>
      </div>
    </section>
  );
}
