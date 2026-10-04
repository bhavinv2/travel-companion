import { useEffect, useRef, useState } from 'react';
import Icon from './Icon.jsx';
import { site } from '../data/site.js';
import { cx } from './ui.jsx';

/* The dial-code picker, the same control the travel-insurance page uses.
 *
 * Ported from frontend/insurance/src/components/CountryCombo.tsx rather than reinvented, so
 * the two public pages ask for a phone number the same way. The list itself comes from the
 * server -- services/phone.py is the one definition, and it is what validates the number
 * afterwards, so a picker offering anything else would only mislead.
 *
 * The short fallback list is for `npm run dev`, where nothing is injected. It is deliberately
 * only the common ones: a stale copy of 130 countries is worse than an obviously partial one.
 */
const FALLBACK = [
  { name: 'United States', iso: 'US', dial: '1' },
  { name: 'India', iso: 'IN', dial: '91' },
  { name: 'Canada', iso: 'CA', dial: '1' },
  { name: 'United Kingdom', iso: 'GB', dial: '44' },
  { name: 'Australia', iso: 'AU', dial: '61' },
  { name: 'United Arab Emirates', iso: 'AE', dial: '971' },
  { name: 'Singapore', iso: 'SG', dial: '65' },
];

export const COUNTRIES = (site.dialCodes && site.dialCodes.length) ? site.dialCodes : FALLBACK;
const DEFAULT_ISO = 'IN';   // the parents are in India; the person booking often is not

/** The country's flag. Windows has no flag font and draws the two letters instead, which in
 *  this control reads as "US +1" -- still correct, just not a flag. */
function flagEmoji(iso) {
  if (!iso || iso.length !== 2) return '';
  return String.fromCodePoint(...[...iso.toUpperCase()]
    .map((ch) => 0x1F1E6 + ch.charCodeAt(0) - 65));
}

const POP_CHROME = 94;
const LIST_MAX = 232;
const LIST_MIN = 132;

export function countryFor(dial) {
  return COUNTRIES.find((c) => '+' + c.dial === dial)
      || COUNTRIES.find((c) => c.iso === DEFAULT_ISO)
      || COUNTRIES[0];
}

/** Dial code + number, as one field. `value` is { dial, tel }. */
export default function PhoneField({ id, label, value, onChange, required, hint, invalid }) {
  const box = useRef(null);
  const search = useRef(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [place, setPlace] = useState({ up: false, listMax: LIST_MAX });
  const current = countryFor(value.dial);

  useEffect(() => {
    const away = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, []);

  useEffect(() => {
    if (open && search.current) search.current.focus({ preventScroll: true });
  }, [open]);

  /* Open upwards when there is more room there, and cap the list so the popover never spills
     out of whatever is clipping it -- here that is usually the booking dialog's own scroll. */
  const measure = () => {
    const el = box.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    let host = el.parentElement;
    while (host && host !== document.body) {
      const o = getComputedStyle(host);
      if (o.overflow !== 'visible' || o.overflowY !== 'visible') break;
      host = host.parentElement;
    }
    const hostRect = host && host !== document.body ? host.getBoundingClientRect() : null;
    const top = hostRect ? Math.max(hostRect.top, 0) : 0;
    const bottom = hostRect ? Math.min(hostRect.bottom, window.innerHeight) : window.innerHeight;
    const below = bottom - r.bottom - 12;
    const above = r.top - top - 12;
    const up = above > below;
    const room = (up ? above : below) - POP_CHROME;
    setPlace({ up, listMax: Math.max(LIST_MIN, Math.min(LIST_MAX, room)) });
  };

  const toggle = (next) => {
    const willOpen = next === undefined ? !open : next;
    if (willOpen) { measure(); setQuery(''); }
    setOpen(willOpen);
  };

  const q = query.toLowerCase().replace(/\+/g, '').trim();
  const rows = COUNTRIES.filter(
    (c) => !q || c.name.toLowerCase().includes(q) || c.dial.includes(q));

  return (
    <div className={cx('fld', invalid && 'err')}>
      <label htmlFor={id}>{label}{required && <b> *</b>}</label>
      <div className="ph-row">
        <div className="itel" ref={box}>
          <button type="button" className="itel-btn" aria-haspopup="listbox"
                  aria-expanded={open} aria-label="Country dialling code"
                  onClick={() => toggle()}>
            <span className="itel-flag">{flagEmoji(current.iso)}</span>
            <span className="itel-code">+{current.dial}</span>
            <Icon name="arrow" sw={2.4} className="itel-chev" />
          </button>
          {open && (
            <div className={cx('itel-pop', place.up && 'up')}>
              <input type="text" className="itel-search" placeholder="Search country or code"
                     autoComplete="off" ref={search} value={query}
                     onChange={(e) => setQuery(e.target.value)} />
              <ul className="itel-list" role="listbox" style={{ maxHeight: place.listMax }}>
                {rows.length === 0 && <li className="itel-none">No match</li>}
                {rows.map((c) => (
                  <li key={c.iso + c.dial} role="option"
                      aria-selected={c.iso === current.iso}
                      className={cx(c.iso === current.iso && 'on')}
                      onClick={() => { onChange({ ...value, dial: '+' + c.dial }); toggle(false); }}>
                    <span className="itel-fl">{flagEmoji(c.iso)}</span>
                    <span className="itel-nm">{c.name}</span>
                    <span className="itel-dl">+{c.dial}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
        <input id={id} className="ph-num" type="tel" inputMode="tel" autoComplete="tel"
               placeholder="Phone number" value={value.tel} required={required}
               onChange={(e) => onChange({ ...value, tel: e.target.value })} />
      </div>
      {hint && <span className="ph-hint">{hint}</span>}
      <span className="emsg">Enter a phone number we can reach you on.</span>
    </div>
  );
}
