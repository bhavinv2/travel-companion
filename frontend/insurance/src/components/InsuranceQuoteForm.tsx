import { useState } from 'react';
import Icon from './Icon';
import { DestinationCombo } from './CountryCombo';
import SideDecor from './SideDecor';
import FlightPath from './FlightPath';
import { useReveal } from '../hooks/useReveal';
import { buildPlanQuoteUrl } from '../utils/quoteUrl';
import { photo, site } from '../data/site';
import { planFor, requestQuoteUrl } from '../utils/quoteRequest';

/** Today in the visitor's own timezone, as yyyy-mm-dd. */
const today = (() => {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
})();

const PLANS = [
  {
    id: 'visitors', icon: 'i-shield', tone: 'blue', title: 'Visitors', subtitle: 'Visiting the USA',
    presection: 'visitorUSA', heading: 'Visitor Insurance',
    blurb: 'Cover for parents and family visiting the USA — medical emergencies, hospitalisation and doctor visits while they stay with you.',
  },
  {
    id: 'medical', icon: 'i-plane', tone: 'amber', title: 'Travel Medical', subtitle: 'Canada, Australia & rest of world',
    presection: 'travelOutsideUSA', heading: 'Travel Medical Insurance',
    blurb: 'Cover for Canada, Australia and the rest of the world — emergency treatment, evacuation and trip disruptions abroad.',
  },
  {
    id: 'schengen', icon: 'i-globe', tone: 'green', title: 'Schengen', subtitle: 'Europe visa cover',
    presection: 'schengen', heading: 'Schengen Visa Insurance',
    blurb: 'Built for Schengen visa applications — minimum medical cover across all 29 Schengen countries, with documents by email.',
  },
] as const;

export default function InsuranceQuoteForm() {
  const reveal = useReveal<HTMLElement>();
  const [plan, setPlan] = useState<typeof PLANS[number]['id']>('visitors');
  const active = PLANS.find((p) => p.id === plan)!;
  const [start, setStart] = useState(today);
  const [end, setEnd] = useState('');
  const [citizenship, setCitizenship] = useState('India');
  const [citizenshipInvalid, setCitizenshipInvalid] = useState(false);
  const [destination, setDestination] = useState('Canada');
  const [destinationInvalid, setDestinationInvalid] = useState(false);
  const [ages, setAges] = useState<string[]>(['', '']);
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');

  function setAge(i: number, v: string) {
    setAges((a) => a.map((x, idx) => (idx === i ? v : x)));
  }
  function addTraveller() {
    setAges((a) => (a.length < 8 ? [...a, ''] : a));
  }
  function removeTraveller(i: number) {
    setAges((a) => (a.length > 1 ? a.filter((_, idx) => idx !== i) : a));
  }

  const isMedical = plan === 'medical';

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    let ok = true;
    if (!citizenship) { setCitizenshipInvalid(true); ok = false; }
    if (isMedical && !destination) { setDestinationInvalid(true); ok = false; }
    if (!ok) return;
    const presection = PLANS.find((p) => p.id === plan)!.presection;
    // Through our own endpoint first: it prices with the parameters we have verified against the
    // partner's widget and records the lead, so somebody who never comes back can still be
    // followed up. The direct partner link stays as the fallback.
    const served = await requestQuoteUrl({
      plan: planFor(destination, presection),
      start, end, citizenship, ages, email, phone,
      destination: isMedical ? destination : undefined,
    });
    window.location.assign(served || buildPlanQuoteUrl({
      presection, start, end, citizenship, ages, email, phone,
      destination: isMedical ? destination : undefined,
    }));
  }

  return (
    <section className="iform-outer" aria-label="Travel insurance quote form">
      {/* travel motifs scattered across the navy ground, as in the reference */}
      <span className="iform-motifs" aria-hidden="true">
        <Icon name="i-plane" className="ifm ifm-1" rotate={-18} />
        <Icon name="i-globe" className="ifm ifm-2" />
        <Icon name="i-plane" className="ifm ifm-3" rotate={12} />
        <Icon name="i-bag" className="ifm ifm-4" rotate={-8} />
        <Icon name="i-pin" className="ifm ifm-5" />
        <Icon name="i-heart" className="ifm ifm-6" rotate={10} />
        <svg className="ifm-trail" viewBox="0 0 900 120" preserveAspectRatio="none">
          <path d="M6 96 C 190 26, 430 110, 640 44 C 760 8, 840 26, 894 58" fill="none"
                stroke="var(--horizon)" strokeWidth="2.5" strokeDasharray="2 13" strokeLinecap="round" />
        </svg>
      </span>
      <span className="script-tag iform-tagline">Insured<br />before<br />takeoff</span>
      <FlightPath side="left" top="40px" />
      <FlightPath side="right" top="270px" />
      <SideDecor icons={[
        { name: 'i-pin', side: 'left', top: '4%', size: 26, rotate: -8, opacity: 0.16 },
        { name: 'i-heart', side: 'left', top: '86%', size: 30, rotate: 10, opacity: 0.14 },
        { name: 'i-bag', side: 'right', top: '2%', size: 110, rotate: 8, opacity: 0.08 },
        { name: 'i-globe', side: 'right', top: '48%', size: 30, rotate: -10, opacity: 0.15 },
      ]} />
      <div className="iform-flank left">
        <div className="iform-photo">
          <img src={photo('story-international.jpg')} alt="View from an aeroplane window above the clouds" loading="lazy" />
        </div>
        <span className="script-tag iform-flank-cap" style={{ color: 'var(--blue)' }}>Protected every mile.</span>
      </div>
      <div className="iform-flank right">
        <div className="iform-photo">
          <img src={photo('story-tourists.jpg')} alt="Historic bridge in Paris lit up at dusk" loading="lazy" />
        </div>
        <span className="script-tag iform-flank-cap" style={{ color: 'var(--horizon)' }}>Covered every corner.</span>
      </div>

      <div className={`wrap narrow iform-wrap ${reveal.className}`} ref={reveal.ref as any}>
      <div className="iform-tabs" role="radiogroup" aria-label="Plan type">
        {PLANS.map((p) => (
          <button
            key={p.id}
            type="button"
            className={`iform-tab t-${p.tone}${plan === p.id ? ' on' : ''}`}
            role="radio"
            aria-checked={plan === p.id}
            onClick={() => setPlan(p.id)}
          >
            <span className="iform-tab-ic"><Icon name={p.icon} /></span>
            <span className="iform-tab-tx">
              <b>{p.title}</b>
              <span>{p.subtitle}</span>
            </span>
          </button>
        ))}
      </div>
      <form className="iform" onSubmit={handleSubmit}>
        <div className="iform-hd" key={active.id}>
          <h2 className="h3">{active.heading}</h2>
          <p className="small">{active.blurb}</p>
        </div>

        <div className="iform-panel">
          <div className={`iform-fields${isMedical ? ' iform-fields-4' : ''}`}>
            <p className="fg">
              <label className="lbl" htmlFor="if-start">Coverage starts <span style={{ color: 'var(--blue)' }}>*</span></label>
              <span className="iw"><Icon name="i-cal" className="ico sm" />
                <input
                  className="inp" id="if-start" type="date" min={today} required
                  value={start}
                  onChange={(e) => { const v = e.target.value; setStart(v); if (end && end < v) setEnd(v); }}
                />
              </span>
            </p>
            <p className="fg">
              <label className="lbl" htmlFor="if-end">Coverage ends <span style={{ color: 'var(--blue)' }}>*</span></label>
              <span className="iw"><Icon name="i-cal" className="ico sm" />
                <input
                  className={`inp${end ? '' : ' is-empty'}`} id="if-end" type="date" min={start || today} required
                  value={end} onChange={(e) => setEnd(e.target.value)}
                />
                {!end && <span className="date-ph" aria-hidden="true">dd-mm-yyyy</span>}
              </span>
            </p>
            <div className="fg">
              <label className="lbl" htmlFor="if-cit">Country of citizenship <span style={{ color: 'var(--blue)' }}>*</span></label>
              <DestinationCombo
                id="if-cit"
                value={citizenship}
                invalid={citizenshipInvalid}
                onChange={(v) => { setCitizenship(v); setCitizenshipInvalid(false); }}
              />
            </div>
            {isMedical && (
              <div className="fg">
                <label className="lbl" htmlFor="if-dest">Travelling to <span style={{ color: 'var(--blue)' }}>*</span></label>
                <DestinationCombo
                  id="if-dest"
                  value={destination}
                  invalid={destinationInvalid}
                  onChange={(v) => { setDestination(v); setDestinationInvalid(false); }}
                />
              </div>
            )}
          </div>

          <div className="iform-ages">
            <div className="iform-ages-hd">
              <label className="lbl" style={{ marginBottom: 0 }}>Traveller ages <span style={{ color: 'var(--blue)' }}>*</span></label>
              <button className="add-traveller" type="button" onClick={addTraveller}>
                <Icon name="i-plus" className="ico sm" />Add traveller
              </button>
            </div>
            <div className="age-row">
              {ages.map((v, i) => (
                <span className="age-chip" key={i}>
                  <span className="num">{i + 1}</span>
                  <input
                    type="number" min={0} max={110} inputMode="numeric"
                    placeholder={i === 0 ? 'e.g. 65' : 'Age'}
                    value={v}
                    onChange={(e) => setAge(i, e.target.value)}
                  />
                  {ages.length > 1 && (
                    <button type="button" aria-label={`Remove traveller ${i + 1}`} onClick={() => removeTraveller(i)}>
                      <Icon name="i-x" className="ico s xs" />
                    </button>
                  )}
                </span>
              ))}
            </div>
            <p className="tiny" style={{ marginTop: 10 }}>Add everyone travelling &mdash; each age is priced separately.</p>
          </div>

          <div className="iform-contact">
            <p className="fg">
              <label className="lbl" htmlFor="if-mail">Your email <span style={{ color: 'var(--blue)' }}>*</span> <span className="tiny">(for follow-up)</span></label>
              <span className="iw"><Icon name="i-mail" className="ico sm" />
                <input className="inp" id="if-mail" type="email" placeholder="you@example.com" required value={email} onChange={(e) => setEmail(e.target.value)} />
              </span>
            </p>
            <p className="fg">
              <label className="lbl" htmlFor="if-tel">Phone <span style={{ color: 'var(--blue)' }}>*</span></label>
              <span className="iw"><Icon name="i-mobile" className="ico sm" />
                <input className="inp" id="if-tel" type="tel" required placeholder="+91 98765 43210" value={phone} onChange={(e) => setPhone(e.target.value)} />
              </span>
            </p>
          </div>

          {/* Both of these are claims about what the business actually offers, so they are entered
              in Admin -> Insurance page and render only once somebody has. A price anchor is the
              strongest thing this form could say -- and an invented one is the worst. */}
          {(site.priceFrom || site.assurances?.length) && (
            <div className="iform-claims">
              {site.priceFrom && (
                <p className="iform-price">
                  <Icon name="i-wallet" className="ico sm" />
                  <b>{site.priceFrom}</b>
                </p>
              )}
              {!!site.assurances?.length && (
                <ul className="iform-assure">
                  {site.assurances.map((a) => (
                    <li key={a}><Icon name="i-check" className="ico g xs" />{a}</li>
                  ))}
                </ul>
              )}
            </div>
          )}

          <div className="iform-ft">
            <span className="iform-trust">
              <span className="l1"><Icon name="i-lock" className="ico g sm" />Free quote &middot; no account needed</span>
              <span>Live pricing from <a href="https://preventia360.com/" target="_blank" rel="noopener noreferrer" className="preventia-link">Preventia360</a></span>
            </span>
            <button className="btn btn-p btn-lg" type="submit">
              Get a Free Quote<Icon name="i-arrow" className="ico w sm" />
            </button>
          </div>
        </div>

        <p className="iform-note iform-note-hl">
          In partnership with <a href="https://preventia360.com/" target="_blank" rel="noopener noreferrer" className="preventia-link">Preventia360</a> &mdash; quotes are priced live on their site, where you complete the purchase.
        </p>
      </form>
      </div>
    </section>
  );
}
