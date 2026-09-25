// Central icon + illustration-figure sprite sheet, mounted once and referenced
// everywhere via <Icon name="i-shield" /> or <use href="#fig" />.
export default function IconSprite() {
  return (
    <svg width="0" height="0" style={{ position: 'absolute' }} aria-hidden="true">
      <defs>
        <symbol id="fig" viewBox="0 0 60 100">
          <path d="M3 100V64a27 27 0 0 1 54 0v36z" />
          <circle cx="30" cy="18" r="15" fill="#8C5A3C" />
          <path d="M15 16a15 15 0 0 1 30 0c-4-5-9-7-15-7s-11 2-15 7z" fill="#2B1B14" />
        </symbol>
        <symbol id="elder" viewBox="0 0 60 100">
          <path d="M3 100V64a27 27 0 0 1 54 0v36z" />
          <ellipse cx="30" cy="70" rx="6" ry="10" fill="#fff" fillOpacity=".85" />
          <circle cx="30" cy="18" r="15" fill="#A36B4A" />
          <path d="M15 16a15 15 0 0 1 30 0c-4-5-9-7-15-7s-11 2-15 7z" fill="#E9EDF5" />
        </symbol>
        <symbol id="bag" viewBox="0 0 40 60">
          <path d="M13 10V2h14v8h-3V5h-8v5z" />
          <rect x="2" y="10" width="36" height="44" rx="7" />
          <rect x="8" y="54" width="5" height="5" rx="2" />
          <rect x="27" y="54" width="5" height="5" rx="2" />
        </symbol>
        <symbol id="plane" viewBox="0 0 184 70">
          <path d="M86 24h24L92 6H80z" />
          <path d="M0 30C24 20 132 18 164 22c14 2 20 8 12 12-32 6-142 6-176-4z" />
          <path d="M78 30h34L70 66H52z" />
          <path d="M6 30-6 0h16l24 24z" />
        </symbol>

        <symbol id="i-shield" viewBox="0 0 24 24"><path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6z" /><path d="m9 12 2 2 4-4" /></symbol>
        <symbol id="i-globe" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.5 2.5 3.8 5.5 3.8 9s-1.3 6.5-3.8 9c-2.5-2.5-3.8-5.5-3.8-9S9.5 5.5 12 3z" /></symbol>
        <symbol id="i-heart" viewBox="0 0 24 24"><path d="M20.4 12.5 12 21l-8.4-8.5A5 5 0 0 1 12 6a5 5 0 0 1 8.4 6.5z" /><path d="M3.5 12H8l1.5-2.5 3 5 1.5-2.5h6" /></symbol>
        <symbol id="i-headset" viewBox="0 0 24 24"><path d="M4 15v-3a8 8 0 0 1 16 0v3" /><rect x="2.5" y="14" width="4.5" height="6" rx="1.5" /><rect x="17" y="14" width="4.5" height="6" rx="1.5" /></symbol>
        <symbol id="i-steth" viewBox="0 0 24 24"><path d="M5 3v5a4 4 0 0 0 8 0V3" /><path d="M9 12v2a5 5 0 0 0 10 0v-2" /><circle cx="19" cy="10" r="2" /></symbol>
        <symbol id="i-hospital" viewBox="0 0 24 24"><path d="M4 21V5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v16M2 21h20" /><path d="M12 7v6M9 10h6M10 21v-4h4v4" /></symbol>
        <symbol id="i-route" viewBox="0 0 24 24"><circle cx="6" cy="19" r="2" /><circle cx="18" cy="5" r="2" /><path d="M8 19h8.5a3.5 3.5 0 0 0 0-7h-9a3.5 3.5 0 0 1 0-7H16" /></symbol>
        <symbol id="i-bag" viewBox="0 0 24 24"><rect x="5" y="7" width="14" height="13" rx="2" /><path d="M9 7V4h6v3M9 11v5M15 11v5" /></symbol>
        <symbol id="i-clock" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></symbol>
        <symbol id="i-plane" viewBox="0 0 24 24"><path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z" /></symbol>
        <symbol id="i-ambulance" viewBox="0 0 24 24"><path d="M2 17V8a1 1 0 0 1 1-1h11v10" /><path d="M14 10h4l4 4v3h-2" /><circle cx="7" cy="17.5" r="2" /><circle cx="17" cy="17.5" r="2" /><path d="M9 17.5h6M8 9.5v5M5.5 12h5" /></symbol>
        <symbol id="i-wallet" viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="14" rx="2.5" /><path d="M3 10h18M16 15h2" /></symbol>
        <symbol id="i-file" viewBox="0 0 24 24"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6M8 13h8M8 17h5" /></symbol>
        <symbol id="i-lock" viewBox="0 0 24 24"><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></symbol>
        <symbol id="i-check" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5" /></symbol>
        <symbol id="i-checkc" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" /><path d="m8 12 3 3 5-6" /></symbol>
        <symbol id="i-minusc" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" /><path d="M8 12h8" /></symbol>
        <symbol id="i-arrow" viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6" /></symbol>
        <symbol id="i-back" viewBox="0 0 24 24"><path d="M19 12H5M11 6l-6 6 6 6" /></symbol>
        <symbol id="i-video" viewBox="0 0 24 24"><rect x="2" y="6" width="14" height="12" rx="2" /><path d="m16 10.5 6-3.5v10l-6-3.5" /></symbol>
        <symbol id="i-mic" viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></symbol>
        <symbol id="i-info" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></symbol>
        <symbol id="i-users" viewBox="0 0 24 24"><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0" /><circle cx="17" cy="9" r="2.5" /><path d="M16.5 14a5 5 0 0 1 5 6" /></symbol>
        <symbol id="i-pin" viewBox="0 0 24 24"><path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 0 1 16 0z" /><circle cx="12" cy="10" r="3" /></symbol>
        <symbol id="i-cal" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M16 3v4M8 3v4M3 10h18" /></symbol>
        <symbol id="i-passport" viewBox="0 0 24 24"><rect x="5" y="3" width="14" height="18" rx="2" /><circle cx="12" cy="10" r="3" /><path d="M9 16h6" /></symbol>
        <symbol id="i-stamp" viewBox="0 0 24 24"><path d="M9 13V9a3 3 0 1 1 6 0v4" /><path d="M5 13h14l1 4H4z" /><path d="M4 21h16" /></symbol>
        <symbol id="i-flag" viewBox="0 0 24 24"><path d="M5 21V4M5 4h11l-2 4 2 4H5" /></symbol>
        <symbol id="i-ticket" viewBox="0 0 24 24"><path d="M3 8a2 2 0 0 0 2-2h14a2 2 0 0 0 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 0-2 2H5a2 2 0 0 0-2-2v-2a2 2 0 0 0 0-4z" /><path d="M14 7v2M14 11v2M14 15v2" /></symbol>
        <symbol id="i-landmark" viewBox="0 0 24 24"><path d="M3 21h18M5 10h14M12 3 4 7h16zM6 10v8M10 10v8M14 10v8M18 10v8" /></symbol>
        <symbol id="i-list" viewBox="0 0 24 24"><path d="M8 6h13M8 12h13M8 18h13" /><path d="M3.5 6h.01M3.5 12h.01M3.5 18h.01" /></symbol>
        <symbol id="i-phone" viewBox="0 0 24 24"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z" /></symbol>
        <symbol id="i-mail" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 7 9 6 9-6" /></symbol>
        <symbol id="i-menu" viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16" /></symbol>
        <symbol id="i-x" viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12" /></symbol>
        <symbol id="i-plus" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></symbol>
        <symbol id="i-minus" viewBox="0 0 24 24"><path d="M5 12h14" /></symbol>
        <symbol id="i-chev" viewBox="0 0 24 24"><path d="m9 6 6 6-6 6" /></symbol>
        <symbol id="i-star" viewBox="0 0 24 24"><path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z" /></symbol>
        <symbol id="i-sparkle" viewBox="0 0 24 24"><path d="M12 2c.6 4.4 2.2 6 6.6 6.6-4.4.6-6 2.2-6.6 6.6-.6-4.4-2.2-6-6.6-6.6C9.8 8 11.4 6.4 12 2z" /><path d="M19 15c.3 1.8.9 2.4 2.7 2.7-1.8.3-2.4.9-2.7 2.7-.3-1.8-.9-2.4-2.7-2.7 1.8-.3 2.4-.9 2.7-2.7z" /></symbol>
        <symbol id="i-user" viewBox="0 0 24 24"><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></symbol>
        <symbol id="i-mobile" viewBox="0 0 24 24"><rect x="6" y="2" width="12" height="20" rx="2.5" /><path d="M11 18h2" /></symbol>
        <symbol id="i-ig" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="5" /><circle cx="12" cy="12" r="4" /><path d="M17.5 6.5h.01" /></symbol>
        <symbol id="i-fb" viewBox="0 0 24 24"><path d="M15 3h-3a4 4 0 0 0-4 4v3H5v4h3v7h4v-7h3l1-4h-4V7a1 1 0 0 1 1-1h3z" /></symbol>
        <symbol id="i-li" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="3" /><path d="M8 10v7M8 7v.01M12 17v-4a2 2 0 0 1 4 0v4M12 10v7" /></symbol>
        <symbol id="i-yt" viewBox="0 0 24 24"><rect x="2" y="5" width="20" height="14" rx="4" /><path d="m10 9 5 3-5 3z" /></symbol>
        <symbol id="i-whatsapp" viewBox="0 0 24 24"><path d="M12.04 2.02c-5.5 0-9.96 4.46-9.96 9.96 0 1.76.46 3.45 1.34 4.96L2 22l5.2-1.36a9.9 9.9 0 0 0 4.84 1.24h.01c5.5 0 9.96-4.46 9.96-9.96 0-2.66-1.04-5.16-2.92-7.04a9.88 9.88 0 0 0-7.05-2.9zM12.05 20.2h-.01a8.2 8.2 0 0 1-4.18-1.15l-.3-.18-3.09.81.82-3.01-.2-.31a8.22 8.22 0 0 1-1.26-4.38c0-4.54 3.7-8.24 8.25-8.24 2.2 0 4.27.86 5.83 2.42a8.2 8.2 0 0 1 2.41 5.83c0 4.55-3.7 8.25-8.24 8.25zm4.52-6.16c-.25-.12-1.47-.72-1.69-.81-.23-.08-.39-.12-.56.13-.16.24-.64.8-.79.97-.14.16-.29.18-.54.06-.25-.12-1.05-.39-1.99-1.23-.74-.66-1.23-1.47-1.38-1.72-.14-.25-.02-.38.11-.5.11-.11.25-.29.37-.43.13-.15.17-.25.25-.42.08-.16.04-.31-.02-.43-.06-.12-.56-1.34-.76-1.84-.2-.48-.4-.42-.56-.42-.14 0-.31-.02-.47-.02-.16 0-.43.06-.65.31-.22.24-.86.84-.86 2.05 0 1.21.88 2.38 1 2.54.12.16 1.73 2.64 4.19 3.7.59.25 1.04.4 1.4.51.59.19 1.12.16 1.54.1.47-.07 1.47-.6 1.68-1.18.21-.58.21-1.07.14-1.18-.06-.1-.22-.16-.47-.28z" /></symbol>
      </defs>
    </svg>
  );
}
