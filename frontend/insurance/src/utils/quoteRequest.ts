/* Ask our own server for the partner quote, the way the travel-companion drawer already does.
 *
 * The page used to build a preventia360 URL in the browser and send people straight there. That
 * works, but the request exists nowhere afterwards: nobody can follow up with the person who
 * asked for a quote and never came back. POSTing to /api/insurance-quote instead means the
 * server calls the partner with the parameters we have verified against their widget, records
 * the lead in insurance_quotes, and hands back the URL to open.
 *
 * There is deliberately no client-side fallback. It used to fall back to buildPlanQuoteUrl on any
 * failure, which sent people to a DIFFERENT partner page -- /get-travel-insurance-quotes/, the
 * partner's own blank form -- rather than /retrieve-insurance-quotes/?id=..., the priced results
 * our endpoint produces. So a validation error or a bad minute did not show an error: it quietly
 * dropped somebody on a form they had already filled in, and lost the lead on the way. Saying
 * what went wrong and letting them try again is better on every count, and it is what the
 * travel-companion drawer has always done.
 */
import { SCHENGEN } from '../data/countries';
import { site } from '../data/site';

export type PlanKind = 'visitors' | 'health' | 'schengen';

/** ISO-3 for a country name, using the list the server sent. '' when we cannot map it. */
export function iso3(name?: string): string {
  if (!name) return '';
  return (site.countries || {})[name] || '';
}

/** Which of the three products this trip is, matching the server's own rules. */
export function planFor(destination: string, presection?: string): PlanKind {
  if (presection === 'visitorUSA' || destination === 'United States') return 'visitors';
  if (presection === 'schengen' || SCHENGEN.has(destination)) return 'schengen';
  return 'health';
}

export interface QuoteRequest {
  plan: PlanKind;
  start: string;
  end: string;
  citizenship: string;   // country NAME; mapped to ISO-3 here
  destination?: string;  // country NAME
  ages: string[];
  email: string;
  phone: string;
}

export interface QuoteResult {
  /** the partner's quote-results page, when we got one */
  url?: string;
  /** what to tell the visitor, when we did not */
  error?: string;
}

const GENERIC = 'We could not reach our insurance partner just now. Please try again in a moment.';

/** Ask the server to price this trip. Always resolves; never navigates on its own. */
export async function requestQuote(req: QuoteRequest): Promise<QuoteResult> {
  if (!site.quoteUrl) return { error: GENERIC };

  const citizenship = iso3(req.citizenship);
  const destination = iso3(req.destination);
  if (!citizenship) {
    return { error: 'Please choose the country of citizenship.' };
  }
  // Travel-medical is the only product priced for a specific country.
  if (req.plan === 'health' && !destination) {
    return { error: 'Please choose the country being travelled to.' };
  }

  const body: Record<string, unknown> = {
    insurance_type: req.plan,
    start_date: req.start,
    end_date: req.end,
    citizenship,
    travellers: req.ages.filter(Boolean).map((age) => ({ age })),
    email: req.email,
    phone: req.phone,
  };
  if (req.plan === 'health') body.destination = destination;

  try {
    const res = await fetch(site.quoteUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(site.csrfToken ? { 'X-CSRFToken': site.csrfToken } : {}),
      },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => null);
    if (data && data.success && data.url) return { url: data.url as string };
    return { error: (data && data.error) || GENERIC };
  } catch {
    return { error: GENERIC };
  }
}

/** Hand the visitor their quotes without losing our page, exactly as the companion drawer does.
 *  Returns false if the browser blocked the new tab, so the caller can show the link instead. */
export function openQuotes(url: string): boolean {
  const w = window.open(url, '_blank', 'noopener');
  return !!w;
}
