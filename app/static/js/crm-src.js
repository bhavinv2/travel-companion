/* Where this visitor first came from, kept for the Sales CRM.

   On the first visit only: the ad or campaign in the address (utm_*, gclid from Google Ads, fbclid
   from Facebook / Instagram), the site that linked here, and the first page seen. Stored in a
   first-party cookie for 90 days; every form on the site sends it along with the enquiry (the
   server reads it in services/crm.utm_from_request), so a lead says which campaign earned it even
   when the person comes back a week later to fill the form in. Nothing is sent anywhere else. */
(function () {
  'use strict';
  var NAME = 'nps_src';
  try {
    if (document.cookie.split('; ').some(function (c) { return c.indexOf(NAME + '=') === 0; })) return;
    var p = new URLSearchParams(location.search), out = {};
    ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'gclid', 'fbclid'].forEach(function (k) {
      var v = p.get(k);
      if (v) out[k] = v.slice(0, 200);
    });
    var ref = document.referrer || '';
    if (ref) {
      try { if (new URL(ref).host !== location.host) out.referrer = ref.slice(0, 200); } catch (e) { /* not a URL */ }
    }
    out.landing = (location.pathname || '/').slice(0, 200);
    document.cookie = NAME + '=' + encodeURIComponent(JSON.stringify(out)) +
      '; Max-Age=' + 90 * 86400 + '; Path=/; SameSite=Lax' + (location.protocol === 'https:' ? '; Secure' : '');
  } catch (e) { /* cookies off: the lead still arrives, only without its campaign */ }
})();
