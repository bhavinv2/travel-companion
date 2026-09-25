import Icon from './Icon';
import { asset } from '../data/site';

export default function Footer() {
  return (
    <footer id="about" style={{ background: 'var(--navy)', padding: '36px 0 24px', color: '#C9D5F0' }}>
      <div className="wrap">
        <div className="fgrid">
          <div className="fbrand">
            <a className="logo" href="#top" aria-label="NRI Parent Service home" style={{ color: '#fff' }}>
              <span className="logo-mark">
                <img src={asset('logo-mark.png')} alt="" width={200} height={161} />
              </span>
              <span className="logo-word" style={{ color: '#fff' }}>
                NRI Parent Service
                <span style={{ color: 'var(--horizon)' }}>Travel Insurance</span>
              </span>
            </a>
            <p className="small" style={{ marginTop: 18, color: '#C9D5F0', maxWidth: 340 }}>
              Travel insurance, visitor insurance and claims guidance for international travellers and their families.
            </p>
            <span className="script-tag" style={{ fontSize: 22, color: 'var(--horizon)', marginTop: 10, display: 'block' }}>Until your next journey.</span>
            <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
              <a className="soc" href="#about" aria-label="Instagram"><Icon name="i-ig" className="ico w sm" /></a>
              <a className="soc" href="#about" aria-label="Facebook"><Icon name="i-fb" className="ico w sm" /></a>
              <a className="soc" href="#about" aria-label="LinkedIn"><Icon name="i-li" className="ico w sm" /></a>
              <a className="soc" href="#about" aria-label="YouTube"><Icon name="i-yt" className="ico w sm" /></a>
            </div>
          </div>
          <nav aria-label="Insurance">
            <div className="fh">Insurance</div>
            <a className="fl" href="#top">Travel Insurance</a>
            <a className="fl" href="#visitor">Visitor Insurance</a>
            <a className="fl" href="#benefits">Travel Medical Insurance</a>
            <a className="fl" href="#benefits">International Travel Insurance</a>
            <a className="fl" href="#faq">Travel Claims</a>
          </nav>
          <nav aria-label="Resources">
            <div className="fh">Resources</div>
            <a className="fl" href="#about">Travel Guides</a>
            <a className="fl" href="#faq">FAQs</a>
            <a className="fl" href="#about">Travel Tips</a>
            <a className="fl" href="#faq">Claims Assistance</a>
          </nav>
          <nav aria-label="Company">
            <div className="fh">Company</div>
            <a className="fl" href="#about">About Us</a>
            <a className="fl" href="#support">Contact</a>
            <a className="fl" href="#about">Privacy Policy</a>
            <a className="fl" href="#about">Terms &amp; Conditions</a>
          </nav>
          <div id="support">
            <div className="fh">Support</div>
            <a className="fl" href="tel:+918019111360"><Icon name="i-phone" className="ico h xs" />+91 80191 11360</a>
            <a className="fl" href="tel:+19179005094"><Icon name="i-phone" className="ico h xs" />+1 917 900 5094</a>
            <a className="fl" href="mailto:support@nriparentservice.com"><Icon name="i-mail" className="ico h xs" />support@nriparentservice.com</a>
            <span className="fl" style={{ cursor: 'default' }}><Icon name="i-clock" className="ico h xs" />Across time zones</span>
          </div>
        </div>
        <hr style={{ border: 0, borderTop: '1px solid rgba(255,255,255,.12)', margin: '40px 0 20px' }} />
        <div className="fbot">
          <p className="tiny" style={{ color: '#A9B8DB' }}>
            &copy; {new Date().getFullYear()} NRI Parent Service. All rights reserved.<br />
            Insurance is the subject matter of solicitation.
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '14px 24px' }}>
            <a className="fl" href="#about" style={{ fontSize: 14 }}>Privacy Policy</a>
            <a className="fl" href="#about" style={{ fontSize: 14 }}>Terms &amp; Conditions</a>
            <a className="fl" href="#about" style={{ fontSize: 14 }}>Sitemap</a>
          </div>
        </div>
      </div>
    </footer>
  );
}
