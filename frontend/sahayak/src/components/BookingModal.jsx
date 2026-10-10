import { useEffect, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import Icon from './Icon.jsx';
import { ArrowButton, Chips, Quote, Upload, cx } from './ui.jsx';
import thumb from '../assets/hero-need.jpg';

import { GIG_SERVICES, SERVICE_KEYS, gigFor } from '../data/services.js';
import PhoneField, { phoneError, phonePair } from './PhoneField.jsx';
import { site, postJson, specializations } from '../data/site.js';
import * as v from '../validate.js';

/* The services the booking dropdown offers.
 *
 * The server's catalogue when there is one -- it is what /api/sahayak-booking validates
 * against, so offering anything else would collect a booking the server then refuses. The
 * baked GIG list is the fallback for `npm run dev`, where nothing is injected. */
const bookable = () =>
  site.services?.length
    ? site.services.map((s) => ({ key: s.key, title: s.name, duration: s.duration }))
    : GIG_SERVICES.map((g) => ({ key: g.key, title: g.title }));

// Kept for other components that list the service names.
export const SERVICES = SERVICE_KEYS;

/* Booking ("Pre") fields from the GIG sheet: patient, service, meet-up location, drop location
   (service-dependent), follow-up, attached document -- plus contact details.

   No appointment date or time. The team rings to agree one, and the server records the moment
   the request was made in its place, so the copy Preventia receives still carries a date. */
const EMPTY = {
  who: '', svc: '', spec: '', address: '', city: '', pin: '', drop: '',
  followUp: '', file: null, name: '', phone: '', dial: '+91', iso: 'IN', frequency: '',
};

/* Keyed by the GIG sheet's own service names, which is what gigFor() hands back -- the
   catalogue's keys are Preventia's category codes and do not match these. */
const DROP_LABEL = {
  'Out-Patient Visit': 'Hospital or clinic to visit',
  'In-Patient Visit': 'Hospital for admission',
  'Pharmacy Delivery': 'Preferred pharmacy (optional)',
  Other: 'Drop location (optional)',
};

function validate(d) {
  const svc = gigFor(d.svc);
  return v.collect({
    who: v.required(d.who, 'Please choose who needs support.'),
    svc: v.required(d.svc, 'Please choose a service.'),
    address: v.minText(d.address, 8, 'Please enter the house number, street and area.'),
    city: v.personName(d.city, 'the city') && 'Please enter the city.',
    pin: v.pin(d.pin),
    drop: svc?.drop === 'required' && v.minText(d.drop, 3, 'Please enter where the Sahayak should take your parent.'),
    name: v.personName(d.name),
    // Required, and long enough to ring: the team confirms every booking by phone,
    // so a booking without a reachable number is a booking nobody can action.
    phone: phoneError({ dial: d.dial, iso: d.iso, tel: d.phone }, { required: true }),
  });
}

/**
 * Quick-booking dialog. Stays mounted so answers survive closing and reopening.
 * `prefill` ({ svc, who, city, when, followUp }) is applied each time the dialog
 * opens -- the hero card sends some of it, the service finder sends all of it.
 */
export default function BookingModal({ open, prefill, onClose }) {
  const [data, setData] = useState(EMPTY);
  const [errors, setErrors] = useState({});
  const [done, setDone] = useState(false);
  const [sending, setSending] = useState(false);
  const [failed, setFailed] = useState('');
  const [uploadKey, setUploadKey] = useState(0);
  const bodyRef = useRef(null);
  const whoRef = useRef(null);
  const lastFocus = useRef(null);
  const specs = specializations();

  const set = (k, val) => {
    setData((d) => ({ ...d, [k]: val }));
    setErrors((e) => ({ ...e, [k]: '' }));
  };

  useEffect(() => {
    if (!open) return;
    lastFocus.current = document.activeElement;
    setDone(false);
    setErrors({});
    setFailed('');
    if (prefill?.svc) setData((d) => ({ ...d, svc: prefill.svc }));
    // "When?" from the hero card (One-time / Weekly / Ongoing / Urgent) travels with the booking.
    if (prefill?.when) setData((d) => ({ ...d, frequency: prefill.when }));
    if (prefill?.who) setData((d) => ({ ...d, who: prefill.who }));
    if (prefill?.city) setData((d) => ({ ...d, city: prefill.city }));
    // the finder asks whether a doctor already requested this, which answers the sheet's
    // "is this a follow-up" without putting the question a second time
    if (prefill?.followUp) setData((d) => ({ ...d, followUp: prefill.followUp }));
    document.body.classList.add('lock');
    const t = setTimeout(() => whoRef.current?.querySelector('.chip')?.focus(), 60);
    const onKey = (e) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    return () => {
      clearTimeout(t);
      document.removeEventListener('keydown', onKey);
      document.body.classList.remove('lock');
      lastFocus.current?.focus?.();
    };
  }, [open, prefill, onClose]);

  const submit = async () => {
    const e = validate(data);
    if (Object.keys(e).length) {
      // Clear, force a reflow, then re-apply so the shake animation replays on every attempt.
      flushSync(() => setErrors({}));
      void bodyRef.current.offsetWidth;
      flushSync(() => setErrors(e));
      v.focusFirstError(bodyRef.current);
      return;
    }
    setSending(true);
    setFailed('');
    const pair = phonePair({ dial: data.dial, iso: data.iso, tel: data.phone });
    const spec = specs.find((s) => s.code === data.spec);
    try {
      /* Mapped onto the columns sahayak_bookings already has rather than new ones: `who` is
         who the visit is for, `name` is who asked for it, and the city rides with the address
         because the table stores an address, a landmark and a PIN. */
      await postJson(site.bookingUrl, {
        service: data.svc,
        patient_name: data.who,
        contact_name: data.name.trim(),
        // the number as typed and its country, apart -- see PhoneField.phonePair
        phone: pair.tel,
        phone_cc: pair.cc,
        address: [data.address.trim(), data.city.trim()].filter(Boolean).join(', '),
        pincode: data.pin.trim(),
        when_type: 'asap',
        specialization: spec ? spec.code : '',
        notes: [
          data.frequency && `How often: ${data.frequency}`,
          data.drop && `Drop location: ${data.drop}`,
          data.followUp && `Follow-up visit: ${data.followUp}`,
          data.file && `They have a document to send: ${data.file.name || 'attached'}`,
        ].filter(Boolean).join('\n'),
      });
    } catch (err) {
      setFailed(err.message);
      setSending(false);
      return;
    }
    setSending(false);
    setDone(true);
    setData(EMPTY);
    setUploadKey((k) => k + 1);
  };

  const fld = (key, extra) => cx('fld', errors[key] && 'err', extra);
  const msg = (key) => <span className="emsg">{errors[key]}</span>;
  const svc = gigFor(data.svc);
  const picked = bookable().find((g) => g.key === data.svc);

  return (
    <div className="bk-wrap" hidden={!open}>
      <div className="bk-wrap">
        <button type="button" className="bk-back" aria-label="Close booking form" onClick={onClose}></button>
        <div className="bk" role="dialog" aria-modal="true" aria-labelledby="bk-t">
          <div className="bk-top">
            <div className="bk-img" aria-hidden="true"><img src={thumb} alt="" /></div>
            <div>
              <span className="kick" style={{ marginBottom: 6 }}>Quick booking</span>
              <h2 className="bk-t" id="bk-t">Book a Sahayak</h2>
              <p className="bk-s">Tell us what is needed — we'll call you to agree a time.</p>
            </div>
            <button type="button" className="bk-x" aria-label="Close" onClick={onClose}>
              <Icon name="close" sw={2.2} />
            </button>
          </div>

          <div className="bk-form" hidden={done}>
            <div className="bk-body" ref={bodyRef}>
              <div className={fld('who')}>
                <span className="lbl">Who needs support? <b>*</b></span>
                <Chips ref={whoRef} options={['Mother', 'Father', 'Both Parents', 'Other']} value={data.who} onChange={(val) => set('who', val)} />
                {msg('who')}
              </div>
              <div className={fld('svc')}>
                <label htmlFor="bk-svc">Service <b>*</b></label>
                <select id="bk-svc" name="service" value={data.svc} onChange={(e) => set('svc', e.target.value)}>
                  <option value="">Select a service</option>
                  {bookable().map((g) => <option key={g.key} value={g.key}>{g.title}</option>)}
                </select>
                {svc && (
                  <span className="bk-hint">
                    {picked?.duration && <span className="bk-dur"><Icon name="clock" sw={2.2} />{picked.duration}</span>}
                    Includes: {svc.includes.join(' · ')}{data.frequency && <> · <strong>{data.frequency}</strong></>}
                  </span>
                )}
                {msg('svc')}
              </div>
              {/* Which kind of Sahayak, from Preventia's own list. Not offered at all when that
                  list is empty -- a choice nobody can honour is worse than no choice. */}
              {specs.length > 0 && (
                <div className="fld">
                  <label htmlFor="bk-spec">Sahayak specialisation <small className="opt">optional</small></label>
                  <select id="bk-spec" name="specialization" value={data.spec} onChange={(e) => set('spec', e.target.value)}>
                    <option value="">No preference</option>
                    {specs.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
                  </select>
                  {data.spec && specs.find((s) => s.code === data.spec)?.description && (
                    <span className="ph-hint">{specs.find((s) => s.code === data.spec).description}</span>
                  )}
                </div>
              )}
              <div className={fld('address')}>
                <label htmlFor="bk-address">Meet-up location <b>*</b></label>
                <input id="bk-address" name="meetup_address" autoComplete="street-address" placeholder="House no., street, area, landmark" value={data.address} onChange={(e) => set('address', e.target.value)} />
                {msg('address')}
              </div>
              <div className="bk-row">
                <div className={fld('city')}>
                  <label htmlFor="bk-city">City <b>*</b></label>
                  <input id="bk-city" name="city" autoComplete="address-level2" placeholder="e.g. Hyderabad" value={data.city} onChange={(e) => set('city', e.target.value)} />
                  {msg('city')}
                </div>
                <div className={fld('pin')}>
                  <label htmlFor="bk-pin">PIN code <b>*</b></label>
                  <input id="bk-pin" name="pin" inputMode="numeric" autoComplete="postal-code" maxLength={6} placeholder="6 digits"
                         value={data.pin} onChange={(e) => set('pin', e.target.value.replace(/\D/g, '').slice(0, 6))} />
                  {msg('pin')}
                </div>
              </div>
              {svc?.drop && (
                <div className={fld('drop')}>
                  <label htmlFor="bk-drop">{DROP_LABEL[svc.key]} {svc.drop === 'required' && <b>*</b>}</label>
                  <input id="bk-drop" name="drop_location" placeholder="Name and area" value={data.drop} onChange={(e) => set('drop', e.target.value)} />
                  {msg('drop')}
                </div>
              )}
              <div className="bk-row">
                <div className="fld">
                  <span className="lbl">Is this a follow-up visit?</span>
                  <Chips options={['Yes', 'No']} value={data.followUp} onChange={(val) => set('followUp', val)} />
                </div>
                <div className="fld">
                  <span className="lbl">Attach a document</span>
                  <Upload key={uploadKey} id="bk-doc" name="document" icon="upload" title="Prescription or report" hint="Optional · PDF, JPG, PNG" action="Browse" onChange={(f) => set('file', f)} />
                </div>
              </div>
              <div className="bk-row">
                <div className={fld('name')}>
                  <label htmlFor="bk-name">Your name <b>*</b></label>
                  <input id="bk-name" name="name" autoComplete="name" value={data.name} onChange={(e) => set('name', e.target.value)} />
                  {msg('name')}
                </div>
                <PhoneField
                  id="bk-phone"
                  label="Phone / WhatsApp"
                  required
                  error={errors.phone}
                  value={{ dial: data.dial, iso: data.iso, tel: data.phone }}
                  onChange={(val) => {
                    setData((d) => ({ ...d, dial: val.dial, iso: val.iso || d.iso, phone: val.tel }));
                    setErrors((e) => ({ ...e, phone: '' }));
                  }}
                />
              </div>
            </div>
            <div className="bk-foot">
              <a href="#request" className="bk-more" onClick={onClose}>Want to share more details? Use the full form</a>
              <ArrowButton onClick={submit} disabled={sending}>
                {sending ? 'Sending…' : 'Book a Sahayak'}
              </ArrowButton>
            </div>
            {/* What actually went wrong, from the server. A booking that silently fails is
                somebody waiting for a call that is never coming. */}
            {failed && <p className="bk-fail" role="alert">{failed}</p>}
          </div>

          <div className="bk-done" hidden={!done}>
            <div className="done-box" style={{ padding: '36px 28px 40px' }}>
              <div className="big-check"><Icon name="check" sw={2.6} /></div>
              <h3 className="q">Booking request received</h3>
              <Quote style={{ margin: '0 auto 12px' }}>Care is on its way.</Quote>
              <p className="qs" style={{ maxWidth: 400, margin: '0 auto 24px' }}>
                Our care team will call you shortly to agree a time and match a suitable Sahayak.
              </p>
              <button type="button" className="btn btn-o" onClick={onClose}>Done</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
