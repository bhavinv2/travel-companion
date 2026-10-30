/* Server-supplied links and content, injected by templates/homepage_draft/landing.html as
 * window.__HOMEPAGE__. The defaults are what `npm run dev` uses standalone. The content lists
 * (reviews, questions, posts) may be empty: their sections then do not show. */
const injected = (typeof window !== 'undefined' && window.__HOMEPAGE__) || {};

export const site = {
  // false when the page sits inside base.html, which already draws the site header and footer
  chrome: injected.chrome !== false,
  // which page to draw; standalone `npm run dev` shows /?page=about for the About page
  page: injected.page || new URLSearchParams(window.location.search).get('page') || 'home',
  homeUrl: injected.homeUrl || '/',
  aboutUrl: injected.aboutUrl || '/?page=about',
  contactUrl: injected.contactUrl || '/contact-us',
  insuranceUrl: injected.insuranceUrl || '/travel-insurance',
  sahayakUrl: injected.sahayakUrl || '/sahayak',
  companionUrl: injected.companionUrl || '/',
  blogUrl: injected.blogUrl || '/blog',
  helpUrl: injected.helpUrl || '/help',
  // the services' own pages on the group's other site
  doctorUrl: injected.doctorUrl || 'https://preventia360.com/call-on-doc/',
  giftUrl: injected.giftUrl || 'https://preventia360.com/gift-health/',
  fitUrl: injected.fitUrl || 'https://preventia360.com/fit2fly/',
  // approved reviews: {quote, rating, name, photo, service}
  reviews: injected.reviews || [],
  // the Help centre's questions: {question, answer}
  faqs: injected.faqs || [],
  // {sahayak: '₹149', insurance: 'From …'}: each '' until known
  prices: injected.prices || {},
  // the WordPress blog's newest posts: {title, url, date, summary, img, label}
  posts: injected.posts || [],
  // the published numbers ({label, display, digits}) and address
  phones: injected.phones || [],
  email: injected.email || '',
};

/* "Talk to a Care Advisor": the site's live chat when it is on the page (static/js/live-chat.js),
 * else the link goes where it points (the contact page). */
export function talk(e) {
  if (window.liveChat && typeof window.liveChat.open === 'function') {
    e.preventDefault();
    window.liveChat.open();
  }
}

export const TALK = 'Talk to a Care Advisor';

/* A page on another site (a full address: the group's Call-ON-Doc, Gift Health and Fit2Fly pages)
 * opens in a new tab, as the site's own menu opens them; this app's pages (paths) open in place. */
export function away(href) {
  return /^https?:\/\//.test(href || '') ? { target: '_blank', rel: 'noopener' } : {};
}
