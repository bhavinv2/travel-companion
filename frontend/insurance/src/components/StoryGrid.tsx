import { useCallback, useEffect, useRef, useState } from 'react';
import SideDecor from './SideDecor';
import { useReveal } from '../hooks/useReveal';
import { photo } from '../data/site';

const STORIES = [
  {
    title: 'Parents Visiting Children', desc: 'Longer stays with family overseas, with cover built for senior travellers.',
    tag: 'Most popular',
    photo: photo('story-parents.jpg'), alt: 'Parents sharing tea with their son at home, luggage packed by the sofa',
  },
  {
    title: 'Visitors & Tourists', desc: 'Short trips and sightseeing abroad.',
    photo: photo('story-tourists.jpg'), alt: 'A historic bridge in Paris lit up at dusk',
  },
  {
    title: 'Families Travelling Abroad', desc: 'One plan for parents and children.',
    photo: photo('story-families.jpg'), alt: 'Multi-generation family walking through airport departures with their luggage',
  },
  {
    title: 'Business Travellers', desc: 'Work trips, conferences and meetings.',
    photo: photo('story-business.jpg'), alt: 'Business traveller resting feet on a suitcase in an airport departure lounge as a plane takes off',
  },
  {
    title: 'Senior Travellers', desc: 'Plans suited to travellers over 60.',
    photo: photo('story-senior.jpg'), alt: 'Senior couple walking arm in arm through a historic city plaza abroad',
  },
  {
    title: 'Students & Young Travellers', desc: 'Study, exchange and gap-year travel.',
    photo: photo('story-students.jpg'), alt: 'Young travellers studying together with laptops',
  },
  {
    title: 'International Travellers', desc: 'Multi-country and long-haul journeys.',
    photo: photo('story-international.jpg'), alt: 'View from an aeroplane window above the clouds',
  },
  {
    title: 'Frequent Travellers', desc: 'Multi-trip options for regular flyers.',
    photo: photo('story-frequent.jpg'), alt: 'Open passport page covered in colourful travel stamps',
  },
  {
    title: 'Solo Travellers', desc: 'Cover built for travelling on your own.',
    photo: photo('story-solo.jpg'), alt: 'A solo traveller wheeling a suitcase through a modern airport terminal',
  },
];

/** 4x3 cell grid, in fill order. */
const CELLS: [number, number][] = [
  [1, 1], [1, 2], [1, 3], [1, 4],
  [2, 1], [2, 2], [2, 3], [2, 4],
  [3, 1], [3, 2], [3, 3], [3, 4],
];
/** Where one tile sits: row, column and how many of each it spans. Kept as numbers
 *  rather than a grid-area string so the CSS can transition the box itself —
 *  grid-area jumps, left/top/width/height animate. */
interface Cell { r: number; c: number; rs: number; cs: number }
const area = (r: number, c: number, rs = 1, cs = 1): Cell => ({ r, c, rs, cs });

/** Where the expanded tile sits — always a 2x2 block containing its own cell,
 *  so the pointer never leaves it and the hover can't flicker. */
function bigBlock(slot: number): [number, number] {
  if (slot <= 4) return [1, 3];   // top-right quadrant
  if (slot <= 6) return [2, 1];   // bottom-left
  return [2, 3];                  // bottom-right
}

/**
 * Lays the 9 tiles onto the 12 cells. With nothing hovered the parent takes the
 * 2x2 top-left block. When a small tile is hovered it takes a 2x2 block, the
 * parent drops to a single cell, and every displaced tile is re-seated into the
 * cells the parent just gave up — so no gap is left and nothing is covered.
 */
function layout(hovered: number | null): Cell[] {
  const areas = new Array<Cell>(9);
  if (hovered === null) {
    areas[0] = area(1, 1, 2, 2);
    [[1, 3], [1, 4], [2, 3], [2, 4], [3, 1], [3, 2], [3, 3], [3, 4]]
      .forEach(([r, c], i) => { areas[i + 1] = area(r, c); });
    return areas;
  }
  const [br, bc] = bigBlock(hovered);
  const taken = new Set([`1,1`]);
  for (let r = br; r < br + 2; r++) for (let c = bc; c < bc + 2; c++) taken.add(`${r},${c}`);
  areas[0] = area(1, 1);
  areas[hovered] = area(br, bc, 2, 2);
  const free = CELLS.filter(([r, c]) => !taken.has(`${r},${c}`));
  let n = 0;
  for (let i = 1; i < 9; i++) {
    if (i === hovered) continue;
    const [r, c] = free[n++];
    areas[i] = area(r, c);
  }
  return areas;
}

/** Matches the tile transition in the stylesheet. */
const MOVE_MS = 450;
/** How long the pointer must rest on a tile before the grid rearranges. */
const HOVER_DELAY_MS = 500;

export default function StoryGrid() {
  const reveal = useReveal<HTMLDivElement>();
  const [hovered, setHovered] = useState<number | null>(null);
  const areas = layout(hovered);

  // which tiles keep their cell through this change — they hold the upper layer
  // so the travelling ones pass behind them rather than over them
  const prevAreas = useRef<Cell[] | null>(null);
  const still = areas.map((a, i) => {
    const p = prevAreas.current?.[i];
    return !!p && p.r === a.r && p.c === a.c && p.rs === a.rs && p.cs === a.cs;
  });
  // a tile that moves to a different cell has to cross ground another tile is
  // still standing on; one that only changes size stays put and stays opaque
  const shifted = areas.map((a, i) => {
    const p = prevAreas.current?.[i];
    return !!p && (p.r !== a.r || p.c !== a.c);
  });
  useEffect(() => { prevAreas.current = areas; });

  // Hover is driven by pointer *movement* and hit-testing, never by the tiles'
  // own mouseenter/mouseleave: those fire again every time a tile slides under a
  // still cursor, which restarts the layout and makes the grid flicker. A lock
  // also keeps one move from being interrupted, and re-tests where the pointer
  // actually ended up once the move finishes.
  const hoveredRef = useRef<number | null>(null);
  const pointerRef = useRef<{ x: number; y: number } | null>(null);
  const lockedRef = useRef(false);
  const timerRef = useRef<number | undefined>(undefined);
  // the tile the pointer is resting on, waiting out HOVER_DELAY_MS
  const pendingRef = useRef<number | null | undefined>(undefined);
  const dwellRef = useRef<number | undefined>(undefined);
  // a dwell that finished while the grid was still moving
  const queuedRef = useRef<number | null | undefined>(undefined);
  const gridRef = useRef<HTMLDivElement | null>(null);

  const slotUnderPointer = useCallback(() => {
    const p = pointerRef.current;
    if (!p) return null;
    const el = document.elementFromPoint(p.x, p.y) as HTMLElement | null;
    const tile = el?.closest<HTMLElement>('.story');
    if (!tile?.dataset.slot) return null;
    const slot = Number(tile.dataset.slot);
    return slot > 0 ? slot : null;   // the feature tile never expands
  }, []);

  const commit = useCallback((next: number | null) => {
    if (hoveredRef.current === next) return;
    hoveredRef.current = next;
    setHovered(next);
    // `moving` takes the travelling tiles out of the hit-testing for the length
    // of the animation, so none of them can pick up :hover on the way past
    lockedRef.current = true;
    gridRef.current?.classList.add('moving');
    window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => {
      lockedRef.current = false;
      gridRef.current?.classList.remove('moving');
      // only a dwell the pointer earned gets applied — never a tile that merely
      // drifted under a still cursor
      const queued = queuedRef.current;
      queuedRef.current = undefined;
      if (queued !== undefined) commit(queued);
    }, MOVE_MS);
  }, []);

  /** Arm the dwell timer for whatever the pointer is over now. */
  const intend = useCallback((next: number | null) => {
    if (next === hoveredRef.current) {          // already showing it — nothing pending
      pendingRef.current = undefined;
      window.clearTimeout(dwellRef.current);
      return;
    }
    if (pendingRef.current === next) return;    // same target, keep its timer running
    pendingRef.current = next;
    window.clearTimeout(dwellRef.current);
    dwellRef.current = window.setTimeout(() => {
      pendingRef.current = undefined;
      // hit-test again now the grid has settled, in case the reading that armed
      // this timer caught a tile in mid-flight
      const now = slotUnderPointer();
      if (now === hoveredRef.current) return;
      if (lockedRef.current) queuedRef.current = now;
      else commit(now);
    }, HOVER_DELAY_MS);
  }, [commit, slotUnderPointer]);

  useEffect(() => () => {
    window.clearTimeout(timerRef.current);
    window.clearTimeout(dwellRef.current);
  }, []);

  function handleMove(e: React.MouseEvent) {
    pointerRef.current = { x: e.clientX, y: e.clientY };
    intend(slotUnderPointer());
  }
  function handleLeave() {
    pointerRef.current = null;
    pendingRef.current = undefined;
    queuedRef.current = undefined;
    window.clearTimeout(dwellRef.current);
    commit(null);                               // leaving the grid collapses at once
  }

  return (
    <section className="sec" style={{ background: 'var(--cloud)' }}>
      <SideDecor icons={[
        { name: 'i-users', side: 'left', top: '30%', size: 30, rotate: -6, opacity: 0.14 },
        { name: 'i-plane', side: 'left', top: '8%', size: 90, rotate: -20, opacity: 0.06 },
        { name: 'i-globe', side: 'right', top: '55%', size: 30, rotate: 10, opacity: 0.14 },
        { name: 'i-passport', side: 'right', top: '80%', size: 100, rotate: 10, opacity: 0.06 },
      ]} />
      <div className={`wrap z1 ${reveal.className}`} ref={reveal.ref as any}>
        <div className="center">
          <span className="kick">Who we protect</span>
          <h2 className="h2" style={{ marginTop: 12 }}>Travel Protection for Every Kind of Traveller</h2>
          <span className="script-tag" style={{ fontSize: 24, marginTop: 6, color: 'var(--marigold)' }}>Every story, covered.</span>
        </div>
        <div className="stories" ref={gridRef} onMouseMove={handleMove} onMouseLeave={handleLeave}>
          {STORIES.map((s, slot) => (
            <article
              className={`story${slot === 0 ? ' feat' : ''}${hovered === slot ? ' big' : ''}${still[slot] ? ' still' : ''}${shifted[slot] ? ' shifted' : ''}`}
              key={s.title}
              data-slot={slot}
              style={{
                ['--r' as string]: areas[slot].r,
                ['--c' as string]: areas[slot].c,
                ['--rs' as string]: areas[slot].rs,
                ['--cs' as string]: areas[slot].cs,
              } as React.CSSProperties}
              onFocus={() => slot !== 0 && commit(slot)}
              onBlur={() => slot !== 0 && commit(null)}
              tabIndex={0}
            >
              <img src={s.photo} alt={s.alt} loading="lazy" decoding="async" draggable={false} />
              {s.tag && <span className="story-tag">{s.tag}</span>}
              <div className="story-b"><h3>{s.title}</h3><p>{s.desc}</p></div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
