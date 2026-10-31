import Icon from './Icon.jsx';

/* What the travel-insurance and companion pages scatter in their empty spaces, for the home page:
 * faint line icons (their SideDecor), a dotted flight path with a little plane (their FlightPath),
 * snapshot photos with a handwritten caption (their flank photos) and handwritten notes ("Insured
 * before takeoff"). Decoration only: hidden from screen readers, never in the way of a click, and
 * gone on narrow screens, where there is no empty space to fill (styles.css .dk). `at` places each
 * one in its section: {top, left, right, bottom}. */

function place(at = {}, extra = {}) {
  const s = { ...extra };
  ['top', 'left', 'right', 'bottom'].forEach((k) => { if (at[k] != null) s[k] = at[k]; });
  return s;
}

/* [name, {top, left|right, size, rotate, opacity}] */
export function Doodles({ items }) {
  return items.map(([name, at], i) => (
    <span key={i} className="dk dd" aria-hidden="true"
      style={place(at, { '--sz': `${at.size || 28}px`, '--r': `${at.rotate || 0}deg`, '--o': at.opacity ?? 0.16,
                         '--dly': `${(i % 4) * 0.8}s` })}>
      <Icon name={name} stroke={1.5} className="" />
    </span>
  ));
}

/* A dotted path with a plane at its end; `flip` sends it the other way. */
export function Trail({ at, width = 220, flip, tone }) {
  return (
    <span className={`dk trail${flip ? ' flip' : ''}${tone ? ' ' + tone : ''}`} aria-hidden="true" style={place(at, { width })}>
      <svg viewBox="0 0 240 90" preserveAspectRatio="none">
        <path d="M4 82 C 60 18, 140 84, 214 20" fill="none" strokeWidth="2.4" strokeDasharray="2 11" strokeLinecap="round" />
      </svg>
      <Icon name="plane" stroke={1.7} className="trail-plane" />
    </span>
  );
}

/* A snapshot: a small photo in a white frame, tilted, its caption handwritten under it. */
export function Snap({ src, caption, at, rotate = -5, width = 150, pos = 'center', tone }) {
  return (
    <span className={`dk snap${tone ? ' ' + tone : ''}`} aria-hidden="true" style={place(at, { width, '--r': `${rotate}deg` })}>
      <span className="snap-ph"><img src={src} alt="" loading="lazy" decoding="async" style={{ objectPosition: pos }} /></span>
      {caption && <span className="snap-cap">{caption}</span>}
    </span>
  );
}

/* The empty band left of the content on a wide screen, filled: a photo cut to a shape (arch,
 * circle, blob, pill, or `art` for a drawing with no frame), a tinted shape behind it, a dotted
 * ring round it, and small icons in bubbles sitting on the ring. It takes the band's width
 * (styles.css .side): where the band is too narrow for the photo only the icons stay, in a
 * column, and where there is no band at all, nothing. `icons` are [name, colour]; `top` places
 * it down its section. */
export function Side({ img, pos = 'center', shape = 'arch', top, tint = '#2446B8', icons = [] }) {
  return (
    <span className={`dk side ${shape}`} aria-hidden="true" style={{ top, '--c': tint }}>
      <span className="side-in">
        {img && <span className="side-ring" />}
        {img && <span className="side-ph"><img src={img} alt="" loading="lazy" decoding="async" style={{ objectPosition: pos }} /></span>}
        {icons.map(([name, color], i) => (
          <i key={name} className={`side-ic n${i}`} style={{ '--ic': color }}><Icon name={name} stroke={1.9} className="" /></i>
        ))}
      </span>
    </span>
  );
}

/* A handwritten note, with a small line icon after it. */
export function Note({ children, at, rotate = -4, icon = 'heart', tone }) {
  return (
    <span className={`dk note${tone ? ' ' + tone : ''}`} aria-hidden="true" style={place(at, { '--r': `${rotate}deg` })}>
      {children}{icon && <Icon name={icon} stroke={1.8} className="" />}
    </span>
  );
}
