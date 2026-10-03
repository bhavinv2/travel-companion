import { useState } from 'react';
import Icon, { Underline } from './Icon.jsx';
import MultiStepForm, { Field, Q } from './MultiStepForm.jsx';
import { SERVICES } from './BookingModal.jsx';
import { GIG_SERVICES, gigFor } from '../data/services.js';
import ServiceBento from './ServiceBento.jsx';
import ServiceFinder from './ServiceFinder.jsx';
import { ArrowButton, ArrowLink, Chips, Quote, Reveal, SectionHead, SideDecor, Tag, cx } from './ui.jsx';
import { useInView } from '../hooks.js';
import { site, postJson, catalogue } from '../data/site.js';
import meetImg from '../assets/meet-sahayak-family.jpg';
import callImg from '../assets/hero-need.jpg';

/* The cards are the catalogue -- Preventia's services, their names, their blurbs and their
 * prices -- wearing the GIG sheet's photograph and colours, which the API does not carry. The
 * steps on each card are the sheet's; the panel replaces them with Preventia's own the moment
 * it opens one.
 *
 * Matched on the service key, so a category Preventia adds still gets a card: it just arrives
 * without a photograph rather than not at all.
 */
const cards = () => catalogue(GIG_SERVICES).map((s) => {
  const g = gigFor(s.key) || {};
  return {
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
  { icon: 'personPlus', title: 'Matched With a Professional', text: 'A qualified health professional near them, checked and verified before they ever turn up.', chip: 'Background verified', tone: 'g' },
  { icon: 'calendarCheck', title: 'Confirm the Visit', text: 'Choose a date and time that suits your parents.', chip: 'Flexible scheduling' },
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
            Book a trained health professional to take your parents through whatever the
            health need is — the check, the test, the appointment, the hospital, the
            medicines — with every step recorded as it is done.
          </Reveal>
          <Reveal className="ctas">
            <ArrowButton onClick={() => openBook()}>Book a Sahayak</ArrowButton>
            <a className="btn btn-o" href="#services">Explore Sahayak Services</a>
          </Reveal>
          <Reveal className="trust">
            <div>Verified professionals</div>
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
          sub="Each service below is run end to end by a trained health professional, and every step is recorded as it happens — so what your parents went through is something you can read, not something you have to ask about."
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
              Every Sahayak is a qualified health professional — background-checked, trained on the service they are
              sent for, and backed by a doctor who reviews and signs off the visit. They speak your parents’
              language and know what to do when something is not routine.
            </p>
            <ul className="mt-chips" aria-label="What every Sahayak brings">
              <li>Background verified</li>
              <li>Professionally trained</li>
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
  who: '', city: '', area: '', pin: '', what: [], when: '', details: '',
  name: '', relationship: '', phone: '', whatsapp: '', email: '', contact_time: 'Morning (IST)',
};

function RequestForm() {
  const [data, setData] = useState(REQUEST_EMPTY);
  const set = (k, v) => setData((d) => ({ ...d, [k]: v }));
  const f = { data, set };

  const steps = [
    {
      short: 'Who', label: 'Who needs support',
      content: (
        <>
          <Q title="Who needs support?" sub="Who the Sahayak will be assisting." />
          <Chips options={['Mother', 'Father', 'Both Parents', 'Other Family Member']} value={data.who} onChange={(v) => set('who', v)} />
        </>
      ),
    },
    {
      short: 'Where', label: 'Location',
      content: (
        <>
          <Q title="Where is it needed?" sub="So we can find a professional close to your parent's home." />
          <div className="fields">
            <Field id="n-city" label="City" name="city" placeholder="e.g. Hyderabad" {...f} />
            <Field id="n-area" label="Area" name="area" placeholder="Locality or neighbourhood" {...f} />
            <Field id="n-pin" label="PIN Code" name="pin" inputMode="numeric" placeholder="6-digit PIN" {...f} />
          </div>
        </>
      ),
    },
    {
      short: 'Support', label: 'Support needed',
      content: (
        <>
          <Q title="What support is needed?" sub="Select all that apply." />
          <Chips multi options={SERVICES} value={data.what} onChange={(v) => set('what', v)} />
        </>
      ),
    },
    {
      short: 'When', label: 'Timing',
      content: (
        <>
          <Q title="When is support needed?" sub="You can always change this later." />
          <Chips options={['One-time', 'Weekly', 'Regular / Ongoing', 'Urgent Assistance']} value={data.when} onChange={(v) => set('when', v)} />
        </>
      ),
    },
    {
      short: 'Details', label: 'Details',
      content: (
        <>
          <Q title="Tell us more" sub="Anything that helps us understand your parent's needs — health conditions, mobility, language preference." />
          <Field
            as="textarea" id="n-more" label="Describe your parent's requirement" name="details"
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
            <Field id="n-name" label="Name" name="name" autoComplete="name" {...f} />
            <Field id="n-rel" label="Relationship" name="relationship" placeholder="e.g. Son, Daughter" {...f} />
            <Field id="n-ph" label="Phone Number" name="phone" type="tel" autoComplete="tel" placeholder="With country code" {...f} />
            <Field id="n-wa" label="WhatsApp Number" name="whatsapp" type="tel" placeholder="With country code" {...f} />
            <Field id="n-em" label="Email" name="email" type="email" autoComplete="email" {...f} />
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
      submitLabel="Request a Sahayak"
      fine="Our team will review your requirement and help you with the next steps."
      onSubmit={() =>
        /* The same endpoint the quick dialog uses, with the extra answers in the notes: this
           form asks more, but it is asking for the same thing -- a visit. */
        postJson(site.bookingUrl, {
          service: data.what[0] || (site.services?.[0]?.key ?? ''),
          patient_name: data.who,
          contact_name: data.name,
          phone: data.phone,
          email: data.email,
          address: [data.area, data.city].filter(Boolean).join(', '),
          pincode: data.pin,
          when_type: 'asap',
          notes: [
            data.what.length > 1 && `Also asked about: ${data.what.slice(1).join(', ')}`,
            data.when && `When: ${data.when}`,
            data.relationship && `Relationship: ${data.relationship}`,
            data.whatsapp && `WhatsApp: ${data.whatsapp}`,
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
        {/* Straight after the nine cards: this is where somebody who has just scrolled them
            and not recognised their own situation is standing. */}
        <ServiceFinder openBook={openBook} />
        <Journey openBook={openBook} />
        <MeetAndPrice openBook={openBook} />
        <MilesAway />
        <Request />
      </main>
    </div>
  );
}
