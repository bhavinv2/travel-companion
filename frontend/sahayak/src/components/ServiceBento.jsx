import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Icon from './Icon.jsx';
import { ArrowButton, cx } from './ui.jsx';

/*
 * "What a Sahayak helps with" — bento grid in the pattern of nriparentservice.com's
 * "Who we protect": 4 columns × 3 rows. The first service starts large (2×2); resting the
 * pointer on another card grows that card into the 2×2 block and reveals its description,
 * while the rest reflow. Each card has a "What it covers" button that opens the visit
 * journey (GIG-sheet steps) on the same wave path as "How to Become a Sahayak".
 */

// Every 1×1 cell, in reading order.
const CELLS = [[1, 1], [1, 2], [1, 3], [1, 4], [2, 1], [2, 2], [2, 3], [2, 4], [3, 1], [3, 2], [3, 3], [3, 4]];
const slot = (r, c, rs = 1, cs = 1) => ({ r, c, rs, cs });

// Where the enlarged 2×2 block goes for card `i` (1–8): near the card's resting position.
const bigCorner = (i) => (i <= 4 ? [1, 3] : i <= 6 ? [2, 1] : [2, 3]);

function layout(active, n) {
  const out = new Array(n);
  if (active === null) {
    out[0] = slot(1, 1, 2, 2);
    [[1, 3], [1, 4], [2, 3], [2, 4], [3, 1], [3, 2], [3, 3], [3, 4]].forEach(([r, c], k) => { out[k + 1] = slot(r, c); });
    return out;
  }
  const [br, bc] = bigCorner(active);
  const taken = new Set(['1,1', `${br},${bc}`, `${br},${bc + 1}`, `${br + 1},${bc}`, `${br + 1},${bc + 1}`]);
  out[0] = slot(1, 1);
  out[active] = slot(br, bc, 2, 2);
  const free = CELLS.filter(([r, c]) => !taken.has(`${r},${c}`));
  let k = 0;
  for (let i = 1; i < n; i++) if (i !== active) { const [r, c] = free[k++]; out[i] = slot(r, c); }
  return out;
}

const DWELL = 380; // ms the pointer must rest before a card grows
const LOCK = 450; // ms the grid is left alone while cards move

export default function ServiceBento({ services, openBook }) {
  const [active, setActive] = useState(null);
  const [cover, setCover] = useState(null);
  const grid = useRef(null);
  const pointer = useRef(null);
  const timer = useRef();
  const locked = useRef(false);
  const lockTimer = useRef();
  const current = useRef(null);

  const apply = useCallback((i) => {
    if (current.current === i) return;
    current.current = i;
    setActive(i);
    locked.current = true;
    clearTimeout(lockTimer.current);
    lockTimer.current = setTimeout(() => { locked.current = false; }, LOCK);
  }, []);

  // After the pointer rests, grow whichever card is under it (the first card means "default").
  const schedule = useCallback(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      if (locked.current) return schedule();
      const pt = pointer.current;
      if (!pt) return;
      const card = document.elementFromPoint(pt.x, pt.y)?.closest('.sk-c');
      if (!card) return;
      const i = Number(card.dataset.slot);
      apply(i > 0 ? i : null);
    }, DWELL);
  }, [apply]);

  useEffect(() => () => { clearTimeout(timer.current); clearTimeout(lockTimer.current); }, []);

  const pos = layout(active, services.length);

  return (
    <>
      <div
        className={cx('sk', active !== null && 'moving')}
        ref={grid}
        onMouseMove={(e) => { pointer.current = { x: e.clientX, y: e.clientY }; schedule(); }}
        onMouseLeave={() => { pointer.current = null; clearTimeout(timer.current); apply(null); }}
      >
        {services.map((s, i) => {
          const big = active === i || (active === null && i === 0);
          return (
            <article
              key={s.key}
              data-slot={i}
              tabIndex={0}
              className={cx('sk-c', big && 'big', s.img && 'has-img')}
              style={{ '--imgbg': s.imgBg, '--sc': s.sc, '--st': s.st, '--r': pos[i].r, '--c': pos[i].c, '--rs': pos[i].rs, '--cs': pos[i].cs }}
              onFocus={() => i > 0 && apply(i)}
            >
              {s.img && (
                <>
                  {/* whole photo fitted inside the card; spare edges take the photo's own edge colour (s.imgBg) */}
                  <img className="sk-photo" src={s.img} alt="" loading="lazy" style={s.imgFit ? { objectFit: s.imgFit, objectPosition: s.imgPos } : undefined} />
                </>
              )}
              <span className="sk-num" aria-hidden="true">{String(i + 1).padStart(2, '0')}</span>
              <span className="sk-tag">{i === 0 ? 'Most complete' : s.tag}</span>
              <div className="sk-b">
                <h3>{s.title}</h3>
                <div className="sk-reveal">
                  <div>
                    <p>{s.text}</p>
                    <div className="sk-acts">
                      <button type="button" className="sk-book" onClick={() => openBook({ svc: s.key })}>
                        Book this service<Icon name="arrow" sw={2} />
                      </button>
                      <button type="button" className="sk-cover" onClick={() => setCover(s)}>
                        <PathGlyph />
                        What it covers
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </article>
          );
        })}
      </div>
      {/* rendered at page level so no section can draw on top of it */}
      {cover && createPortal(<CoverageModal service={cover} onClose={() => setCover(null)} openBook={openBook} />, document.getElementById('page') || document.body)}
    </>
  );
}

/** Tiny wave with a travelling dot — a preview of the journey the button opens. */
function PathGlyph() {
  const d = 'M2 12 C7 2 11 2 16 12 S25 22 30 12';
  return (
    <svg className="sk-glyph" viewBox="0 0 32 24" aria-hidden="true">
      <path d={d} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeDasharray="2 3" />
      <circle r="3" fill="currentColor"><animateMotion dur="2.4s" repeatCount="indefinite" path={d} /></circle>
    </svg>
  );
}

/* ---------- "What it covers": the visit journey on a draggable wave path ---------- */

const STEP_X = 400;
const LOW = 340; // node centre y for even steps
const HIGH = 80; // node centre y for odd steps

function wavePath(n) {
  let d = `M0 240 C110 240 110 ${LOW} 220 ${LOW}`;
  for (let i = 0; i < n - 1; i++) {
    const x0 = 220 + STEP_X * i;
    const y0 = i % 2 === 0 ? LOW : HIGH;
    const y1 = (i + 1) % 2 === 0 ? LOW : HIGH;
    d += ` C${x0 + 200} ${y0} ${x0 + 200} ${y1} ${x0 + STEP_X} ${y1}`;
  }
  const xl = 220 + STEP_X * (n - 1);
  const yl = (n - 1) % 2 === 0 ? LOW : HIGH;
  return d + ` C${xl + 130} ${yl} ${xl + 130} 200 ${xl + 260} 200`;
}

/**
 * The traveller on the journey path: a trained Sahayak (cap with a care cross, uniform,
 * stethoscope) in a badge, with a heartbeat ring and a "Your Sahayak" name tag.
 * Drawn around (0,0) and carried along the wave by animateMotion.
 */
function SahayakMarker({ path, dur }) {
  return (
    <g className="sah">
      <animateMotion dur={dur} repeatCount="indefinite" path={path} />
      <circle className="sah-pulse" r="24">
        <animate attributeName="r" values="24;42" dur="1.6s" repeatCount="indefinite" />
        <animate attributeName="opacity" values=".55;0" dur="1.6s" repeatCount="indefinite" />
      </circle>
      <circle className="sah-ring" r="25" />
      <clipPath id="sah-clip"><circle r="22" /></clipPath>
      <g clipPath="url(#sah-clip)">
        <circle className="sah-bg" r="22" />
        {/* uniform + shoulders */}
        <path className="sah-body" d="M-19 22 C-19 9 -11 4 0 4 C11 4 19 9 19 22 Z" />
        {/* collar */}
        <path d="M-5 4 L0 10 L5 4" fill="none" stroke="#fff" strokeWidth="1.6" strokeLinejoin="round" />
        {/* stethoscope */}
        <path d="M-7 6 C-8 14 -3 17 0 17 C3 17 8 14 7 6" fill="none" stroke="#E9EEF8" strokeWidth="1.4" />
        <circle cx="0" cy="17.5" r="1.8" fill="#E9EEF8" />
        {/* face + hair */}
        <circle cx="0" cy="-4" r="7.5" fill="#F0C29E" />
        <path d="M-7.6 -4 C-8 -12 -3 -14.5 0 -14.5 C3 -14.5 8 -12 7.6 -4 C6 -8 3 -9.5 0 -9.5 C-3 -9.5 -6 -8 -7.6 -4 Z" fill="#2B2220" />
        {/* cap with care cross */}
        <path className="sah-cap" d="M-8 -12 L8 -12 L6.5 -17.5 L-6.5 -17.5 Z" />
        <path d="M0 -16.6 V-13 M-1.8 -14.8 H1.8" stroke="#fff" strokeWidth="1.4" strokeLinecap="round" />
        <circle cx="-2.6" cy="-4" r=".9" fill="#2B2220" />
        <circle cx="2.6" cy="-4" r=".9" fill="#2B2220" />
        <path d="M-2.4 -0.6 Q0 1.4 2.4 -0.6" fill="none" stroke="#B5674A" strokeWidth="1" strokeLinecap="round" />
      </g>
      {/* care badge */}
      <circle cx="18" cy="-17" r="7.5" fill="#fff" className="sah-badge" />
      <path d="M18 -20.6 V-13.4 M14.4 -17 H21.6" stroke="#E5484D" strokeWidth="2.2" strokeLinecap="round" />
      {/* name tag */}
      <rect className="sah-tag" x="-44" y="31" width="88" height="21" rx="10.5" />
      <text x="0" y="45.5" textAnchor="middle" className="sah-txt">Your Sahayak</text>
    </g>
  );
}

function CoverageModal({ service: s, onClose, openBook }) {
  const track = useRef(null);
  const bar = useRef(null);
  const [dragging, setDragging] = useState(false);
  const steps = s.journey;
  const width = 220 + STEP_X * (steps.length - 1) + 260;
  const d = wavePath(steps.length);
  const required = steps.filter((x) => !x.optional).length;

  // Lock page scroll, close on Escape.
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    document.body.classList.add('lock');
    return () => { document.removeEventListener('keydown', onKey); document.body.classList.remove('lock'); };
  }, [onClose]);

  // Drag to scroll with the mouse; progress bar follows the scroll position.
  useEffect(() => {
    const el = track.current;
    const b = bar.current;
    if (!el || !b) return;
    let down = false, moved = false, sx = 0, sl = 0;
    const upd = () => {
      b.style.width = (el.clientWidth / el.scrollWidth) * 100 + '%';
      b.style.transform = 'translateX(' + (el.scrollLeft / el.clientWidth) * 100 + '%)';
    };
    const onDown = (e) => { if (e.pointerType !== 'mouse' || e.button !== 0) return; down = true; moved = false; sx = e.clientX; sl = el.scrollLeft; };
    const onMove = (e) => { if (!down) return; const dx = e.clientX - sx; if (Math.abs(dx) > 4) { moved = true; setDragging(true); } el.scrollLeft = sl - dx; };
    const onUp = () => { if (!down) return; down = false; setDragging(false); };
    const onClick = (e) => { if (moved) { e.preventDefault(); e.stopPropagation(); moved = false; } };
    el.addEventListener('pointerdown', onDown);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    el.addEventListener('click', onClick, true);
    el.addEventListener('scroll', upd);
    window.addEventListener('resize', upd);
    upd();
    return () => {
      el.removeEventListener('pointerdown', onDown);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      el.removeEventListener('click', onClick, true);
      el.removeEventListener('scroll', upd);
      window.removeEventListener('resize', upd);
    };
  }, [s]);

  const step = (dir) => track.current?.scrollBy({ left: STEP_X * dir, behavior: 'smooth' });

  return (
    <div className="cov-wrap" role="dialog" aria-modal="true" aria-labelledby="cov-t">
      <button type="button" className="cov-back" aria-label="Close" onClick={onClose}></button>
      <div className="cov" style={{ '--sc': s.sc, '--st': s.st }}>
        <div className="cov-top">
          <div>
            <span className="cov-kick">What it covers</span>
            <h2 id="cov-t">{s.title}</h2>
            <p>{s.text}</p>
          </div>
          <button type="button" className="bk-x" aria-label="Close" onClick={onClose}><Icon name="close" sw={2.2} /></button>
        </div>

        <div className="cov-bar">
          <span className="cov-legend"><i className="req"></i>Required · {required}</span>
          <span className="cov-legend"><i className="opt"></i>Optional · {steps.length - required}</span>
          <div className="pp-prog" aria-hidden="true"><i ref={bar}></i></div>
          <div className="rs-nav">
            <button type="button" className="rs-arr" aria-label="Previous steps" onClick={() => step(-1)}><Icon name="arrowLeft" sw={2} /></button>
            <button type="button" className="rs-arr" aria-label="Next steps" onClick={() => step(1)}><Icon name="arrow" sw={2} /></button>
          </div>
        </div>

        <div ref={track} className={cx('pp-track cov-track in', dragging && 'dragging')}>
          <div className="pp-in" style={{ width }}>
            <svg className="pp-svg" viewBox={`0 0 ${width} 480`} width={width} height="480" aria-hidden="true">
              <path className="pp-shadow" d={d} transform="translate(0 22)" />
              <path className="pp-line" pathLength="100" d={d} />
              <SahayakMarker path={d} dur={`${steps.length * 2.2}s`} />
            </svg>
            {steps.flatMap((st, i) => {
              const x = 220 + i * STEP_X;
              const low = i % 2 === 0;
              return [
                <div key={`o${i}`} className={cx('pp-node', st.optional && 'opt')} style={{ left: x - 38, top: low ? 302 : 42 }}>
                  <span className="pp-hex"><b>{String(i + 1).padStart(2, '0')}</b></span>
                </div>,
                <div key={`t${i}`} className={cx('pp-txt', low ? 'pp-u' : 'pp-d')} style={{ left: x - 140, top: low ? 96 : 172 }}>
                  <small>{st.optional ? 'Optional' : 'Required'}</small>
                  <h3>{st.title}</h3>
                  <p>{st.text}</p>
                </div>,
              ];
            })}
          </div>
        </div>

        <div className="cov-foot">
          <span>Drag the path or use the arrows to follow the visit.</span>
          <ArrowButton onClick={() => { onClose(); openBook({ svc: s.key }); }}>Book {s.title}</ArrowButton>
        </div>
      </div>
    </div>
  );
}
