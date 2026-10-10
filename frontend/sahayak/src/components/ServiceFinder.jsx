import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Icon from './Icon.jsx';
import { cx } from './ui.jsx';
import { catalogue, helpline, site } from '../data/site.js';
import artImg from '../assets/finder-care.jpg';
import { GIG_SERVICES, gigFor } from '../data/services.js';
import { INCLUDES, NEEDS } from '../data/needs.js';

/* "Which service do we need?" -- four taps, from what the family can describe to the service that
 * covers it.
 *
 * The first version scored every service against every answer, and the "anything in particular"
 * list counted for more than anything else: Wellness Screen does nearly everything on that list
 * as a matter of course, so ticking two or three things made it the answer whatever had been
 * said before -- every family was told to book a Wellness Screen. Now the question that matters
 * is asked plainly ("what do they need most?", in the family's words, one answer per service)
 * and decides the match; the extras only adjust it when they plainly contradict it, and otherwise
 * pick the alternatives and say what the match does and does not cover.
 */

// What a family would say, mapped to the GIG sheet's service. One tile per service.
const NEED_TILES = [
  { key: 'checkup', gig: 'Wellness Screen', icon: 'pulse', label: 'A full health check-up', hint: 'Vitals, blood & urine tests, ECG' },
  { key: 'tests', gig: 'Lab Work', icon: 'tube', label: 'Tests a doctor asked for', hint: 'Samples collected at home' },
  { key: 'readings', gig: 'Vitals', icon: 'heartBeat', label: 'Regular BP & sugar checks', hint: 'Readings recorded and shared' },
  { key: 'clinic', gig: 'Out-Patient Visit', icon: 'stethoscope', label: 'Someone to take them to a doctor', hint: 'There and back, same day' },
  { key: 'hospital', gig: 'In-Patient Visit', icon: 'hospital', label: 'Support during a hospital stay', hint: 'Admission, procedure, discharge' },
  { key: 'medicines', gig: 'Pharmacy Delivery', icon: 'pill', label: 'Medicines picked up & delivered', hint: 'Pharmacy to their door' },
  { key: 'online', gig: 'Virtual Consultation Support', icon: 'video', label: 'Help with an online consultation', hint: 'Set up and sit through the call' },
  { key: 'try', gig: 'Demo Visit', icon: 'personPlus', label: 'A first visit to try Sahayak', hint: 'Get to know them, set up records' },
  { key: 'other', gig: 'Other', icon: 'plusCircle', label: 'Something else', hint: 'Tell us and we will plan it' },
];

// The sheet's matrix (data/needs.js) is keyed by Preventia's codes; the GIG names are what gigFor
// hands back for any key, whichever list the page was given.
const INCLUDES_BY_GIG = {
  'Wellness Screen': INCLUDES.wellness_screen,
  'Lab Work': INCLUDES.lab_work,
  Vitals: INCLUDES.vitals,
  'Out-Patient Visit': INCLUDES.out_patient_visit,
  'In-Patient Visit': INCLUDES.in_patient_visit,
  'Pharmacy Delivery': INCLUDES.pharmacy_delivery,
  'Demo Visit': INCLUDES.demo,
  'Virtual Consultation Support': INCLUDES.virtual_consult_support,
  Other: INCLUDES.other,
};

// When one service is the answer, these are the ones most often worth a second look.
const RELATED = {
  'Wellness Screen': ['Vitals', 'Lab Work'],
  'Lab Work': ['Wellness Screen', 'Vitals'],
  Vitals: ['Wellness Screen', 'Demo Visit'],
  'Out-Patient Visit': ['In-Patient Visit', 'Virtual Consultation Support'],
  'In-Patient Visit': ['Out-Patient Visit', 'Vitals'],
  'Pharmacy Delivery': ['Vitals', 'Virtual Consultation Support'],
  'Virtual Consultation Support': ['Vitals', 'Out-Patient Visit'],
  'Demo Visit': ['Wellness Screen', 'Vitals'],
  Other: ['Demo Visit', 'Wellness Screen'],
};

const OFTEN = [
  { key: 'One-time', label: 'Just this once', icon: 'calendarCheck', w: { 'Wellness Screen': 0.5, 'Lab Work': 0.5, 'Demo Visit': 0.5 } },
  { key: 'Weekly', label: 'Every week or two', icon: 'calendar', w: { Vitals: 1, 'Pharmacy Delivery': 1 } },
  { key: 'Ongoing', label: 'Regularly, for a while', icon: 'refresh', w: { Vitals: 1, 'Pharmacy Delivery': 1 } },
  { key: 'Urgent', label: 'As soon as possible', icon: 'siren', w: { 'Out-Patient Visit': 0.5, 'Lab Work': 0.5 } },
];

const WHO = [
  { key: 'Mother', label: 'My mother', icon: 'heart' },
  { key: 'Father', label: 'My father', icon: 'heart' },
  { key: 'Both Parents', label: 'Both of them', icon: 'family' },
  { key: 'Other', label: 'Someone else', icon: 'userPlus', hint: 'A relative or family friend' },
];

const STEPS = [
  { key: 'who', q: 'Who is this for?', items: WHO },
  { key: 'need', q: 'What do they need most?', sub: 'Pick the one closest — you can add more next.', items: NEED_TILES, wide: true },
  { key: 'extras', q: 'Anything else to include?', sub: 'Optional — choose any that apply.', items: NEEDS, multi: true },
  { key: 'often', q: 'How often will this be needed?', items: OFTEN },
];

const PRIMARY = 12;          // the service they named: decisive unless the extras plainly say otherwise
const POINTS = { MAD: 2, OPT: 1 };
const MISSING = -2;

const labelOf = (k) => (NEEDS.find((n) => n.key === k) || {}).label || k;

/** Every catalogue service, scored against the answers, best first. */
function rank(list, a) {
  const tile = NEED_TILES.find((t) => t.key === a.need);
  const often = OFTEN.find((o) => o.key === a.often);
  const related = tile ? RELATED[tile.gig] || [] : [];
  return list
    .map((svc) => {
      const gig = gigFor(svc.key);
      const g = gig ? gig.key : '';
      const has = INCLUDES_BY_GIG[g] || {};
      let n = 0;
      const primary = !!tile && tile.gig === g;
      if (primary) n += PRIMARY;
      const covers = [];
      const gaps = [];
      let mad = 0;
      a.extras.forEach((k) => {
        const mark = has[k];
        n += mark ? POINTS[mark] : MISSING;
        if (mark === 'MAD') mad += 1;
        (mark ? covers : gaps).push(k);
      });
      if (often && often.w[g]) n += often.w[g];
      const rel = related.indexOf(g);
      return { svc, gig, n, mad, covers, gaps, primary, rel: rel < 0 ? 99 : rel };
    })
    .sort((x, y) => y.n - x.n || Number(y.primary) - Number(x.primary) || y.mad - x.mad || x.rel - y.rel);
}

/** One answer: a tile with an icon. A button, so the whole tile is the target on a phone. */
function Tile({ item, chosen, multi, onPick }) {
  return (
    <button type="button" role={multi ? 'checkbox' : 'radio'} aria-checked={chosen}
            className={cx('fx-tile', chosen && 'on', multi && 'multi')} onClick={onPick}>
      {item.icon && <span className="fx-tile-ic" aria-hidden="true"><Icon name={item.icon} sw={1.9} /></span>}
      <span className="fx-tile-tx">
        <b>{item.label}</b>
        {item.hint && <small>{item.hint}</small>}
      </span>
      <span className="fx-tick" aria-hidden="true"><Icon name="check" sw={3.2} /></span>
    </button>
  );
}

/** The photograph a service is shown with -- the bento's own, or its colour and icon. */
function SvcArt({ gig, className }) {
  if (gig && gig.img) {
    return <img className={className} src={gig.img} alt="" style={{ objectPosition: gig.imgPos || '50% 40%' }} />;
  }
  return (
    <span className={cx(className, 'fx-noart')} style={{ '--sc': gig?.sc || '#0B3AA8', '--st': gig?.st || '#E3EAFD' }}>
      <Icon name={gig?.icon || 'stethoscope'} sw={1.8} />
    </span>
  );
}

const EMPTY = { who: null, need: null, extras: [], often: null };

function Wizard({ openBook, onBooked }) {
  const list = useMemo(() => catalogue(GIG_SERVICES), []);
  // Only offer a need the catalogue can actually book.
  const tiles = useMemo(() => NEED_TILES.filter((t) => list.some((s) => gigFor(s.key)?.key === t.gig)), [list]);
  const steps = useMemo(() => STEPS.map((s) => (s.key === 'need' ? { ...s, items: tiles.length ? tiles : NEED_TILES } : s)), [tiles]);
  const [step, setStep] = useState(0);
  const [a, setA] = useState(EMPTY);
  const timer = useRef();
  useEffect(() => () => clearTimeout(timer.current), []);

  const done = step >= steps.length;
  const current = steps[step];
  const ranked = useMemo(() => (done ? rank(list, a) : []), [done, list, a]);
  const best = ranked[0];
  const alts = ranked.slice(1).filter((r) => r.n > -2).slice(0, 2);
  const tile = NEED_TILES.find((t) => t.key === a.need);

  const pick = (key) => {
    if (current.multi) {
      setA((x) => ({ ...x, extras: x.extras.includes(key) ? x.extras.filter((k) => k !== key) : x.extras.concat(key) }));
      return;
    }
    setA((x) => ({ ...x, [current.key]: key }));
    // one answer is the whole question: move on by itself, after the tick has been seen
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setStep((s) => s + 1), 260);
  };
  const chosen = (key) => (current.multi ? a.extras.includes(key) : a[current.key] === key);
  const canGo = current && (current.multi || !!a[current.key]);

  // Everything they told us, carried into the booking rather than asked for twice.
  const book = (svc) => {
    if (onBooked) onBooked();
    openBook({ svc, who: a.who || '', when: a.often || '' });
  };

  const pct = Math.round((Math.min(step, steps.length) / steps.length) * 100);

  if (done && best) {
    const why = [];
    if (best.primary && tile) why.push(tile.label);
    best.covers.forEach((k) => why.push(labelOf(k)));
    return (
      <div className="fx fx-res" aria-live="polite">
        <div className="fx-match">
          <div className="fx-match-art">
            <SvcArt gig={best.gig} className="fx-match-img" />
            <span className="fx-badge"><Icon name="check" sw={3} />Best match</span>
          </div>
          <div className="fx-match-body">
            <h4>{best.svc.name}</h4>
            {best.svc.blurb && <p className="fx-blurb">{best.svc.blurb}</p>}
            <div className="fx-meta">
              {best.svc.duration && <span className="fx-pill"><Icon name="clock" sw={2.2} />{best.svc.duration}</span>}
              {best.svc.price && <span className="fx-pill price">&#8377;{best.svc.price}</span>}
            </div>
          </div>
        </div>

        {why.length > 0 && (
          <ul className="fx-why" aria-label="Why this fits">
            {why.map((w) => <li key={w}><span className="fx-why-ic"><Icon name="check" sw={3} /></span>{w}</li>)}
          </ul>
        )}
        {/* Said plainly rather than quietly dropped: being told afterwards that the visit never
            included the thing you asked for is how trust goes. */}
        {best.gaps.length > 0 && (
          <p className="fx-gap">
            <span className="fx-gap-ic"><Icon name="close" sw={2.6} /></span>
            <span>Does not include {best.gaps.map(labelOf).join(', ').toLowerCase()} — tell us when we call and we will plan for it.</span>
          </p>
        )}

        <div className="fx-acts">
          <button type="button" className="fx-book" onClick={() => book(best.svc.key)}>
            Book {best.svc.name}<Icon name="arrow" sw={2.2} />
          </button>
          <button type="button" className="fx-again" onClick={() => { setA(EMPTY); setStep(0); }}>
            <Icon name="refresh" sw={2} />Start again
          </button>
        </div>
        <p className="fx-carry">
          <span className="fx-carry-ic"><Icon name="clipboard" sw={2} /></span>
          Your answers are carried into the booking form, so you will not be asked twice.
        </p>

        {alts.length > 0 && (
          <div className="fx-alts">
            <p className="fx-alts-h">Also worth a look</p>
            {alts.map((r) => (
              <button key={r.svc.key} type="button" className="fx-alt" onClick={() => book(r.svc.key)}>
                <SvcArt gig={r.gig} className="fx-alt-img" />
                <span className="fx-alt-tx">
                  <b>{r.svc.name}</b>
                  <small>{[r.svc.duration, r.svc.price && `₹${r.svc.price}`].filter(Boolean).join(' · ') || 'Book this instead'}</small>
                </span>
                <span className="fx-alt-go"><Icon name="arrow" sw={2.2} /></span>
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="fx">
      <div className="fx-prog">
        <span className="fx-prog-tx">Question {step + 1} of {steps.length}</span>
        <span className="fx-bar" aria-hidden="true"><i style={{ width: `${Math.max(pct, 6)}%` }}></i></span>
      </div>
      <p className="fx-q">{current.q}</p>
      {current.sub && <p className="fx-sub">{current.sub}</p>}
      <div className={cx('fx-tiles', current.wide && 'wide', current.multi && 'chips')}
           role={current.multi ? 'group' : 'radiogroup'} aria-label={current.q}>
        {current.items.map((item) => (
          <Tile key={item.key} item={item} multi={current.multi} chosen={chosen(item.key)} onPick={() => pick(item.key)} />
        ))}
      </div>
      <div className="fx-nav">
        {step > 0 ? (
          <button type="button" className="fx-back" onClick={() => setStep(step - 1)}>
            <Icon name="arrowLeft" sw={2.2} />Back
          </button>
        ) : <span />}
        {(current.multi || step === steps.length - 1) && (
          <button type="button" className="fx-next" disabled={!canGo} onClick={() => setStep(step + 1)}>
            {current.multi ? (a.extras.length ? 'Next' : 'Skip') : 'See my match'}
            <Icon name="arrow" sw={2.2} />
          </button>
        )}
      </div>
    </div>
  );
}

/* The popup it lives in.
 *
 * Shown ten seconds after somebody lands, once per browser session, and only on the families'
 * journey -- a professional reading about joining does not need to be asked whose mother it
 * is. It waits rather than interrupting: if a field is focused or another dialog is already
 * open it tries again later instead of landing on top of what somebody is doing.
 *
 * Two panels, the second of which is always a person: nobody should have to finish a
 * questionnaire to find a phone number.
 */
const SEEN = 'sahayak_finder_seen';
const DELAY = 10000;
const RETRY = 8000;

export default function FinderModal({ mode, openBook }) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState('find');
  const closeRef = useRef(null);
  const timer = useRef();

  const dismiss = () => {
    setOpen(false);
    try { sessionStorage.setItem(SEEN, '1'); } catch { /* private window */ }
  };

  useEffect(() => {
    // Switching to the professionals' journey takes it away: somebody who has just said they
    // are a nurse should not be left looking at "who needs support, my mother or my father".
    if (mode !== 'need') { setOpen(false); return undefined; }
    let seen = false;
    try { seen = !!sessionStorage.getItem(SEEN); } catch { /* private window */ }
    const forced = /[?&#]finder(=1)?(&|$)/.test(location.search + location.hash);
    if (seen && !forced) return undefined;

    /* Open, not merely present. The booking dialog stays mounted so answers survive being
       closed and reopened -- it hides with `hidden`, it does not unmount -- so testing for
       the element itself was true from the moment the page loaded, and this popup retried
       for ever and never appeared. offsetParent is null for anything hidden or display:none,
       which is the cheap way to ask "is this actually on screen". */
    const showing = (sel) => {
      const el = document.querySelector(sel);
      return !!el && el.offsetParent !== null;
    };
    const busy = () => {
      const el = document.activeElement;
      return (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))
        || showing('.bk-wrap')
        || showing('.cov-wrap')
        || document.body.classList.contains('lock');
    };
    const show = () => {
      if (busy() && !forced) { timer.current = setTimeout(show, RETRY); return; }
      setOpen(true);
      try { sessionStorage.setItem(SEEN, '1'); } catch { /* private window */ }
    };
    timer.current = setTimeout(show, forced ? 500 : DELAY);
    return () => clearTimeout(timer.current);
  }, [mode]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') dismiss(); };
    document.addEventListener('keydown', onKey);
    document.body.classList.add('lock');
    const t = setTimeout(() => closeRef.current && closeRef.current.focus(), 80);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.classList.remove('lock');
      clearTimeout(t);
    };
  }, [open]);

  if (!open) return null;
  const phone = helpline();
  return createPortal(
    <div className="fm-wrap" role="dialog" aria-modal="true" aria-labelledby="fm-title">
      <button type="button" className="fm-back" aria-label="Close" onClick={dismiss}></button>
      <div className="fm">
        <div className="fm-art" aria-hidden="true">
          <img src={artImg} alt="" />
          <div className="fm-art-tx">
            <span className="fm-art-k">Sahayak</span>
            <b>Not sure which service your parents need?</b>
            <ul>
              <li><Icon name="check" sw={3} />Four quick questions</li>
              <li><Icon name="check" sw={3} />A registered nurse for each visit</li>
              <li><Icon name="check" sw={3} />Or talk to a person, any time</li>
            </ul>
          </div>
        </div>

        <div className="fm-main">
          <button type="button" className="fm-x" aria-label="Close" ref={closeRef}
                  onClick={dismiss}><Icon name="close" sw={2.2} /></button>
          <h2 id="fm-title">Find the right service</h2>
          <p className="fm-sub">Answer a few questions and we will suggest the visit that fits.</p>
          <div className="fm-seg" role="tablist">
            <button type="button" role="tab" aria-selected={tab === 'find'}
                    className={cx('fm-seg-b', tab === 'find' && 'on')}
                    onClick={() => setTab('find')}><Icon name="searchCheck" sw={2} />Find a service</button>
            <button type="button" role="tab" aria-selected={tab === 'talk'}
                    className={cx('fm-seg-b', tab === 'talk' && 'on')}
                    onClick={() => setTab('talk')}><Icon name="phone" sw={2} />Talk to us</button>
          </div>

          <div className="fm-panel">
            {tab === 'find' ? (
              <Wizard openBook={openBook} onBooked={dismiss} />
            ) : (
              <div className="fm-talk">
                <p className="fm-talk-lead">
                  <b>Would rather just ask somebody?</b>
                  <span>A real person reads every message and replies within one working day.</span>
                </p>
                <div className="fm-ways">
                  {phone && (
                    <a className="fm-way" href={'tel:+' + phone.digits}>
                      <span className="fm-way-i"><Icon name="phone" sw={1.9} /></span>
                      <span><small>Call us</small><b>{phone.display}</b></span>
                    </a>
                  )}
                  {site.waLink && (
                    <a className="fm-way wa" href={site.waLink} target="_blank" rel="noopener">
                      <span className="fm-way-i"><Icon name="chat" sw={1.9} /></span>
                      <span><small>WhatsApp</small><b>Start a chat</b></span>
                    </a>
                  )}
                  {site.supportEmail && (
                    <a className="fm-way" href={'mailto:' + site.supportEmail}>
                      <span className="fm-way-i"><Icon name="chatLines" sw={1.9} /></span>
                      <span><small>Email</small><b>{site.supportEmail}</b></span>
                    </a>
                  )}
                  {site.contactUrl && (
                    <a className="fm-way" href={site.contactUrl}>
                      <span className="fm-way-i"><Icon name="docLines" sw={1.9} /></span>
                      <span><small>Write to us</small><b>Send a message</b></span>
                    </a>
                  )}
                </div>
                <button type="button" className="fm-switch" onClick={() => setTab('find')}>
                  Or answer a few questions instead<Icon name="arrow" sw={2} />
                </button>
              </div>
            )}
          </div>

          <button type="button" className="fm-later" onClick={dismiss}>Maybe later</button>
        </div>
      </div>
    </div>,
    document.body);
}
