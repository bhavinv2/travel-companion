import { SCHENGEN } from '../data/countries';
import type { QuoteForm } from '../context/QuoteContext';

export const QUOTE_URL = 'https://preventia360.brokersnexus.com/get-travel-insurance-quotes/';

const SECTIONS = {
  usa: 'visitorUSA',
  outside: 'travelOutsideUSA',
  schengen: 'schengen',
  study: 'studyAbroad',
  group: 'groupTravelMedical',
};

function presectionFor(dest: string, purpose: string, count: number) {
  if (dest === 'United States') return SECTIONS.usa;
  if (SCHENGEN.has(dest)) return SECTIONS.schengen;
  if (purpose === 'Study') return SECTIONS.study;
  if (count >= 5) return SECTIONS.group;
  return SECTIONS.outside;
}

export interface PlanQuoteInput {
  presection: string;
  start: string;
  end: string;
  citizenship: string;
  destination?: string;
  ages: string[];
  email: string;
  phone: string;
}

/** Used by the plan-type quote form (Visitors / Travel Medical / Schengen). */
export function buildPlanQuoteUrl(input: PlanQuoteInput): string {
  const q: string[] = [];
  const add = (k: string, v: string) => {
    if (v) q.push(`${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
  };
  const ages = input.ages.filter(Boolean);
  add('presection', input.presection);
  add('start_date', input.start);
  add('end_date', input.end);
  add('citizenship', input.citizenship);
  if (input.destination) add('destination', input.destination);
  add('travellers', String(input.ages.length));
  add('ages', ages.join(','));
  add('email', input.email);
  add('phone', input.phone);
  add('utm_source', 'landing-page');
  return `${QUOTE_URL}${q.length ? `?${q.join('&')}` : ''}`;
}

export function buildQuoteUrl(form: QuoteForm): string {
  const q: string[] = [];
  const add = (k: string, v: string | number) => {
    if (v) q.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  };
  add('presection', presectionFor(form.destination, form.purpose, form.travellers));
  add('destination', form.destination);
  add('start_date', form.start);
  add('end_date', form.end);
  add('travellers', form.travellers);
  add('ages', form.ages.slice(0, form.travellers).filter(Boolean).join(','));
  add('citizenship', form.citizenship);
  add('residence', form.residence);
  add('name', form.name);
  add('email', form.email);
  add('phone', form.phone ? `${form.dial} ${form.phone}`.trim() : '');
  add('purpose', form.purpose);
  add('pre_existing', form.preExisting);
  add('utm_source', 'landing-page');
  return `${QUOTE_URL}${q.length ? `?${q.join('&')}` : ''}`;
}
