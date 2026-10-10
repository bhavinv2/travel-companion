import { useState } from 'react';
import Icon, { Underline } from './Icon.jsx';
import MultiStepForm, { ChipsField, Field, Q } from './MultiStepForm.jsx';
import { GIG_SERVICES, gigFor } from '../data/services.js';
import ServiceBento from './ServiceBento.jsx';
import { ArrowButton, ArrowLink, Chips, Quote, Reveal, SectionHead, SideDecor, Tag, cx } from './ui.jsx';
import { useInView } from '../hooks.js';
import { site, postJson, catalogue, specializations } from '../data/site.js';
import meetImg from '../assets/meet-sahayak-family.jpg';
import callImg from '../assets/hero-need.jpg';
import PhoneField, { phoneError, phonePair, phoneText } from './PhoneField.jsx';
import * as v from '../validate.js';

/* The cards are the catalogue -- Preventia's services, their names, their blurbs and their
 * prices -- wearing the GIG sheet's photograph and colours, which the API does not carry. The
 * steps on each card are the sheet's; the panel replaces them with Preventia's own the moment
 * it opens one.
 *
 * Matched on the service key, so a category Preventia adds still gets a card: it just arrives
 * without a photograph rather than not at all.
 */
// The colours the sheet's own services use, lent in turn to a category we have nothing for. A
// card with no colour of its own drew its "Book this service" button white on white.
const PALETTE = GIG_SERVICES.map((g) => ({ sc: g.sc, st: g.st }));

/* The first card is drawn large and labelled "Most complete", so it is the service that is: the
   Wellness Screen, whatever order the catalogue arrives in. Taking whatever came first put an
   online consultation under that label, blown up from a small photograph. */
const mostCompleteFirst = (list) => {
  const i = list.findIndex((s) => gigFor(s.key)?.key === 'Wellness Screen');
  return i > 0 ? [list[i], ...list.slice(0, i), ...list.slice(i + 1)] : list;
};

const cards = () => mostCompleteFirst(catalogue(GIG_SERVICES)).map((s, i) => {
  const g = gigFor(s.key) || {};
  return {
    ...PALETTE[i % PALETTE.length],
    tag: s.duration || '',
    ...g,
    key: s.key,
    title: s.name || g.title,
    text: s.blurb || g.text || '',
    price: s.price,
    duration: s.duration,
    journey: g.journey || [],
    includes: g.includes || [],
    optional: g.optional || [],
  };
});

// How it works: numbered steps on a dashed track (pattern from nriparentservice.com).
const JOURNEY = [
  { icon: 'phoneForm', title: 'Tell Us What You Need', text: "Your parent's location, needs and the support required.", chip: 'Takes two minutes' },
  { icon: 'searchPerson', title: 'Choose the Right Service', text: "Pick the help that matches your parent's situation.", chip: `${catalogue(GIG_SERVICES).length} services to pick` },
  { icon: 'personPlus', title: 'Matched With a Registered Nurse', text: 'A B.Sc Nursing, GNM or ANM nurse near them, with their registration checked before they ever turn up.', chip: 'Registration verified', tone: 'g' },
  { icon: 'calendarCheck', title: 'Confirm the Visit', text: 'We call you to agree a date and time that suits your parents.', chip: 'Flexible scheduling' },
  { icon: 'logo', title: 'The Visit, Step by Step', text: 'Your Sahayak works through each step and logs it as it is done.', chip: 'Regular updates' },
  { icon: 'refresh', title: 'Everything Kept', text: 'Readings, prescriptions and notes stay on record, ready for the next visit or the next doctor.', chip: 'One-time or ongoing', tone: 'g' },
];

function Hero({ openBook }) {
  return (
    <section className="hero hn" id="care">
      <div className="wrap hero-grid">
        <div>
          <Reveal as="h2" className="h-xl hn-h">
            A Health Professional With Your Parents, <em>Every Step<Underline /></em>
          </Reveal>
          <Reveal><Quote>Someone qualified, and a record you can read.</Quote></Reveal>
          <Reveal as="p" className="lead">
            Book a registered nurse to take your parents through whatever the
            health need is — the check, the test, the appointment, the hospital, the
            medicines — with every step recorded as it is done.
          </Reveal>
          <Reveal className="ctas">
            <ArrowButton onClick={() => openBook()}>Book a Sahayak</ArrowButton>
            <a className="btn btn-o" href="#services">Explore Sahayak Services</a>
          </Reveal>
          <Reveal className="trust">
            <div>Registered, verified nurses</div>
            <div>Care at home, no clinic queues</div>
            <div>You stay informed</div>
            <div>One-time or ongoing care</div>
          </Reveal>
        </div>

        <Reveal className="vis" aria-label="Illustration: a Sahayak visit update shared with the family">
          <div className="vis-bg">
            <div className="blob" style={{ width: 280, height: 280, right: -70, top: -80, background: 'var(--at)' }}></div>
            <div className="blob" style={{ width: 180, height: 180, left: -50, bottom: -60, background: '#fff', opacity: 0.6 }}></div>
          </div>
          <svg className="arc abs" viewBox="0 0 560 560" preserveAspectRatio="none" style={{ inset: 0, width: '100%', height: '100%' }} fill="none" aria-hidden="true">
            <path d="M150 70 C 470 40, 560 250, 430 480" strokeWidth="2.4" strokeLinecap="round" />
          </svg>
          <div className="abs rise d3 v-you" style={{ left: 24, top: 34 }}><Tag className="float3" icon="globe" title="You" sub="Wherever you are" /></div>
          <div className="abs rise d5 v-parents" style={{ right: 22, bottom: 26 }}><Tag className="home float2" icon="home" title="Your parents" sub="Cared for at home" /></div>

          <div className="abs rise d4 v-main" style={{ left: 28, top: 112, width: 330 }}>
            <div className="card float" style={{ padding: 24 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 8 }}>
                <div className="avatar">S</div>
                <div style={{ flexGrow: 1 }}>
                  <div style={{ fontWeight: 700, fontSize: 15.5 }}>Sahayak visit</div>
                  <div style={{ fontSize: 13, color: 'var(--mut)', marginTop: 2 }}>Home health check · 10:00 AM</div>
                </div>
                <span className="live"><i></i>Live</span>
              </div>
              {[['c1', 'Vitals checked', '10:12'], ['c2', 'Medicines reviewed', '10:20'], ['c3', 'Next visit planned', '10:28']].map(([c, t, time]) => (
                <div key={c} className={`chk ${c}`}><span className="ci"><Icon name="check" sw={3} /></span>{t}<small>{time}</small></div>
              ))}
              <div className="bubble"><Icon name="chat" sw={1.9} />Visit update shared with you</div>
            </div>
          </div>

          <div className="abs rise d6 v-side" style={{ right: 8, top: 262, width: 160 }}>
            <div className="card float2" style={{ padding: 18 }}>
              <div className="mini-l" style={{ marginBottom: 6 }}>Today's vitals</div>
              <div className="vit"><b>128/82</b><span>BP</span></div>
              <div className="vit"><b>108</b><span>Sugar</span></div>
              <div style={{ fontSize: 11, color: 'var(--mut)', marginTop: 8 }}>Sample update</div>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

function Services({ openBook }) {
  return (
    <section className="sec tight" id="services">
      <div className="wrap">
        <SectionHead
          kick="What a Sahayak handles"
          title={<>A Professional on <em>Every Step</em></>}
          quote="Not a visit. Someone seeing it through."
          sub="Each service below is run end to end by a registered nurse, and every step is recorded as it happens — so what your parents went through is something you can read, not something you have to ask about."
        />
        <ServiceBento services={cards()} openBook={openBook} />
      </div>
    </section>
  );
}

function Journey({ openBook }) {
  const [ref, inView] = useInView();
  return (
    <section className="sec tight" id="how">
      <div className="wrap">
        <SectionHead
          center
          kick="How it works"
          title={<>From a Request to <em>a Record</em></>}
          quote="Six steps, and you see every one of them."
          tone="h"
          sub="You say what is needed, we send someone qualified, and everything from their arrival to the doctor’s sign-off reaches you — wherever in the world you are."
        />
        <ol ref={ref} className={cx('hw io-t', inView && 'in')}>
          {JOURNEY.map((s, i) => (
            <li key={s.title} className={cx('hw-s', s.tone === 'g' && 'g')}>
              <span className="hw-n" aria-hidden="true">{i + 1}</span>
              {i === JOURNEY.length - 1 && <span className="hw-end" aria-hidden="true"><Icon name="homeSmallHeart" sw={1.8} /></span>}
              <div className="hw-c">
                <span className="hw-ic"><Icon name={s.icon} sw={1.8} /></span>
                <h3><span className="sr">Step {i + 1}: </span>{s.title}</h3>
                <p>{s.text}</p>
                <span className="hw-chip">{s.chip}</span>
              </div>
            </li>
          ))}
        </ol>
        <div className="hw-cta">
          <ArrowButton onClick={() => openBook()}>Book a Sahayak</ArrowButton>
          <p><Icon name="check" sw={2.4} />No commitment — our team calls you to confirm the details</p>
        </div>
      </div>
    </section>
  );
}

function MeetAndPrice({ openBook }) {
  const [cur, setCur] = useState('inr');
  return (
    <section className="sec tight" id="price">
      <div className="wrap">
        <Reveal className="mt">
          <div className="mt-photo">
            <img src={meetImg} alt="A Sahayak sitting with an elderly couple at their dining table, going over their care plan on a tablet" />
          </div>
          <div className="mt-body">
            <span className="kick">Who turns up</span>
            <h2 className="h2">Meet Your <em>Sahayak</em></h2>
            <Quote>Qualified, verified, and the same face each time.</Quote>
            <p className="mt-lead">
              Every Sahayak is a registered nurse — B.Sc Nursing, GNM or ANM — background-checked, trained on the
              service they are sent for, and backed by a doctor who reviews and signs off the visit. They speak your parents’
              language and know what to do when something is not routine.
            </p>
            <ul className="mt-chips" aria-label="What every Sahayak brings">
              <li>Registered nurses</li>
              <li>B.Sc Nursing · GNM · ANM</li>
              <li>Background verified</li>
              <li>Telugu · Hindi · English</li>
              <li>BLS certified</li>
            </ul>
            <div className="pr">
              <div className="pr-top">
                <span className="pr-l">Reserve a Sahayak</span>
                <div className="cur" role="group" aria-label="Show price in">
                  {[['inr', '₹ INR'], ['usd', '$ USD']].map(([k, label]) => (
                    <button key={k} type="button" className={cx(cur === k && 'on')} aria-pressed={cur === k} onClick={() => setCur(k)}>{label}</button>
                  ))}
                </div>
              </div>
              <div className="pr-row">
                <div className="pr-amt">
                  {/* key forces the flip animation to replay when the currency changes */}
                  <span className="amt" key={cur}>
                    <span className="sym">{cur === 'inr' ? '₹' : '$'}</span>{cur === 'inr' ? '499' : '4.99'}<sup>*</sup><span className="per">/hr</span>
                  </span>
                </div>
                <ArrowButton onClick={() => openBook()}>Book a Sahayak Visit</ArrowButton>
              </div>
              <div className="pr-plan">
                <span><b>Need care every week or month?</b> Contact us for weekly and monthly requirements.</span>
                <a href="#request">Contact us</a>
              </div>
              <p className="pr-fine">*[Add your pricing terms here]</p>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

function MilesAway() {
  return (
    <section className="sec tight" id="miles">
      <div className="wrap">
        <div className="ma">
          <Reveal className="ma-vis">
            <div className="lap">
              <div className="lap-scr">
                <img src={callImg} alt="A video call showing a Sahayak with an elderly mother at home" />
                <span className="lap-live"><i></i>Video call · 12:04</span>
                <span className="lap-self" aria-hidden="true">You</span>
                <span className="lap-ctl" aria-hidden="true">
                  <i><Icon name="mic" sw={2} /></i>
                  <i><Icon name="video" sw={2} /></i>
                  <i className="end"><Icon name="phoneEnd" sw={2} /></i>
                </span>
              </div>
              <div className="lap-base" aria-hidden="true"></div>
            </div>
            <div className="ma-tag t1" aria-hidden="true"><Tag className="float3" icon="heart" sw={2} title="Mom" sub="At home, with her Sahayak" /></div>
            <div className="ma-tag t2" aria-hidden="true"><Tag className="float2" icon="globe" sw={2} title="You" sub="Thousands of miles away" /></div>
          </Reveal>
          <Reveal className="ma-copy">
            <span className="kick">Always close</span>
            <h2 className="h2">You May Be Miles Away. <em>But You Can Still Be There.</em></h2>
            <Quote tone="p">Distance should not mean being in the dark.</Quote>
            <p className="sub">Being far away should not mean finding out late. A professional handles it at their end, the app records each step, and you read what happened without having to press your parents for details.</p>
            <div className="ma-f">
              <div><b>Peace of mind</b><small>Know someone is there</small></div>
              <div><b>Stay connected</b><small>Keep informed</small></div>
              <div><b>Professional support</b><small>Care you can trust</small></div>
            </div>
            <ArrowLink href="#request">Tell Us How We Can Help</ArrowLink>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

// Helpline numbers shown in the "Prefer to talk it through?" box.
export const HELPLINES = [
  { number: '+91 80191 11360', tel: '+918019111360', country: 'India' },
  { number: '+1 917 900 5094', tel: '+19179005094', country: 'USA' },
];

export function FormAside({ title, quote, text, items, callLabel, callValue, phones }) {
  return (
    <Reveal as="aside" className="aside">
      <div className="blobd" aria-hidden="true"></div>
      <h3>{title}</h3>
      {quote && <Quote>{quote}</Quote>}
      <p>{text}</p>
      <ul>
        {items.map((it) => (
          <li key={it}><span><Icon name="check" sw={2.4} /></span>{it}</li>
        ))}
      </ul>
      <div className="call">
        <span className="logo" style={{ background: 'rgba(255,255,255,.16)' }}><Icon name="phone" className="i" /></span>
        <div>
          <small>{callLabel}</small>
          {phones ? (
            <ul className="call-nums">
              {phones.map((p) => (
                <li key={p.tel}>
                  <a href={`tel:${p.tel}`}>{p.number}</a>
                  <span>{p.country}</span>
                </li>
              ))}
            </ul>
          ) : (
            <b>{callValue}</b>
          )}
        </div>
      </div>
    </Reveal>
  );
}

const REQUEST_EMPTY = {
  who: '', city: '', area: '', pin: '', what: [], spec: '', when: '', details: '',
  name: '', relationship: '', phone: '', phone_cc: '+91', phone_iso: 'IN',
  whatsapp: '', whatsapp_cc: '+91', whatsapp_iso: 'IN',
  email: '', contact_time: 'Morning (IST)',
};

/* What each step needs before it lets you on -- what /api/sahayak-booking would refuse, asked a
   step at a time so the message sits beside the box it is about. */
const REQUEST_CHECKS = [
  (d) => v.collect({ who: v.required(d.who, 'Please choose who needs support.') }),
  (d) => v.collect({
    city: v.personName(d.city, 'the city') && 'Please enter the city.',
    area: v.minText(d.area, 3, 'Please enter the locality or neighbourhood.'),
    pin: v.pin(d.pin),
  }),
  (d) => v.collect({ what: d.what.length ? '' : 'Choose at least one kind of support.' }),
  (d) => v.collect({ when: v.required(d.when, 'Please choose when support is needed.') }),
  () => ({}),
  (d) => v.collect({
    name: v.personName(d.name),
    phone: phoneError({ dial: d.phone_cc, iso: d.phone_iso, tel: d.phone }, { required: true }),
    whatsapp: phoneError({ dial: d.whatsapp_cc, iso: d.whatsapp_iso, tel: d.whatsapp }),
    email: v.email(d.email, { optional: true }),
  }),
];

function RequestForm() {
  const [data, setData] = useState(REQUEST_EMPTY);
  const [errors, setErrors] = useState({});
  const set = (k, val) => {
    setData((d) => ({ ...d, [k]: val }));
    setErrors((e) => (e[k] ? { ...e, [k]: '' } : e));
  };
  const f = { data, set };
  const err = (k) => errors[k] || '';
  const specs = specializations();
  const validate = (step) => {
    const e = REQUEST_CHECKS[step](data);
    setErrors(e);
    return !Object.keys(e).length;
  };

  const steps = [
    {
      short: 'Who', label: 'Who needs support',
      content: (
        <>
          <Q title="Who needs support?" sub="Who the Sahayak will be assisting." />
          <ChipsField error={err('who')}>
            <Chips options={['Mother', 'Father', 'Both Parents', 'Other Family Member']} value={data.who} onChange={(val) => set('who', val)} />
          </ChipsField>
        </>
      ),
    },
    {
      short: 'Where', label: 'Location',
      content: (
        <>
          <Q title="Where is it needed?" sub="So we can find a professional close to your parent's home." />
          <div className="fields">
            <Field id="n-city" label="City" req name="city" placeholder="e.g. Hyderabad" autoComplete="address-level2" error={err('city')} {...f} />
            <Field id="n-area" label="Area" req name="area" placeholder="Locality or neighbourhood" error={err('area')} {...f} />
            <Field id="n-pin" label="PIN Code" req name="pin" inputMode="numeric" maxLength={6} placeholder="6-digit PIN" autoComplete="postal-code"
                   error={err('pin')} data={data} set={(k, val) => set(k, val.replace(/\D/g, '').slice(0, 6))} />
          </div>
        </>
      ),
    },
    {
      short: 'Support', label: 'Support needed',
      content: (
        <>
          <Q title="What support is needed?" sub="Select all that apply." />
          <ChipsField error={err('what')}>
            <Chips multi options={catalogue(GIG_SERVICES).map((s) => s.name)} value={data.what} onChange={(val) => set('what', val)} />
          </ChipsField>
          {/* Preventia's list of what a Sahayak can specialise in; not offered when it is empty */}
          {specs.length > 0 && (
            <div className="fields" style={{ marginTop: 20 }}>
              <Field as="select" full id="n-spec" label="Sahayak specialisation (optional)" name="spec" {...f}>
                <option value="">No preference</option>
                {specs.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
              </Field>
            </div>
          )}
        </>
      ),
    },
    {
      short: 'When', label: 'Timing',
      content: (
        <>
          <Q title="When is support needed?" sub="You can always change this later — we call to agree the exact time." />
          <ChipsField error={err('when')}>
            <Chips options={['One-time', 'Weekly', 'Regular / Ongoing', 'Urgent Assistance']} value={data.when} onChange={(val) => set('when', val)} />
          </ChipsField>
        </>
      ),
    },
    {
      short: 'Details', label: 'Details',
      content: (
        <>
          <Q title="Tell us more" sub="Anything that helps us understand your parent's needs — health conditions, mobility, language preference." />
          <Field
            as="textarea" id="n-more" label="Describe your parent's requirement" name="details" maxLength={1500}
            placeholder="For example: My father needs BP and sugar checks twice a week and help getting to his cardiology follow-up."
            {...f}
          />
        </>
      ),
    },
    {
      short: 'Contact', label: 'Contact details',
      content: (
        <>
          <Q title="Your contact details" sub="So our team can reach you about next steps." />
          <div className="fields">
            <Field id="n-name" label="Name" req name="name" autoComplete="name" error={err('name')} {...f} />
            <Field id="n-rel" label="Relationship" name="relationship" placeholder="e.g. Son, Daughter" {...f} />
            {/* The country is chosen, not typed: these were text boxes that said "With country
                code" and left it to the family to remember it -- the same picker the join form
                and the booking dialog use. */}
            <PhoneField id="n-ph" label="Phone Number" required error={err('phone')}
                        value={{ dial: data.phone_cc, iso: data.phone_iso, tel: data.phone }}
                        onChange={(val) => { set('phone_cc', val.dial); set('phone_iso', val.iso || data.phone_iso); set('phone', val.tel); }} />
            <PhoneField id="n-wa" label="WhatsApp Number" hint="Leave blank if it is the same" error={err('whatsapp')}
                        value={{ dial: data.whatsapp_cc, iso: data.whatsapp_iso, tel: data.whatsapp }}
                        onChange={(val) => { set('whatsapp_cc', val.dial); set('whatsapp_iso', val.iso || data.whatsapp_iso); set('whatsapp', val.tel); }} />
            <Field id="n-em" label="Email" name="email" type="email" autoComplete="email" error={err('email')} {...f} />
            <Field as="select" id="n-time" label="Preferred Contact Time" name="contact_time" {...f}>
              <option>Morning (IST)</option><option>Afternoon (IST)</option><option>Evening (IST)</option><option>Any time</option>
            </Field>
          </div>
        </>
      ),
    },
  ];

  return (
    <MultiStepForm
      anchor="request"
      steps={steps}
      validate={validate}
      submitLabel="Request a Sahayak"
      fine="Our team will review your requirement and help you with the next steps."
      onSubmit={() =>
        /* The same endpoint the quick dialog uses, with the extra answers in the notes: this
           form asks more, but it is asking for the same thing -- a visit. */
        postJson(site.bookingUrl, {
          /* The chips show the catalogue's names; the endpoint takes its keys. Sending the name
             was refused as "choose which service you need" by a form that had just asked. */
          service: (catalogue(GIG_SERVICES).find((s) => s.name === data.what[0]) || {}).key
            || (site.services?.[0]?.key ?? ''),
          patient_name: data.who,
          contact_name: data.name,
          // the number as typed and its country, apart; the server stores it as E.164
          phone: data.phone.trim(),
          phone_cc: phonePair({ dial: data.phone_cc, iso: data.phone_iso, tel: data.phone }).cc,
          email: data.email,
          address: [data.area.trim(), data.city.trim()].filter(Boolean).join(', '),
          pincode: data.pin.trim(),
          when_type: 'asap',
          specialization: data.spec,
          notes: [
            data.what.length > 1 && `Also asked about: ${data.what.slice(1).join(', ')}`,
            data.when && `When: ${data.when}`,
            data.relationship && `Relationship: ${data.relationship}`,
            data.whatsapp.trim() && `WhatsApp: ${phoneText({ dial: data.whatsapp_cc, tel: data.whatsapp })}`,
            data.contact_time && `Best time to call: ${data.contact_time}`,
            data.details && `\n${data.details}`,
          ].filter(Boolean).join('\n'),
        })
      }
      done={{
        title: 'Request received',
        text: 'Our team will review your requirement and reach out at your preferred time to help with the next steps.',
        reset: 'Start another request',
        maxWidth: 440,
      }}
    />
  );
}

function Request() {
  return (
    <section className="sec tight" id="request">
      <SideDecor icons={[
        { name: 'chat', side: 'left', top: '10%', size: 34, rotate: -10, opacity: 0.16 },
        { name: 'home', side: 'left', top: '60%', size: 90, rotate: 10, opacity: 0.07 },
        { name: 'phone', side: 'right', top: '6%', size: 32, rotate: 8, opacity: 0.16 },
        { name: 'globe', side: 'right', top: '50%', size: 96, rotate: -8, opacity: 0.07 },
      ]} />
      <div className="wrap">
        <SectionHead
          kick="Request care"
          title={<>Tell Us What <em>Your Parent Needs</em></>}
          quote="One message, and a professional is on it."
          tone="p"
          sub="A few quick questions, one at a time. It takes about two minutes."
        />
        <div className="form-wrap">
          <FormAside
            title="Helpful to have ready"
            quote="A little detail goes a long way."
            text="Nothing formal — just enough for us to understand the situation."
            items={["Your parent's area and PIN code", 'What kind of help they need', "When you'd like support to start", 'A good time for us to call you']}
            callLabel="Prefer to talk it through?"
            phones={HELPLINES}
          />
          <RequestForm />
        </div>
      </div>
    </section>
  );
}

export default function NeedMode({ openBook }) {
  return (
    <div className="m-need">
      <main>
        <Hero openBook={openBook} />
        <Services openBook={openBook} />
        <Journey openBook={openBook} />
        <MeetAndPrice openBook={openBook} />
        <MilesAway />
        <Request />
      </main>
    </div>
  );
}
