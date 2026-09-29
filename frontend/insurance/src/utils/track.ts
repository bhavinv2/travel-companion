/* Google Ads conversions.
 *
 * The page fires four, and every one of them goes through here so that the rules are written
 * once instead of at four call sites:
 *
 *   - nothing is sent unless the SERVER said to. The labels arrive in window.__INSURANCE__ and
 *     are empty in tests, on localhost and anywhere GOOGLE_ADS_ID is unset, so `npm run dev` and
 *     the test suite report nothing.
 *   - nothing is sent unless gtag actually loaded. It is a third-party script on a page that
 *     works without it: ad blockers, a slow network and privacy settings all routinely stop it,
 *     and a TypeError inside a form submit would cost a real enquiry to record a fake one.
 *
 * A conversion means the thing happened, not that somebody clicked at it. Three of the four fire
 * after the server has confirmed the lead; the WhatsApp one fires on the click because opening
 * WhatsApp IS the event, and we never hear about it again.
 */
import { site } from '../data/site';

export type Conversion = 'quote' | 'popup_lead' | 'expert_form' | 'whatsapp';

export function track(action: Conversion): void {
  const sendTo = (site.conversions || {})[action];
  if (!sendTo) return;
  const gtag = (window as unknown as { gtag?: (...args: unknown[]) => void }).gtag;
  if (typeof gtag !== 'function') return;
  try {
    gtag('event', 'conversion', { send_to: sendTo });
  } catch {
    /* tracking must never be the reason a form stops working */
  }
}
