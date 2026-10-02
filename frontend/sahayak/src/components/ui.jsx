import { forwardRef, useState } from 'react';
import { useInView } from '../hooks.js';
import Icon from './Icon.jsx';

const cx = (...c) => c.filter(Boolean).join(' ');

/** Element that fades/slides in when scrolled into view (the `.reveal` animation). */
export function Reveal({ as: Tag = 'div', className, children, ...rest }) {
  const [ref, inView] = useInView();
  return (
    <Tag ref={ref} className={cx(className, 'reveal', inView && 'in')} {...rest}>
      {children}
    </Tag>
  );
}

export function ArrowButton({ children, className = 'btn btn-p', ...rest }) {
  return (
    <button type="button" className={className} {...rest}>
      {children}
      <Icon name="arrow" sw={2} />
    </button>
  );
}

export function ArrowLink({ children, className = 'btn btn-p', ...rest }) {
  return (
    <a className={className} {...rest}>
      {children}
      <Icon name="arrow" sw={2} />
    </a>
  );
}

/**
 * A row of toggle chips. Single-select: value is a string ('' when none; clicking the
 * selected chip clears it). Multi-select: value is an array.
 */
export const Chips = forwardRef(function Chips({ options, value, onChange, multi = false }, ref) {
  const isOn = (o) => (multi ? value.includes(o) : value === o);
  const toggle = (o) => {
    if (multi) onChange(isOn(o) ? value.filter((v) => v !== o) : [...value, o]);
    else onChange(isOn(o) ? '' : o);
  };
  return (
    <div className="chips" ref={ref}>
      {options.map((o) => (
        <button
          key={o}
          type="button"
          className={cx('chip', isOn(o) && 'on')}
          aria-pressed={isOn(o)}
          onClick={() => toggle(o)}
        >
          {o}
        </button>
      ))}
    </div>
  );
});

/** A floating label pill used on the hero illustrations. */
export function Tag({ icon, sw = 1.9, title, sub, className }) {
  return (
    <div className={cx('tag', className)}>
      <span><Icon name={icon} sw={sw} /></span>
      <span style={{ width: 'auto', height: 'auto', background: 'none', color: 'inherit', display: 'block' }}>
        {title}
        <small>{sub}</small>
      </span>
    </div>
  );
}

/** Dashed upload box; shows the chosen file name in place of the action label. */
export function Upload({ id, name, icon, title, hint, action = 'Upload', onChange }) {
  const [file, setFile] = useState(null);
  return (
    <label className="up" htmlFor={id}>
      <input
        id={id}
        type="file"
        name={name}
        onChange={(e) => {
          const f = e.target.files[0] || null;
          setFile(f);
          onChange?.(f);
        }}
      />
      <span className="ic"><Icon name={icon} /></span>
      <span><b>{title}</b><small>{hint}</small></span>
      <span className={cx('go', file && 'fname')}>{file ? file.name : action}</span>
    </label>
  );
}

/**
 * Handwritten quote shown under a section title.
 * tone: 'a' accent (default), 'p' primary, 'h' light primary.
 */
export function Quote({ children, tone = 'a', style }) {
  return <span className={cx('script', tone !== 'a' && tone)} style={style}>{children}</span>;
}

/** Faded icons along the left/right page edges (wide screens only). */
export function SideDecor({ icons }) {
  return (
    <div className="side-decor" aria-hidden="true">
      {icons.map((ic, i) => (
        <span
          key={i}
          className={ic.side}
          style={{
            top: ic.top,
            width: ic.size ?? 46,
            height: ic.size ?? 46,
            opacity: ic.opacity ?? 0.12,
            transform: ic.rotate ? `rotate(${ic.rotate}deg)` : undefined,
          }}
        >
          <Icon name={ic.name} sw={1.4} />
        </span>
      ))}
    </div>
  );
}

/** Kicker, title, quote and lead in one block; `center` centres it. */
export function SectionHead({ kick, title, quote, tone, sub, center, className }) {
  return (
    <Reveal className={cx('sec-h', center && 'c', className)}>
      {kick && <span className="kick">{kick}</span>}
      <h2 className="h2">{title}</h2>
      {quote && <Quote tone={tone}>{quote}</Quote>}
      {sub && <p className="sub">{sub}</p>}
    </Reveal>
  );
}

export { cx };
