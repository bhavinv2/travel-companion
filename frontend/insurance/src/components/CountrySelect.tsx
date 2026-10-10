import { COUNTRIES, flagEmoji } from '../data/countries';

interface CountrySelectProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  className?: string;
  required?: boolean;
  placeholder?: string;
  'aria-label'?: string;
}

const sorted = [...COUNTRIES].sort((a, b) => a.name.localeCompare(b.name));

export default function CountrySelect({
  id,
  value,
  onChange,
  className = 'inp',
  required,
  placeholder = 'Select a country',
  ...rest
}: CountrySelectProps) {
  return (
    <select
      id={id}
      className={className}
      value={value}
      required={required}
      onChange={(e) => onChange(e.target.value)}
      {...rest}
    >
      <option value="">{placeholder}</option>
      {sorted.map((c) => (
        <option key={c.iso} value={c.name}>
          {flagEmoji(c.iso)} {c.name}
        </option>
      ))}
    </select>
  );
}

/** The dialling-code picker. Its value is the COUNTRY (an ISO code such as "IN"), not the code:
 *  +1 is the US, Canada and a dozen islands, so options keyed by "+1" all shared one value and a
 *  visitor who picked the United States saw Canada when the form redrew. The form sends this ISO
 *  as `phone_cc` beside the number, and the server does the rest. */
export function DialSelect({
  id,
  value,
  onChange,
  className = 'inp',
}: {
  id?: string;
  value: string;
  onChange: (iso: string) => void;
  className?: string;
}) {
  return (
    <select id={id} className={className} value={value} onChange={(e) => onChange(e.target.value)} aria-label="Country code">
      {sorted.map((c) => (
        <option key={c.iso} value={c.iso}>
          {flagEmoji(c.iso)} +{c.dial}
        </option>
      ))}
    </select>
  );
}
