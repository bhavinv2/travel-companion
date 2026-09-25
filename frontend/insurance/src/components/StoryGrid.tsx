import SideDecor from './SideDecor';
import { useReveal } from '../hooks/useReveal';
import { photo } from '../data/site';

const STORIES = [
  {
    title: 'Parents Visiting Children', desc: 'Longer stays with family overseas, with cover built for senior travellers.',
    tag: 'Most popular', className: 'story tall wide',
    photo: photo('story-parents.jpg'), alt: 'Family gathered together on a beach at sunset',
  },
  {
    title: 'Visitors & Tourists', desc: 'Short trips and sightseeing abroad.',
    photo: photo('story-tourists.jpg'), alt: 'A historic bridge in Paris lit up at dusk',
  },
  {
    title: 'Families Travelling Abroad', desc: 'One plan for parents and children.',
    photo: photo('story-families.jpg'), alt: 'Calm beach at sunrise, a family holiday scene',
  },
  {
    title: 'Business Travellers', desc: 'Work trips, conferences and meetings.',
    photo: photo('story-business.jpg'), alt: 'Professional traveller ready for a business trip',
  },
  {
    title: 'Senior Travellers', desc: 'Plans suited to travellers over 60.',
    photo: photo('story-senior.jpg'), alt: 'Keepsake photos and letters from a lifetime of travel',
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
    photo: photo('story-frequent.jpg'), alt: 'Hotel sign lit up at night for a travelling guest',
  },
];

export default function StoryGrid() {
  const reveal = useReveal<HTMLDivElement>();

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
        <div className="stories">
          {STORIES.map((s) => (
            <article className={s.className ?? 'story'} key={s.title}>
              <img src={s.photo} alt={s.alt} loading="lazy" />
              {s.tag && <span className="story-tag">{s.tag}</span>}
              <div className="story-b"><h3>{s.title}</h3><p>{s.desc}</p></div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
