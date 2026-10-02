import { useEffect, useRef, useState } from 'react';
import Icon, { Underline } from './Icon.jsx';
import MultiStepForm, { Field, Q } from './MultiStepForm.jsx';
import { FormAside, HELPLINES } from './NeedMode.jsx';
import { ArrowLink, Chips, Quote, Reveal, SectionHead, SideDecor, Upload, cx } from './ui.jsx';
import { useInView } from '../hooks.js';
import { site, postJson } from '../data/site.js';
import { GIG_SERVICES } from '../data/services.js';
import whyFlexible from '../assets/why-flexible.jpg';
import whyTraining from '../assets/why-training.jpg';
import whyCommunity from '../assets/why-community.jpg';
import whyGrowth from '../assets/why-growth.jpg';

// Who can become a Sahayak — accent colour, qualification chips and a one-line fit.
const ROLES = [
  { c: '#0F9D8C', title: 'Nurses & ANMs', bg: 'Nurse', cta: 'Apply as a Nurse / ANM', chips: ['GNM', 'B.Sc Nursing', 'ANM'], text: 'Registered nurses and auxiliary nurse midwives with hands-on patient care experience.' },
  { c: '#D9771B', title: 'Phlebotomists', bg: 'Phlebotomist', cta: 'Apply as a Phlebotomist', chips: ['DMLT', 'Sample collection'], text: 'Trained in safe blood draws and collecting samples at home for lab tests.' },
  { c: '#D14B3A', title: 'Paramedics', bg: 'Paramedic', cta: 'Apply as a Paramedic', chips: ['Emergency care', 'BLS'], text: 'Experienced in emergency response, first aid and patient transfers.' },
  { c: '#1D7FC4', title: 'Certified Health Workers', bg: 'Health Worker', cta: 'Apply as a Health Worker', chips: ['Community health', 'Certified'], text: 'Certified community and home health workers who support daily care.' },
  { c: '#7250D6', title: 'Care Coordinators', bg: 'Care Coordinator', cta: 'Apply as a Care Coordinator', chips: ['Care planning', 'Family liaison'], text: 'Organised communicators who keep families, parents and doctors in sync.' },
  { c: '#2E9A55', title: 'Other Healthcare Professionals', bg: 'Other', cta: 'Apply as a Professional', chips: ['Physiotherapy', 'Allied health'], text: 'Physiotherapists, dietitians and other allied health professionals.' },
];

// What a Sahayak does — Care Coordination is the featured duty.
const YOUR_ROLE = [
  { title: 'Home Health Support', text: 'Assist families with basic healthcare needs at home.' },
  { title: 'Vitals Monitoring', text: 'Support routine monitoring of basic health parameters.' },
  { title: 'Doctor Visit Assistance', text: 'Accompany and assist parents during healthcare appointments.' },
  { title: 'Hospital Support', text: 'Help families navigate hospital visits and care-related requirements.' },
  { title: 'Sample Collection Support', text: 'Assist with approved diagnostic and sample collection services where applicable.' },
  { title: 'Medication Assistance', text: 'Support medication routines according to the assigned care requirements.' },
];
const FEATURED_DUTY = {
  title: 'Care Coordination',
  text: 'Help keep families informed and coordinate with the appropriate care team — the bridge between parents, their children and doctors.',
};

// Path steps alternate below (u) and above (d) the wave; x is the node's centre.
const PATH = [
  { icon: 'docLines', kicker: '01 · Apply', title: 'Tell Us About Yourself', text: 'Start your application by sharing your basic details and healthcare background.', stat: 'Application submitted' },
  { icon: 'idCard', kicker: '02 · Verify', title: 'Submit Your Credentials', text: 'Provide your professional, identification and experience details for verification.', stat: 'Documents verified' },
  { icon: 'searchCheck', kicker: '03 · Get reviewed', title: 'Application Review', text: 'Our team reviews your information and assesses your suitability for the Sahayak network.', stat: 'Details reviewed' },
  { icon: 'grad', kicker: '04 · Learn & prepare', title: 'Complete Training', text: 'Get familiar with the Sahayak platform, service process, safety practices and role-specific requirements.', stat: 'Training & orientation' },
  { icon: 'heart', kicker: '05 · Start providing care', title: 'Begin Your Sahayak Journey', text: 'Once approved and prepared, you can begin accepting suitable service opportunities.', stat: 'Profile activated' },
  { icon: 'trend', kicker: '06 · Keep growing', title: 'Learn, Support & Grow', text: 'Continue developing your skills through ongoing training, support and new opportunities.', stat: 'Ongoing' },
];

const PATH_D = 'M0 240 C110 240 110 340 220 340 C420 340 420 80 620 80 C820 80 820 340 1020 340 C1220 340 1220 80 1420 80 C1620 80 1620 340 1820 340 C2020 340 2020 80 2220 80 C2350 80 2350 200 2480 200';

// Why join: photo cards — title always visible, description revealed on hover/focus.
const WHY = [
  { img: whyFlexible, tag: 'Your schedule', pos: '24% 30%', title: 'Flexible Opportunities', text: 'Choose opportunities that fit your availability.', alt: 'A smiling Sahayak with her phone while an elderly man books an appointment in the app' },
  { img: whyTraining, tag: 'Learning', pos: '50% 35%', title: 'Training & Guidance', text: 'Get the knowledge and support needed for your role.', alt: 'A senior trainer showing the Sahayak app on a tablet to four trainee Sahayaks' },
  { img: whyCommunity, tag: 'At home', pos: '50% 35%', title: 'Community-Based Care', text: 'Help people who need healthcare support in their own homes.', alt: 'A smiling Sahayak sharing tea with an elderly woman in her living room' },
  { img: whyGrowth, tag: 'Career growth', pos: '55% 30%', title: 'Professional Development & Ongoing Support', text: 'Continue learning and build your healthcare experience. Get assistance throughout your Sahayak journey.', alt: 'A Sahayak taking an online healthcare course on her laptop, with her certificate of achievement beside her' },
];

function Hero() {
  const days = [['M', 1.2], ['T'], ['W', 1.35], ['T', 1.5], ['F'], ['S', 1.65], ['S']];
  return (
    <section className="hero hn" id="join">
      <div className="wrap hero-grid">
        <div>
          <Reveal as="h2" className="h-xl hn-h">Turn Your Healthcare Skills Into <em>Meaningful Care<Underline /></em></Reveal>
          <Reveal><Quote>Every visit is a chance to heal.</Quote></Reveal>
          <Reveal as="p" className="lead">Join the Sahayak network and use your healthcare experience to support families and older adults in your community.</Reveal>
          <Reveal className="ctas">
            <ArrowLink href="#apply">Become a Sahayak</ArrowLink>
            <a className="btn btn-o" href="#role">What You Can Do</a>
          </Reveal>
        </div>

        <Reveal className="vis" aria-label="Illustration: a Sahayak profile moving through onboarding, with a care request and weekly availability">
          <div className="vis-bg">
            <div className="blob" style={{ width: 300, height: 300, left: -90, top: -100, background: 'var(--at)' }}></div>
            <div className="blob" style={{ width: 200, height: 200, right: -60, bottom: -70, background: '#fff', opacity: 0.6 }}></div>
          </div>

          <div className="abs rise d3" style={{ left: 36, top: 64, width: 332 }}>
            <div className="card float" style={{ padding: 24 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 14 }}>
                <div className="ring">
                  <svg viewBox="0 0 58 58" aria-hidden="true">
                    <circle cx="29" cy="29" r="27" fill="none" stroke="#E6E9F0" strokeWidth="3.5" />
                    <circle className="fg" cx="29" cy="29" r="27" fill="none" strokeWidth="3.5" strokeLinecap="round" />
                  </svg>
                  <b>R</b>
                </div>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 16 }}>Your Sahayak profile</div>
                  <div style={{ marginTop: 6 }}><span className="rchip">Nurse · 3–5 yrs</span></div>
                </div>
              </div>
              <div className="prog rise d4"><span className="ci ok"><Icon name="check" sw={3} /></span>Application submitted</div>
              <div className="prog rise d5"><span className="ci ok"><Icon name="check" sw={3} /></span>Documents verified</div>
              <div className="prog rise d6"><span className="ci run"></span>Training &amp; orientation</div>
              <div className="barw rise d6"><i></i></div>
              <div className="prog rise d7" style={{ color: 'var(--mut)' }}><span className="ci wait"></span>Profile activated</div>
            </div>
          </div>

          <div className="abs rise d5" style={{ right: 22, top: 36, width: 236 }}>
            <div className="card float2" style={{ padding: 18 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                <span className="live"><i></i>New</span>
                <span style={{ fontSize: 12.5, color: 'var(--mut)', fontWeight: 600 }}>Care request near you</span>
              </div>
              <div style={{ fontWeight: 700, fontSize: 15 }}>Doctor visit assistance</div>
              <div style={{ fontSize: 13, color: 'var(--mut)', margin: '4px 0 14px', display: 'flex', alignItems: 'center', gap: 6 }}>
                <Icon name="pin" sw={2} width="14" height="14" />Tomorrow · 9:00 AM
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button type="button" className="sbtn" style={{ flexGrow: 1 }}>Details</button>
                <button type="button" className="sbtn p" style={{ flexGrow: 1 }}>Accept</button>
              </div>
            </div>
          </div>

          <div className="abs rise d7" style={{ right: 34, bottom: 40, width: 300 }}>
            <div className="card float3" style={{ padding: 20 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                <span className="mini-l">Your week</span>
                <span style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--pd)' }}>You choose</span>
              </div>
              <div className="days" aria-hidden="true">
                {days.map(([d, delay], i) => (
                  <span key={i} className={cx(delay && 'on')} style={delay ? { animationDelay: `${delay}s` } : undefined}>{d}</span>
                ))}
              </div>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

function Roles({ onApplyAs }) {
  return (
    <section className="sec tight" id="roles">
      <div className="wrap">
        <SectionHead
          center
          kick="Who can join"
          title={<>Your Healthcare Experience <em>Can Make a Difference</em></>}
          quote="Every skill has a home here."
          tone="p"
          sub="If you have relevant healthcare experience and want to provide community-based support, there’s a place for you in the Sahayak network."
        />
        <div className="rl">
          {ROLES.map((r, i) => (
            <Reveal as="article" key={r.bg} className="rl-c" style={{ '--c': r.c }}>
              <span className="rl-n">{String(i + 1).padStart(2, '0')}</span>
              <h3>{r.title}</h3>
              <p>{r.text}</p>
              <ul className="rl-chips">
                {r.chips.map((ch) => <li key={ch}>{ch}</li>)}
              </ul>
              <a className="rl-go" href="#apply" onClick={() => onApplyAs(r.bg)}>
                {r.cta}
                <Icon name="arrow" sw={2} />
              </a>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

function YourRole() {
  return (
    <section className="sec tight" id="role">
      <div className="wrap">
        <SectionHead
          center
          kick="Your role"
          title={<>What You Can Do <em>as a Sahayak</em></>}
          quote="Small acts of care, big moments of comfort."
          sub="Every assignment is matched to your qualifications and the family’s needs — so you always know exactly what’s expected."
        />
        <div className="dt">
          {YOUR_ROLE.map((r, i) => (
            <Reveal as="article" key={r.title} className="dt-c">
              <span className="dt-n">{String(i + 1).padStart(2, '0')}</span>
              <div>
                <h3>{r.title}</h3>
                <p>{r.text}</p>
              </div>
            </Reveal>
          ))}
          <Reveal as="article" className="dt-c dt-feat">
            <span className="dt-n">07</span>
            <div>
              <span className="dt-badge">At the heart of every visit</span>
              <h3>{FEATURED_DUTY.title}</h3>
              <p>{FEATURED_DUTY.text}</p>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

/*
 * The traveller on "How to Become a Sahayak": one person who changes at every step of the path,
 * matching the step names —
 *   01 Apply (form) → 02 Verify (ID card) → 03 Get reviewed (under review)
 *   → 04 Learn & prepare (graduation cap, until step 05) → Verified Sahayak (uniform, green tick)
 *   after step 05 Begin Your Sahayak Journey, through to the last step.
 * Stages switch halfway between steps; 'In training' carries on from step 04 to step 05, and
 * 'Verified Sahayak' appears once the traveller crosses step 05. Fractions are measured along the wave path.
 * Drawn around (0,0).
 */
const STAGE_AT = [0, 0.1643, 0.3286, 0.4929, 0.7529, 1];
function stageAnim(i) {
  const n = STAGE_AT.length - 1;
  const vals = [];
  for (let k = 0; k < n; k++) vals.push(k === i ? 1 : 0);
  vals.push(i === n - 1 ? 1 : 0);
  return { values: vals.join(';'), keyTimes: STAGE_AT.join(';') };
}

function Face({ skin = '#F0C29E', hair = '#2B2220' }) {
  return (
    <>
      <circle cx="0" cy="-4" r="7.5" fill={skin} />
      <path d="M-7.6 -4 C-8 -12 -3 -14.5 0 -14.5 C3 -14.5 8 -12 7.6 -4 C6 -8 3 -9.5 0 -9.5 C-3 -9.5 -6 -8 -7.6 -4 Z" fill={hair} />
      <circle cx="-2.6" cy="-4" r=".9" fill={hair} />
      <circle cx="2.6" cy="-4" r=".9" fill={hair} />
      <path d="M-2.4 -0.6 Q0 1.4 2.4 -0.6" fill="none" stroke="#B5674A" strokeWidth="1" strokeLinecap="round" />
    </>
  );
}

const Body = ({ fill }) => <path d="M-19 22 C-19 9 -11 4 0 4 C11 4 19 9 19 22 Z" fill={fill} />;
const Uniform = () => (
  <>
    <path className="jt-uniform" d="M-19 22 C-19 9 -11 4 0 4 C11 4 19 9 19 22 Z" />
    <path d="M-5 4 L0 10 L5 4" fill="none" stroke="#fff" strokeWidth="1.6" strokeLinejoin="round" />
    <path d="M-7 6 C-8 14 -3 17 0 17 C3 17 8 14 7 6" fill="none" stroke="#E9EEF8" strokeWidth="1.4" />
    <circle cx="0" cy="17.5" r="1.8" fill="#E9EEF8" />
  </>
);
const NurseCap = () => (
  <>
    <path className="jt-uniform" d="M-8 -12 L8 -12 L6.5 -17.5 L-6.5 -17.5 Z" />
    <path d="M0 -16.6 V-13 M-1.8 -14.8 H1.8" stroke="#fff" strokeWidth="1.4" strokeLinecap="round" />
  </>
);

// [label, tag colour, avatar background, figure, corner badge]
const STAGES = [
  ['Applying', '#C9781A', '#FFF4E5',
    <>
      <Body fill="#E08A2E" />
      <path d="M-4 4 L0 8 L4 4" fill="none" stroke="#fff" strokeWidth="1.4" />
      <Face />
      <g transform="rotate(-10 8 13)">
        <rect x="3" y="7" width="11" height="13" rx="1.5" fill="#fff" stroke="#C9781A" strokeWidth="1" />
        <path d="M5.5 11 H11.5 M5.5 14 H11.5 M5.5 17 H9.5" stroke="#C9781A" strokeWidth=".9" />
      </g>
    </>,
    <path d="M15 -19.5 H21 M15 -17 H21 M15 -14.5 H19" stroke="#C9781A" strokeWidth="1.3" strokeLinecap="round" />],
  ['Verifying', '#0E7C86', '#E3F6F7',
    <>
      <Body fill="#1A9AA5" />
      <path d="M-4 4 L0 8 L4 4" fill="none" stroke="#fff" strokeWidth="1.4" />
      <Face />
      <rect x="2" y="8" width="14" height="10" rx="1.6" fill="#fff" stroke="#0E7C86" strokeWidth="1" />
      <circle cx="6" cy="13" r="2" fill="#0E7C86" />
      <path d="M9.5 11.5 H14 M9.5 14.5 H13" stroke="#0E7C86" strokeWidth=".9" />
    </>,
    <>
      <rect x="13.5" y="-20.5" width="9" height="7" rx="1.2" fill="none" stroke="#0E7C86" strokeWidth="1.3" />
      <circle cx="16.3" cy="-17" r="1.2" fill="#0E7C86" />
    </>],
  ['Under review', '#7A4FD0', '#F1EBFF',
    <>
      <Body fill="#8B63DC" />
      <path d="M-4 4 L0 8 L4 4" fill="none" stroke="#fff" strokeWidth="1.4" />
      <Face />
      <circle cx="9" cy="12" r="5" fill="#fff" fillOpacity=".7" stroke="#5B37B0" strokeWidth="1.6" />
      <path d="M12.6 15.6 L16 19" stroke="#5B37B0" strokeWidth="2" strokeLinecap="round" />
    </>,
    <>
      <circle cx="17.3" cy="-17.6" r="3.3" fill="none" stroke="#7A4FD0" strokeWidth="1.4" />
      <path d="M19.6 -15.3 L21.6 -13.3" stroke="#7A4FD0" strokeWidth="1.6" strokeLinecap="round" />
    </>],
  ['In training', '#4F5BD5', '#EEF2FF',
    <>
      <Body fill="#4F5BD5" />
      <Face />
      <path d="M-11 -13 L0 -18 L11 -13 L0 -8 Z" fill="#1F2A6B" />
      <path d="M7 -11.5 V-6" stroke="#F2C46E" strokeWidth="1.2" />
      <circle cx="7" cy="-5.5" r="1.2" fill="#F2C46E" />
      <path d="M-12 9 L-1 11 L-1 21 L-12 19 Z" fill="#fff" />
      <path d="M12 9 L1 11 L1 21 L12 19 Z" fill="#E4E9FF" />
    </>,
    <path d="M13.5 -18 L18 -20.5 L22.5 -18 L18 -15.5 Z" fill="#4F5BD5" />],
  ['Verified Sahayak', '#16A34A', null,
    <>
      <Uniform />
      <Face />
      <NurseCap />
    </>,
    'verified'],
];

function JourneyTraveller({ path, dur }) {
  const d = `${dur}s`;
  return (
    <g className="jt">
      <animateMotion dur={d} repeatCount="indefinite" path={path} />
      <circle className="jt-pulse" r="24">
        <animate attributeName="r" values="24;40" dur="1.6s" repeatCount="indefinite" />
        <animate attributeName="opacity" values=".5;0" dur="1.6s" repeatCount="indefinite" />
      </circle>
      <circle className="jt-ring" r="25" />
      <clipPath id="jt-clip"><circle r="22" /></clipPath>
      {STAGES.map(([label, color, bg, figure, badge], i) => {
        const a = stageAnim(i);
        const w = label.length * 6.4 + 22;
        return (
          <g key={label} opacity={i === 0 ? 1 : 0}>
            <animate attributeName="opacity" values={a.values} keyTimes={a.keyTimes} calcMode="discrete" dur={d} repeatCount="indefinite" />
            <g clipPath="url(#jt-clip)">
              <circle r="22" fill={bg || undefined} className={bg ? undefined : 'jt-bg'} />
              {figure}
            </g>
            {badge === 'verified' ? (
              <>
                <circle cx="18" cy="-17" r="8" fill="#16A34A" stroke="#fff" strokeWidth="2" />
                <path d="M14.6 -17 L17.2 -14.4 L21.6 -19.4" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </>
            ) : badge === 'star' ? (
              <>
                <circle cx="18" cy="-17" r="8" fill="#F59E0B" stroke="#fff" strokeWidth="2" />
                <path d="M18 -21.6 L19.3 -18.4 L22.6 -18.2 L20 -16.1 L20.9 -12.8 L18 -14.7 L15.1 -12.8 L16 -16.1 L13.4 -18.2 L16.7 -18.4 Z" fill="#fff" />
              </>
            ) : (
              <>
                <circle cx="18" cy="-17" r="7.5" fill="#fff" stroke={color} strokeOpacity=".35" strokeWidth="1.5" />
                {badge}
              </>
            )}
            <rect x={-w / 2} y="31" width={w} height="21" rx="10.5" fill={color} />
            <text x="0" y="45.5" textAnchor="middle" className="jt-txt">{label}</text>
          </g>
        );
      })}
    </g>
  );
}

// One node's worth of track. The nodes are laid out on this spacing below, and the auto-advance
// and the arrows both move by it, so a step always lands on a step.
const PATH_STEP = 400;
const PATH_DWELL = 3400;   // how long each step holds before the track glides on
const PATH_RESUME = 5000;  // how long a manual nudge keeps the timer out of the way afterwards

/** Horizontally scrollable wave. It walks along on its own; a drag, the arrows, the pointer
 *  resting on it and the pause button all take precedence over the timer. */
function ThePath({ mode }) {
  const [ioRef, inView] = useInView();
  const barRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [playing, setPlaying] = useState(true);
  // Honour the OS setting: where motion is unwelcome the track only ever moves when asked to.
  const [canAuto] = useState(
    () => !(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches));
  // The timer stands down while the pointer is over the track or mid-drag, and for a few seconds
  // after any manual nudge, so it never fights the reader. Refs rather than state: the interval
  // reads them live, and none of it should cause a render.
  const held = useRef({ hover: false, drag: false, until: 0 });

  useEffect(() => {
    const el = ioRef.current;
    const bar = barRef.current;
    if (!el || !bar) return;
    let down = false, moved = false, sx = 0, sl = 0;

    const upd = () => {
      if (!el.scrollWidth) return;
      bar.style.width = (el.clientWidth / el.scrollWidth) * 100 + '%';
      bar.style.transform = 'translateX(' + (el.scrollLeft / el.clientWidth) * 100 + '%)';
    };
    const onDown = (e) => {
      if (e.pointerType !== 'mouse' || e.button !== 0) return;
      down = true; moved = false; sx = e.clientX; sl = el.scrollLeft;
      held.current.drag = true;
    };
    const onMove = (e) => {
      if (!down) return;
      const dx = e.clientX - sx;
      if (Math.abs(dx) > 4) { moved = true; setDragging(true); }
      el.scrollLeft = sl - dx;
    };
    const onUp = () => {
      if (!down) return;
      down = false;
      held.current.drag = false;
      held.current.until = Date.now() + PATH_RESUME;
      setDragging(false);
    };
    // Touch scrolls the track natively, so there is no pointerdown to hang a hold off -- the
    // scroll event is the only sign it happened.
    const onTouch = () => { held.current.until = Date.now() + PATH_RESUME; };
    const onEnter = () => { held.current.hover = true; };
    const onLeave = () => { held.current.hover = false; };
    // Swallow the click that ends a drag so links inside the track don't fire.
    const onClick = (e) => {
      if (moved) { e.preventDefault(); e.stopPropagation(); moved = false; }
    };
    const onDragStart = (e) => e.preventDefault();

    el.addEventListener('pointerdown', onDown);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    el.addEventListener('click', onClick, true);
    el.addEventListener('dragstart', onDragStart);
    el.addEventListener('scroll', upd);
    el.addEventListener('touchstart', onTouch, { passive: true });
    el.addEventListener('pointerenter', onEnter);
    el.addEventListener('pointerleave', onLeave);
    window.addEventListener('resize', upd);
    upd();
    return () => {
      el.removeEventListener('pointerdown', onDown);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      el.removeEventListener('click', onClick, true);
      el.removeEventListener('dragstart', onDragStart);
      el.removeEventListener('scroll', upd);
      el.removeEventListener('touchstart', onTouch);
      el.removeEventListener('pointerenter', onEnter);
      el.removeEventListener('pointerleave', onLeave);
      window.removeEventListener('resize', upd);
    };
    // Re-measure when the mode changes: the track has no size while its mode is hidden.
  }, [ioRef, mode]);

  // useInView's flag latches on first sight, which is right for the reveal animation and wrong
  // here: the timer needs to know whether the track is on screen *now*, or it would walk through
  // the whole journey while the reader is three sections further down -- and while the other mode
  // is showing, since a hidden track never intersects.
  const [onScreen, setOnScreen] = useState(false);
  useEffect(() => {
    const el = ioRef.current;
    if (!el) return;
    if (!('IntersectionObserver' in window)) { setOnScreen(true); return; }
    const io = new IntersectionObserver((es) => setOnScreen(es.some((e) => e.isIntersecting)),
      { threshold: 0.35 });
    io.observe(el);
    return () => io.disconnect();
  }, [ioRef, mode]);

  // Walk the track along a step at a time, then hold the last step for a double beat and glide
  // back to the beginning.
  useEffect(() => {
    const el = ioRef.current;
    if (!el || !canAuto || !playing || !onScreen) return;
    let resting = false;
    const id = setInterval(() => {
      const h = held.current;
      if (document.hidden || h.hover || h.drag || Date.now() < h.until) return;
      const end = el.scrollWidth - el.clientWidth;
      if (end < 1) return;                       // the whole wave fits: nothing to advance
      if (el.scrollLeft >= end - 8) {
        if (!resting) { resting = true; return; }
        resting = false;
        el.scrollTo({ left: 0, behavior: 'smooth' });
        return;
      }
      // +1 so a drag that stopped exactly on a step still moves on to the next one
      el.scrollTo({ left: Math.min(end, Math.ceil((el.scrollLeft + 1) / PATH_STEP) * PATH_STEP),
        behavior: 'smooth' });
    }, PATH_DWELL);
    return () => clearInterval(id);
  }, [ioRef, canAuto, playing, onScreen]);

  const step = (dir) => {
    held.current.until = Date.now() + PATH_RESUME;
    ioRef.current?.scrollBy({ left: PATH_STEP * dir, behavior: 'smooth' });
  };

  return (
    <section className="sec tight" id="path">
      <div className="wrap">
        <Reveal className="pp-h">
          <span className="pp-k"><i></i>The path<i></i></span>
          <h2 className="pp-t">How to Become a Sahayak<span>.</span></h2>
          <Quote tone="h">From your first form to your first visit.</Quote>
          <p className="sub">From application to your first visit — every stage is clear, so you always know what happens after you apply.</p>
        </Reveal>
        <Reveal className="pp-bar-row">
          <span className="pp-hint">
            <Icon name="hand" />
            {canAuto
              ? (playing ? 'Moves on its own — drag to explore' : 'Paused — drag to explore')
              : 'Drag to explore the journey'}
          </span>
          <div className="pp-prog" aria-hidden="true"><i ref={barRef}></i></div>
          <div className="rs-nav">
            {/* Moving content that starts by itself needs a way to stop it that does not depend
                on hovering -- the hover and drag holds alone leave a keyboard out in the cold. */}
            {canAuto && (
              <button type="button" className="rs-arr" aria-pressed={!playing}
                aria-label={playing ? 'Pause the journey' : 'Play the journey'}
                onClick={() => setPlaying((p) => !p)}>
                <Icon name={playing ? 'pause' : 'play'} sw={2} />
              </button>
            )}
            <button type="button" className="rs-arr" aria-label="Previous steps" onClick={() => step(-1)}><Icon name="arrowLeft" sw={2} /></button>
            <button type="button" className="rs-arr" aria-label="Next steps" onClick={() => step(1)}><Icon name="arrow" sw={2} /></button>
          </div>
        </Reveal>
      </div>
      <div ref={ioRef} className={cx('pp-track io-t', inView && 'in', dragging && 'dragging')}>
        <div className="pp-in" style={{ width: 2480 }}>
          <svg className="pp-svg" viewBox="0 0 2480 480" width="2480" height="480" aria-hidden="true">
            <path className="pp-shadow" d={PATH_D} transform="translate(0 22)" />
            <path className="pp-line" pathLength="100" d={PATH_D} />
            <JourneyTraveller path={PATH_D} dur={14} />
          </svg>
          {PATH.flatMap((p, i) => {
            const x = 220 + i * PATH_STEP;
            const low = i % 2 === 0; // node sits in a trough of the wave
            return [
              <div key={`n${i}`} className="pp-num" style={{ left: x + 40, top: low ? 58 : 145 }} aria-hidden="true">{i + 1}</div>,
              <div key={`o${i}`} className="pp-node" style={{ left: x - 38, top: low ? 302 : 42 }}>
                <span className="pp-hex"><Icon name={p.icon} sw={1.9} /></span>
              </div>,
              <div key={`t${i}`} className={cx('pp-txt', low ? 'pp-u' : 'pp-d')} style={{ left: x - 140, top: low ? 90 : 172 }}>
                <small>{p.kicker}</small>
                <h3>{p.title}</h3>
                <p>{p.text}</p>
                <span className="stat"><Icon name="check" sw={2.6} />{p.stat}</span>
              </div>,
            ];
          })}
        </div>
      </div>
      <Reveal className="wrap pp-foot"><ArrowLink href="#apply">Start your application</ArrowLink></Reveal>
    </section>
  );
}

/** Why join: same-size photo cards in a carousel with left/right arrows (also swipeable). */
function WhyJoin() {
  const track = useRef(null);
  const [edge, setEdge] = useState({ start: true, end: false });

  const update = () => {
    const el = track.current;
    if (!el) return;
    setEdge({ start: el.scrollLeft <= 10, end: el.scrollLeft + el.clientWidth >= el.scrollWidth - 10 });
  };
  useEffect(() => {
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);

  // Move by exactly one card (card width + gap).
  const slide = (dir) => {
    const el = track.current;
    const card = el?.firstElementChild;
    if (!card) return;
    const gap = parseFloat(getComputedStyle(el).columnGap) || 0;
    el.scrollBy({ left: dir * (card.getBoundingClientRect().width + gap), behavior: 'smooth' });
  };

  return (
    <section className="sec tight" id="why">
      <div className="wrap">
        <SectionHead
          center
          kick="Why join"
          title={<>More Than a Job. <em>A Chance to Make a Difference.</em></>}
          quote="Work that warms hearts — including yours."
          sub="Flexible work, real training and a team behind you — while you help families stay close to the care their parents need."
        />
        <Reveal className="band wp-car">
          <button type="button" className="rs-arr wp-prev" aria-label="Previous" disabled={edge.start} onClick={() => slide(-1)}>
            <Icon name="arrowLeft" sw={2} />
          </button>
          <div className="why wp" ref={track} onScroll={update}>
            {WHY.map((w) => (
              <article key={w.title} className="wp-c" tabIndex={0}>
                <img src={w.img} alt={w.alt} loading="lazy" style={w.pos ? { objectPosition: w.pos } : undefined} />
                <span className="wp-tag">{w.tag}</span>
                <div className="wp-t">
                  <h3>{w.title}</h3>
                  <p>{w.text}</p>
                </div>
              </article>
            ))}
          </div>
          <button type="button" className="rs-arr wp-next" aria-label="Next" disabled={edge.end} onClick={() => slide(1)}>
            <Icon name="arrow" sw={2} />
          </button>
        </Reveal>
      </div>
    </section>
  );
}

const APPLY_EMPTY = {
  full_name: '', mobile: '', whatsapp: '', email: '', age: '', location: '',
  background: '', years: '',
  highest_qualification: '', healthcare_qualification: '', certification: '', institution: '', year: '',
  home: '', elder: '', hosp: '', experience: '',
  services: [],
  work: '', service_city: '', service_pins: '', availability: [],
  files: {},
};

function ApplyForm({ applyAs }) {
  const [data, setData] = useState(APPLY_EMPTY);
  const [jump, setJump] = useState(null);
  const set = (k, v) => setData((d) => ({ ...d, [k]: v }));
  const setFile = (k) => (file) => setData((d) => ({ ...d, files: { ...d.files, [k]: file } }));
  const f = { data, set };

  // Picking a role (role card or hero card) pre-fills what we know and opens the background step.
  useEffect(() => {
    if (!applyAs) return;
    setData((d) => ({
      ...d,
      background: applyAs.bg,
      ...(applyAs.name ? { full_name: applyAs.name } : {}),
      ...(applyAs.city ? { location: applyAs.city } : {}),
      ...(applyAs.years ? { years: applyAs.years } : {}),
    }));
    setJump({ step: 1, nonce: applyAs.nonce });
  }, [applyAs]);

  const yn = (key, text) => (
    <div className="yn">
      <span>{text}</span>
      <Chips options={['Yes', 'No']} value={data[key]} onChange={(v) => set(key, v)} />
    </div>
  );

  const steps = [
    {
      short: 'Basics', label: 'Basic information',
      content: (
        <>
          <Q title="Let's get to know you" sub="Your basic details, so our team can reach you." />
          <div className="fields">
            <Field full id="b-name" label="Full Name" name="full_name" autoComplete="name" {...f} />
            <Field id="b-mob" label="Mobile Number" name="mobile" type="tel" autoComplete="tel" {...f} />
            <Field id="b-wa" label="WhatsApp Number" name="whatsapp" type="tel" {...f} />
            <Field id="b-em" label="Email" name="email" type="email" autoComplete="email" {...f} />
            <Field id="b-age" label="Age" name="age" inputMode="numeric" {...f} />
            <Field full id="b-loc" label="City / Area / PIN Code" name="location" placeholder="e.g. Hyderabad, Kukatpally, 500072" {...f} />
          </div>
        </>
      ),
    },
    {
      short: 'Background', label: 'Professional background',
      content: (
        <>
          <Q title="Tell us about your healthcare experience" sub="What best describes your background?" />
          <Chips
            options={['Nurse', 'ANM', 'Paramedic', 'Phlebotomist', 'Health Worker', 'Care Coordinator', 'Other']}
            value={data.background}
            onChange={(v) => set('background', v)}
          />
          <p className="ql">Years of experience</p>
          <Chips options={['Less than 1 year', '1–3 years', '3–5 years', '5+ years']} value={data.years} onChange={(v) => set('years', v)} />
        </>
      ),
    },
    {
      short: 'Qualify', label: 'Qualifications',
      content: (
        <>
          <Q title="Your education & certification" sub="Share your highest and healthcare-specific qualifications." />
          <div className="fields">
            <Field id="b-hq" label="Highest Qualification" name="highest_qualification" {...f} />
            <Field id="b-hcq" label="Healthcare Qualification" name="healthcare_qualification" placeholder="e.g. GNM, B.Sc Nursing, DMLT" {...f} />
            <Field id="b-cert" label="Certification" name="certification" {...f} />
            <Field id="b-inst" label="Institution" name="institution" {...f} />
            <Field id="b-yr" label="Year of Completion" name="year" inputMode="numeric" {...f} />
            <div className="fld full">
              <Upload id="b-certup" name="certificate" icon="upload" title="Upload Certificate / Supporting Document" hint="PDF, JPG or PNG" action="Browse" onChange={setFile('certificate')} />
            </div>
          </div>
        </>
      ),
    },
    {
      short: 'Experience', label: 'Experience',
      content: (
        <>
          <Q title="Tell us about your previous experience" sub="Quick yes or no answers, then a few lines in your own words." />
          {yn('home', 'Have you worked in home healthcare?')}
          {yn('elder', 'Have you assisted elderly patients?')}
          {yn('hosp', 'Have you worked with hospitals or clinics?')}
          <div className="fld" style={{ marginTop: 22 }}>
            <label htmlFor="b-exp">Describe your relevant experience</label>
            <textarea id="b-exp" name="experience" value={data.experience} onChange={(e) => set('experience', e.target.value)} />
          </div>
        </>
      ),
    },
    {
      short: 'Services', label: 'Services you can provide',
      content: (
        <>
          <Q title="What kind of support can you provide?" sub="Select all that apply." />
          <Chips
            multi
            options={GIG_SERVICES.map((g) => g.title)}
            value={data.services}
            onChange={(v) => set('services', v)}
          />
        </>
      ),
    },
    {
      short: 'Availability', label: 'Availability',
      content: (
        <>
          <Q title="When can you provide Sahayak services?" sub="Preferred work type" />
          <Chips options={['Full-time', 'Part-time', 'Flexible']} value={data.work} onChange={(v) => set('work', v)} />
          <p className="ql">Preferred service area</p>
          <div className="fields">
            <Field id="b-scity" label="City" name="service_city" {...f} />
            <Field id="b-spin" label="Areas / PIN Codes" name="service_pins" placeholder="Separate with commas" {...f} />
          </div>
          <p className="ql">Availability</p>
          <Chips multi options={['Morning', 'Afternoon', 'Evening', 'Flexible']} value={data.availability} onChange={(v) => set('availability', v)} />
        </>
      ),
    },
    {
      short: 'Documents', label: 'Documents & verification',
      content: (
        <>
          <Q title="Complete your verification" sub="Upload clear copies. Our team checks every document before activating a profile." />
          <div className="ups">
            <Upload id="d-id" name="id_proof" icon="idCard" title="ID Proof" hint="Government-issued photo ID" onChange={setFile('id_proof')} />
            <Upload id="d-q" name="qualification_certificate" icon="grad" title="Qualification Certificate" hint="Degree or diploma" onChange={setFile('qualification_certificate')} />
            <Upload id="d-p" name="professional_certificate" icon="shield" title="Professional Certificate" hint="Registration or license, if applicable" onChange={setFile('professional_certificate')} />
            <Upload id="d-e" name="experience_proof" icon="briefcase" title="Experience Proof" hint="Letter from employer or hospital" onChange={setFile('experience_proof')} />
            <Upload id="d-o" name="other_documents" icon="doc" title="Other Supporting Documents" hint="Optional" onChange={setFile('other_documents')} />
          </div>
        </>
      ),
    },
  ];

  return (
    <MultiStepForm
      anchor="apply"
      steps={steps}
      jump={jump}
      submitLabel="Submit for Review"
      onSubmit={() =>
        /* Documents are deliberately not sent: /api/sahayak-apply does not take uploads, and
           the team asks for certificates on the confirming call. What was attached is named
           so whoever rings knows to ask for it. */
        postJson(site.applyUrl, {
          ...data,
          services: (data.services || []).join(', '),
          availability: (data.availability || []).join(', '),
          files: undefined,
          documents_offered: Object.keys(data.files || {}).join(', '),
        })
      }
      done={{
        title: 'Application submitted',
        text: 'Thank you for applying. Our team will review your details and documents, then guide you through training and orientation.',
        reset: 'Back to the form',
        maxWidth: 460,
      }}
    />
  );
}

function Apply({ applyAs }) {
  return (
    <section className="sec tight" id="apply">
      <SideDecor icons={[
        { name: 'docLines', side: 'left', top: '8%', size: 34, rotate: -8, opacity: 0.16 },
        { name: 'grad', side: 'left', top: '56%', size: 96, rotate: 10, opacity: 0.07 },
        { name: 'shield', side: 'right', top: '12%', size: 34, rotate: 8, opacity: 0.16 },
        { name: 'heart', side: 'right', top: '60%', size: 90, rotate: -10, opacity: 0.07 },
      ]} />
      <div className="wrap">
        <SectionHead
          kick="Apply"
          title={<>Ready to Become <em>a Sahayak?</em></>}
          quote="Your next chapter starts here."
          tone="p"
          sub="Seven short steps. You can go back and change any answer before you submit."
        />
        <div className="form-wrap">
          <FormAside
            title="Keep these documents ready"
            quote="Trust starts with the paperwork."
            text="You'll upload them in the last step for verification."
            items={['ID proof', 'Qualification certificate', 'Professional certificate', 'Experience proof']}
            callLabel="Questions about applying?"
            phones={HELPLINES}
          />
          <ApplyForm applyAs={applyAs} />
        </div>
      </div>
    </section>
  );
}

export default function BecomeMode({ mode, applyAs, onApplyAs }) {
  return (
    <div className="m-become">
      <main>
        <Hero />
        <Roles onApplyAs={onApplyAs} />
        <YourRole />
        <ThePath mode={mode} />
        <WhyJoin />
        <Apply applyAs={applyAs} />
      </main>
    </div>
  );
}
