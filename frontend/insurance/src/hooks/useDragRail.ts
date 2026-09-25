import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Shared behaviour for the drag carousels (benefits rail, partner logos):
 * pointer dragging, arrow paging and the disabled state of the side buttons.
 */
export function useDragRail() {
  const railRef = useRef<HTMLDivElement>(null);
  const drag = useRef({ down: false, sx: 0, sl: 0, moved: 0 });

  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(true);

  const checkScroll = useCallback(() => {
    const rail = railRef.current;
    if (!rail) return;
    const atStart = rail.scrollLeft <= 4;
    const atEnd = rail.scrollLeft + rail.clientWidth >= rail.scrollWidth - 4;
    setCanScrollLeft(!atStart);
    setCanScrollRight(!atEnd);
  }, []);

  useEffect(() => {
    checkScroll();
    window.addEventListener('resize', checkScroll);
    return () => window.removeEventListener('resize', checkScroll);
  }, [checkScroll]);

  function onPointerDown(e: React.PointerEvent) {
    if ((e.target as HTMLElement).closest('button')) return;
    const rail = railRef.current;
    if (!rail) return;
    drag.current = { down: true, sx: e.clientX, sl: rail.scrollLeft, moved: 0 };
    rail.classList.add('drag');
    rail.setPointerCapture(e.pointerId);
  }
  function onPointerMove(e: React.PointerEvent) {
    if (!drag.current.down) return;
    const rail = railRef.current;
    if (!rail) return;
    const dx = e.clientX - drag.current.sx;
    drag.current.moved = Math.abs(dx);
    rail.scrollLeft = drag.current.sl - dx;
    checkScroll();
  }
  function endDrag() {
    drag.current.down = false;
    railRef.current?.classList.remove('drag');
    checkScroll();
  }

  function scrollRail(dir: 'prev' | 'next') {
    const rail = railRef.current;
    if (!rail) return;
    const w = (rail.firstElementChild as HTMLElement)?.offsetWidth ?? 300;
    rail.scrollBy({ left: dir === 'next' ? w + 20 : -(w + 20), behavior: 'smooth' });
    setTimeout(checkScroll, 350);
  }

  /** Spread onto the scrolling element. */
  const railProps = {
    ref: railRef,
    onScroll: checkScroll,
    onPointerDown,
    onPointerMove,
    onPointerUp: endDrag,
    onPointerCancel: endDrag,
  };

  return { railRef, railProps, scrollRail, canScrollLeft, canScrollRight };
}
