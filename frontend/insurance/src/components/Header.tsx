import { useState } from 'react';
import Icon from './Icon';
import { useQuote } from '../context/QuoteContext';
import { asset } from '../data/site';

const NAV_LINKS = [
  { href: '#top', label: 'Travel Insurance', current: true },
  { href: '#visitor', label: 'Visitor Insurance' },
  { href: '#benefits', label: 'Benefits' },
  { href: '#faq', label: 'Claims Assistance' },
  { href: '#faq', label: 'FAQs' },
  { href: '#about', label: 'About Us' },
];

export default function Header() {
  const [open, setOpen] = useState(false);
  const { openQuote } = useQuote();

  function closeMenu() {
    setOpen(false);
  }

  return (
    <header className="hdr">
      <div className="wrap hdr-in">
        <a className="logo" href="#top" aria-label="NRI Parent Service home">
          <span className="logo-mark">
            <img src={asset('logo-mark.png')} alt="" width={200} height={161} />
          </span>
          <span className="logo-word">
            NRI Parent Service
            <span>Travel Insurance</span>
          </span>
        </a>
        <nav className="nav" aria-label="Main">
          {NAV_LINKS.map((l) => (
            <a key={l.label} href={l.href} aria-current={l.current ? 'page' : undefined}>
              {l.label}
            </a>
          ))}
        </nav>
        <div className="hdr-act">
          <a className="btn btn-o lnk-support" href="#support" style={{ border: 0, background: 'transparent' }}>
            <Icon name="i-headset" className="ico n sm" />
            Support
          </a>
          <a className="btn btn-o lnk-signin" href="#signin">Sign in</a>
          <button className="btn btn-p" type="button" onClick={() => openQuote()}>Get a Quote</button>
          <button
            className="burger"
            type="button"
            aria-expanded={open}
            aria-controls="mnav"
            aria-label={open ? 'Close menu' : 'Open menu'}
            onClick={() => setOpen((o) => !o)}
          >
            <Icon name={open ? 'i-x' : 'i-menu'} className="ico n" />
          </button>
        </div>
      </div>
      <nav className="mnav wrap" id="mnav" aria-label="Mobile" data-open={open}>
        {NAV_LINKS.map((l) => (
          <a key={l.label} className="ml" href={l.href} onClick={closeMenu}>
            {l.label}
            <Icon name="i-chev" className="ico s sm" />
          </a>
        ))}
        <div className="g2">
          <a className="btn btn-o" href="#support" onClick={closeMenu}>Support</a>
          <a className="btn btn-o" href="#signin" onClick={closeMenu}>Sign in</a>
        </div>
        <button
          className="btn btn-p"
          type="button"
          style={{ marginTop: 10 }}
          onClick={() => {
            closeMenu();
            openQuote();
          }}
        >
          Get a Free Quote
        </button>
      </nav>
    </header>
  );
}
