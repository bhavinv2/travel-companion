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

export function DialSelect({
  id,
  value,
  onChange,
  className = 'inp',
}: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  className?: string;
}) {
  return (
    <select id={id} className={className} value={value} onChange={(e) => onChange(e.target.value)} aria-label="Country code">
      {sorted.map((c) => (
        <option key={c.iso} value={`+${c.dial}`}>
          {flagEmoji(c.iso)} +{c.dial}
        </option>
      ))}
    </select>
  );
}
