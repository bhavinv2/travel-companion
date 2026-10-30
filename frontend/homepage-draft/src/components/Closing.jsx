import Icon from './Icon.jsx';
import { Brand } from './Nav.jsx';
import { site } from '../data/site.js';
import { useReveal, useScroll } from '../hooks.js';
import ctaPhoto from '../assets/photos/cta-care.jpg';
import coverUsa from '../assets/blog/travel-insurance-parents-usa.jpg';
import coverClaim from '../assets/blog/claim-process.jpg';
import coverAlone from '../assets/blog/parents-living-alone.jpg';

/* Blog, final call to action, footer and the floating buttons: the bottom of the page. */

/* The newest four posts published at nriparentservice.com/blog, linking to the live site.
 * Titles, dates and covers are the site's own (covers are each post's share image, resized);
 * the summary is the post's meta description where it has one, else the opening of its
 * excerpt. The site has no categories, so the label just names the post's subject. */
const BLOG_HOME = 'https://nriparentservice.com/blog/';
const POSTS = [
  { slug: 'how-to-buy-travel-insurance-for-parents-visiting-the-usa', label: 'Travel Insurance', date: 'October 9, 2026', img: coverUsa,
    title: 'How to Buy Travel Insurance for Parents Visiting the USA?',
    text: 'Learn how to buy travel insurance for parents visiting the USA, including coverage, benefits, costs, and tips for choosing the right plan.' },
  { slug: 'what-should-nris-know-before-booking-a-travel-insurance-for-their-parents', label: 'Travel Insurance', date: 'October 8, 2026', img: coverClaim,
    title: 'What Should NRIs Know Before Booking a Travel Insurance for Their Parents?',
    text: 'For NRIs, having parents visit them abroad is…' },
  { slug: 'how-does-the-travel-insurance-claim-process-work-what-you-should-know-before-you-need-it', label: 'Travel Insurance', date: 'October 7, 2026', img: coverClaim,
    title: 'How Does the Travel Insurance Claim Process Work? What You Should Know Before You Need It',
    text: 'Buying travel insurance is…' },
  { slug: 'what-is-the-best-way-to-support-parents-living-alone-in-india', label: 'Parent Care', date: 'October 6, 2026', img: coverAlone,
    title: 'What Is the Best Way to Support Parents Living Alone in India?',
    text: 'For many NRIs living in the USA, Canada,…' },
];

export function Blog() {
  const head = useReveal();
  const grid = useReveal(0.1);
  return (
    <section className="sec blog" id="resources" aria-labelledby="blog-h">
      <div className="wrap">
        <div className="sec-h rv-up" ref={head}>
          <div>
            <span className="kick">Insights</span>
            <h2 className="h2" id="blog-h">Helpful Resources for NRIs &amp; Their Parents</h2>
            <span className="script-tag st-amber">Guidance, made simple.</span>
            <p className="lede">Practical guidance on elderly care, healthcare, travel, wellness and supporting parents from abroad.</p>
          </div>
          <a className="btn btn-o" href={BLOG_HOME}>View All Blogs<Icon name="arrow" /></a>
        </div>
        {/* the "Why Choose" cards' format (.wgrid / .wcard), one row of four: the newest four
            posts; the rest are behind View All Blogs */}
        <div className="wgrid rv-stagger" ref={grid}>
          {POSTS.map((p, i) => (
            <a className="wcard wpost" href={`https://nriparentservice.com/${p.slug}/`} key={p.slug} style={{ '--d': `${i * 100}ms` }}>
              <img src={p.img} alt="" loading="lazy" decoding="async" />
              <span className="wtag">{p.label}</span>
              <div className="wbody">
                <h3>{p.title}</h3>
                <p><b>{p.date}</b> · {p.text}</p>
              </div>
            </a>
          ))}
        </div>
      </div>
    </section>
  );
}

/* The travel-insurance page's "Ready to Travel With More Confidence?" panel
 * (frontend/insurance/src/components/FinalCTA.tsx): same photo, scrim, flight path and layout,
 * with this page's words and links. */
export function FinalCTA({
  title = 'You May Be Miles Away. Your Care Doesn’t Have to Be.',
  lead = 'Give your parents the support they deserve, right here in India.',
  script = ['Their care,', 'our promise'],
}) {
  const box = useReveal();
  return (
    <section className="fcta-sec" id="book" aria-labelledby="final-h">
      <div className="wrap rv-up" ref={box}>
        <div className="fcta">
          <img className="fcta-bg" src={ctaPhoto} loading="lazy" decoding="async"
            alt="An elderly mother at home in India on a tablet video call, with her Sahayak beside her" />
          <span className="fcta-scrim" aria-hidden="true" />
          <svg className="fcta-path" viewBox="0 0 760 90" preserveAspectRatio="none" aria-hidden="true">
            <path d="M8 74 C 170 28, 330 14, 470 26" fill="none" stroke="#6B9BFF" strokeWidth="2.5"
              strokeLinecap="round" strokeDasharray="2 12" />
          </svg>
          <Icon name="plane" className="fcta-plane" />
          <Icon name="pin" className="fcta-pin" />
          <span className="fcta-script">{script[0]}<br />{script[1]}</span>
          <div className="fcta-copy">
            <h2 className="fcta-h" id="final-h">{title}</h2>
            <p className="fcta-lead">{lead}</p>
            <div className="fcta-btns">
              <a className="btn fcta-a" href={site.sahayakUrl}>Book a Sahayak</a>
              <a className="btn fcta-b" href={site.contactUrl}>Talk to Us</a>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

export function Footer() {
  const soc = [
    ['instagram', 'Instagram', 'https://www.instagram.com/'],
    ['facebook', 'Facebook', 'https://www.facebook.com/'],
    ['linkedin', 'LinkedIn', 'https://www.linkedin.com/'],
    ['youtube', 'YouTube', 'https://www.youtube.com/'],
  ];
  return (
    <footer className="foot" id="contact">
      <div className="wrap">
        <div className="foot-g">
          <div className="foot-about">
            <Brand />
            <p>Trusted support for your parents in India, coordinated for families living abroad.</p>
            <div className="soc">
              {soc.map(([ic, label, href]) => <a key={ic} href={href} aria-label={label}><Icon name={ic} stroke={1.9} /></a>)}
            </div>
          </div>
          <nav aria-labelledby="fq"><h3 id="fq">Quick Links</h3><ul>
            <li><a href="#top">Home</a></li>
            <li><a href="#services">Services</a></li>
            <li><a href="#why">Why Us</a></li>
            <li><a href="#reviews">Reviews</a></li>
            <li><a href={site.blogUrl}>Blogs</a></li>
            <li><a href={site.contactUrl}>Contact Us</a></li>
          </ul></nav>
          <nav aria-labelledby="fs"><h3 id="fs">Services</h3><ul>
            <li><a href={site.insuranceUrl}>Travel Insurance</a></li>
            <li><a href={site.companionUrl}>Travel Companion</a></li>
            <li><a href={site.sahayakUrl}>Sahayak</a></li>
            <li><a href="#ch-care">Virtual Doctor</a></li>
            <li><a href="#ch-health">Gift Health</a></li>
            <li><a href="#ch-health">Fit2Fly</a></li>
          </ul></nav>
          <div><h3>Contact</h3><ul>
            <li><span>Phone: [YOUR HELPLINE]</span></li>
            <li><span>Email: [YOUR SUPPORT EMAIL]</span></li>
            <li><span>WhatsApp: [YOUR NUMBER]</span></li>
            <li><a className="lnk" href={site.contactUrl}>Contact us<Icon name="arrow" /></a></li>
          </ul></div>
        </div>
        <div className="foot-b">
          <span><strong>NRI Parent Service</strong> — Powered by Preventia360</span>
          <span>© {new Date().getFullYear()} NRI Parent Service. All rights reserved.</span>
        </div>
      </div>
    </footer>
  );
}

/* Talk-to-us pill that appears after the hero, and a back-to-top button. */
export function Floaters() {
  const { y } = useScroll();
  const show = y > 600;
  return (
    <div className={`floaters${show ? ' show' : ''}`}>
      <a className="talk-fab" href={site.contactUrl} tabIndex={show ? 0 : -1}>
        <span className="ring" aria-hidden="true" /><Icon name="chat" /><span>Talk to Us</span>
      </a>
      <a className="top-fab" href="#top" aria-label="Back to top" tabIndex={show ? 0 : -1}><Icon name="up" /></a>
    </div>
  );
}

/* A slow ticker of what we're there for, between the hero and the services. */
export function Ticker() {
  const items = ['Every appointment', 'Every hospital visit', 'Every journey', 'Everyday need', 'Every time zone', 'Every update shared'];
  const set = (hidden) => (
    <div className="tk-set" aria-hidden={hidden || undefined}>
      {items.map((t) => <span key={t}><Icon name="sparkle" />{t}</span>)}
    </div>
  );
  return <div className="ticker"><div className="tk-track">{set(false)}{set(true)}</div></div>;
}
