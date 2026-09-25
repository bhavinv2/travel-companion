import { useState } from 'react';
import Icon from './Icon';
import SideDecor from './SideDecor';
import { PhoneCombo, DestinationCombo } from './CountryCombo';
import { useReveal } from '../hooks/useReveal';
import { site } from '../data/site';

// Fallback only: the live page injects the number staff set in Admin -> Landing page, so this
// build can never advertise a number nobody is watching.
const WHATSAPP_NUMBER = '918019111360';

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

    // Record it first. The original only built a WhatsApp link, so an enquiry existed nowhere
    // until the person actually sent that message; now it lands in the inbox CS already works
    // from. The thank-you shows either way -- a failed write is ours to chase in the logs, not
    // a dead end for somebody who has already typed their details in.
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
        /* keep going: the WhatsApp hand-off below still works */
      }
    }
    setSent(true);
  }

  return (
    <section className="sec" id="contact" style={{ background: 'var(--cloud)' }}>
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
          <div className="expert-contacts">
            <div className="ec">
              <span className="ec-ic"><Icon name="i-mail" className="ico w sm" /></span>
              <span><span className="ec-l">Email</span><span className="ec-v">{site.supportEmail || 'support@nriparentservice.com'}</span></span>
            </div>
            <div className="ec">
              <span className="ec-ic"><Icon name="i-phone" className="ico w sm" /></span>
              <span><span className="ec-l">Phone number</span><span className="ec-v">{site.supportPhone || '+91 80191 11360'}</span></span>
            </div>
            <div className="ec">
              <span className="ec-ic"><Icon name="i-clock" className="ico w sm" /></span>
              <span><span className="ec-l">Availability</span><span className="ec-v">Across time zones, every day</span></span>
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
    </section>
  );
}
