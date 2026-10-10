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

/** The country a value is for. The ISO wins when there is one: +1 is the US, Canada and a dozen
 *  islands, +7 Russia and Kazakhstan, so a dial code alone redrew "United States" as whichever
 *  of them happened to come first in the list. */
export function countryFor(dial, iso) {
  return (iso && COUNTRIES.find((c) => c.iso === iso))
      || COUNTRIES.find((c) => '+' + c.dial === dial)
      || COUNTRIES.find((c) => c.iso === DEFAULT_ISO)
      || COUNTRIES[0];
}

/** What a form sends for one of these fields: the number as typed and the country it was typed
 *  for, separately -- the shape every server-rendered form on the site already posts.
 *
 *  Not "+<dial> <number>" joined: a leading + tells services/phone.normalise the number is
 *  already international, so it skips dropping the national trunk 0. A Swede typing their usual
 *  "0764498115" was stored as +460764498115 -- a different number. Sent apart, the server drops
 *  the 0 exactly as it does for every other form; a + typed into the box still wins. */
export function phonePair(value) {
  return { tel: (value.tel || '').trim(), cc: countryFor(value.dial, value.iso).iso };
}

/* Digits after the country code, per code, for the countries where that is fixed -- the same
   table services/phone.NATIONAL_RANGE holds the server to, injected with the page. */
const RULES = site.phoneRules || { 1: [10, 10], 91: [10, 10], 44: [9, 10], 61: [9, 9], 971: [8, 9], 65: [8, 8] };
const DIALS = [...new Set(COUNTRIES.map((c) => c.dial))].sort((a, b) => b.length - a.length);

/** What is wrong with a number, in plain words, or '' when it can be dialled.
 *
 *  Reads it the way services/phone.normalise does -- a leading + or 00 means the code is typed
 *  in, a single trunk 0 is dropped, a national number typed with its code but no + is accepted --
 *  and then holds it to the country's length, so "one digit short" is said here, before sending. */
export function phoneError(value, { required = false } = {}) {
  const raw = (value.tel || '').trim();
  if (!raw) return required ? 'Enter a phone number we can reach you on.' : '';
  if (/[^\d\s()+.\-]/.test(raw)) return 'Use digits only.';
  let digits = raw.replace(/\D/g, '');
  const country = countryFor(value.dial, value.iso);
  let dial = country.dial;
  let national;
  if (raw.startsWith('+') || digits.startsWith('00')) {
    if (digits.startsWith('00')) digits = digits.slice(2);
    dial = DIALS.find((d) => digits.startsWith(d)) || '';
    if (!dial) return 'That number does not start with a country code.';
    national = digits.slice(dial.length);
  } else {
    national = digits.replace(/^0+/, '');
    const [lo] = RULES[dial] || [];
    if (lo && national.length > lo && national.startsWith(dial)
        && national.length - dial.length >= lo) national = national.slice(dial.length);
  }
  const [lo, hi] = RULES[dial] || [6, 15 - dial.length];
  if (national.length < lo) return `That number is too short for +${dial} — it needs ${lo === hi ? lo : `${lo}–${hi}`} digits.`;
  if (national.length > hi) return `That number is too long for +${dial} — it needs ${lo === hi ? lo : `${lo}–${hi}`} digits.`;
  return '';
}

/** A number as a person should read it, for text that is never normalised by the server (a note
 *  CS reads). A + typed into the box wins; otherwise the code, then the number without its
 *  national trunk 0 -- "+46 0764498115" is not a number anybody can ring. */
export function phoneText(value) {
  const tel = (value.tel || '').trim();
  if (!tel) return '';
  if (tel.startsWith('+')) return tel;
  return `${value.dial || ''} ${tel.replace(/^0+/, '')}`.trim();
}

/** Dial code + number, as one field. `value` is { dial, tel, iso? }. */
export default function PhoneField({ id, label, value, onChange, required, hint, invalid, error }) {
  const box = useRef(null);
  const search = useRef(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [place, setPlace] = useState({ up: false, listMax: LIST_MAX });
  const current = countryFor(value.dial, value.iso);

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
    <div className={cx('fld', (invalid || error) && 'err')}>
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
                      onClick={() => { onChange({ ...value, dial: '+' + c.dial, iso: c.iso }); toggle(false); }}>
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
               placeholder={current.dial === '91' ? '98480 00000' : 'Phone number'}
               value={value.tel} required={required} aria-invalid={!!(invalid || error)}
               onChange={(e) => onChange({ ...value, tel: e.target.value })} />
      </div>
      {hint && <span className="ph-hint">{hint}</span>}
      <span className="emsg">{error || 'Enter a phone number we can reach you on.'}</span>
    </div>
  );
}
