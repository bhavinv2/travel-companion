import { useEffect, useRef, useState } from 'react';
import Icon from './Icon';
import { COUNTRIES, flagEmoji, type Country } from '../data/countries';

interface BaseProps {
  invalid?: boolean;
}

function usePopover() {
  const boxRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('click', onDoc);
    return () => document.removeEventListener('click', onDoc);
  }, []);

  function toggle(next?: boolean) {
    const willOpen = next ?? !open;
    setOpen(willOpen);
    if (willOpen) setQuery('');
  }

  const rows = COUNTRIES.filter((c) => {
    const q = query.toLowerCase().replace(/\+/g, '').trim();
    return !q || c.name.toLowerCase().includes(q) || c.dial.includes(q);
  });

  return { boxRef, open, toggle, query, setQuery, rows };
}

/** Flag + dial-code searchable picker, matching the original "expert form" mobile field. */
export function PhoneCombo({
  dial, onChange,
}: BaseProps & { dial: string; onChange: (c: Country) => void }) {
  const { boxRef, open, toggle, query, setQuery, rows } = usePopover();
  const current = COUNTRIES.find((c) => `+${c.dial}` === dial) ?? COUNTRIES.find((c) => c.name === 'India')!;

  return (
    <div className="itel" id="x-itel" ref={boxRef}>
      <button type="button" className="itel-btn" aria-haspopup="listbox" aria-expanded={open} onClick={() => toggle()}>
        <span className="itel-flag">{flagEmoji(current.iso)}</span>
        <span className="itel-code">+{current.dial}</span>
        <Icon name="i-chev" className="ico s xs" rotate={90} />
      </button>
      {open && (
        <div className="itel-pop">
          <input
            type="text"
            className="itel-search"
            placeholder="Search country or code"
            autoComplete="off"
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <ul className="itel-list" role="listbox">
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
  value, onChange, invalid,
}: BaseProps & { value: string; onChange: (name: string) => void }) {
  const { boxRef, open, toggle, query, setQuery, rows } = usePopover();

  return (
    <div className="idest" id="x-idest" ref={boxRef}>
      <button
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
        <div className="itel-pop idest-pop">
          <input
            type="text"
            className="itel-search"
            placeholder="Search country"
            autoComplete="off"
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <ul className="itel-list" role="listbox">
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
