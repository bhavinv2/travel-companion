/* Who can join as a Sahayak: registered nurses, by one of three routes into nursing.
 *
 * Everything on the "Join as a Sahayak" side reads this -- the hero card's tabs, the "Who can join"
 * cards, the application form's choices -- so the page cannot offer a fourth kind of applicant in
 * one corner while the server (services/sahayak.QUALIFICATIONS) refuses it in another.
 *
 * `does` is the kind of assignment each is typically matched to. Every assignment is still matched
 * to the individual nurse's training and registration; this is a guide for the reader, not a rule.
 */
export const NURSING = [
  {
    key: 'B.Sc Nursing',
    full: 'Bachelor of Science in Nursing',
    length: '4-year degree',
    reg: 'Registered Nurse & Midwife (RN & RM)',
    c: '#1D7FC4',
    icon: 'grad',
    text: 'Degree-trained nurses who can take a visit from the first reading to the doctor’s review, and know when something needs escalating.',
    does: [
      'Full wellness screens — vitals, ECG, history and a medicines review',
      'Home sample collection for lab work',
      'Sitting in on online doctor consultations and hospital stays',
    ],
  },
  {
    key: 'GNM',
    full: 'General Nursing and Midwifery',
    length: '3-year diploma',
    reg: 'Registered Nurse & Midwife (RN & RM)',
    c: '#0F9D8C',
    icon: 'stethoscope',
    text: 'Diploma-trained nurses with ward experience — the checks, the readings and the calm a family needs on a hospital day.',
    does: [
      'Vitals checks and wellness screens at home',
      'Home sample collection for lab work',
      'Going with parents to clinic visits and hospital admissions',
    ],
  },
  {
    key: 'ANM',
    full: 'Auxiliary Nursing and Midwifery',
    length: '2-year diploma',
    reg: 'Registered ANM',
    c: '#7250D6',
    icon: 'heartBeat',
    text: 'Community-trained nurses who are at home in a family’s home — readings, medicines and keeping the record straight.',
    does: [
      'Vitals — BP, pulse, SpO₂, temperature and sugar',
      'Going through medicines and keeping health records up to date',
      'Going with parents to appointments and pharmacy pick-ups',
    ],
  },
];

export const nursingFor = (key) => NURSING.find((n) => n.key === key) || null;

/** What every applicant needs, whichever of the three they hold. */
export const ELIGIBILITY = [
  { icon: 'grad', title: 'B.Sc Nursing, GNM or ANM', text: 'From a nursing institution recognised by the Indian Nursing Council.' },
  { icon: 'shield', title: 'Current registration', text: 'With your State Nursing Council — we verify the number.' },
  { icon: 'phone', title: 'A smartphone', text: 'The Sahayak app guides each visit and records every step.' },
  { icon: 'home', title: 'Home visits near you', text: 'Assignments in your own city and the areas you choose.' },
];

/** The councils a registration can be with -- one per state, and Delhi. */
export const NURSING_COUNCILS = [
  'Andhra Pradesh', 'Arunachal Pradesh', 'Assam', 'Bihar', 'Chhattisgarh', 'Delhi', 'Goa', 'Gujarat',
  'Haryana', 'Himachal Pradesh', 'Jammu & Kashmir', 'Jharkhand', 'Karnataka', 'Kerala',
  'Madhya Pradesh', 'Maharashtra', 'Manipur', 'Meghalaya', 'Mizoram', 'Nagaland', 'Odisha', 'Punjab',
  'Rajasthan', 'Sikkim', 'Tamil Nadu', 'Telangana', 'Tripura', 'Uttar Pradesh', 'Uttarakhand',
  'West Bengal',
];
