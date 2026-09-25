import { useState } from 'react';
import Icon from './Icon';
 import { photo } from '../data/site';
import CountrySelect from './CountrySelect';
import SideDecor from './SideDecor';
import FlightPath from './FlightPath';
import { useReveal } from '../hooks/useReveal';
import { buildPlanQuoteUrl } from '../utils/quoteUrl';
import { planFor, requestQuoteUrl } from '../utils/quoteRequest';

const today = new Date().toISOString().slice(0, 10);

const PLANS = [
  { id: 'visitors', icon: 'i-shield', title: 'Visitors', subtitle: 'Visiting the USA', presection: 'visitorUSA' },
  { id: 'medical', icon: 'i-plane', title: 'Travel Medical', subtitle: 'Canada, Australia & rest of world', presection: 'travelOutsideUSA' },
  { id: 'schengen', icon: 'i-globe', title: 'Schengen', subtitle: 'Europe visa cover', presection: 'schengen' },
] as const;

export default function InsuranceQuoteForm() {
  const reveal = useReveal<HTMLElement>();
  const [plan, setPlan] = useState<typeof PLANS[number]['id']>('visitors');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [citizenship, setCitizenship] = useState('India');
  const [destination, setDestination] = useState('Canada');
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
    const presection = PLANS.find((p) => p.id === plan)!.presection;
    // Through our own endpoint first: it prices with the parameters we have verified against the
    // partner's widget and records the lead, so somebody who never comes back can be followed up.
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
        <span className="script-tag iform-flank-cap" style={{ color: 'var(--blue)' }}>Ready when you are.</span>
      </div>
      <div className="iform-flank right">
        <div className="iform-photo">
          <img src={photo('story-tourists.jpg')} alt="Historic bridge in Paris lit up at dusk" loading="lazy" />
        </div>
      </div>

      <div className={`wrap iform-wrap ${reveal.className}`} ref={reveal.ref as any}>
      <form className="iform" onSubmit={handleSubmit}>
        <div className="iform-hd" style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'flex-end', gap: 12 }}>
          <div>
            <h2 className="h3">Travel Insurance</h2>
            <p className="small">Choose your cover and get live quotes in seconds.</p>
          </div>
          <span className="script-tag" style={{ fontSize: 20, color: 'var(--blue)' }}>Coverage in minutes.</span>
        </div>

        <div className="iform-panel">
          <div className="plan-grid" role="radiogroup" aria-label="Plan type">
            {PLANS.map((p) => (
              <button
                key={p.id}
                type="button"
                className={`plan-card${plan === p.id ? ' on' : ''}`}
                role="radio"
                aria-checked={plan === p.id}
                onClick={() => setPlan(p.id)}
              >
                <span className="plan-card-ic"><Icon name={p.icon} className={plan === p.id ? 'ico w' : 'ico'} /></span>
                <span>
                  <span className="plan-card-tt">{p.title}</span>
                  <span className="plan-card-sub">{p.subtitle}</span>
                </span>
                <span className="plan-card-chk"><Icon name="i-check" className="ico w xs" /></span>
              </button>
            ))}
          </div>

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
                <input className="inp" id="if-end" type="date" min={start || today} required value={end} onChange={(e) => setEnd(e.target.value)} />
              </span>
            </p>
            <p className="fg">
              <label className="lbl" htmlFor="if-cit">Country of citizenship <span style={{ color: 'var(--blue)' }}>*</span></label>
              <span className="iw"><Icon name="i-passport" className="ico sm" />
                <CountrySelect id="if-cit" className="inp" value={citizenship} onChange={setCitizenship} required />
              </span>
            </p>
            {isMedical && (
              <p className="fg">
                <label className="lbl" htmlFor="if-dest">Travelling to <span style={{ color: 'var(--blue)' }}>*</span></label>
                <span className="iw"><Icon name="i-pin" className="ico sm" />
                  <CountrySelect id="if-dest" className="inp" value={destination} onChange={setDestination} required />
                </span>
              </p>
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
              <label className="lbl" htmlFor="if-tel">Phone <span className="tiny">(optional)</span></label>
              <span className="iw"><Icon name="i-mobile" className="ico sm" />
                <input className="inp" id="if-tel" type="tel" placeholder="+91 98765 43210" value={phone} onChange={(e) => setPhone(e.target.value)} />
              </span>
            </p>
          </div>

          <div className="iform-ft">
            <span className="iform-trust">
              <span className="l1"><Icon name="i-lock" className="ico g sm" />Free quote &middot; no account needed</span>
              <span>Live pricing from <b style={{ color: 'var(--navy)' }}>Preventia360</b></span>
            </span>
            <button className="btn btn-p btn-lg" type="submit">
              Get free quotes<Icon name="i-arrow" className="ico w sm" />
            </button>
          </div>
        </div>

        <p className="iform-note">
          In partnership with <b style={{ color: 'var(--navy)' }}>Preventia360</b> &mdash; quotes are priced live on their site, where you complete the purchase.
        </p>
      </form>
      </div>
    </section>
  );
}
