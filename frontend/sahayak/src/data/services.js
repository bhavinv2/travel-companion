import imgWellness from '../assets/services/wellness.jpg';
import imgLab from '../assets/services/lab.jpg';
import imgVitals from '../assets/services/vitals.jpg';
import imgOutpatient from '../assets/services/outpatient.jpg';
import imgInpatient from '../assets/services/inpatient.jpg';
import imgPharmacy from '../assets/services/pharmacy.jpg';
// Demo, online consultation and "other" are panels of the care-ecosystem picture the hero uses
// (frontend/sahayak/design/), so the three photographs sit in the same family as the rest.
import imgDemo from '../assets/services/demo.jpg';
import imgVirtual from '../assets/services/virtual-consult.jpg';
import imgOther from '../assets/services/other.jpg';

// Sahayak gig services, taken from the GIG sheet of "All forms preventia.xlsx".
// Each service's `includes` lists the visit steps the sheet marks Mandatory (MAD) for that column;
// `optional` lists the ones marked Optional (OPT). Check-in and check-out are MAD for every service.
//
// Sheet section → label used here: Wellness Questionary → Wellness questionnaire; Customer digilization → App set-up
// for your parents; Health Records → Health records; Medicines → Medicines review; Drop to location → Drop to …
// Verified against every collapsed (+) group of the GIG sheet, rows 3–217.
//
// Booking ("Pre") fields from the sheet: Patient, Appointment date, Appointment time, MeetUp location,
// Drop location (only some services), Is this a follow-up, Attach document.
// `drop` is 'required' where the sheet's "Drop to location" step is MAD, 'optional' where it is OPT,
// 'yes' where only the booking row asks for it, and absent where it doesn't apply.


// Visit journey shown in "What it covers": one stop per GIG-sheet section, in sheet order.
// A trailing "?" marks a section the sheet flags Optional (OPT) for that service; others are Mandatory (MAD).
const STEPS = {
  booking: { title: 'Booking', text: 'You pick the service and where the Sahayak should meet your parent; we call to agree the time.' },
  checkin: { title: 'Check-in', text: 'Your Sahayak checks in on arrival — time and location recorded.' },
  wq: { title: 'Wellness questionnaire', text: 'Health history, lifestyle, allergies and current symptoms.' },
  vitals: { title: 'Vitals', text: 'BP, pulse, SpO₂, temperature, sugar, breathing rate, weight and BMI.' },
  blood: { title: 'Blood work', text: 'Pre- or post-meal blood tests, as advised.' },
  urine: { title: 'Urine test', text: 'Urine tests where they are needed.' },
  ecg: { title: 'ECG', text: 'A quick ECG reading during the visit.' },
  digital: { title: 'App set-up', text: 'Help your parents use the app for bookings, records and payments.' },
  clinical: { title: 'Clinical history', text: 'Complaints, past illnesses, surgeries, allergies and family history.' },
  meds: { title: 'Medicines', text: 'Medicine names, doses and schedule recorded.' },
  records: { title: 'Health records', text: 'Prescriptions, lab reports and visit notes saved for you.' },
  drop: { title: 'Drop to location', text: 'Your parent is taken to the hospital, clinic or chosen place.' },
  checkout: { title: 'Check-out', text: 'Visit closed with time and location — and a summary shared with you.' },
  sample: { title: 'Sample submission', text: 'Samples handed to the lab, with the time recorded.' },
  rating: { title: 'Your feedback', text: 'Rate the visit and tell us how it went.' },
};
const journey = (spec) =>
  spec.split(' ').map((t) => {
    const key = t.replace('?', '');
    return { key, ...STEPS[key], optional: t.endsWith('?') };
  });
const JOURNEYS = {
  'Wellness Screen': journey('booking checkin wq vitals blood urine ecg digital clinical meds records checkout rating?'),
  'Lab Work': journey('booking checkin blood? urine? ecg? digital? meds? records? checkout sample rating?'),
  Vitals: journey('booking checkin wq? vitals digital? clinical? meds? records? checkout rating?'),
  'Out-Patient Visit': journey('booking checkin digital? meds? records? drop checkout rating?'),
  'In-Patient Visit': journey('booking checkin digital? meds? records? drop checkout rating?'),
  'Pharmacy Delivery': journey('booking checkin digital? meds? records? checkout rating?'),
  'Demo Visit': journey('booking checkin wq vitals digital? clinical meds records checkout rating?'),
  'Virtual Consultation Support': journey('booking checkin wq vitals? digital? clinical? meds? records? checkout rating?'),
  Other: journey('booking checkin wq vitals? blood? urine? ecg? digital? clinical? meds? records? drop? checkout sample? rating?'),
};

export const GIG_SERVICES = [
  {
    key: 'Wellness Screen',
    title: 'Wellness Screen',
    tag: 'At home',
    icon: 'pulse',
    // wide photo: fill the card; people and the full kit sit in the middle of the frame
    img: imgWellness, imgFit: 'cover', imgPos: '30% 50%',
    sc: '#2F5BEA', st: '#E3EAFD',
    text: 'A complete at-home health check, with results added to your parents’ health records.',
    includes: ['Wellness questionnaire', 'Full vitals', 'Blood & urine tests', 'ECG', 'Clinical history', 'Medicines review', 'Health records updated', 'App set-up for your parents'],
    optional: [],
  },
  {
    key: 'Lab Work',
    title: 'Lab Work',
    tag: 'Home or lab',
    icon: 'tube',
    // wide photo: fill the card, anchored right so the Sahayak, patient and kit stay in view
    img: imgLab, imgFit: 'cover', imgPos: '100% 50%',
    sc: '#C02A5E', st: '#FBE2EB',
    text: 'Samples collected at home and submitted to the lab, so your parents skip the queue.',
    includes: ['Sample collection', 'Submission to the lab'],
    optional: ['Blood tests', 'Urine tests', 'ECG', 'Medicines review', 'Health records'],
  },
  {
    key: 'Vitals',
    title: 'Vitals Check',
    tag: 'At home',
    icon: 'heartBeat',
    // wide photo: fill the card, anchored right so the Sahayak, patient and devices stay in view
    img: imgVitals, imgFit: 'cover', imgPos: '100% 50%',
    sc: '#0E7C70', st: '#DAF2EE',
    text: 'BP, pulse, oxygen, temperature, sugar, breathing rate, weight and BMI — recorded and shared with you.',
    includes: ['BP, pulse & SpO₂', 'Temperature & sugar', 'Weight & BMI'],
    optional: ['Wellness questionnaire', 'Clinical history', 'Medicines review', 'Health records'],
  },
  {
    key: 'Out-Patient Visit',
    title: 'Out-Patient Visit',
    tag: 'Clinic visit',
    icon: 'stethoscope',
    // wide photo: fill the card, centred on the Sahayak walking the father to his consultation
    img: imgOutpatient, imgFit: 'cover', imgPos: '56% 30%',
    sc: '#6D45CF', st: '#EDE6FB',
    text: 'Your Sahayak picks your parents up, goes with them to the doctor and brings them home.',
    includes: ['Pick-up from home', 'Drop to hospital or clinic'],
    optional: ['Medicines'],
    drop: 'required',
  },
  {
    key: 'In-Patient Visit',
    title: 'In-Patient Visit',
    tag: 'Hospital',
    icon: 'hospital',
    // 4-panel collage: fit the whole image so no panel is cut; edges take its top/bottom tones
    img: imgInpatient,
    imgBg: 'linear-gradient(180deg,#B0B8BA,#5C6668)',
    sc: '#B8520E', st: '#FDE9D8',
    text: 'Support when your parents are admitted — accompanying them to the hospital and staying close.',
    includes: ['Pick-up from home', 'Drop to hospital'],
    optional: ['Medicines'],
    drop: 'required',
  },
  {
    key: 'Pharmacy Delivery',
    title: 'Pharmacy Delivery',
    tag: 'On the go',
    icon: 'pill',
    // wide photo: fill the card, centred on the doorstep hand-over of the medicine bag
    img: imgPharmacy, imgFit: 'cover', imgPos: '52% 30%',
    sc: '#1D6FA3', st: '#DDEFFA',
    text: 'Medicines collected from the pharmacy and delivered to your parents’ door.',
    includes: ['Pharmacy pick-up', 'Doorstep delivery'],
    optional: ['Medicines review'],
    drop: 'yes',
  },
  {
    key: 'Demo Visit',
    title: 'Demo Visit',
    tag: 'First visit',
    icon: 'personPlus',
    // the Sahayak and a father going through his records on a tablet
    img: imgDemo, imgFit: 'cover', imgPos: '30% 40%',
    sc: '#23804A', st: '#DDF2E5',
    text: 'A first visit to get to know your parents: health questionnaire, vitals, history and medicines.',
    includes: ['Wellness questionnaire', 'Vitals', 'Clinical history', 'Medicines review', 'Health records set up'],
    optional: ['App set-up for your parents'],
  },
  {
    key: 'Virtual Consultation Support',
    title: 'Virtual Consultation Support',
    tag: 'Online doctor',
    icon: 'video',
    // a doctor on a video call, the mother in the corner of the screen
    img: imgVirtual, imgFit: 'cover', imgPos: '40% 30%',
    sc: '#0B7A6D', st: '#E1F5F2',
    text: 'Your Sahayak sits with your parents during an online doctor consultation and helps it run smoothly.',
    includes: ['Wellness questionnaire', 'Call set-up & support'],
    optional: ['Vitals', 'Clinical history', 'Medicines'],
  },
  {
    key: 'Other',
    title: 'Other Support',
    tag: 'Anything else',
    icon: 'plusCircle',
    // a Sahayak helping a mother with her exercises
    img: imgOther, imgFit: 'cover', imgPos: '45% 35%',
    sc: '#B23A1C', st: '#FDE3DB',
    text: 'Something else your parents need? Tell us and we’ll plan the visit around it.',
    includes: ['Wellness questionnaire', 'Planned around your request'],
    optional: ['Vitals', 'Lab tests & ECG', 'Sample submission', 'Drop location'],
    drop: 'optional',
  },
];

GIG_SERVICES.forEach((g) => { g.journey = JOURNEYS[g.key]; });

export const SERVICE_KEYS = GIG_SERVICES.map((s) => s.key);
export const serviceByKey = (k) => GIG_SERVICES.find((s) => s.key === k);

/* Preventia's category codes, matched back to the rows of the GIG sheet above.
 *
 * The API names the categories and prices them but carries nothing about what a visit
 * actually covers -- that lives only in the sheet. Most codes line up once punctuation is
 * flattened (OUT_PATIENT_VISIT -> out_patient_visit -> 'Out-Patient Visit'); two do not, so
 * the match cannot be purely mechanical.
 */
const slug = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_+$/g, '');
const SLUG_ALIASES = {
  demo: 'demo_visit',
  virtual_consult_support: 'virtual_consultation_support',
};
const BY_SLUG = {};
GIG_SERVICES.forEach((s) => { BY_SLUG[slug(s.key)] = s; });

/** The GIG-sheet entry for a catalogue key, or null if we have nothing for it. */
export function gigFor(key) {
  const k = slug(key);
  return BY_SLUG[SLUG_ALIASES[k] || k] || null;
}
