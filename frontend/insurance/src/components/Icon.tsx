interface IconProps {
  name: string;
  className?: string;
  rotate?: number;
  style?: React.CSSProperties;
}

export default function Icon({ name, className = 'ico', rotate, style }: IconProps) {
  const combinedStyle = rotate
    ? { ...style, transform: `rotate(${rotate}deg)` }
    : style;

  return (
    <svg className={className} style={combinedStyle} aria-hidden="true">
      <use href={`#${name}`} />
    </svg>
  );
}
