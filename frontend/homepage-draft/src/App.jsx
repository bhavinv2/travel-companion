import Nav from './components/Nav.jsx';
import Hero from './components/Hero.jsx';
import { Companion, Insurance, Sahayak, Health } from './components/Showcase.jsx';
import Journey from './components/Journey.jsx';
import Why from './components/Why.jsx';
import Reviews from './components/Reviews.jsx';
import About from './components/About.jsx';
import Steps from './components/Steps.jsx';
import Faq from './components/Faq.jsx';
import { Blog, FinalCTA, Footer, Floaters } from './components/Closing.jsx';
import { site } from './data/site.js';

/* Every section runs edge to edge on its own photo: the hero (the care circle -- the six services
 * turning around your parents, the one in front told beside it), the journey (the plane down the services, drawn by the
 * scroll), a band of detail for each service, how it works, why us, what families say, questions,
 * the blog and the last call to action. */
function Home() {
  return (
    <>
      <Hero />
      <Journey />
      <Companion />
      <Insurance />
      <Sahayak />
      <Health />
      <Steps />
      <Why />
      <Reviews />
      <Faq />
      <Blog />
      <FinalCTA />
    </>
  );
}

/* One bundle, two pages: the server says which one this is (routes/homepage_draft.py). */
export default function App() {
  return (
    <div className="hpd" id="top">
      {site.chrome && <Nav />}
      <main>{site.page === 'about' ? <About /> : <Home />}</main>
      {site.chrome && <Footer />}
      <Floaters />
    </div>
  );
}
