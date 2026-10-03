/* GENERATED from "All forms preventia.xlsx", sheet GIG -- do not hand-edit.
 * Regenerate with scratchpad/gen_needs.py when the sheet changes.
 *
 * What each service actually includes, and how strongly: 'MAD' where the sheet marks the
 * functionality Mandatory for that service, 'OPT' where it marks it Optional, absent where
 * the service does not do it at all. The questionnaire scores a person's answers against
 * this, so a recommendation can say which of their answers it is based on.
 *
 * Rows that are identical for all nine services -- booking, check-in, check-out, the rating
 * -- are left out: they cannot tell two services apart.
 */

/** The things a family might ask for, in their words, keyed to the sheet's rows. */
export const NEEDS = [
  { key: 'vitals', label: 'Basic readings taken', hint: 'BP, pulse, sugar, temperature, weight' },
  { key: 'blood', label: 'A blood sample', hint: 'Collected at home' },
  { key: 'urine', label: 'A urine sample', hint: 'Collected at home' },
  { key: 'ecg', label: 'An ECG', hint: 'Taken at home on a portable machine' },
  { key: 'lab', label: 'Samples taken to a lab', hint: 'Handed over and logged' },
  { key: 'wellness', label: 'A full health questionnaire', hint: 'History, lifestyle, allergies, symptoms' },
  { key: 'history', label: 'Medical history written up', hint: 'Complaints, past illness, surgery, family history' },
  { key: 'medicines', label: 'Their medicines gone through', hint: 'What is prescribed and taken' },
  { key: 'records', label: 'Reports kept on file', hint: 'Prescriptions and results saved for you to read' },
  { key: 'escort', label: 'Taken somewhere and brought back', hint: 'A clinic, a hospital or a lab' },
  { key: 'app', label: 'Help using the app', hint: 'So your parents can book and see records themselves' },
]
  .map((n) => ({ ...n }));

/** service key -> { need key: 'MAD' | 'OPT' }. Anything absent, the service does not do. */
export const INCLUDES = {
  wellness_screen: { vitals: 'MAD', blood: 'MAD', urine: 'MAD', ecg: 'MAD', wellness: 'MAD', history: 'MAD', medicines: 'MAD', records: 'MAD', app: 'MAD' },
  lab_work: { blood: 'OPT', urine: 'OPT', ecg: 'OPT', lab: 'MAD', medicines: 'OPT', records: 'OPT', app: 'OPT' },
  vitals: { vitals: 'MAD', wellness: 'OPT', history: 'OPT', medicines: 'OPT', records: 'OPT', app: 'OPT' },
  out_patient_visit: { medicines: 'OPT', records: 'OPT', escort: 'MAD', app: 'OPT' },
  in_patient_visit: { medicines: 'OPT', records: 'OPT', escort: 'MAD', app: 'OPT' },
  pharmacy_delivery: { medicines: 'OPT', records: 'OPT', app: 'OPT' },
  demo: { vitals: 'MAD', wellness: 'MAD', history: 'MAD', medicines: 'MAD', records: 'MAD', app: 'OPT' },
  virtual_consult_support: { vitals: 'OPT', wellness: 'MAD', history: 'OPT', medicines: 'OPT', records: 'OPT', app: 'OPT' },
  other: { vitals: 'OPT', blood: 'OPT', urine: 'OPT', ecg: 'OPT', lab: 'OPT', wellness: 'MAD', history: 'OPT', medicines: 'OPT', records: 'OPT', escort: 'OPT', app: 'OPT' },
};
