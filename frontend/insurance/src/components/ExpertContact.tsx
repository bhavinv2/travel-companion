import { useState } from 'react';
import Icon from './Icon';
import SideDecor from './SideDecor';
import { PhoneCombo, DestinationCombo } from './CountryCombo';
import { useReveal } from '../hooks/useReveal';
import { photo, site } from '../data/site';

// Fallbacks only: the served page injects whatever staff set in the admin screens.
const WHATSAPP_NUMBER = '918019111360';
const SUPPORT_EMAIL = 'support@nriparentservice.com';
const SUPPORT_PHONES = [
  { label: 'India', display: '+91 80191 11360', digits: '918019111360' },
  { label: 'USA', display: '+1 917 900 5094', digits: '19179005094' },
];

export default function ExpertContact() {
  const reveal = useReveal<HTMLDivElement>();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [dial, setDial] = useState('+91');
  const [tel, setTel] = useState('');
  const [dest, setDest] = useState('');
  const [destInvalid, setDestInvalid] = useState(false);
  const [sent, setSent] = useState(false);
  const [waUrl, setWaUrl] = useState('');

  // Staff set these in Admin -> Landing page; the constants above are what this build ships with
  // for the dev server. A line staff have cleared is not published at all.
  const supportEmail = site.supportEmail || SUPPORT_EMAIL;
  const phones = site.supportPhones?.length ? site.supportPhones : SUPPORT_PHONES;

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!e.currentTarget.checkValidity()) {
      e.currentTarget.reportValidity();
      return;
    }
    if (!dest) {
      setDestInvalid(true);
      return;
    }
    const lines = [
      'Hello! I would like to discuss travel insurance with an expert.', '',
      `Name: ${name}`,
      `Email: ${email}`,
      `Mobile: ${dial} ${tel}`,
      `Destination: ${dest}`,
    ];
    const number = (site.whatsapp || WHATSAPP_NUMBER).replace(/[^0-9]/g, '');
    setWaUrl(`https://api.whatsapp.com/send/?phone=${number}&text=${encodeURIComponent(lines.join('\n'))}`);

    // A WhatsApp link somebody never clicks leaves no trace of the enquiry. Record it in the inbox
    // CS already works from first, hand off second; a failed POST must not block the hand-off.
    if (site.enquiryUrl) {
      try {
        await fetch(site.enquiryUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(site.csrfToken ? { 'X-CSRFToken': site.csrfToken } : {}),
          },
          body: JSON.stringify({ name, email, phone: `${dial} ${tel}`, destination: dest }),
        });
      } catch {
        /* the WhatsApp hand-off below still works */
      }
    }
    setSent(true);
  }

  return (
    <section className="sec expert-sec" id="contact">
      <span className="expert-glow" aria-hidden="true" />
      <SideDecor icons={[
        { name: 'i-mail', side: 'left', top: '22%', size: 28, rotate: -8, opacity: 0.14 },
        { name: 'i-headset', side: 'left', top: '68%', size: 95, rotate: 10, opacity: 0.06 },
        { name: 'i-phone', side: 'right', top: '62%', size: 30, rotate: 10, opacity: 0.14 },
        { name: 'i-clock', side: 'right', top: '14%', size: 85, rotate: -10, opacity: 0.06 },
      ]} />
      <div className={`wrap expert z1 ${reveal.className}`} ref={reveal.ref as any}>
        <div className="expert-info">
          <span className="kick">We're here to help you</span>
          <h2 className="h2" style={{ marginTop: 14 }}>Discuss Your <span className="expert-mute">Travel Cover</span> With an Expert</h2>
          <span className="script-tag" style={{ fontSize: 22, color: 'var(--blue)' }}>We're just a message away.</span>
          <p className="lead" style={{ marginTop: 16, maxWidth: 470 }}>
            Not sure which plan fits your trip? Share a few details and one of our travel insurance specialists will walk you through the options &mdash; no cost, no obligation.
          </p>
          {/* Every line here is something you can act on. Read-only text made a visitor on a
              phone copy a number out by hand, and gave the two numbers no context -- +91 and
              +1 only mean something once you know which team is on the end of each. */}
          <div className="expert-contacts">
            <a className="ec ec-act" href={`mailto:${supportEmail}`}>
              <span className="ec-ic"><Icon name="i-mail" className="ico w sm" /></span>
              <span className="ec-bd">
                <span className="ec-l">Email</span>
                <span className="ec-v">{supportEmail}</span>
              </span>
              <span className="ec-go"><Icon name="i-arrow" className="ico sm" /></span>
            </a>

            <div className="ec ec-tel">
              <span className="ec-ic"><Icon name="i-phone" className="ico w sm" /></span>
              <span className="ec-bd">
                <span className="ec-l">Call or WhatsApp</span>
                <span className="ec-nums">
                  {phones.map((p) => (
                    <span className="ec-num" key={p.digits}>
                      <a className="ec-v" href={`tel:+${p.digits}`}>{p.display}</a>
                      <span className="ec-tag">{p.label}</span>
                      <a
                        className="ec-wa"
                        href={`https://api.whatsapp.com/send/?phone=${p.digits}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label={`Message our ${p.label} team on WhatsApp`}
                      >
                        <Icon name="i-whatsapp" className="ico-solid" style={{ width: 17, height: 17 }} />
                      </a>
                    </span>
                  ))}
                </span>
              </span>
            </div>

            <div className="ec">
              <span className="ec-ic"><Icon name="i-clock" className="ico w sm" /></span>
              <span className="ec-bd">
                <span className="ec-l">Availability</span>
                <span className="ec-v">Across time zones, every day</span>
              </span>
            </div>
          </div>
        </div>
        <div className="expert-col">
          {!sent ? (
            <form className="expert-form card" onSubmit={handleSubmit}>
              <label className="xlbl" htmlFor="x-name">Name</label>
              <input className="xinp" id="x-name" type="text" placeholder="Your full name" required value={name} onChange={(e) => setName(e.target.value)} />
              <label className="xlbl" htmlFor="x-mail">Email</label>
              <input className="xinp" id="x-mail" type="email" placeholder="you@gmail.com" required value={email} onChange={(e) => setEmail(e.target.value)} />
              <label className="xlbl" htmlFor="x-tel">Mobile number</label>
              <div className="xtel">
                <PhoneCombo dial={dial} onChange={(c) => setDial(`+${c.dial}`)} />
                <input className="xinp" id="x-tel" type="tel" inputMode="tel" placeholder="00000 00000" required value={tel} onChange={(e) => setTel(e.target.value)} />
              </div>
              <label className="xlbl">Destination</label>
              <DestinationCombo
                value={dest}
                invalid={destInvalid}
                onChange={(v) => { setDest(v); setDestInvalid(false); }}
              />
              <button className="xbtn" type="submit">
                <span className="xbtn-ic"><Icon name="i-arrow" className="ico w sm" /></span>
                Get a Consultation
              </button>
            </form>
          ) : (
            <div className="expert-form card cpop-thanks">
              <button className="cpop-edit" type="button" onClick={() => setSent(false)}>
                <Icon name="i-back" className="ico n sm" />
                Edit My Details
              </button>
              <span className="cpop-wa-ic"><Icon name="i-whatsapp" className="ico-solid" style={{ width: 30, height: 30 }} /></span>
              <h2 className="cpop-h2">Thank You!</h2>
              <p className="cpop-sub2">Get Your Details on <b>WhatsApp</b> with Our Assistance</p>
              <p className="cpop-body">Our team will contact you shortly on WhatsApp to assist you with the next steps.</p>
              <div className="cpop-pic">
                <img src={photo('whatsapp-expert.jpg')} alt="Our travel insurance expert, ready to chat on WhatsApp" width={582} height={326} loading="lazy" decoding="async" />
              </div>
              <a className="cpop-wa" href={waUrl} target="_blank" rel="noopener noreferrer">
                <Icon name="i-whatsapp" className="ico-solid" style={{ width: 22, height: 22 }} />
                Chat with Us on WhatsApp
                <Icon name="i-arrow" className="ico w sm" />
              </a>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
