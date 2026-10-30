import Icon from './Icon.jsx';
import { useDragRail } from '../hooks.js';

/* The travel-insurance page's carousel: a drag-to-scroll rail between two round side arrows,
 * each greyed out at its end. Partners and reviews both use it. */
export default function Rail({ label, className = '', children }) {
  const { railProps, scrollRail, canScrollLeft, canScrollRight } = useDragRail();
  return (
    <div className="rail-wrap-box">
      <button className="rnav-side left" type="button" aria-label={`Previous ${label}`}
        disabled={!canScrollLeft} onClick={() => scrollRail('prev')}>
        <Icon name="left" />
      </button>
      <div className={`rail ${className}`} tabIndex={0} role="group" aria-label={`${label} — drag or use arrows`} {...railProps}>
        {children}
      </div>
      <button className="rnav-side right" type="button" aria-label={`Next ${label}`}
        disabled={!canScrollRight} onClick={() => scrollRail('next')}>
        <Icon name="right" />
      </button>
    </div>
  );
}
