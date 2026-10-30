import { useEffect, useRef, useState } from 'react';
import Icon from './Icon.jsx';
import Rail from './Rail.jsx';
import { useReveal } from '../hooks.js';
import mission from '../assets/about/mission.png';
import vision from '../assets/about/vision.png';
import values from '../assets/about/values.png';
import madhu from '../assets/about/madhu-vulli.jpg';
import vinay from '../assets/about/vinay-kumar-punjala.jpg';
import prakash from '../assets/about/veeramalla-prakash.jpg';
import vijay from '../assets/about/chennamchetty-vijay-kumar.jpg';
import satheesh from '../assets/about/satheesh-kathula.jpg';
import pApollo from '../assets/about/partner-apollo.png';
import pHealthcare from '../assets/about/partner-healthcare.png';
import pManipal from '../assets/about/partner-manipal.png';
import pMax from '../assets/about/partner-max.png';
import pStari from '../assets/about/partner-stari.png';
import pIcici from '../assets/about/partner-icicrelom.png';

/* The About page. Every heading, paragraph, name, bio and image is nriparentservice.com/about-us's
 * own; the layout is this site's, in colour. The small labels, handwritten lines and the
 * advisors' speciality tags are summaries of that same content, not new claims. */

const GUIDES = [
  { tone: 'blue', img: mission, title: 'Our Mission', text: 'Creating trusted care, comfort, safety, and lifelong support for every NRI parent globally.' },
  { tone: 'coral', img: vision, title: 'Our Vision', text: 'Connecting NRI families with trusted care, wellness, safety, and support for parents at home.' },
  { tone: 'green', img: values, title: 'Our Values', text: 'Driven by compassion, trust, dignity, safety, and excellence to support parents with care always.' },
];

const STORY = [
  'Madhu Vulli is an NRI who deeply understands the emotional and practical challenges faced by families whose parents live independently in India while their children live abroad.',
  'During the COVID-19 pandemic, Madhu personally experienced the helplessness and emotional pain of being thousands of miles away while his parents faced health challenges in India. The uncertainty, inability to be physically present, and difficulty coordinating trusted support made him realize a problem shared by millions of NRIs around the world.',
  'That experience became the inspiration behind NRI Parent Service — a mission-driven initiative created to bridge the gap between global families and local care in India.',
  'The goal is simple yet meaningful: to ensure that parents in India receive trusted, compassionate, and dependable support whenever they need it. Whether it is preventive healthcare, access to quality medical services, travel companionship, property management, emergency assistance, or everyday support, NRI Parent Service is committed to being a reliable helping hand for families separated by distance.',
];
const STORY_CLOSE = 'By building a trusted network of care and support services, Madhu aims to give NRIs peace of mind — knowing their parents are cared for, connected, and never alone, no matter where they are in the world.';

const ADVISORS = [
  { tone: 'green', name: 'Dr Vinay Kumar Punjala', tag: 'Surgical Gastroenterology', img: vinay, bio: [
    'Dr. Vinay Kumar Punjala is a distinguished Surgical Gastroenterologist and Advanced Laparoscopic Surgeon, recognized for his dedication to excellence in healthcare and patient care. With vast experience in gastrointestinal and minimally invasive surgeries, he has built a reputation for clinical expertise, compassion, and innovation in the medical field.',
  ] },
  { tone: 'purple', name: 'Veeramalla Prakash', tag: 'Policy & Water Resources', img: prakash, bio: [
    'Veeramalla Prakash, also known as "Telangana Prakash," is an Indian advocate, writer, and politician. He is considered one of the co-founders of the TRS party.',
    'Veeramalla Prakash is also known for his expertise in irrigation policy, water resource management, and Telangana history. He worked as Policy Advisor to the Chief Minister of Telangana and later served as Chairman of the Telangana Water Resources Development Corporation. His policy recommendations supported agriculture, irrigation projects, and regional development.',
  ] },
  { tone: 'amber', name: 'Dr. Chennamchetty Vijay Kumar', tag: 'Pulmonology · 16 years', img: vijay, bio: [
    'Dr. Chennamchetty Vijay Kumar is a highly experienced Pulmonology & Respiratory Medicine Specialist based in Hyderabad, Telangana. With 16 years of dedicated practice, he has established himself as a prominent figure in the field of respiratory health. Dr. Chennamchetty\'s extensive qualifications include an MD in Pulmonology, IDCC in Critical Care, FSM in Sleep Medicine, and an FCCP accreditation, showcasing his comprehensive expertise in various facets of pulmonary and sleep-related disorders.',
  ] },
  { tone: 'blue', name: 'Dr. Satheesh Kathula', creds: 'MD, FACP, DipABLM', tag: 'Medical Oncology · 33 years', img: satheesh, bio: [
    'Dr. Satheesh Kathula is a medical oncologist with 33 years of experience caring for patients with cancer. He specializes in oncology, focusing on the diagnosis and treatment of various types of cancer.',
    'He is Cancer Wellness and Prevention Advocate, Global Healthcare Leader, Educator, Author, AI in Healthcare.',
  ] },
];

const PARTNERS = [
  { name: 'Apollo', src: pApollo },
  { name: 'Health Care', src: pHealthcare },
  { name: 'Manipal Hospitals', src: pManipal },
  { name: 'MAX Health Care', src: pMax },
  { name: 'STARI Health Insurance', src: pStari },
  { name: 'ICICRELom', src: pIcici },
];

function Guides() {
  const ref = useReveal(0.1);
  return (
    <section className="sec abx-guides-sec" aria-labelledby="guide-h">
      <div className="wrap">
        <div className="p2-head">
          <span className="kick">Who we are</span>
          <h2 className="h2" id="guide-h">What Guides Us</h2>
          <span className="script-tag st-blue">Care, at the heart of it.</span>
        </div>
        <div className="abx-guides rv-stagger" ref={ref}>
          {GUIDES.map((g, i) => (
            <article className={`abx-guide t-${g.tone}`} key={g.title} style={{ '--d': `${i * 120}ms` }}>
              <span className="abx-guide-ic"><img src={g.img} alt="" width={229} height={215} /></span>
              <h3>{g.title}</h3>
              <p>{g.text}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function Story() {
  const pic = useReveal();
  const txt = useReveal();
  return (
    <section className="sec abx-story-sec" id="story" aria-labelledby="story-h">
      <div className="wrap abx-story">
        <figure className="abx-founder rv-left" ref={pic}>
          <span className="abx-frame" aria-hidden="true" />
          <span className="abx-dots" aria-hidden="true" />
          <img src={madhu} alt="Madhu Vulli, Founder" loading="lazy" decoding="async" />
          <figcaption><b>Madhu Vulli</b><span>Founder</span></figcaption>
        </figure>
        <div className="abx-story-txt rv-up" ref={txt}>
          <span className="kick">Our story</span>
          <h2 className="h2" id="story-h">Welcome!</h2>
          <span className="script-tag st-amber">Where it all began.</span>
          {STORY.map((p, i) => <p key={i} className={i === 0 ? 'abx-lead' : ''}>{p}</p>)}
          <blockquote className="abx-quote"><Icon name="heart" /><p>{STORY_CLOSE}</p></blockquote>
        </div>
      </div>
    </section>
  );
}

function Advisor({ a, i, onOpen }) {
  return (
    <article className={`abx-adv t-${a.tone}`} style={{ '--d': `${i * 100}ms` }}>
      <div className="abx-adv-top">
        <img src={a.img} alt={`${a.name}, Advisor`} loading="lazy" decoding="async" />
      </div>
      <div className="abx-adv-b">
        <span className="abx-tag">{a.tag}</span>
        <h3>{a.name}</h3>
        <small className="abx-role">Advisor{a.creds ? ` · ${a.creds}` : ''}</small>
        <div className="abx-bio">
          {a.bio.map((p, k) => <p key={k}>{p}</p>)}
        </div>
        <button type="button" className="abx-more" aria-haspopup="dialog" onClick={(e) => onOpen(a, e.currentTarget)}>
          Read more<Icon name="arrow" />
        </button>
      </div>
    </article>
  );
}

/* The full profile, in a pop-up over the page. A native <dialog> opened with showModal(), so
 * the browser keeps focus inside it, Esc closes it and the page behind is inert; a click on
 * the backdrop closes it too, and focus goes back to the Read more that opened it. */
function Profile({ a, onClose }) {
  const ref = useRef(null);
  useEffect(() => {
    const d = ref.current;
    if (a && !d.open) d.showModal();
    if (!a && d.open) d.close();
  }, [a]);
  return (
    <dialog ref={ref} className={`abx-dlg${a ? ` t-${a.tone}` : ''}`} aria-labelledby="abx-dlg-h"
      onClose={onClose} onClick={(e) => { if (e.target === ref.current) ref.current.close(); }}>
      {a && (
        <div className="abx-dlg-in">
          <button type="button" className="abx-x" aria-label="Close" onClick={() => ref.current.close()}><Icon name="close" /></button>
          <div className="abx-dlg-top">
            <img src={a.img} alt="" />
            <div>
              <span className="abx-tag">{a.tag}</span>
              <h3 id="abx-dlg-h">{a.name}</h3>
              <small>Advisor{a.creds ? ` · ${a.creds}` : ''}</small>
            </div>
          </div>
          <div className="abx-dlg-b">
            {a.bio.map((p, k) => <p key={k}>{p}</p>)}
          </div>
        </div>
      )}
    </dialog>
  );
}

function Advisors() {
  const ref = useReveal(0.1);
  const [shown, setShown] = useState(null);
  const opener = useRef(null);
  const open = (a, btn) => { opener.current = btn; setShown(a); };
  const close = () => { setShown(null); if (opener.current) opener.current.focus(); };
  return (
    <section className="sec abx-adv-sec" aria-labelledby="adv-h">
      <div className="wrap">
        <div className="p2-head">
          <span className="kick">Founder &amp; Advisors</span>
          <h2 className="h2" id="adv-h">Our Advisors</h2>
          <span className="script-tag st-blue">Guided by experience.</span>
        </div>
        <div className="abx-advs rv-stagger" ref={ref}>
          {ADVISORS.map((a, i) => <Advisor a={a} i={i} key={a.name} onOpen={open} />)}
        </div>
        <Profile a={shown} onClose={close} />
      </div>
    </section>
  );
}

function Partners() {
  return (
    <section className="partners2 abx-partners" aria-labelledby="ap-h">
      <div className="wrap">
        <div className="p2-head">
          <span className="kick">Our network</span>
          <h2 className="h2" id="ap-h">Our Trusted Partners</h2>
          <span className="script-tag st-amber">Better care, together.</span>
          <p className="lede">Comprehensive care across diabetes, lifestyle diseases, and general medicine.</p>
        </div>
        <Rail label="partners" className="logo-rail">
          {PARTNERS.map((p) => (
            <div className="lgo" key={p.name}>
              <img src={p.src} alt={p.name} loading="lazy" decoding="async" draggable={false} />
            </div>
          ))}
        </Rail>
      </div>
    </section>
  );
}

export default function About() {
  return (
    <div className="abx">
      <Guides />
      <Story />
      <Advisors />
      <Partners />
    </div>
  );
}
