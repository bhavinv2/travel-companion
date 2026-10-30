import Nav from './components/Nav.jsx';
import Hero from './components/Hero.jsx';
import Journey from './components/Journey.jsx';
import Bridge from './components/Bridge.jsx';
import Orbit from './components/Orbit.jsx';
import Why from './components/Why.jsx';
import Reviews from './components/Reviews.jsx';
import Partners from './components/Partners.jsx';
import About from './components/About.jsx';
import { Blog, FinalCTA, Footer, Floaters, Ticker } from './components/Closing.jsx';
import { site } from './data/site.js';

function Home() {
  return (
    <>
      <Hero />
      <Ticker />
      <Orbit />
      <Journey />
      <Bridge />
      <Why />
      <Reviews />
      <Partners />
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
