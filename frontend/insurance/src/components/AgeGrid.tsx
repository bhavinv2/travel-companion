interface AgeGridProps {
  count: number;
  prefix: string;
  values: string[];
  onChange: (index: number, value: string) => void;
  style?: React.CSSProperties;
}

export default function AgeGrid({ count, prefix, values, onChange, style }: AgeGridProps) {
  return (
    <div className="ages-g" style={style}>
      {Array.from({ length: count }, (_, i) => (
        <p className="fg" key={i}>
          <label className="tiny" htmlFor={`${prefix}${i + 1}`} style={{ display: 'block', marginBottom: 6 }}>
            Traveller {i + 1}
          </label>
          <input
            className="inp inp-s"
            id={`${prefix}${i + 1}`}
            type="number"
            min={0}
            max={110}
            inputMode="numeric"
            placeholder="Age"
            value={values[i] ?? ''}
            onChange={(e) => onChange(i, e.target.value)}
          />
        </p>
      ))}
    </div>
  );
}
