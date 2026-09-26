/* Support, as a popup rather than a trip to the help centre.
 *
 * The navbar's Support link points at /help and always will -- that is the answer with no
 * JavaScript, and the help centre is the right destination for "how does this work". On this page
 * we can do better for the other kind of visitor, the one who wants a person: intercept the click
 * and ask for their details here, on the page they were reading, in this page's own styling.
 *
 * It lands in the same CS inbox as every other enquiry, tagged as insurance, so nobody has to
 * remember to check a second place.
 */
import { useEffect, useRef, useState } from 'react';
import Icon from './Icon';
import { OptionCombo, PhoneCombo } from './CountryCombo';
import { site } from '../data/site';

const SUPPORT_EMAIL = 'support@nriparentservice.com';

const TOPICS = [
  'Which plan fits my trip',
  'Cover for parents visiting',
  'Schengen visa requirements',
  'Pre-existing conditions',
  'A policy I already bought',
  'Making a claim',
  'Something else',
];

const VIA = ['WhatsApp', 'Phone call', 'Email'] as const;

export default function SupportModal() {
  const [open, setOpen] = useState(false);
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [dial, setDial] = useState('+91');
  const [tel, setTel] = useState('');
  const [topic, setTopic] = useState(TOPICS[0]);
  const [via, setVia] = useState<(typeof VIA)[number]>('WhatsApp');
  const [message, setMessage] = useState('');
  const first = useRef<HTMLInputElement>(null);

  // The button lives in the server-rendered navbar, so the two are wired together here rather
  // than by a shared parent. Anything carrying data-open-support opens it too.
  useEffect(() => {
    function show(e?: Event) {
      e?.preventDefault();
      setOpen(true);
    }
    const nodes = Array.from(
      document.querySelectorAll<HTMLElement>('#navSupport, [data-open-support]'),
    );
    nodes.forEach((n) => n.addEventListener('click', show));
    return () => nodes.forEach((n) => n.removeEventListener('click', show));
  }, []);

  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const t = setTimeout(() => first.current?.focus(), 60);
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('keydown', onKey);
    return () => {
      clearTimeout(t);
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = previous;
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  if (!open) return null;

  const supportEmail = site.supportEmail || SUPPORT_EMAIL;
  const phones = site.supportPhones || [];

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    if (!form.checkValidity()) {
      form.reportValidity();
      return;
    }
    setBusy(true);
    setError('');
    try {
      const res = await fetch(site.enquiryUrl || '/api/insurance-enquiry', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(site.csrfToken ? { 'X-CSRFToken': site.csrfToken } : {}),
        },
        body: JSON.stringify({
          kind: 'support',
          name,
          email,
          phone: `${dial} ${tel}`,
          subject: topic,
          preferred: via,
          message,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.success) setSent(true);
      else setError(data.error || 'Something went wrong. Please try again, or email us.');
    } catch {
      setError('We could not reach the server. Please try again, or email us.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="ov" onMouseDown={(e) => { if (e.target === e.currentTarget) setOpen(false); }}>
      <div className="modal spop" role="dialog" aria-modal="true" aria-labelledby="spop-title">
        <button className="cpop-x" type="button" aria-label="Close" onClick={() => setOpen(false)}>
          <Icon name="i-x" className="ico n sm" />
        </button>

        <div className="spop-side">
          <span className="spop-kick"><Icon name="i-headset" className="ico w sm" />Support</span>
          <h2 className="spop-h" id="spop-title">Talk to a travel insurance specialist</h2>
          <p className="spop-sub">
            Tell us what you need and how to reach you. A real person answers &mdash; no bots, no cost.
          </p>

          <ul className="spop-points">
            <li><Icon name="i-check" className="ico w xs" />Help choosing between visitor, travel medical and Schengen cover</li>
            <li><Icon name="i-check" className="ico w xs" />Questions about a policy you already hold</li>
            <li><Icon name="i-check" className="ico w xs" />Guidance on claims and documents</li>
          </ul>

          <div className="spop-direct">
            <a href={`mailto:${supportEmail}`}>
              <Icon name="i-mail" className="ico w sm" />{supportEmail}
            </a>
            {phones.map((p) => (
              <a key={p.digits} href={`tel:+${p.digits}`}>
                <Icon name="i-phone" className="ico w sm" />{p.display}
                <span className="spop-tag">{p.label}</span>
              </a>
            ))}
          </div>
        </div>

        {!sent ? (
          <form className="spop-form" onSubmit={handleSubmit} noValidate={false}>
            <div className="spop-row">
              <p className="fg">
                <label className="lbl" htmlFor="sp-name">Your name <span className="req">*</span></label>
                <span className="cfield">
                  <Icon name="i-user" className="ico s sm" />
                  <input ref={first} className="cinp" id="sp-name" type="text" required
                         placeholder="Anitha Reddy" autoComplete="name"
                         value={name} onChange={(e) => setName(e.target.value)} />
                </span>
              </p>
              <p className="fg">
                <label className="lbl" htmlFor="sp-mail">Email <span className="req">*</span></label>
                <span className="cfield">
                  <Icon name="i-mail" className="ico s sm" />
                  <input className="cinp" id="sp-mail" type="email" required
                         placeholder="you@example.com" autoComplete="email"
                         value={email} onChange={(e) => setEmail(e.target.value)} />
                </span>
              </p>
            </div>

            <p className="fg">
              <label className="lbl" htmlFor="sp-tel">Phone / WhatsApp <span className="req">*</span></label>
              <span className="xtel">
                <PhoneCombo dial={dial} onChange={(c) => setDial(`+${c.dial}`)} />
                <span className="cfield" style={{ flex: 1 }}>
                  <Icon name="i-phone" className="ico s sm" />
                  <input className="cinp" id="sp-tel" type="tel" inputMode="tel" required
                         placeholder="00000 00000" autoComplete="tel"
                         value={tel} onChange={(e) => setTel(e.target.value)} />
                </span>
              </span>
            </p>

            <div className="fg">
              <label className="lbl" htmlFor="sp-topic">What do you need help with?</label>
              <OptionCombo id="sp-topic" icon="i-list" value={topic} options={TOPICS} onChange={setTopic} />
            </div>

            <div className="fg">
              <span className="lbl">How should we reach you?</span>
              <div className="spop-pills" role="radiogroup" aria-label="How should we reach you?">
                {VIA.map((v) => (
                  <button key={v} type="button" role="radio" aria-checked={via === v}
                          className={`spop-pill${via === v ? ' on' : ''}`} onClick={() => setVia(v)}>
                    {v}
                  </button>
                ))}
              </div>
            </div>

            <p className="fg">
              <label className="lbl" htmlFor="sp-msg">Your message <span className="req">*</span></label>
              <textarea className="cinp spop-ta" id="sp-msg" required minLength={10} rows={3}
                        placeholder="Two parents visiting us in Dallas in November — which plan covers a heart condition?"
                        value={message} onChange={(e) => setMessage(e.target.value)} />
            </p>

            {error && <p className="spop-err" role="alert">{error}</p>}

            <button className="cpop-cta" type="submit" disabled={busy}>
              {busy ? 'Sending…' : 'Request a call back'}
              <Icon name="i-arrow" className="ico w sm" />
            </button>
            <p className="cpop-safe"><Icon name="i-lock" className="ico s xs" />Your details are used only to answer this request.</p>
          </form>
        ) : (
          <div className="spop-form spop-done">
            <span className="spop-done-ic"><Icon name="i-checkc" className="ico" /></span>
            <h3 className="spop-h" style={{ fontSize: 24 }}>Thank you</h3>
            <p className="spop-sub" style={{ color: 'var(--slate)' }}>
              We have your request and will reply to <b>{email}</b>. If it is urgent, the direct
              lines are on the left.
            </p>
            <button className="cpop-cta" type="button" onClick={() => setOpen(false)}>
              Back to the page<Icon name="i-arrow" className="ico w sm" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
