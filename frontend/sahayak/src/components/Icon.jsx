// Line icons used across the page. Each entry is the inner markup of a 24×24 stroke icon.
const HEART = 'M12 20s-7-4.3-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.7-7 10-7 10z';
const SHIELD = 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z';
const CHAT = 'M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z';
const CALENDAR = (
  <>
    <rect x="3" y="5" width="18" height="16" rx="2" />
    <path d="M3 10h18M8 3v4M16 3v4" />
  </>
);

const ICONS = {
  logo: (<><path d={HEART} /><path d="M8.5 11.5h2l1-2 1.5 4 1-2h1.5" /></>),
  heart: <path d={HEART} />,
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
  arrowLeft: <path d="M19 12H5M11 6l-6 6 6 6" />,
  pause: <path d="M9.5 5v14M14.5 5v14" />,
  play: <path d="M8 5.5v13l11-6.5z" />,
  close: <path d="M6 6l12 12M18 6L6 18" />,
  check: <path d="M5 12l5 5 9-10" />,
  shield: (<><path d={SHIELD} /><path d="M9 12l2 2 4-4" /></>),
  family: (<><circle cx="9" cy="8" r="3" /><path d="M3 20a6 6 0 0 1 12 0" /><path d="M18 14s-3-1.8-3-3.6A1.6 1.6 0 0 1 18 9a1.6 1.6 0 0 1 3 1.4C21 12.2 18 14 18 14z" /></>),
  userPlus: (<><circle cx="9" cy="8" r="3" /><path d="M3 20a6 6 0 0 1 12 0" /><path d="M16 11h6M19 8v6" /></>),
  stethoscope: (<><path d="M6 3v6a4 4 0 0 0 8 0V3" /><path d="M10 13v3a5 5 0 0 0 10 0v-2" /><circle cx="20" cy="12" r="2" /></>),
  home: (<><path d="M3 11l9-7 9 7" /><path d="M5 10v10h14V10" /></>),
  homeHeart: (<><path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z" /><path d="M12 17s-3-1.8-3-3.6A1.6 1.6 0 0 1 12 12a1.6 1.6 0 0 1 3 1.4C15 15.2 12 17 12 17z" /></>),
  homeSmallHeart: (<><path d="M3 11l9-7 9 7" /><path d="M5 10v10h14V10" /><path d="M12 17s-2.5-1.5-2.5-3a1.3 1.3 0 0 1 2.5-.6 1.3 1.3 0 0 1 2.5.6c0 1.5-2.5 3-2.5 3z" /></>),
  homePlus: (<><path d="M3 11l9-7 9 7" /><path d="M5 10v10h14V10" /><path d="M12 12v5M9.5 14.5h5" /></>),
  chat: <path d={CHAT} />,
  chatLines: (<><path d={CHAT} /><path d="M8.5 11h7M8.5 14h4" /></>),
  clock: (<><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>),
  globe: (<><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" /></>),
  pulse: <path d="M3 12h4l3-7 4 14 3-7h4" />,
  hospital: (<><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M12 7v6M9 10h6M9 21v-4h6v4" /></>),
  pill: (<><path d="M10.5 20.5a4.95 4.95 0 0 1-7-7l6-6a4.95 4.95 0 0 1 7 7z" /><path d="M8.5 8.5l7 7" /></>),
  tube: (<><path d="M9 3h6M10 3v14a2 2 0 0 0 4 0V3" /><path d="M10 11h4" /></>),
  route: (<><circle cx="6" cy="19" r="2" /><circle cx="18" cy="5" r="2" /><path d="M8 19h8a3 3 0 0 0 0-6H8a3 3 0 0 1 0-6h8" /></>),
  siren: (<><path d="M12 3v2M5 7l1.5 1.5M19 7l-1.5 1.5" /><path d="M7 20v-5a5 5 0 0 1 10 0v5" /><path d="M5 20h14" /></>),
  phoneForm: (<><rect x="6" y="2" width="12" height="20" rx="2.5" /><path d="M9 7h6M9 10.5h4" /><path d="M9 14.5h6" /><path d="M11 18.5h2" /></>),
  searchPerson: (<><circle cx="10.5" cy="10.5" r="6.5" /><path d="M15.5 15.5L21 21" /><circle cx="10.5" cy="9" r="2" /><path d="M7.2 13.8a3.6 3.6 0 0 1 6.6 0" /></>),
  personPlus: (<><circle cx="12" cy="7" r="3.5" /><path d="M5 21a7 7 0 0 1 14 0" /><path d="M12 14v4M10 16h4" /></>),
  calendar: CALENDAR,
  calendarCheck: (<>{CALENDAR}<path d="M9 15l2 2 4-4" /></>),
  refresh: (<><path d="M20 11a8 8 0 1 0-2.3 5.7" /><path d="M20 5v6h-6" /></>),
  heartCross: (<><path d="M12 21s-7-4.4-7-10.2A4.2 4.2 0 0 1 12 8a4.2 4.2 0 0 1 7 2.8C19 16.6 12 21 12 21z" /><path d="M9 12.5h2v-2h2v2h2v2h-2v2h-2v-2H9z" /></>),
  heartBeat: (<><path d="M12 21s-7-4.4-7-10.2A4.2 4.2 0 0 1 12 8a4.2 4.2 0 0 1 7 2.8C19 16.6 12 21 12 21z" /><path d="M8 13h2l1-2 2 4 1-2h2" /></>),
  language: (<><path d="M4 5h8M8 3v2M6 5c0 4 3 7 6 8M10 5c0 3-2 6-6 8" /><path d="M13 21l4-9 4 9M14.5 18h5" /></>),
  mic: (<><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></>),
  video: (<><rect x="3" y="7" width="13" height="10" rx="2" /><path d="M16 11l5-3v8l-5-3" /></>),
  phoneEnd: <path d="M3 15c5-5 13-5 18 0l-2 3-4-1v-3a10 10 0 0 0-6 0v3l-4 1z" />,
  phone: <path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2" />,
  pin: (<><path d="M12 21s7-6 7-12a7 7 0 0 0-14 0c0 6 7 12 7 12z" /><circle cx="12" cy="9" r="2.5" /></>),
  plusSquare: (<><rect x="4" y="4" width="16" height="16" rx="4" /><path d="M12 8v8M8 12h8" /></>),
  drop: <path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z" />,
  ambulance: (<><path d="M3 16V8h11v8M14 11h4l3 3v2h-7" /><circle cx="7" cy="17" r="2" /><circle cx="17" cy="17" r="2" /><path d="M8.5 10v4M6.5 12h4" /></>),
  clipboard: (<><rect x="5" y="4" width="14" height="17" rx="2" /><path d="M9 4h6v3H9zM9 12h6M9 16h4" /></>),
  plusCircle: (<><circle cx="12" cy="12" r="9" /><path d="M12 8v8M8 12h8" /></>),
  network: (<><circle cx="12" cy="6" r="3" /><circle cx="5" cy="18" r="3" /><circle cx="19" cy="18" r="3" /><path d="M12 9v3M7.5 16l3-3M16.5 16l-3-3" /></>),
  hand: (<><path d="M18 11V6a2 2 0 0 0-4 0v5M14 10V4a2 2 0 0 0-4 0v6M10 10.5V6a2 2 0 0 0-4 0v8" /><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.9-6-2.4l-3.6-3.6a2 2 0 0 1 2.8-2.8L7 15" /></>),
  docLines: (<><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6M8 13h8M8 17h5" /></>),
  doc: (<><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6" /></>),
  idCard: (<><rect x="3" y="5" width="18" height="14" rx="2" /><circle cx="9" cy="12" r="2.5" /><path d="M14 10h4M14 14h4" /></>),
  searchCheck: (<><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4M8.5 11l2 2 3.5-3.5" /></>),
  grad: (<><path d="M2 9l10-5 10 5-10 5z" /><path d="M6 11v5c3 2 9 2 12 0v-5" /></>),
  trend: (<><path d="M3 17l6-6 4 4 8-8" /><path d="M15 7h6v6" /></>),
  lifebuoy: (<><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="4" /><path d="M5.6 5.6l3.6 3.6M14.8 14.8l3.6 3.6M18.4 5.6l-3.6 3.6M9.2 14.8l-3.6 3.6" /></>),
  upload: (<><path d="M12 16V4M7 9l5-5 5 5" /><path d="M4 16v4h16v-4" /></>),
  briefcase: (<><rect x="3" y="7" width="18" height="13" rx="2" /><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></>),
};

export default function Icon({ name, sw = 1.8, ...rest }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={sw}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {ICONS[name]}
    </svg>
  );
}

export function PlayIcon() {
  return (
    <span className="play">
      <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13l11-6.5z" /></svg>
    </span>
  );
}

/** Hand-drawn underline used under highlighted headline words. */
export function Underline() {
  return (
    <svg viewBox="0 0 300 16" preserveAspectRatio="none" fill="none" aria-hidden="true">
      <path d="M3 11C60 4 150 3 297 9" strokeWidth="4" strokeLinecap="round" />
    </svg>
  );
}
