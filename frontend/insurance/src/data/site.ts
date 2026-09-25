/* Everything the server decides, in one place.
 *
 * The Flask page renders a <script> that sets window.__INSURANCE__ before the bundle loads, so
 * testimonials, questions and the enquiry endpoint come from the admin screens rather than from
 * arrays baked into this build. Running `npm run dev` there is nothing to inject, so every
 * accessor falls back to what the component shipped with and the page still works standalone.
 */

export interface SiteReview {
  id?: string;
  quote: string;
  name: string;
  place?: string;
  cc?: string;
  tag?: string;
  photo?: string;
}

export interface SiteFaq {
  question: string;
  answer: string;
}

/** A support line staff have set, with the team that answers it. */
export interface SitePhone {
  /** the team's country, e.g. 'India' */
  label: string;
  /** as typed by staff, e.g. '+91 80191 11360' */
  display: string;
  /** digits only, which is what tel: and wa.me want */
  digits: string;
}

export interface SiteData {
  /** false when the page is embedded in the site's own header and footer */
  chrome?: boolean;
  reviews?: SiteReview[];
  reviewsAreSamples?: boolean;
  faqs?: SiteFaq[];
  /** absolute, already carries the app's URL prefix */
  enquiryUrl?: string;
  csrfToken?: string;
  whatsapp?: string;
  /** where static/insurance/ is served from, prefix included */
  assetBase?: string;
  /** our own quote endpoint; it calls the partner and records the lead */
  quoteUrl?: string;
  /** country name -> ISO-3, so the browser can speak the endpoint's language */
  countries?: Record<string, string>;
  supportEmail?: string;
  /** every support line staff have set; empty when none are, so nothing is published */
  supportPhones?: SitePhone[];
}

declare global {
  interface Window {
    __INSURANCE__?: SiteData;
  }
}

const data: SiteData = (typeof window !== 'undefined' && window.__INSURANCE__) || {};

export const site = data;

/** Server list when there is one, otherwise whatever the component ships with. */
export function fromServer<T>(given: T[] | undefined, fallback: T[]): T[] {
  return given && given.length ? given : fallback;
}

/** The page is embedded unless it explicitly says otherwise (dev server, standalone build). */
export const showChrome = data.chrome !== false;

/** Absolute URL for anything under public/ -- photos, partner logos, the logo mark.
 *
 * Vite rewrites imported assets against `base`, but these are plain runtime strings, so they
 * would resolve against the page URL instead. Under the app's URL prefix the page lives at
 * /travel-insurance while its assets live at <prefix>/static/insurance/ -- two different places,
 * so the base has to be applied by hand.
 */
export function asset(path: string): string {
  // The server knows the real prefix at request time; the build-time base is only a fallback for
  // the dev server. Baking it in means the bundle breaks on any deployment with a different
  // prefix -- and needs a rebuild to fix, which a template variable does not.
  const base = data.assetBase || import.meta.env.BASE_URL || '/';
  return base.replace(/\/$/, '') + '/' + path.replace(/^\//, '');
}

/** asset() for public/photos, which is where most of them live. */
export function photo(file: string): string {
  return asset('photos/' + file.replace(/^\/?(photos\/)?/, ''));
}
