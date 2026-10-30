/* A section's photo, edge to edge behind everything in it. The section's own class lays the shade
 * over it (styles.css .sc-dark / .sc-light / .sc-soft), so the words on top always read. Lazy
 * unless it is the first thing on the page. */
export default function Bg({ src, pos = 'center', eager = false }) {
  return (
    <div className="secbg" aria-hidden="true">
      <img src={src} alt="" loading={eager ? 'eager' : 'lazy'} decoding="async" style={{ objectPosition: pos }} />
    </div>
  );
}
