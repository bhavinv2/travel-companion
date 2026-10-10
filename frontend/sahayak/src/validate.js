/* The checks every form on the page makes before it sends anything.
 *
 * Each returns the message to show, or '' when the value is fine -- so a form can collect them into
 * an errors object keyed by field and render each beside its own box. They mirror what
 * routes/sahayak.py refuses, so a form that passes here is not then turned back by the server.
 */

export const isBlank = (v) => !String(v ?? '').trim();

export function required(v, msg = 'This is required.') {
  return isBlank(v) ? msg : '';
}

/** A person's name: letters, spaces and the punctuation names carry. */
export function personName(v, label = 'your name') {
  const s = String(v ?? '').trim();
  if (!s) return `Please enter ${label}.`;
  if (s.length < 2) return 'That looks too short.';
  if (/[0-9@#$%^&*_=+<>{}[\]\\|/~`]/.test(s)) return 'Use letters only.';
  return '';
}

export function email(v, { optional = false } = {}) {
  const s = String(v ?? '').trim();
  if (!s) return optional ? '' : 'Please enter your e-mail.';
  return /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(s) ? '' : 'That e-mail address does not look right.';
}

/** An Indian PIN code: six digits, never starting with 0. */
export function pin(v, { optional = false } = {}) {
  const s = String(v ?? '').trim();
  if (!s) return optional ? '' : 'Please enter the PIN code.';
  return /^[1-9][0-9]{5}$/.test(s) ? '' : 'A PIN code is 6 digits and does not start with 0.';
}

export function minText(v, min, msg) {
  return String(v ?? '').trim().length < min ? msg : '';
}

export function intRange(v, lo, hi, msg, { optional = false } = {}) {
  const s = String(v ?? '').trim();
  if (!s) return optional ? '' : msg;
  if (!/^\d+$/.test(s)) return msg;
  const n = Number(s);
  return n >= lo && n <= hi ? '' : msg;
}

/** Errors with nothing in them are dropped, so `Object.keys(errs).length` means "something is wrong". */
export function collect(map) {
  const out = {};
  Object.entries(map).forEach(([k, msg]) => { if (msg) out[k] = msg; });
  return out;
}

/** Put the cursor in the first field that needs fixing, inside `root`. */
export function focusFirstError(root) {
  if (!root) return;
  const fld = root.querySelector('.fld.err, .chips-fld.err');
  if (!fld) return;
  fld.scrollIntoView({ block: 'center', behavior: 'smooth' });
  const el = fld.querySelector('input:not([type=file]),select,textarea,.chip,button');
  if (el) setTimeout(() => el.focus({ preventScroll: true }), 250);
}
