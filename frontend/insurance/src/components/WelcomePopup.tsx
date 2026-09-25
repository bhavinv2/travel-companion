import { useEffect, useState } from 'react';
import Icon from './Icon';
import CountrySelect, { DialSelect } from './CountrySelect';
import { useQuote } from '../context/QuoteContext';
import { site } from '../data/site';

// Fallback only: the live page injects the number staff set in Admin -> Landing page.
const WHATSAPP_NUMBER = '918019111360';

export default function WelcomePopup() {
  const { consultOpen, openConsult, closeConsult, quoteOpen } = useQuote();
  const [name, setName] = useState('');
  const [country, setCountry] = useState('India');
  const [dial, setDial] = useState('+91');
  const [tel, setTel] = useState('');
  const [email, setEmail] = useState('');
  const [travel, setTravel] = useState('Canada');
  const [sent, setSent] = useState(false);
  const [waUrl, setWaUrl] = useState('');

  // auto-open once per browser session, 7s after load, unless the quote modal is already up
  useEffect(() => {
    try {
      if (sessionStorage.getItem('welShown')) return;
    } catch {
      // ignore storage errors (private browsing etc.)
    }
    const t = setTimeout(() => {
      if (!quoteOpen) {
        openConsult();
        try { sessionStorage.setItem('welShown', '1'); } catch { /* ignore */ }
      }
    }, 7000);
    return () => clearTimeout(t);
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
    const lines = [
      'Hello! I would like a travel insurance consultation.', '',
      `Name: ${name}`,
      `Country: ${country}`,
      `Mobile: ${dial} ${tel}`,
      `Email: ${email}`,
      `Travel to: ${travel}`,
    ];
    const number = (site.whatsapp || WHATSAPP_NUMBER).replace(/[^0-9]/g, '');
    setWaUrl(`https://api.whatsapp.com/send/?phone=${number}&text=${encodeURIComponent(lines.join('\n'))}`);

    // Same reasoning as the expert form: this is a lead, and a WhatsApp link that somebody never
    // clicks leaves no trace of it. Record first, hand off second.
    if (site.enquiryUrl) {
      try {
        await fetch(site.enquiryUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(site.csrfToken ? { 'X-CSRFToken': site.csrfToken } : {}),
          },
          body: JSON.stringify({ name, email, phone: `${dial} ${tel}`, destination: travel }),
        });
      } catch {
        /* the WhatsApp hand-off below still works */
      }
    }
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
            <h2 className="cpop-h" id="cpop-title">Book Your <span>Consultation Now</span></h2>
            <p className="cpop-sub">Get expert guidance for your safe and hassle-free travel.</p>
            <div className="cpop-fields">
              <span className="cfield">
                <Icon name="i-user" className="ico s sm" />
                <input className="cinp" type="text" placeholder="Name" required value={name} onChange={(e) => setName(e.target.value)} />
              </span>
              <span className="cfield">
                <Icon name="i-globe" className="ico s sm" />
                <CountrySelect value={country} onChange={setCountry} className="cinp csel" required placeholder="Country" />
                <Icon name="i-chev" className="ico s xs cfield-chev" rotate={90} />
              </span>
              <span className="cfield cfield-tel">
                <Icon name="i-phone" className="ico s sm" />
                <DialSelect value={dial} onChange={setDial} className="cdial" />
                <input className="cinp" type="tel" inputMode="tel" placeholder="Mobile Number" required value={tel} onChange={(e) => setTel(e.target.value)} />
              </span>
              <span className="cfield">
                <Icon name="i-mail" className="ico s sm" />
                <input className="cinp" type="email" placeholder="Email" required value={email} onChange={(e) => setEmail(e.target.value)} />
              </span>
              <span className="cfield">
                <Icon name="i-plane" className="ico s sm" />
                <CountrySelect value={travel} onChange={setTravel} className="cinp csel" required placeholder="Travel to" />
                <Icon name="i-chev" className="ico s xs cfield-chev" rotate={90} />
              </span>
            </div>
            <button className="cpop-cta" type="submit">
              Book Consultation Now
              <Icon name="i-arrow" className="ico w sm" />
            </button>
            <p className="cpop-safe"><Icon name="i-lock" className="ico s xs" />Your information is safe with us.</p>
          </form>
        ) : (
          <div className="cpop-bd cpop-thanks">
            <span className="cpop-wa-ic"><Icon name="i-whatsapp" className="ico-solid" style={{ width: 30, height: 30 }} /></span>
            <h2 className="cpop-h2">Thank You!</h2>
            <p className="cpop-sub2">Get Your Details on <b>WhatsApp</b> with Our Assistance</p>
            <p className="cpop-body">Our team will contact you shortly on WhatsApp to assist you with the next steps.</p>
            <a className="cpop-wa" href={waUrl} target="_blank" rel="noopener noreferrer">
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
