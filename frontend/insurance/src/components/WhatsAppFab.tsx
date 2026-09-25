import Icon from './Icon';
import { useQuote } from '../context/QuoteContext';

export default function WhatsAppFab() {
  const { consultOpen } = useQuote();

  return (
    <a
      className={`wafab${consultOpen ? ' wafab-right' : ''}`}
      href="https://api.whatsapp.com/send/?phone=918019111360"
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Chat with us on WhatsApp"
    >
      <Icon name="i-whatsapp" className="ico-solid" style={{ width: 32, height: 32 }} />
      <span className="wafab-tip">Chat with us</span>
    </a>
  );
}
