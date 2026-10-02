import { useState } from 'react';
import { ArrowButton, cx } from './ui.jsx';

// Tabbed quick-start card that overlaps the bottom of the hero (pattern from nriparentservice.com).
// `svc` is the matching service in the booking popup (the GIG-sheet service list), so the
// original tab names can stay while the popup still opens with the right service selected.
const NEED_TABS = [
  {
    key: 'Health Checkup', svc: 'Vitals', title: 'Health Checkup', sub: 'BP, sugar & vitals at home',
    heading: 'Health Checkups at Home',
    text: 'A trained Sahayak visits your parents to check BP, sugar and vitals — and shares the update with you.',
  },
  {
    key: 'Doctor Appointment', svc: 'Out-Patient Visit', title: 'Doctor Visit', sub: 'Before, during & after',
    heading: 'Doctor Visit Assistance',
    text: 'Your Sahayak accompanies your parents to appointments, takes notes and keeps you in the loop.',
  },
  {
    key: 'Hospital Visit', svc: 'In-Patient Visit', title: 'Hospital Visit', sub: 'Visits & procedures',
    heading: 'Hospital Assistance',
    text: 'A trusted companion for hospital visits, procedures and follow-ups — so your parents are never alone.',
  },
];

const BECOME_TABS = [
  {
    key: 'Nurse', title: 'Nurses & ANMs', sub: 'GNM · B.Sc · ANM',
    heading: 'Join as a Nurse or ANM',
    text: 'Use your nursing skills to support families with home health checks, monitoring and care.',
  },
  {
    key: 'Phlebotomist', title: 'Phlebotomists', sub: 'Sample collection',
    heading: 'Join as a Phlebotomist',
    text: 'Collect samples at home and help families complete diagnostic tests without clinic queues.',
  },
  {
    key: 'Care Coordinator', title: 'Care Coordinators', sub: 'Care planning',
    heading: 'Join as a Care Coordinator',
    text: 'Keep families informed and coordinate care between parents, their children and doctors.',
  },
];

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

/** Families: pick a service, fill three quick fields, open the booking popup pre-filled. */
export function NeedHeroCard({ openBook }) {
  const [tab, setTab] = useState(NEED_TABS[0].key);
  const [who, setWho] = useState('');
  const [city, setCity] = useState('');
  const [when, setWhen] = useState('');
  const t = NEED_TABS.find((x) => x.key === tab);

  return (
    <div className="hq rise d5">
      <div className="wrap hq-wrap">
        <Tabs tabs={NEED_TABS} active={tab} onPick={setTab} label="Choose a service" />
        <div className="hq-body" role="tabpanel">
          <h3>{t.heading}</h3>
          <p>{t.text}</p>
          <form
            className="hq-form"
            onSubmit={(e) => {
              e.preventDefault();
              openBook({ svc: t.svc, who, city, when });
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
          <h3>{t.heading}</h3>
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
