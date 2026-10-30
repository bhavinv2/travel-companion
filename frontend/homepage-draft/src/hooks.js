import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * The travel-insurance page's drag carousel (frontend/insurance/src/hooks/useDragRail.ts):
 * pointer dragging, arrow paging and the disabled state of the side buttons.
 */
export function useDragRail() {
  const railRef = useRef(null);
  const drag = useRef({ down: false, sx: 0, sl: 0 });
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(true);

  const checkScroll = useCallback(() => {
    const rail = railRef.current;
    if (!rail) return;
    setCanScrollLeft(rail.scrollLeft > 4);
    setCanScrollRight(rail.scrollLeft + rail.clientWidth < rail.scrollWidth - 4);
  }, []);

  useEffect(() => {
    checkScroll();
    window.addEventListener('resize', checkScroll);
    return () => window.removeEventListener('resize', checkScroll);
  }, [checkScroll]);

  function onPointerDown(e) {
    if (e.pointerType !== 'mouse' || e.target.closest('button,a')) return;
    const rail = railRef.current;
    drag.current = { down: true, sx: e.clientX, sl: rail.scrollLeft };
    rail.classList.add('drag');
    rail.setPointerCapture(e.pointerId);
  }
  function onPointerMove(e) {
    if (!drag.current.down) return;
    railRef.current.scrollLeft = drag.current.sl - (e.clientX - drag.current.sx);
    checkScroll();
  }
  function endDrag() {
    drag.current.down = false;
    if (railRef.current) railRef.current.classList.remove('drag');
    checkScroll();
  }

  function scrollRail(dir) {
    const rail = railRef.current;
    if (!rail) return;
    const w = rail.firstElementChild ? rail.firstElementChild.offsetWidth : 300;
    rail.scrollBy({ left: dir === 'next' ? w + 16 : -(w + 16), behavior: 'smooth' });
    setTimeout(checkScroll, 350);
  }

  const railProps = {
    ref: railRef,
    onScroll: checkScroll,
    onPointerDown,
    onPointerMove,
    onPointerUp: endDrag,
    onPointerCancel: endDrag,
  };

  return { railProps, scrollRail, canScrollLeft, canScrollRight };
}

export const reduceMotion = () =>
  typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Adds `in` to the element the first time it scrolls into view; CSS does the animating. */
export function useReveal(threshold = 0.15) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (!('IntersectionObserver' in window)) { el.classList.add('in'); return; }
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
      });
    }, { threshold });
    io.observe(el);
    return () => io.disconnect();
  }, [threshold]);
  return ref;
}

/** Window scroll position as a 0..1 fraction of the page, plus raw scrollY. */
export function useScroll() {
  const [s, setS] = useState({ y: 0, p: 0 });
  useEffect(() => {
    let ticking = false;
    const read = () => {
      ticking = false;
      const max = document.documentElement.scrollHeight - window.innerHeight;
      setS({ y: window.scrollY, p: max > 0 ? window.scrollY / max : 0 });
    };
    const on = () => { if (!ticking) { ticking = true; requestAnimationFrame(read); } };
    read();
    window.addEventListener('scroll', on, { passive: true });
    window.addEventListener('resize', on);
    return () => { window.removeEventListener('scroll', on); window.removeEventListener('resize', on); };
  }, []);
  return s;
}

/** Mouse-follow 3D tilt: sets --rx/--ry/--mx/--my on the element. */
export function tiltHandlers(max = 8) {
  return {
    onMouseMove(e) {
      if (reduceMotion()) return;
      const el = e.currentTarget;
      const r = el.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width;
      const y = (e.clientY - r.top) / r.height;
      el.style.setProperty('--ry', `${(x - 0.5) * max * 2}deg`);
      el.style.setProperty('--rx', `${(0.5 - y) * max * 2}deg`);
      el.style.setProperty('--mx', `${x * 100}%`);
      el.style.setProperty('--my', `${y * 100}%`);
    },
    onMouseLeave(e) {
      const el = e.currentTarget;
      el.style.setProperty('--rx', '0deg');
      el.style.setProperty('--ry', '0deg');
    },
  };
}
