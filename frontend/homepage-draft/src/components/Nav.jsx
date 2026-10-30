import { useEffect, useState } from 'react';
import Icon from './Icon.jsx';
import { site } from '../data/site.js';
import { useScroll } from '../hooks.js';

const LINKS = [
  ['#services', 'Services'],
  ['#why', 'Why Us'],
  ['#reviews', 'Reviews'],
  ['#partners', 'Partners'],
  ['#resources', 'Resources'],
];

export function Brand({ href = '#top' }) {
  return (
    <a className="brand" href={href} aria-label="NRI Parent Service home">
      <span className="logo"><Icon name="logo" stroke={1.9} /></span>
      <span><b>NRI Parent Service</b><small>Your Parents, Our Priority</small></span>
    </a>
  );
}

export default function Nav() {
  const { y, p } = useScroll();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    const onResize = () => { if (window.innerWidth > 1100) setOpen(false); };
    document.addEventListener('keydown', onKey);
    window.addEventListener('resize', onResize);
    return () => { document.removeEventListener('keydown', onKey); window.removeEventListener('resize', onResize); };
  }, []);

  return (
    <header className={`nav${y > 30 ? ' scrolled' : ''}`}>
      <div className="progress" style={{ transform: `scaleX(${p})` }} aria-hidden="true" />
      <div className="wrap nav-in">
        <Brand />
        <nav className="links" aria-label="Main">
          {LINKS.map(([h, t]) => <a key={h} href={h}>{t}</a>)}
          <a href={site.contactUrl}>Contact</a>
        </nav>
        <div className="nav-cta">
          <a className="btn btn-o btn-sm" href={site.contactUrl}>Talk to Us</a>
          <a className="btn btn-a btn-sm shine" href={site.sahayakUrl}>Book a Sahayak</a>
          <button type="button" className="burger" aria-label={open ? 'Close menu' : 'Open menu'}
            aria-expanded={open} aria-controls="mmenu" onClick={() => setOpen(!open)}>
            <Icon name={open ? 'close' : 'menu'} />
          </button>
        </div>
      </div>
      <div className={`mmenu${open ? ' open' : ''}`} id="mmenu" hidden={!open}>
        <div className="wrap">
          <nav aria-label="Mobile">
            {LINKS.map(([h, t], i) => (
              <a key={h} href={h} style={{ '--d': `${i * 40}ms` }} onClick={() => setOpen(false)}>{t}</a>
            ))}
            <a href={site.contactUrl} style={{ '--d': `${LINKS.length * 40}ms` }}>Contact</a>
          </nav>
          <div className="mm-cta">
            <a className="btn btn-o" href={site.contactUrl}>Talk to Us</a>
            <a className="btn btn-a" href={site.sahayakUrl}>Book a Sahayak</a>
          </div>
        </div>
      </div>
    </header>
  );
}
