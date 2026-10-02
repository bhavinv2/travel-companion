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
 * }} */
export const site = (typeof window !== 'undefined' && window.__SAHAYAK__) || {};

/** A published support line, or '' when staff have not set one. Never invented. */
export const helpline = () => (site.phones && site.phones[0]) || null;

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
