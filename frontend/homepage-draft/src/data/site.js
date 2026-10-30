/* Server-supplied links, injected by templates/homepage_draft/landing.html as window.__HOMEPAGE__.
 * The defaults are what `npm run dev` uses standalone. */
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
};
