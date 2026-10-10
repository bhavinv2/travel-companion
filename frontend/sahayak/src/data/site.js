/* Everything the server decides, in one place.
 *
 * The Flask page renders a <script> that sets window.__SAHAYAK__ before the bundle loads, so
 * the service catalogue, the helpline numbers and the endpoints come from the admin screens
 * rather than from arrays baked into this build. Running `npm run dev` there is nothing to
 * inject and the fallbacks below are used, which is what lets the page be worked on standalone.
 *
 * The same arrangement as frontend/insurance/src/data/site.ts. Written as plain JS because
 * this app is JSX, not TypeScript.
 */

/** @type {{
 *   csrfToken?: string,
 *   bookingUrl?: string,
 *   applyUrl?: string,
 *   enquiryUrl?: string,
 *   services?: {key: string, name: string, blurb: string, price: string, duration: string}[],
 *   faqs?: {question: string, answer: string}[],
 *   phones?: {label: string, display: string, digits: string}[],
 *   supportEmail?: string,
 *   whatsapp?: string,
 *   waLink?: string,
 *   contactUrl?: string,
 *   phoneRules?: Object<string, number[]>,
 *   specializations?: {code: string, name: string, description: string}[],
 *   qualifications?: string[],
 * }} */
export const site = (typeof window !== 'undefined' && window.__SAHAYAK__) || {};

/** The specialisations a family may ask for when booking -- Preventia's list, handed over by the
 *  page. Empty when they could not be asked, and then the choice is simply not offered. */
export const specializations = () => (Array.isArray(site.specializations) ? site.specializations : []);

/** Who can join as a Sahayak: registered nurses with one of these. services/sahayak.QUALIFICATIONS
 *  is the list the server holds an application to; this fallback is only for `npm run dev`. */
export const QUALIFICATIONS = (site.qualifications && site.qualifications.length)
  ? site.qualifications : ['B.Sc Nursing', 'GNM', 'ANM'];

/** A published support line, or '' when staff have not set one. Never invented. */
export const helpline = () => (site.phones && site.phones[0]) || null;

/** The service catalogue, as one list for the whole page.
 *
 * Until now the page carried two: this one, which the server fills from Preventia (falling back
 * to the admin screen and then to shipped defaults), and the GIG_SERVICES array baked into the
 * bundle. The hero, the bento grid and the apply dropdown read the baked one while the booking
 * popup read this one, so the popup offered a different set of services from the section above
 * it. Everything that lists services should call this.
 *
 * `fallback` is what to use when the server injected nothing -- running `npm run dev` there is
 * no window.__SAHAYAK__ at all, and the page still has to render.
 */
export function catalogue(fallback = []) {
  if (site.services && site.services.length) return site.services;
  return fallback.map((g) => ({
    key: g.key,
    name: g.title || g.key,
    blurb: g.blurb || g.text || '',
    price: g.price || '',
    duration: g.duration || '',
    icon: g.icon || '',
  }));
}

/* What a visit covers, per service, from Preventia -- asked for one service at a time.
 *
 * Not handed over with the page: the upstream call is slow and its response large, and nine of
 * them cold is eleven seconds of a landing page nobody is looking at yet. So the page renders
 * the steps the bundle shipped with (the GIG sheet, which is where Preventia's own list came
 * from) and replaces them the moment the real ones arrive.
 *
 * Answers are kept for the life of the page: opening the same service twice should not ask
 * twice. A failure is cached as "nothing", so a service whose steps cannot be fetched is not
 * retried on every hover.
 */
const JOURNEYS = new Map();

export function journeyFor(key, onReady) {
  if (!key || !site.journeyUrl) return null;
  if (JOURNEYS.has(key)) return JOURNEYS.get(key);
  JOURNEYS.set(key, null);                       // in flight: do not ask again
  fetch(site.journeyUrl + '?service=' + encodeURIComponent(key))
    .then((r) => r.json())
    .then((b) => {
      const steps = (b && b.steps) || [];
      JOURNEYS.set(key, steps.length ? steps : []);
      if (steps.length && onReady) onReady(steps);
    })
    .catch(() => { JOURNEYS.set(key, []); });
  return null;
}

/** POST JSON to one of our endpoints with the CSRF token the page was rendered with.
 *
 * Returns the parsed body on success and throws an Error carrying the server's message
 * otherwise, so a caller can show what was actually wrong instead of "something went wrong".
 * Flask-WTF rejects a POST with no token, so a page opened before a restart fails loudly here
 * rather than appearing to save.
 */
export async function postJson(url, payload) {
  if (!url) throw new Error('This form is not connected yet.');
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': site.csrfToken || '' },
    body: JSON.stringify(payload),
  });
  let body = {};
  try {
    body = await r.json();
  } catch {
    /* a proxy error page rather than our JSON; the status is what matters */
  }
  if (!r.ok || body.success === false) {
    throw new Error(body.error || 'Sorry — that did not go through. Please try again.');
  }
  return body;
}
