import { useEffect, useRef, useState } from 'react';
import Icon from './Icon';
import { COUNTRIES, flagEmoji, type Country } from '../data/countries';

interface BaseProps {
  invalid?: boolean;
}

/** Height of the popover's chrome (search box + padding) above the country list. */
const POP_CHROME = 94;
const LIST_MAX = 232;
const LIST_MIN = 132;

function usePopover() {
  const boxRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  // the popover is drawn inside a scrollable card, so it has to fit that card
  const [place, setPlace] = useState({ up: false, listMax: LIST_MAX });

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  /** Open above instead of below when there is more room there, and cap the
   *  list so the popover never spills past its scroll container. */
  function measure() {
    const box = boxRef.current;
    if (!box) return;
    const r = box.getBoundingClientRect();
    // the popover is bounded by whichever ancestor clips or scrolls first —
    // a modal, a section with overflow:hidden, or failing that the viewport
    let host: HTMLElement | null = box.parentElement;
    while (host && host !== document.body) {
      const o = getComputedStyle(host);
      if (o.overflow !== 'visible' || o.overflowY !== 'visible') break;
      host = host.parentElement;
    }
    const hostRect = host && host !== document.body ? host.getBoundingClientRect() : null;
    // the sticky header sits above the popover, so treat it as the ceiling
    const headerH = document.querySelector('.hdr')?.getBoundingClientRect().height ?? 0;
    const top = hostRect ? Math.max(hostRect.top, headerH) : headerH;
    let bottom = hostRect ? Math.min(hostRect.bottom, window.innerHeight) : window.innerHeight;
    // the floating WhatsApp button is fixed at root level, so it paints over this
    // popover no matter its z-index — stop short of it when they would collide
    const fab = document.querySelector('.wafab');
    if (fab) {
      const f = fab.getBoundingClientRect();
      if (!(r.right < f.left || r.left > f.right)) bottom = Math.min(bottom, f.top - 10);
    }
    const below = bottom - r.bottom - 12;
    const above = r.top - top - 12;
    const up = above > below;
    const room = (up ? above : below) - POP_CHROME;
    setPlace({ up, listMax: Math.max(LIST_MIN, Math.min(LIST_MAX, room)) });
  }

  function toggle(next?: boolean) {
    const willOpen = next ?? !open;
    if (willOpen) measure();
    setOpen(willOpen);
    if (willOpen) setQuery('');
  }

  // autoFocus scrolls the field into view, which moves the popover after it has
  // been placed — focus without scrolling instead
  useEffect(() => {
    if (open) searchRef.current?.focus({ preventScroll: true });
  }, [open]);

  const rows = COUNTRIES.filter((c) => {
    const q = query.toLowerCase().replace(/\+/g, '').trim();
    return !q || c.name.toLowerCase().includes(q) || c.dial.includes(q);
  });

  return { boxRef, searchRef, open, toggle, query, setQuery, rows, place };
}

/** Flag + dial-code searchable picker, matching the original "expert form" mobile field. */
export function PhoneCombo({
  dial, onChange,
}: BaseProps & { dial: string; onChange: (c: Country) => void }) {
  const { boxRef, searchRef, open, toggle, query, setQuery, rows, place } = usePopover();
  const current = COUNTRIES.find((c) => `+${c.dial}` === dial) ?? COUNTRIES.find((c) => c.name === 'India')!;

  return (
    <div className="itel" id="x-itel" ref={boxRef}>
      <button type="button" className="itel-btn" aria-haspopup="listbox" aria-expanded={open} onClick={() => toggle()}>
        <span className="itel-flag">{flagEmoji(current.iso)}</span>
        <span className="itel-code">+{current.dial}</span>
        <Icon name="i-chev" className="ico s xs" rotate={90} />
      </button>
      {open && (
        <div className={`itel-pop${place.up ? ' up' : ''}`}>
          <input
            type="text"
            className="itel-search"
            placeholder="Search country or code"
            autoComplete="off"
            ref={searchRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <ul className="itel-list" role="listbox" style={{ maxHeight: place.listMax }}>
            {rows.length === 0 && <li style={{ justifyContent: 'center', color: 'var(--slate)', cursor: 'default' }}>No match</li>}
            {rows.map((c) => (
              <li key={c.iso} role="option" aria-selected={c.name === current.name} onClick={() => { onChange(c); toggle(false); }}>
                <span style={{ fontSize: 16 }}>{flagEmoji(c.iso)}</span>
                <span className="itel-nm">{c.name}</span>
                <span className="itel-dl">+{c.dial}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Searchable destination country picker, matching the original "expert form" destination field. */
export function DestinationCombo({
  id, value, onChange, invalid,
}: BaseProps & { id?: string; value: string; onChange: (name: string) => void }) {
  const { boxRef, searchRef, open, toggle, query, setQuery, rows, place } = usePopover();

  return (
    <div className="idest" ref={boxRef}>
      <button
        id={id}
        type="button"
        className={`idest-btn${invalid ? ' invalid' : ''}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => toggle()}
      >
        <span className={`idest-val${value ? '' : ' ph'}`}>{value || 'Select a country'}</span>
        <Icon name="i-chev" className="ico s xs" rotate={90} />
      </button>
      {open && (
        <div className={`itel-pop idest-pop${place.up ? ' up' : ''}`}>
          <input
            type="text"
            className="itel-search"
            placeholder="Search country"
            autoComplete="off"
            ref={searchRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <ul className="itel-list" role="listbox" style={{ maxHeight: place.listMax }}>
            {rows.length === 0 && <li style={{ justifyContent: 'center', color: 'var(--slate)', cursor: 'default' }}>No match</li>}
            {rows.map((c) => (
              <li key={c.iso} role="option" aria-selected={c.name === value} onClick={() => { onChange(c.name); toggle(false); }}>
                <span style={{ fontSize: 16 }}>{flagEmoji(c.iso)}</span>
                <span className="itel-nm">{c.name}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** A plain list of choices in the same dropdown as the country pickers.
 *
 * A native <select> looked out of place here: its list is drawn by the operating system, so on a
 * page styled this carefully it arrives as a grey system menu in a different font, and the only
 * part we can style -- the closed control -- ends up promising something the open list does not
 * deliver. This reuses the popover the country fields already use, including its placement logic,
 * so it sits correctly inside a scrolling modal. No search box: a handful of options do not need
 * one.
 */
export function OptionCombo({
  id, value, options, onChange, icon,
}: {
  id?: string;
  value: string;
  options: readonly string[];
  onChange: (value: string) => void;
  icon?: string;
}) {
  const { boxRef, open, toggle, place } = usePopover();

  return (
    <div className="idest" ref={boxRef}>
      <button
        id={id}
        type="button"
        className="idest-btn"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => toggle()}
      >
        {icon && <Icon name={icon} className="ico s sm" />}
        <span className="idest-val">{value}</span>
        <Icon name="i-chev" className="ico s xs" rotate={90} />
      </button>
      {open && (
        <div className={`itel-pop idest-pop${place.up ? ' up' : ''}`}>
          <ul className="itel-list" role="listbox" style={{ maxHeight: place.listMax }}>
            {options.map((o) => (
              <li
                key={o}
                role="option"
                aria-selected={o === value}
                className={o === value ? 'on' : undefined}
                onClick={() => { onChange(o); toggle(false); }}
              >
                <span className="itel-nm">{o}</span>
                {o === value && <Icon name="i-check" className="ico s xs" />}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
