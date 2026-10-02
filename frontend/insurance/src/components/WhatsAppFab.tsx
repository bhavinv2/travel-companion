import Icon from './Icon';
import { useQuote } from '../context/QuoteContext';
import { track } from '../utils/track';
import { site } from '../data/site';

// Fallback for `npm run dev` only; the served page injects whatever staff published.
const WHATSAPP_NUMBER = '918019111360';

export default function WhatsAppFab() {
  const { consultOpen } = useQuote();
  // The number staff marked for WhatsApp on Admin -> Landing page. Hard-coding it here meant
  // changing it on the admin screen moved every button on the page except this one.
  const number = (site.whatsapp || WHATSAPP_NUMBER).replace(/[^0-9]/g, '');

  return (
    <a
      className={`wafab${consultOpen ? ' wafab-right' : ''}`}
      href={`https://api.whatsapp.com/send/?phone=${number}`}
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Chat with us on WhatsApp"
      onClick={() => track('whatsapp')}
    >
      <Icon name="i-whatsapp" className="ico-solid" style={{ width: 32, height: 32 }} />
      <span className="wafab-tip">Chat with us</span>
    </a>
  );
}
