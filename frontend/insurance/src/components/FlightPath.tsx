interface FlightPathProps {
  side: 'left' | 'right';
  top: string;
}

/**
 * A faint dashed flight-route curve with a small plane riding along it —
 * the decorative "route" motif from the reference site's side margins.
 */
export default function FlightPath({ side, top }: FlightPathProps) {
  return (
    <div className={`flight-path ${side}`} style={{ top }} aria-hidden="true">
      <svg viewBox="0 0 160 220" width="160" height="220" fill="none">
        <path
          d="M14 8C36 60 8 120 46 150C74 172 108 168 146 210"
          stroke="var(--horizon)"
          strokeWidth="2"
          strokeDasharray="1.5 9"
          strokeLinecap="round"
        />
        <circle cx="14" cy="8" r="3" fill="var(--horizon)" />
        <g transform="translate(146,210) rotate(50)">
          <use
            href="#i-plane"
            width="24"
            height="24"
            x="-12"
            y="-12"
            stroke="var(--horizon)"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </g>
      </svg>
    </div>
  );
}
