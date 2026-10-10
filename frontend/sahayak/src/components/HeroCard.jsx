import { useEffect, useRef, useState } from 'react';
import Icon from './Icon.jsx';
import { ArrowButton, cx } from './ui.jsx';
import { catalogue, journeyFor } from '../data/site.js';
import { GIG_SERVICES, gigFor } from '../data/services.js';
import { NURSING } from '../data/nursing.js';

// Quick-start card that overlaps the bottom of the hero (pattern from nriparentservice.com).
//
// It used to carry three hand-written tabs whose names matched nothing the rest of the page
// offered, which meant five of the real services had no route from the hero at all and the two
// the visitor could see were named differently in the booking popup. The row is now one chip
// per service in the catalogue, whatever that catalogue turns out to hold -- so when Preventia
// is connected, the names, the descriptions and the prices here are theirs.

// One tab per qualification Sahayak recruits -- the same three the rest of the page offers.
const BECOME_TABS = NURSING.map((q) => ({
  key: q.key, title: q.key, sub: q.length,
  text: q.text,
  full: q.full,
  reg: q.reg,
}));

function Tabs({ tabs, active, onPick, label }) {
  // The bar carries the white tab background and the curved join into the card below.
  return (
    <div className="hq-tabbar">
      <div className="hq-tabs" role="tablist" aria-label={label}>
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={active === t.key}
            className={cx('hq-tab', active === t.key && 'on')}
            onClick={() => onPick(t.key)}
          >
            <b>{t.title}</b>
            <small>{t.sub}</small>
          </button>
        ))}
      </div>
    </div>
  );
}

/* One chip per service. The label travels with the chip wherever there is room: eight medical
 * glyphs with nothing beside them is a guessing game, unlike the three on the companion page
 * where the icons are unmistakable. Below a phone's width the unselected chips do collapse to
 * the circle alone -- there is no room for eight labels and the selected one still reads -- and
 * the icon keeps its accessible name either way. */
function ServiceChips({ list, active, onPick }) {
  const row = useRef(null);
  /* Keep the chosen chip whole. The row scrolls, so picking one near the edge otherwise leaves
     it half cut off, which reads as a broken layout rather than as more to see. Scrolls by the
     least that makes it fit, so the row does not jump about on a wide screen where it already
     did fit -- and runs again once the label has finished opening, because on a phone the chip
     is still collapsed at the moment the click is handled and would measure far too narrow. */
  useEffect(() => {
    const fit = () => {
      const box = row.current;
      const el = box && box.querySelector('.hq-chip.on');
      if (!box || !el) return;
      const b = box.getBoundingClientRect();
      const c = el.getBoundingClientRect();
      if (c.left < b.left) box.scrollLeft -= b.left - c.left + 10;
      else if (c.right > b.right) box.scrollLeft += c.right - b.right + 10;
    };
    fit();
    const t = setTimeout(fit, 340);       // just past the label's 300ms open
    return () => clearTimeout(t);
  }, [active]);

  return (
    <div className="hq-tabbar">
      <div className="hq-chips" role="tablist" aria-label="Choose a service" ref={row}>
        {list.map((s) => (
          <button
            key={s.key}
            type="button"
            role="tab"
            aria-selected={active === s.key}
            title={s.name}
            className={cx('hq-chip', active === s.key && 'on')}
            onClick={() => onPick(s.key)}
          >
            <span className="hq-chip-ico" aria-hidden="true">
              {/* The catalogue names a Font Awesome class, which the site's own header already
                  loads. Standalone there is no Font Awesome, so fall back to a bundled glyph. */}
              {s.icon ? <i className={'fa-solid ' + s.icon}></i> : <Icon name="stethoscope" sw={1.9} />}
            </span>
            <span className="hq-chip-tx">{s.name}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

/** Families: pick a service, fill three quick fields, open the booking popup pre-filled. */
export function NeedHeroCard({ openBook }) {
  const list = catalogue(GIG_SERVICES);
  const [tab, setTab] = useState(list[0] ? list[0].key : '');
  const [who, setWho] = useState('');
  const [city, setCity] = useState('');
  const [when, setWhen] = useState('');
  const t = list.find((x) => x.key === tab) || list[0];
  const [steps, setSteps] = useState(null);
  const key = t && t.key;
  /* Preventia's own list of what the visit covers, fetched for the service being shown and
     swapped in when it lands. Until then the card shows the steps the bundle shipped with, so
     the card is never blank and never waits. */
  useEffect(() => {
    if (!key) return;
    setSteps(journeyFor(key, (s) => setSteps(s)));
  }, [key]);
  if (!t) return null;                 // a catalogue with nothing in it: draw no card at all
  const gig = gigFor(t.key);
  const covers = steps && steps.length
    ? steps.map((s) => ({ name: s.title, optional: s.optional }))
    : gig
      ? gig.includes.map((x) => ({ name: x, optional: false }))
        .concat(gig.optional.map((x) => ({ name: x, optional: true })))
      : [];

  return (
    <div className="hq rise d5">
      <div className="wrap hq-wrap">
        <ServiceChips list={list} active={t.key} onPick={setTab} />
        <div className="hq-body" role="tabpanel">
          {/* How long it takes, not what it costs, and up beside the name where it is seen: it
              used to sit as a line of grey text under the description, which nobody noticed.
              This card is the first thing on the page, and leading a worried family with a price
              tag puts the wrong thing first -- the figure is shown once they have chosen. */}
          <div className="hq-head">
            <h3>{t.name}</h3>
            {t.duration && (
              <span className="hq-dur" title="How long the visit usually takes">
                <span className="hq-dur-ic"><Icon name="clock" sw={2.2} /></span>
                <span className="hq-dur-tx"><small>Visit takes</small><b>{t.duration}</b></span>
              </span>
            )}
          </div>
          <p>{t.blurb}</p>
          {/* What the visit actually covers. The catalogue API names and prices a service but
              says nothing about its contents; the steps come from the GIG sheet, which is the
              only place they are written down. Optional ones are marked rather than hidden --
              "if needed" is the honest answer and the alternative is a promise we have not
              made. */}
          {covers.length > 0 && (
            <ul className="hq-inc">
              {covers.map((c) => (
                <li key={c.name} className={c.optional ? 'opt' : undefined}>
                  {c.name}{c.optional && <small> if needed</small>}
                </li>
              ))}
            </ul>
          )}
          <form
            className="hq-form"
            onSubmit={(e) => {
              e.preventDefault();
              openBook({ svc: t.key, who, city, when });
            }}
          >
            <div className="fld">
              <label htmlFor="hq-who">Who needs support?</label>
              <select id="hq-who" value={who} onChange={(e) => setWho(e.target.value)}>
                <option value="">Select</option>
                <option>Mother</option><option>Father</option><option>Both Parents</option><option>Other</option>
              </select>
            </div>
            <div className="fld">
              <label htmlFor="hq-city">Parent's city</label>
              <input id="hq-city" placeholder="e.g. Hyderabad" value={city} onChange={(e) => setCity(e.target.value)} />
            </div>
            <div className="fld">
              <label htmlFor="hq-when">When?</label>
              <select id="hq-when" value={when} onChange={(e) => setWhen(e.target.value)}>
                <option value="">Select</option>
                <option>One-time</option><option>Weekly</option><option>Ongoing</option><option>Urgent</option>
              </select>
            </div>
            <ArrowButton type="submit">Book a Sahayak</ArrowButton>
          </form>
        </div>
      </div>
    </div>
  );
}

/** Professionals: pick a role, fill three quick fields, jump into the application form pre-filled. */
export function BecomeHeroCard({ onApply }) {
  const [tab, setTab] = useState(BECOME_TABS[0].key);
  const [name, setName] = useState('');
  const [city, setCity] = useState('');
  const [years, setYears] = useState('');
  const t = BECOME_TABS.find((x) => x.key === tab);

  return (
    <div className="hq rise d5">
      <div className="wrap hq-wrap">
        <Tabs tabs={BECOME_TABS} active={tab} onPick={setTab} label="Choose your role" />
        <div className="hq-body" role="tabpanel">
          <div className="hq-head">
            <h3>{t.full}</h3>
            <span className="hq-dur hq-reg">
              <span className="hq-dur-ic"><Icon name="shield" sw={2.2} /></span>
              <span className="hq-dur-tx"><small>Registered as</small><b>{t.reg}</b></span>
            </span>
          </div>
          <p>{t.text}</p>
          <form
            className="hq-form"
            onSubmit={(e) => {
              e.preventDefault();
              onApply({ bg: tab, name, city, years });
            }}
          >
            <div className="fld">
              <label htmlFor="hq-name">Full name</label>
              <input id="hq-name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="fld">
              <label htmlFor="hq-bcity">City</label>
              <input id="hq-bcity" placeholder="e.g. Hyderabad" value={city} onChange={(e) => setCity(e.target.value)} />
            </div>
            <div className="fld">
              <label htmlFor="hq-years">Experience</label>
              <select id="hq-years" value={years} onChange={(e) => setYears(e.target.value)}>
                <option value="">Select</option>
                <option>Less than 1 year</option><option>1–3 years</option><option>3–5 years</option><option>5+ years</option>
              </select>
            </div>
            <ArrowButton type="submit">Start application</ArrowButton>
          </form>
        </div>
      </div>
    </div>
  );
}
