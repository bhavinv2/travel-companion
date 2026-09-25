interface IconProps {
  name: string;
  className?: string;
  rotate?: number;
  style?: React.CSSProperties;
}

export default function Icon({ name, className = 'ico', rotate, style }: IconProps) {
  return (
    <svg className={className} style={style} aria-hidden="true">
      <use href={`#${name}`} transform={rotate ? `rotate(${rotate} 12 12)` : undefined} />
    </svg>
  );
}
