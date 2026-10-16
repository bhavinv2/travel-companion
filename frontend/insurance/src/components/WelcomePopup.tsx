import { useEffect, useRef, useState } from 'react';
import Icon from './Icon';
import { PhoneCombo, DestinationCombo } from './CountryCombo';
import { spokenNumber } from '../utils/phone';
import { useQuote } from '../context/QuoteContext';
import { photo, site } from '../data/site';
import { track } from '../utils/track';

// Fallback only: the served page injects the number staff set in the admin screens.
const WHATSAPP_NUMBER = '918019111360';

export default function WelcomePopup() {
  const { consultOpen, openConsult, closeConsult, quoteOpen } = useQuote();
  const [name, setName] = useState('');
  const [country, setCountry] = useState('India');
  const [countryInvalid, setCountryInvalid] = useState(false);
  // +1: the parents are in India, the person filling this in usually is not
  const [dial, setDial] = useState('+1');
  // the country itself, not just its code: +1 alone cannot say US or Canada
  const [iso, setIso] = useState('US');
  const [tel, setTel] = useState('');
  const [email, setEmail] = useState('');
  const [travel, setTravel] = useState('Canada');
  const [travelInvalid, setTravelInvalid] = useState(false);
  const [sent, setSent] = useState(false);
  // true: the server stored the enquiry; false: it did not; null: nowhere to send it (dev build)
  const [saved, setSaved] = useState<boolean | null>(null);
  const [waUrl, setWaUrl] = useState('');
  // The listeners below outlive a render, so they read the live value through a ref rather than
  // closing over a stale one.
  const quoteOpenRef = useRef(quoteOpen);
  quoteOpenRef.current = quoteOpen;

  /* Auto-open once per browser session. It used to fire at a flat 7 seconds, which lands on
     somebody who has just started reading the second section -- the most annoying possible
     moment, and the one that teaches people to close the thing without looking.
     Now it waits for a signal that they are actually finished or leaving:
       * the pointer leaves through the top of the window (heading for the tab bar or Back),
       * or they reach the foot of the page,
       * or two minutes pass, as a floor.
     Whichever comes first, and never while the quote modal is up. */
  useEffect(() => {
    try {
      if (sessionStorage.getItem('welShown')) return;
    } catch {
      // ignore storage errors (private browsing etc.)
    }
    let done = false;

    function fire() {
      if (done || quoteOpenRef.current) return;
      done = true;
      cleanup();
      openConsult();
      try { sessionStorage.setItem('welShown', '1'); } catch { /* ignore */ }
    }

    function onLeave(e: MouseEvent) {
      // only upward, and only a real exit -- moving onto a <select> popup also fires mouseout
      if (e.clientY <= 0 && !e.relatedTarget) fire();
    }
    function onScroll() {
      const seen = window.scrollY + window.innerHeight;
      if (seen >= document.body.scrollHeight - 400) fire();
    }

    // A touch screen has no pointer to leave the window, so the scroll signal and the floor are
    // what it gets. That is the right trade: on a phone the popup is the whole screen.
    document.addEventListener('mouseout', onLeave);
    window.addEventListener('scroll', onScroll, { passive: true });
    const t = setTimeout(fire, 120000);

    function cleanup() {
      document.removeEventListener('mouseout', onLeave);
      window.removeEventListener('scroll', onScroll);
      clearTimeout(t);
    }
    return cleanup;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!consultOpen) return;
    document.body.style.overflow = quoteOpen ? document.body.style.overflow : 'hidden';
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') closeConsult();
    }
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      if (!quoteOpen) document.body.style.overflow = '';
    };
  }, [consultOpen, quoteOpen, closeConsult]);

  useEffect(() => {
    if (!consultOpen) {
      setSent(false);
    }
  }, [consultOpen]);

  if (!consultOpen) return null;

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!e.currentTarget.checkValidity()) {
      e.currentTarget.reportValidity();
      return;
    }
    let ok = true;
    if (!country) { setCountryInvalid(true); ok = false; }
    if (!travel) { setTravelInvalid(true); ok = false; }
    if (!ok) return;
    const lines = [
      'Hello! I would like a travel insurance consultation.', '',
      `Name: ${name}`,
      `Country of residence: ${country}`,
      `Mobile: ${spokenNumber(dial, tel)}`,
      `Email: ${email}`,
      `Travel to: ${travel}`,
    ];
    const number = (site.whatsapp ?? WHATSAPP_NUMBER).replace(/[^0-9]/g, '');
    setWaUrl(`https://api.whatsapp.com/send/?phone=${number}&text=${encodeURIComponent(lines.join('\n'))}`);

    // A WhatsApp link somebody never clicks leaves no trace of the enquiry. Record it in the inbox
    // CS already works from first, hand off second; a failed POST must not block the hand-off.
    track('popup_lead');
    let stored: boolean | null = null;
    if (site.enquiryUrl) {
      try {
        const r = await fetch(site.enquiryUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(site.csrfToken ? { 'X-CSRFToken': site.csrfToken } : {}),
          },
          // the number and its country apart; the server normalises the pair to E.164
          body: JSON.stringify({ name, email, phone: tel.trim(), phone_cc: iso, destination: travel }),
        });
        stored = r.ok;
      } catch {
        stored = false;   /* the WhatsApp hand-off below still works */
      }
    }
    setSaved(stored);
    setSent(true);
  }

  return (
    <div className="ov" onMouseDown={(e) => { if (e.target === e.currentTarget) closeConsult(); }}>
      <div className="modal sm cpop" role="dialog" aria-modal="true" aria-labelledby="cpop-title">
        <button className="cpop-x" type="button" aria-label="Close" onClick={closeConsult}>
          <Icon name="i-x" className="ico n sm" />
        </button>

        {!sent ? (
          <form className="cpop-bd" onSubmit={handleSubmit}>
            <div className="cpop-plane" aria-hidden="true">
              <Icon name="i-plane" className="cpop-plane-ic" />
              <svg className="cpop-dots" viewBox="0 0 200 30" preserveAspectRatio="none">
                <path d="M4 22C60 4 140 28 198 6" fill="none" stroke="#B8D0FF" strokeWidth="2" strokeDasharray="1.5 7" strokeLinecap="round" />
              </svg>
            </div>
            <h2 className="cpop-h" id="cpop-title">Request a <span>Consultation</span></h2>
            <p className="cpop-sub">Get expert guidance to help you choose travel insurance.</p>
            <div className="cpop-fields">
              <span className="cfield">
                <Icon name="i-user" className="ico s sm" />
                <input className="cinp" type="text" placeholder="Name" required value={name} onChange={(e) => setName(e.target.value)} />
              </span>
              <div>
                <label className="lbl" style={{ fontSize: 13, marginBottom: 6 }}>Country of residence</label>
                <DestinationCombo value={country} invalid={countryInvalid} onChange={(v) => { setCountry(v); setCountryInvalid(false); }} />
              </div>
              <div className="xtel">
                <PhoneCombo dial={dial} iso={iso} onChange={(c) => { setDial(`+${c.dial}`); setIso(c.iso); }} />
                <span className="cfield" style={{ flex: 1 }}>
                  <Icon name="i-phone" className="ico s sm" />
                  <input className="cinp" type="tel" inputMode="tel" placeholder="Mobile Number" required value={tel} onChange={(e) => setTel(e.target.value)} />
                </span>
              </div>
              <span className="cfield">
                <Icon name="i-mail" className="ico s sm" />
                <input className="cinp" type="email" placeholder="Email" required value={email} onChange={(e) => setEmail(e.target.value)} />
              </span>
              <div>
                <label className="lbl" style={{ fontSize: 13, marginBottom: 6 }}>Travelling to</label>
                <DestinationCombo value={travel} invalid={travelInvalid} onChange={(v) => { setTravel(v); setTravelInvalid(false); }} />
              </div>
            </div>
            <button className="cpop-cta" type="submit">
              Talk to an Expert
              <Icon name="i-arrow" className="ico w sm" />
            </button>
            <p className="cpop-safe"><Icon name="i-lock" className="ico s xs" />Your information is safe with us.</p>
          </form>
        ) : (
          <div className="cpop-bd cpop-thanks">
            <span className="cpop-wa-ic"><Icon name="i-whatsapp" className="ico-solid" style={{ width: 30, height: 30 }} /></span>
            <h2 className="cpop-h2">{saved === false ? 'Almost There' : 'Thank You!'}</h2>
            <p className="cpop-sub2">Get travel insurance guidance on <b>WhatsApp</b>.</p>
            <p className="cpop-body">{saved === true
              ? 'We’ve received your request. Our team will contact you on WhatsApp.'
              : saved === false
                ? 'We could not save your request just now. Message us on WhatsApp and our team will help you from there.'
                : 'Message us on WhatsApp and our team will help you from there.'}</p>
            <div className="cpop-pic">
              <img src={photo('whatsapp-expert.jpg')} alt="Our travel insurance expert, ready to chat on WhatsApp" width={582} height={326} loading="lazy" decoding="async" />
            </div>
            <a className="cpop-wa" href={waUrl} target="_blank" rel="noopener noreferrer"
               onClick={() => track('whatsapp')}>
              <Icon name="i-whatsapp" className="ico-solid" style={{ width: 22, height: 22 }} />
              Chat with Us on WhatsApp
              <Icon name="i-arrow" className="ico w sm" />
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
