import { Doodles, Side, Snap, Trail } from './Deco.jsx';
import sideAirport from '../assets/photos/tc-l1.jpg';
import Icon from './Icon.jsx';
import { Brand } from './Nav.jsx';
import { site, talk, TALK } from '../data/site.js';
import { useReveal, useScroll } from '../hooks.js';
import ctaPhoto from '../assets/photos/cta-care.jpg';
import snapAbroad from '../assets/photos/tc-l5.jpg';
import coverUsa from '../assets/blog/travel-insurance-parents-usa.jpg';
import coverClaim from '../assets/blog/claim-process.jpg';
import coverAlone from '../assets/blog/parents-living-alone.jpg';

/* Blog, final call to action, footer and the floating buttons: the bottom of the page. */

/* The newest four posts on nriparentservice.com/blog, as WordPress lists them now (the server
 * asks it: services/wp_blog.py). POSTS is what the page shows when WordPress cannot be asked --
 * the four newest when this page was built, with their own titles, dates and covers. The site
 * has no categories, so the label just names the post's subject. */
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

const FALLBACK = POSTS.map((p) => ({ ...p, url: `https://nriparentservice.com/${p.slug}/`, summary: p.text }));

export function Blog() {
  const head = useReveal();
  const grid = useReveal(0.1);
  const posts = site.posts.length ? site.posts : FALLBACK;
  return (
    <section className="sc sc-cream blog" id="resources" aria-labelledby="blog-h">
      <Side img={sideAirport} shape="circle" top="24%" tint="#2446B8"
        icons={[['mail', '#2446B8'], ['globe', '#0F9D8C'], ['sparkle', '#C98A12'], ['plane', '#E4613F']]} />
      <Doodles items={[['globe', { top: '8%', right: '3%', size: 32, rotate: 10 }]]} />
      <Trail at={{ top: '70px', right: 'max(200px, calc(50% - 420px))' }} width={170} />
      <div className="wrap">
        <div className="sec-h rv-up" ref={head}>
          <div>
            <span className="kick">Insights</span>
            <h2 className="h2" id="blog-h">Helpful Resources for NRIs &amp; <em>Their Parents</em></h2>
            <span className="script-tag">Guidance, made simple.</span>
            <p className="lede">Practical guidance on elderly care, healthcare, travel, wellness and supporting parents from abroad.</p>
          </div>
          <a className="btn btn-o" href={BLOG_HOME}>View All Blogs</a>
        </div>
        {/* the "Why Choose" cards' format (.wgrid / .wcard), one row of four: the newest four
            posts; the rest are behind View All Blogs */}
        <div className="wgrid rv-stagger" ref={grid}>
          {posts.map((p, i) => (
            <a className="wcard wpost" href={p.url} key={p.url} style={{ '--d': `${i * 100}ms` }}>
              {p.img ? <img src={p.img} alt="" loading="lazy" decoding="async" /> : <span className="wpost-noimg" aria-hidden="true" />}
              <span className="wtag">{p.label}</span>
              <div className="wbody">
                <h3>{p.title}</h3>
                <p>{p.date && <b>{p.date}</b>}{p.date && p.summary ? ' · ' : ''}{p.summary}</p>
              </div>
            </a>
          ))}
        </div>
      </div>
    </section>
  );
}

/* The last word: one compact band -- the photo of a mother and her Sahayak, the promise, the two
 * actions -- with a flight path from a snapshot of where you are to the photo of where they are. */
export function FinalCTA({
  title = 'You May Be Miles Away. Your Care Doesn’t Have to Be.',
  lead = 'Give your parents the support they deserve, right here in India.',
  script = ['Their care,', 'our promise'],
}) {
  const box = useReveal();
  return (
    <section className="fcta2-sec" id="book" aria-labelledby="final-h">
      <div className="wrap rv-up" ref={box}>
        <div className="fcta2">
          <Snap src={snapAbroad} caption="You, abroad" at={{ top: '-56px', right: '-40px' }} rotate={7} width={96} tone="amber" />
          <Trail at={{ top: '-40px', right: '96px' }} width={260} flip />
          <div className="fcta2-ph">
            <img src={ctaPhoto} loading="lazy" decoding="async"
              alt="An elderly mother at home in India on a tablet video call, with her Sahayak beside her" />
          </div>
          <div className="fcta2-copy">
            <span className="fcta2-script">{script[0]} {script[1]}</span>
            <h2 className="fcta2-h" id="final-h">{title}</h2>
            <p className="fcta2-lead">{lead}</p>
          </div>
          <div className="fcta2-btns">
            <a className="btn fcta-a" href={site.contactUrl} onClick={talk}>{TALK}</a>
            <a className="btn fcta-b" href={site.sahayakUrl}>Book a Sahayak</a>
          </div>
        </div>
      </div>
    </section>
  );
}

/* Only drawn by `npm run dev` on its own: inside the site, base.html's footer is the page's. */
export function Footer() {
  return (
    <footer className="foot" id="contact">
      <div className="wrap">
        <div className="foot-g">
          <div className="foot-about">
            <Brand />
            <p>Support for your parents in India, coordinated for families living abroad.</p>
          </div>
          <nav aria-labelledby="fq"><h3 id="fq">Quick Links</h3><ul>
            <li><a href="#top">Home</a></li>
            <li><a href="#how">How It Works</a></li>
            <li><a href="#why">Why Us</a></li>
            {site.reviews.length > 0 && <li><a href="#reviews">Reviews</a></li>}
            <li><a href={site.blogUrl}>Blogs</a></li>
            <li><a href={site.contactUrl}>Contact Us</a></li>
          </ul></nav>
          <nav aria-labelledby="fs"><h3 id="fs">Services</h3><ul>
            <li><a href={site.insuranceUrl}>Travel Insurance</a></li>
            <li><a href={site.companionUrl}>Travel Companion</a></li>
            <li><a href={site.sahayakUrl}>Sahayak</a></li>
            <li><a href="#health">Virtual Doctor</a></li>
            <li><a href="#health">Gift Health</a></li>
            <li><a href="#health">Fit2Fly</a></li>
          </ul></nav>
          <div><h3>Contact</h3><ul>
            {site.phones.map((p) => <li key={p.digits}><a href={`tel:+${p.digits}`}>{p.label}: {p.display}</a></li>)}
            {site.email && <li><a href={`mailto:${site.email}`}>{site.email}</a></li>}
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

/* A back-to-top button once the hero is passed. Talking to us is the site's own chat bubble,
 * in the other corner -- a second chat button here only split the choice. */
export function Floaters() {
  const { y } = useScroll();
  const show = y > 600;
  return (
    <div className={`floaters${show ? ' show' : ''}`}>
      <a className="top-fab" href="#top" aria-label="Back to top" tabIndex={show ? 0 : -1}><Icon name="up" /></a>
    </div>
  );
}
