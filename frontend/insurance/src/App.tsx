import IconSprite from './components/IconSprite';
import Header from './components/Header';
import Hero from './components/Hero';
import InsuranceQuoteForm from './components/InsuranceQuoteForm';
import VisitorInsurance from './components/VisitorInsurance';
import WhyRail from './components/WhyRail';
import StoryGrid from './components/StoryGrid';
import DoctorSection from './components/DoctorSection';
import Requirements from './components/Requirements';
import HowItWorks from './components/HowItWorks';
import Partners from './components/Partners';
import Reviews from './components/Reviews';
import ExpertContact from './components/ExpertContact';
import FAQ from './components/FAQ';
import FinalCTA from './components/FinalCTA';
import Footer from './components/Footer';
import WelcomePopup from './components/WelcomePopup';
import QuoteModal from './components/QuoteModal';
import WhatsAppFab from './components/WhatsAppFab';
import { QuoteProvider } from './context/QuoteContext';
import { showChrome } from './data/site';

export default function App() {
  return (
    <QuoteProvider>
      <IconSprite />
      <a className="skip" href="#main">Skip to content</a>
      {/* Embedded in the site, this page sits inside the shared NRI Parent Service navbar
          and footer, so the build's own would be a second set. Standalone (npm run dev)
          nothing injects the flag and they render as before. */}
      {showChrome && <Header />}
      <main id="main">
        <Hero />
        <InsuranceQuoteForm />
        <VisitorInsurance />
        <WhyRail />
        <StoryGrid />
        <DoctorSection />
        <Requirements />
        <HowItWorks />
        <Partners />
        <Reviews />
        <ExpertContact />
        <FAQ />
        <FinalCTA />
      </main>
      {showChrome && <Footer />}
      <WelcomePopup />
      <QuoteModal />
      <WhatsAppFab />
    </QuoteProvider>
  );
}
