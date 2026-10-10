/** A phone number as a person should read it in text that never reaches the server -- the
 *  pre-filled WhatsApp message a lead form opens. Everything that IS sent goes as the number and
 *  its country apart (`phone` + `phone_cc`), and services/phone.py normalises that pair.
 *
 *  Only two things are done here, both so the message matches what the server would store:
 *  a + typed into the box wins over the picker, and a national trunk 0 is dropped -- "+46
 *  0764498115" is not a number anybody can ring. */
export function spokenNumber(dial: string, tel: string): string {
  const t = (tel || '').trim();
  if (!t) return '';
  if (t.startsWith('+')) return t;
  return `${dial} ${t.replace(/^0+/, '')}`.trim();
}
