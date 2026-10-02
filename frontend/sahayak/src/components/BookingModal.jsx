import { useEffect, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import Icon from './Icon.jsx';
import { ArrowButton, Chips, Quote, Upload, cx } from './ui.jsx';
import thumb from '../assets/hero-need.jpg';

import { GIG_SERVICES, SERVICE_KEYS, serviceByKey } from '../data/services.js';
import { site, postJson } from '../data/site.js';

/* The services the booking dropdown offers.
 *
 * The server's catalogue when there is one -- it is what /api/sahayak-booking validates
 * against, so offering anything else would collect a booking the server then refuses. The
 * baked GIG list is the fallback for `npm run dev`, where nothing is injected. */
const bookable = () =>
  site.services?.length
    ? site.services.map((s) => ({ key: s.key, title: s.name }))
    : GIG_SERVICES.map((g) => ({ key: g.key, title: g.title }));

// Kept for other components that list the service names.
export const SERVICES = SERVICE_KEYS;

const today = () => new Date().toISOString().slice(0, 10);

// Booking ("Pre") fields from the GIG sheet: patient, service, appointment date & time,
// meet-up location, drop location (service-dependent), follow-up, attached document — plus contact details.
const EMPTY = {
  who: '', svc: '', date: '', time: '', address: '', city: '', pin: '', drop: '',
  followUp: '', file: null, name: '', phone: '', frequency: '',
};

const DROP_LABEL = {
  'Out-Patient Visit': 'Hospital or clinic to visit',
  'In-Patient Visit': 'Hospital for admission',
  'Pharmacy Delivery': 'Preferred pharmacy (optional)',
  Other: 'Drop location (optional)',
};

function validate(d) {
  const svc = serviceByKey(d.svc);
  return {
    who: !d.who,
    svc: !d.svc,
    date: !d.date || d.date < today(),
    time: !d.time,
    address: d.address.trim().length < 5,
    city: !d.city.trim(),
    pin: !/^\d{6}$/.test(d.pin.trim()),
    drop: svc?.drop === 'required' && d.drop.trim().length < 3,
    name: !d.name.trim(),
    phone: d.phone.replace(/\D/g, '').length < 10,
  };
}

/**
 * Quick-booking dialog. Stays mounted so answers survive closing and reopening.
 * `prefill` ({ svc, who, city, date }) is applied each time the dialog opens.
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

  const set = (k, v) => {
    setData((d) => ({ ...d, [k]: v }));
    setErrors((e) => ({ ...e, [k]: false }));
  };

  useEffect(() => {
    if (!open) return;
    lastFocus.current = document.activeElement;
    setDone(false);
    setErrors({});
    setFailed('');
    if (prefill?.svc) setData((d) => ({ ...d, svc: prefill.svc }));
    if (prefill?.date) setData((d) => ({ ...d, date: prefill.date }));
    // "When?" from the hero card (One-time / Weekly / Ongoing / Urgent) travels with the booking.
    if (prefill?.when) setData((d) => ({ ...d, frequency: prefill.when }));
    if (prefill?.who) setData((d) => ({ ...d, who: prefill.who }));
    if (prefill?.city) setData((d) => ({ ...d, city: prefill.city }));
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
    if (Object.values(e).some(Boolean)) {
      // Clear, force a reflow, then re-apply so the shake animation replays on every attempt.
      flushSync(() => setErrors({}));
      void bodyRef.current.offsetWidth;
      flushSync(() => setErrors(e));
      bodyRef.current.querySelector('.fld.err')?.querySelector('input,select,.chip')?.focus();
      return;
    }
    setSending(true);
    setFailed('');
    try {
      /* Mapped onto the columns sahayak_bookings already has rather than new ones: `who` is
         who the visit is for, `name` is who asked for it, and the city rides with the address
         because the table stores an address, a landmark and a PIN. */
      await postJson(site.bookingUrl, {
        service: data.svc,
        patient_name: data.who,
        contact_name: data.name,
        phone: data.phone,
        address: [data.address, data.city].filter(Boolean).join(', '),
        pincode: data.pin,
        when_type: 'scheduled',
        scheduled_for: `${data.date}T${data.time}`,
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
  const svc = serviceByKey(data.svc);

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
              <p className="bk-s">Pick a service and a slot — we'll call you to confirm.</p>
            </div>
            <button type="button" className="bk-x" aria-label="Close" onClick={onClose}>
              <Icon name="close" sw={2.2} />
            </button>
          </div>

          <div className="bk-form" hidden={done}>
            <div className="bk-body" ref={bodyRef}>
              <div className={fld('who')}>
                <span className="lbl">Who needs support? <b>*</b></span>
                <Chips ref={whoRef} options={['Mother', 'Father', 'Both Parents', 'Other']} value={data.who} onChange={(v) => set('who', v)} />
                <span className="emsg">Please choose who needs support.</span>
              </div>
              <div className={fld('svc')}>
                <label htmlFor="bk-svc">Service <b>*</b></label>
                <select id="bk-svc" name="service" value={data.svc} onChange={(e) => set('svc', e.target.value)}>
                  <option value="">Select a service</option>
                  {bookable().map((g) => <option key={g.key} value={g.key}>{g.title}</option>)}
                </select>
                {svc && <span className="bk-hint">Includes: {svc.includes.join(' · ')}{data.frequency && <> · <strong>{data.frequency}</strong></>}</span>}
                <span className="emsg">Please choose a service.</span>
              </div>
              <div className="bk-row">
                <div className={fld('date')}>
                  <label htmlFor="bk-date">Appointment date <b>*</b></label>
                  <input id="bk-date" name="appointment_date" type="date" min={today()} value={data.date} onChange={(e) => set('date', e.target.value)} />
                  <span className="emsg">Choose today or a later date.</span>
                </div>
                <div className={fld('time')}>
                  <label htmlFor="bk-time">Appointment time <b>*</b></label>
                  <input id="bk-time" name="appointment_time" type="time" value={data.time} onChange={(e) => set('time', e.target.value)} />
                  <span className="emsg">Please choose a time.</span>
                </div>
              </div>
              <div className={fld('address')}>
                <label htmlFor="bk-address">Meet-up location <b>*</b></label>
                <input id="bk-address" name="meetup_address" autoComplete="street-address" placeholder="House no., street, landmark" value={data.address} onChange={(e) => set('address', e.target.value)} />
                <span className="emsg">Please enter where the Sahayak should meet your parent.</span>
              </div>
              <div className="bk-row">
                <div className={fld('city')}>
                  <label htmlFor="bk-city">City <b>*</b></label>
                  <input id="bk-city" name="city" placeholder="e.g. Hyderabad" value={data.city} onChange={(e) => set('city', e.target.value)} />
                  <span className="emsg">Please enter the city.</span>
                </div>
                <div className={fld('pin')}>
                  <label htmlFor="bk-pin">PIN code <b>*</b></label>
                  <input id="bk-pin" name="pin" inputMode="numeric" maxLength={6} placeholder="6 digits" value={data.pin} onChange={(e) => set('pin', e.target.value)} />
                  <span className="emsg">Enter a valid 6-digit PIN.</span>
                </div>
              </div>
              {svc?.drop && (
                <div className={fld('drop')}>
                  <label htmlFor="bk-drop">{DROP_LABEL[svc.key]} {svc.drop === 'required' && <b>*</b>}</label>
                  <input id="bk-drop" name="drop_location" placeholder="Name and area" value={data.drop} onChange={(e) => set('drop', e.target.value)} />
                  <span className="emsg">Please enter where the Sahayak should take your parent.</span>
                </div>
              )}
              <div className="bk-row">
                <div className="fld">
                  <span className="lbl">Is this a follow-up visit?</span>
                  <Chips options={['Yes', 'No']} value={data.followUp} onChange={(v) => set('followUp', v)} />
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
                  <span className="emsg">Please enter your name.</span>
                </div>
                <div className={fld('phone')}>
                  <label htmlFor="bk-phone">Phone / WhatsApp <b>*</b></label>
                  <input id="bk-phone" name="phone" type="tel" autoComplete="tel" placeholder="With country code" value={data.phone} onChange={(e) => set('phone', e.target.value)} />
                  <span className="emsg">Enter a valid phone number.</span>
                </div>
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
                Our care team will call you at your preferred time to confirm the details and match a suitable Sahayak.
              </p>
              <button type="button" className="btn btn-o" onClick={onClose}>Done</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
