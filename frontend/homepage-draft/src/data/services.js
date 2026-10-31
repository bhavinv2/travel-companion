/* The six services' marks -- name, colour and icon -- the same wherever the page points at a
 * service: the hero's care circle, and the journey's guide and the stops it passes. */
export const MARKS = [
  { key: 'companion', title: 'Travel Companion', color: '#2446B8', icon: 'plane' },
  { key: 'insurance', title: 'Travel Insurance', color: '#0F9D8C', icon: 'shield' },
  { key: 'doctor', title: 'Virtual Doctor', color: '#5B4BD6', icon: 'steth' },
  { key: 'sahayak', title: 'Sahayak', color: '#E4613F', icon: 'home' },
  { key: 'gift', title: 'Gift Health', color: '#C98A12', icon: 'gift' },
  { key: 'fit', title: 'Fit2Fly', color: '#14946E', icon: 'clip' },
];

export const MARK = Object.fromEntries(MARKS.map((m) => [m.key, m]));
