import Icon from './Icon';

interface DecorIcon {
  name: string;
  side: 'left' | 'right';
  top: string;
  size?: number;
  rotate?: number;
  opacity?: number;
}

/**
 * Faint watermark-style icons placed in the empty gutters either side of the
 * centered content column — bare outline glyphs, no tile/background, sizes
 * varied so a couple read as large background shapes and others as small
 * accents (matching the reference site's scattered-icon treatment). Only
 * shows up once the viewport is wide enough for those gutters to actually
 * exist (see .side-decor CSS) — never competes with real content on normal
 * laptop/tablet widths.
 */
export default function SideDecor({ icons }: { icons: DecorIcon[] }) {
  return (
    <div className="side-decor" aria-hidden="true">
      {icons.map((d, i) => (
        <span
          key={i}
          className={`side-decor-ic ${d.side}`}
          style={{
            top: d.top,
            width: d.size ?? 46,
            height: d.size ?? 46,
            opacity: d.opacity,
            transform: d.rotate ? `rotate(${d.rotate}deg)` : undefined,
          }}
        >
          <Icon name={d.name} style={{ width: '100%', height: '100%' }} />
        </span>
      ))}
    </div>
  );
}
