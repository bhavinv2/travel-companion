import { useEffect, useRef } from 'react';
import Icon from './Icon';
import CountrySelect, { DialSelect } from './CountrySelect';
import AgeGrid from './AgeGrid';
import { useQuote } from '../context/QuoteContext';
import { buildQuoteUrl } from '../utils/quoteUrl';
import { planFor, requestQuoteUrl } from '../utils/quoteRequest';

const today = new Date().toISOString().slice(0, 10);
const TITLES = ['Tell us about your trip', 'Who is travelling?', 'Your quotes are ready'];

export default function QuoteModal() {
  const { quoteOpen, closeQuote, step, goStep, form, setForm, setAge, setTravellers } = useQuote();
  const lastFocus = useRef<HTMLElement | null>(null);
  const url = buildQuoteUrl(form);

  useEffect(() => {
    if (quoteOpen) {
      lastFocus.current = document.activeElement as HTMLElement;
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
      lastFocus.current?.focus?.();
    }
    return () => { document.body.style.overflow = ''; };
  }, [quoteOpen]);

  useEffect(() => {
    if (!quoteOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') closeQuote();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [quoteOpen, closeQuote]);

  // reaching step 3 (either by finishing step 2, or a fully-filled search bar
  // jumping straight there) hands off to the live quote engine, same as the
  // original static page's goQuotes().
  useEffect(() => {
    if (!quoteOpen || step !== 3) return;
    let cancelled = false;
    const t = setTimeout(async () => {
      // Same hand-off as the plan form: our endpoint prices and records it, and the direct
      // partner link is the fallback so nobody is left on a spinner.
      const served = await requestQuoteUrl({
        plan: planFor(form.destination),
        start: form.start,
        end: form.end,
        citizenship: form.citizenship,
        destination: form.destination,
        ages: form.ages.slice(0, form.travellers),
        email: form.email,
        phone: form.phone ? `${form.dial} ${form.phone}`.trim() : '',
      });
      if (!cancelled) window.location.assign(served || url);
    }, 700);
    return () => { cancelled = true; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quoteOpen, step]);

  if (!quoteOpen) return null;

  function handleContinue() {
    goStep(2);
  }

  function handleSubmitStep2(e: React.FormEvent) {
    e.preventDefault();
    goStep(3);
  }

  return (
    <div className="ov" onMouseDown={(e) => { if (e.target === e.currentTarget) closeQuote(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="qTitle">
        <div className="modal-hd">
          <div>
            <div className="tiny" style={{ fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase' }}>Free travel insurance quote</div>
            <h2 id="qTitle" style={{ marginTop: 4, fontSize: 'clamp(24px,2.4vw,32px)', lineHeight: 1.25 }}>{TITLES[step - 1]}</h2>
          </div>
          <button className="rbtn" type="button" aria-label="Close quote form" style={{ background: 'var(--sky)' }} onClick={closeQuote}>
            <Icon name="i-x" className="ico n sm" />
          </button>
        </div>

        <ol className="prog">
          {[1, 2, 3].map((s) => (
            <li key={s} className={s < step ? 'done' : s === step ? 'now' : ''}>
              <span className="pn">{s < step ? <Icon name="i-check" className="ico w xs" /> : s}</span>
              <span className="pl">{['Trip Details', 'Traveller Details', 'Quotes'][s - 1]}</span>
              {s < 3 && <i />}
            </li>
          ))}
        </ol>

        <form className="modal-bd" noValidate onSubmit={handleSubmitStep2}>
          {step === 1 && (
            <div>
              <div className="mg3">
                <p className="fg">
                  <label className="lbl" htmlFor="m-dest">Destination</label>
                  <span className="iw"><Icon name="i-pin" className="ico sm" />
                    <CountrySelect id="m-dest" className="inp" value={form.destination} onChange={(v) => setForm({ destination: v })} />
                  </span>
                </p>
                <p className="fg">
                  <label className="lbl" htmlFor="m-start">Start date</label>
                  <span className="iw"><Icon name="i-cal" className="ico sm" />
                    <input className="inp" id="m-start" type="date" min={today} value={form.start}
                      onChange={(e) => { const start = e.target.value; setForm({ start, end: form.end && form.end < start ? start : form.end }); }} />
                  </span>
                </p>
                <p className="fg">
                  <label className="lbl" htmlFor="m-end">End date</label>
                  <span className="iw"><Icon name="i-cal" className="ico sm" />
                    <input className="inp" id="m-end" type="date" min={form.start || today} value={form.end} onChange={(e) => setForm({ end: e.target.value })} />
                  </span>
                </p>
                <div className="fg">
                  <span className="lbl" id="travLbl">Number of travellers</span>
                  <div className="stepper" style={{ border: '1.5px solid var(--mist)', borderRadius: 12, minHeight: 52, justifyContent: 'space-between', padding: '0 6px' }} role="group" aria-labelledby="travLbl">
                    <button className="sbtn" type="button" aria-label="Remove a traveller" style={{ border: 0, background: 'var(--sky)' }} disabled={form.travellers <= 1} onClick={() => setTravellers(form.travellers - 1)}>
                      <Icon name="i-minus" className="ico n sm" />
                    </button>
                    <output style={{ fontSize: 17, fontWeight: 600 }}>{form.travellers === 1 ? '1 traveller' : `${form.travellers} travellers`}</output>
                    <button className="sbtn" type="button" aria-label="Add a traveller" style={{ border: 0, background: 'var(--sky)' }} disabled={form.travellers >= 6} onClick={() => setTravellers(form.travellers + 1)}>
                      <Icon name="i-plus" className="ico sm" />
                    </button>
                  </div>
                </div>
                <p className="fg">
                  <label className="lbl" htmlFor="m-cit">Citizenship</label>
                  <span className="iw"><Icon name="i-passport" className="ico sm" />
                    <CountrySelect id="m-cit" className="inp" value={form.citizenship} onChange={(v) => setForm({ citizenship: v })} />
                  </span>
                </p>
                <p className="fg">
                  <label className="lbl" htmlFor="m-res">Country of residence</label>
                  <span className="iw"><Icon name="i-globe" className="ico sm" />
                    <CountrySelect id="m-res" className="inp" value={form.residence} onChange={(v) => setForm({ residence: v })} />
                  </span>
                </p>
              </div>
              <div style={{ marginTop: 18, background: 'var(--sky)', borderRadius: 16, padding: '16px 18px' }}>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 16px', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: 14, fontWeight: 600 }}>Traveller ages</span>
                  <span className="tiny">Age on the trip start date</span>
                </div>
                <AgeGrid count={form.travellers} prefix="age" values={form.ages} onChange={setAge} style={{ gridTemplateColumns: 'repeat(6,minmax(0,1fr))' }} />
              </div>
              <div className="modal-ft">
                <span className="tiny" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <Icon name="i-lock" className="ico s xs" />Your details stay private and are used only for your quote.
                </span>
                <button className="btn btn-p btn-lg" type="button" onClick={handleContinue}>
                  Continue<Icon name="i-arrow" className="ico w sm" />
                </button>
              </div>
            </div>
          )}

          {step === 2 && (
            <div>
              <div className="mg2">
                <p className="fg">
                  <label className="lbl" htmlFor="m-name">Lead traveller's full name</label>
                  <span className="iw"><Icon name="i-user" className="ico sm" />
                    <input className="inp" id="m-name" type="text" placeholder="As on passport" value={form.name} onChange={(e) => setForm({ name: e.target.value })} />
                  </span>
                </p>
                <p className="fg">
                  <label className="lbl" htmlFor="m-mail">Email for your quotes</label>
                  <span className="iw"><Icon name="i-mail" className="ico sm" />
                    <input className="inp" id="m-mail" type="email" placeholder="you@example.com" value={form.email} onChange={(e) => setForm({ email: e.target.value })} />
                  </span>
                </p>
                <div className="fg">
                  <label className="lbl" htmlFor="m-tel">Mobile number</label>
                  <span className="tel">
                    <DialSelect id="m-dial" value={form.dial} onChange={(v) => setForm({ dial: v })} />
                    <span className="iw" style={{ flex: 1 }}><Icon name="i-mobile" className="ico sm" />
                      <input className="inp" id="m-tel" type="tel" placeholder="00000 00000" value={form.phone} onChange={(e) => setForm({ phone: e.target.value })} />
                    </span>
                  </span>
                </div>
                <p className="fg">
                  <label className="lbl" htmlFor="m-purp">Purpose of trip</label>
                  <span className="iw"><Icon name="i-plane" className="ico sm" />
                    <select className="inp" id="m-purp" value={form.purpose} onChange={(e) => setForm({ purpose: e.target.value })}>
                      <option>Visiting family</option>
                      <option>Holiday</option>
                      <option>Business</option>
                      <option>Study</option>
                    </select>
                  </span>
                </p>
              </div>
              <fieldset className="pre">
                <legend style={{ fontSize: 16, fontWeight: 600, padding: 0 }}>Does any traveller have a pre-existing medical condition?</legend>
                <p className="tiny" style={{ marginTop: 2 }}>This helps show plans that fit. It won't affect which quotes you can see.</p>
                <div className="seg-g">
                  <button className={`seg${form.preExisting === 'no' ? ' on' : ''}`} type="button" aria-pressed={form.preExisting === 'no'} onClick={() => setForm({ preExisting: 'no' })}>No</button>
                  <button className={`seg${form.preExisting === 'yes' ? ' on' : ''}`} type="button" aria-pressed={form.preExisting === 'yes'} onClick={() => setForm({ preExisting: 'yes' })}>Yes</button>
                </div>
              </fieldset>
              <label className="consent">
                <input type="checkbox" checked={form.consent} onChange={(e) => setForm({ consent: e.target.checked })} />
                I agree to be contacted about my quote and accept the <a href="#about">Privacy Policy</a>.
              </label>
              <div className="modal-ft">
                <button className="btn btn-o" type="button" onClick={() => goStep(1)}>
                  <Icon name="i-back" className="ico n sm" />Back
                </button>
                <button className="btn btn-p btn-lg" type="submit">
                  View My Plans<Icon name="i-arrow" className="ico w sm" />
                </button>
              </div>
              <p className="tiny" style={{ marginTop: 12 }}>You'll be taken to our secure quote page to compare 65+ A-rated plans and buy online.</p>
            </div>
          )}

          {step === 3 && (
            <div className="center" style={{ padding: '26px 0 8px', gap: 14 }}>
              <span className="tile" style={{ width: 64, height: 64, borderRadius: 20 }}><Icon name="i-list" /></span>
              <h3 className="h3">Opening your travel insurance plans…</h3>
              <p className="small" style={{ maxWidth: 420, textAlign: 'center' }}>
                We're passing your trip details to our secure quote engine so you can compare plans and buy online.
              </p>
              <a className="btn btn-p btn-lg" href={url} rel="noopener noreferrer">
                View &amp; Buy My Plans<Icon name="i-arrow" className="ico w sm" />
              </a>
              <button className="btn btn-o" type="button" style={{ minHeight: 44 }} onClick={() => goStep(2)}>Edit my details</button>
            </div>
          )}
        </form>
      </div>
    </div>
  );
}
