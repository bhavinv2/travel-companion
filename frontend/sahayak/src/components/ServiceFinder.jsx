import { useMemo, useState } from 'react';
import Icon from './Icon.jsx';
import { ArrowButton, Reveal, SectionHead, cx } from './ui.jsx';
import { catalogue } from '../data/site.js';
import { GIG_SERVICES } from '../data/services.js';
import { INCLUDES, NEEDS } from '../data/needs.js';

/* "Which service do we need?" -- answered from the GIG sheet rather than from opinion.
 *
 * Nine services is a lot to choose between when you are three thousand miles away and not
 * sure what is wrong. The chips above name them; this works the other way round, from what
 * the family can actually describe to the service that covers it.
 *
 * One question at a time. Every question earns its place twice over: it either moves the
 * recommendation, or it fills in something the booking form would otherwise ask again --
 * usually both. Answering six here means the booking opens half filled in, which is the only
 * reason it is worth asking six.
 *
 *   who      -> booking's "who needs support"
 *   what     -> scoring
 *   travel   -> scoring (and the only thing that separates Out-Patient from In-Patient)
 *   often    -> scoring, and the booking's one-off / weekly / ongoing
 *   ordered  -> scoring, and the booking's "is this a follow-up"
 *   needs    -> scoring, against the sheet's matrix
 *
 * The scoring is the sheet's own matrix (data/needs.js, generated from it): each service is
 * scored on how much of what they asked for it actually includes. Mandatory counts for more
 * than optional, and asking for something a service does not do counts against it -- which is
 * what stops "a blood sample" recommending a pharmacy delivery.
 *
 * Two of the questions exist because the matrix cannot answer them. Out-Patient and In-Patient
 * are identical in it -- both are "take them somewhere", nothing else mandatory -- so only
 * asking which splits them. Pharmacy Delivery has nothing mandatory at all beyond the frame
 * every service shares, so it can only be reached by someone saying that is what they want.
 */

// The situation weights carry the recommendation; the ones after it only nudge, so a late
// answer can refine a choice but never overturn what somebody plainly said they needed.
const STEPS = [
  {
    key: 'who', q: 'Who needs support?',
    items: [
      { key: 'Mother', label: 'My mother' },
      { key: 'Father', label: 'My father' },
      { key: 'Both Parents', label: 'Both of them' },
      { key: 'Other', label: 'Somebody else', hint: 'A relative or a family friend' },
    ],
  },
  {
    key: 'what', q: 'What best describes what they need?',
    items: [
      { key: 'tests', label: 'A doctor has asked for tests',
        hint: 'Blood work, urine, an ECG', w: { lab_work: 4, wellness_screen: 1 } },
      { key: 'overdue', label: 'Nobody has checked on them in a while',
        hint: 'No particular complaint', w: { wellness_screen: 4, vitals: 2, demo: 1 } },
      { key: 'appointment', label: 'There is an appointment or admission coming up',
        hint: 'They need someone with them', w: { out_patient_visit: 3, in_patient_visit: 3 } },
      { key: 'routine', label: 'Day-to-day things',
        hint: 'Readings, medicines, keeping records straight',
        w: { vitals: 3, pharmacy_delivery: 3, demo: 1 } },
      { key: 'unsure', label: 'I want to see how this works first',
        hint: 'Before booking anything longer', w: { demo: 5 } },
      { key: 'other', label: 'Something else', hint: 'Tell us and we will arrange it',
        w: { other: 3 } },
    ],
  },
  {
    key: 'travel', q: 'Does someone need to go with them?',
    items: [
      { key: 'home', label: 'No — everything at home', hint: 'Nobody has to leave the house',
        w: { out_patient_visit: -4, in_patient_visit: -4 } },
      { key: 'clinic', label: 'Yes — to a clinic or doctor', hint: 'There and back the same day',
        w: { out_patient_visit: 5 } },
      { key: 'hospital', label: 'Yes — into hospital', hint: 'An admission or a procedure',
        w: { in_patient_visit: 5 } },
      { key: 'collect', label: 'Only to collect something', hint: 'Medicines or a report',
        w: { pharmacy_delivery: 4 } },
    ],
  },
  {
    key: 'often', q: 'How often will this be needed?',
    items: [
      { key: 'One-time', label: 'Just this once',
        w: { wellness_screen: 1, lab_work: 1, demo: 1 } },
      { key: 'Weekly', label: 'Every week or two', w: { vitals: 2, pharmacy_delivery: 1 } },
      { key: 'Ongoing', label: 'Regularly, for a while',
        w: { vitals: 2, pharmacy_delivery: 2 } },
      { key: 'Urgent', label: 'As soon as possible', hint: 'Something has come up',
        w: { out_patient_visit: 1, lab_work: 1 } },
    ],
  },
  {
    key: 'ordered', q: 'Has a doctor already asked for this?',
    items: [
      { key: 'script', label: 'Yes — there is a prescription or request',
        hint: 'You can attach it when you book', w: { lab_work: 2, pharmacy_delivery: 2 } },
      { key: 'followup', label: 'It is a follow-up to an earlier visit',
        w: { out_patient_visit: 1, in_patient_visit: 1 } },
      { key: 'none', label: 'No — we just want them looked at',
        w: { wellness_screen: 1, vitals: 1 } },
      { key: 'dunno', label: 'Not sure', w: {} },
    ],
  },
  {
    key: 'needs', q: 'Anything in particular they need?', multi: true, optional: true,
    note: 'Choose as many as apply, or skip this.', items: NEEDS,
  },
];

const POINTS = { MAD: 3, OPT: 1 };
const MISSING = -3;        // asked for something this service does not do at all

function score(list, answers) {
  const chosen = STEPS
    .filter((s) => !s.multi)
    .map((s) => (s.items.find((i) => i.key === answers[s.key]) || {}).w)
    .filter(Boolean);
  const needs = answers.needs || [];
  return list
    .map((svc) => {
      const has = INCLUDES[svc.key] || {};
      let n = chosen.reduce((t, w) => t + (w[svc.key] || 0), 0);
      const covers = [];
      const gaps = [];
      let mad = 0;
      needs.forEach((k) => {
        const mark = has[k];
        n += mark ? POINTS[mark] : MISSING;
        if (mark === 'MAD') mad += 1;
        (mark ? covers : gaps).push(k);
      });
      return { svc, n, mad, covers, gaps };
    })
    // Ties go to the service that does more of it as a matter of course rather than on
    // request: asking for samples taken to a lab should land on Lab Work, where that is the
    // whole point, not on a service that merely offers it. Without this the tie falls to
    // whatever order the catalogue happened to arrive in.
    .sort((a, b) => b.n - a.n || b.mad - a.mad);
}

const labelOf = (k) => (NEEDS.find((n) => n.key === k) || {}).label || k;

/** One answer. A button, not an <input>, so the whole row is the target on a phone. */
function Choice({ item, chosen, multi, onPick }) {
  return (
    <button type="button" role={multi ? 'checkbox' : 'radio'} aria-checked={chosen}
            className={cx('sf-row', chosen && 'on')} onClick={onPick}>
      <span className={cx('sf-mark', multi && 'box')} aria-hidden="true">
        {multi && <Icon name="check" sw={3.4} />}
      </span>
      <span className="sf-rtx">
        <b>{item.label}</b>
        {item.hint && <small>{item.hint}</small>}
      </span>
    </button>
  );
}

const EMPTY = { who: null, what: null, travel: null, often: null, ordered: null, needs: [] };

export default function ServiceFinder({ openBook }) {
  const list = useMemo(() => catalogue(GIG_SERVICES), []);
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState(EMPTY);

  const ranked = useMemo(() => score(list, answers), [list, answers]);
  const best = ranked[0];
  const runnerUp = ranked[1] && ranked[1].n > 0 && ranked[1].n >= ranked[0].n - 2
    ? ranked[1] : null;

  const done = step >= STEPS.length;
  const current = STEPS[step];
  const chosen = done ? null : answers[current.key];
  const canGo = done || current.optional || (current.multi ? true : !!chosen);

  const set = (key, value) => setAnswers((a) => ({ ...a, [key]: value }));
  const toggle = (key) => setAnswers((a) => ({
    ...a,
    needs: a.needs.includes(key) ? a.needs.filter((x) => x !== key) : a.needs.concat(key),
  }));

  // Everything they told us, carried into the booking rather than asked for twice.
  const book = (svc) => openBook({
    svc,
    who: answers.who || '',
    when: answers.often || '',
    followUp: answers.ordered === 'followup' ? 'Yes'
      : answers.ordered === 'none' || answers.ordered === 'script' ? 'No' : '',
  });

  return (
    <section className="sec tight" id="find">
      <div className="wrap">
        <SectionHead
          center
          kick="Not sure which one"
          title={<>Tell Us What Is Going On, <em>We Will Work It Out</em></>}
          quote="You describe it. We name it."
          sub="A few questions about your parents’ situation, and we point at the service that
               covers it — with what it includes and what it costs. Your answers carry straight
               into the booking, so nothing is asked twice."
        />

        <Reveal className="sf">
          <div className="sf-head">
            <h3>{done ? 'Here is what fits' : 'Find the right service'}</h3>
            <div className="sf-dots" aria-hidden="true">
              {STEPS.map((s, i) => (
                <i key={s.key} className={cx(i === step && 'on', i < step && 'did')}></i>
              ))}
            </div>
            <span className="sf-of">
              {done ? 'Done' : `Question ${step + 1} of ${STEPS.length}`}
            </span>
          </div>

          {!done ? (
            <div className="sf-body">
              <p className="sf-q">{current.q}</p>
              {current.note && <p className="sf-note">{current.note}</p>}
              <div className={cx('sf-rows', current.multi && 'two')}
                   role={current.multi ? 'group' : 'radiogroup'} aria-label={current.q}>
                {current.items.map((item) => (
                  <Choice
                    key={item.key}
                    item={item}
                    multi={current.multi}
                    chosen={current.multi ? answers.needs.includes(item.key)
                                          : chosen === item.key}
                    onPick={() => (current.multi ? toggle(item.key)
                                                 : set(current.key, item.key))}
                  />
                ))}
              </div>
              <div className="sf-nav">
                {step > 0 && (
                  <button type="button" className="sf-back" onClick={() => setStep(step - 1)}>
                    <Icon name="arrowLeft" sw={2.2} />Back
                  </button>
                )}
                <button type="button" className="sf-next" disabled={!canGo}
                        onClick={() => setStep(step + 1)}>
                  {step === STEPS.length - 1
                    ? (answers.needs.length ? 'See my match' : 'Skip and see my match')
                    : 'Next'}
                </button>
              </div>
            </div>
          ) : (
            <div className="sf-body sf-res" aria-live="polite">
              <span className="sf-kick">Closest match</span>
              <h4>{best.svc.name}</h4>
              {best.svc.blurb && <p className="sf-blurb">{best.svc.blurb}</p>}
              {(best.svc.price || best.svc.duration) && (
                <p className="sf-meta">
                  {best.svc.price && <b>&#8377;{best.svc.price}</b>}
                  {best.svc.price && best.svc.duration && <span aria-hidden="true"> · </span>}
                  {best.svc.duration && <span>{best.svc.duration}</span>}
                </p>
              )}
              {best.covers.length > 0 && (
                <ul className="sf-why">
                  {best.covers.map((k) => (
                    <li key={k}><Icon name="check" sw={3} />{labelOf(k)}</li>
                  ))}
                </ul>
              )}
              {/* Said plainly rather than quietly dropped: being told afterwards that the
                  visit never included the thing you asked for is how trust goes. */}
              {best.gaps.length > 0 && (
                <p className="sf-gap">
                  <Icon name="close" sw={2.6} />
                  <span>
                    This one does not cover {best.gaps.map(labelOf).join(', ').toLowerCase()}.
                    {runnerUp && ' Have a look at the alternative below.'}
                  </span>
                </p>
              )}
              <div className="sf-acts">
                <ArrowButton onClick={() => book(best.svc.key)}>
                  Book {best.svc.name}
                </ArrowButton>
                <button type="button" className="sf-again"
                        onClick={() => { setAnswers(EMPTY); setStep(0); }}>Start again</button>
              </div>
              <p className="sf-carry">
                <Icon name="check" sw={3} />
                Your answers come with you — the booking opens already filled in.
              </p>
              {runnerUp && (
                <button type="button" className="sf-alt" onClick={() => book(runnerUp.svc.key)}>
                  <span>Also close: <b>{runnerUp.svc.name}</b></span>
                  <Icon name="arrow" sw={2} />
                </button>
              )}
            </div>
          )}
        </Reveal>
      </div>
    </section>
  );
}
