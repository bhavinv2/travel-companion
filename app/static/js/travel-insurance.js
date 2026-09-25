(function(){
  "use strict";

  /* ============================================================
     CONFIG — quote handoff to the Preventia360 BrokersNexus engine
     Adjust PARAM names here if BrokersNexus expects different keys.
     ============================================================ */
  /* The quote engine lives on /get-travel-insurance-quotes/ — the site root has no
     quote form, which is why a redirect to "/" just showed the home page. The engine
     picks which plan set to load from ?presection=... (values taken from the live site). */
  var QUOTE_URL='https://preventia360.brokersnexus.com/get-travel-insurance-quotes/';
  var SECTIONS={usa:'visitorUSA',outside:'travelOutsideUSA',schengen:'schengen',
                study:'studyAbroad',group:'groupTravelMedical'};
  var SCHENGEN='Austria,Belgium,Croatia,Czechia,Denmark,Estonia,Finland,France,Germany,Greece,Hungary,Iceland,Italy,Latvia,Lithuania,Luxembourg,Malta,Netherlands,Norway,Poland,Portugal,Slovakia,Slovenia,Spain,Sweden,Switzerland'.split(',');
  var PARAMS={destination:'destination',start:'start_date',end:'end_date',travellers:'travellers',
              ages:'ages',citizenship:'citizenship',residence:'residence',name:'name',
              email:'email',phone:'phone',purpose:'purpose',pre:'pre_existing',source:'utm_source'};

  function presectionFor(dest,purpose,count){
    if(dest==='United States') return SECTIONS.usa;
    if(SCHENGEN.indexOf(dest)>-1) return SECTIONS.schengen;
    if(purpose==='Study') return SECTIONS.study;
    if(count>=5) return SECTIONS.group;
    return SECTIONS.outside;
  }

  /* ---------- countries (name|iso2|dial) ---------- */
  var C="Afghanistan|AF|93,Albania|AL|355,Algeria|DZ|213,Argentina|AR|54,Armenia|AM|374,Australia|AU|61,Austria|AT|43,Azerbaijan|AZ|994,Bahrain|BH|973,Bangladesh|BD|880,Belarus|BY|375,Belgium|BE|32,Bhutan|BT|975,Bolivia|BO|591,Bosnia and Herzegovina|BA|387,Botswana|BW|267,Brazil|BR|55,Brunei|BN|673,Bulgaria|BG|359,Cambodia|KH|855,Cameroon|CM|237,Canada|CA|1,Chile|CL|56,China|CN|86,Colombia|CO|57,Costa Rica|CR|506,Croatia|HR|385,Cuba|CU|53,Cyprus|CY|357,Czechia|CZ|420,Denmark|DK|45,Dominican Republic|DO|1,Ecuador|EC|593,Egypt|EG|20,El Salvador|SV|503,Estonia|EE|372,Ethiopia|ET|251,Fiji|FJ|679,Finland|FI|358,France|FR|33,Georgia|GE|995,Germany|DE|49,Ghana|GH|233,Greece|GR|30,Guatemala|GT|502,Honduras|HN|504,Hong Kong|HK|852,Hungary|HU|36,Iceland|IS|354,India|IN|91,Indonesia|ID|62,Iran|IR|98,Iraq|IQ|964,Ireland|IE|353,Israel|IL|972,Italy|IT|39,Jamaica|JM|1,Japan|JP|81,Jordan|JO|962,Kazakhstan|KZ|7,Kenya|KE|254,Kuwait|KW|965,Kyrgyzstan|KG|996,Laos|LA|856,Latvia|LV|371,Lebanon|LB|961,Libya|LY|218,Lithuania|LT|370,Luxembourg|LU|352,Macao|MO|853,Madagascar|MG|261,Malaysia|MY|60,Maldives|MV|960,Malta|MT|356,Mauritius|MU|230,Mexico|MX|52,Moldova|MD|373,Monaco|MC|377,Mongolia|MN|976,Montenegro|ME|382,Morocco|MA|212,Mozambique|MZ|258,Myanmar|MM|95,Namibia|NA|264,Nepal|NP|977,Netherlands|NL|31,New Zealand|NZ|64,Nicaragua|NI|505,Nigeria|NG|234,North Macedonia|MK|389,Norway|NO|47,Oman|OM|968,Pakistan|PK|92,Panama|PA|507,Papua New Guinea|PG|675,Paraguay|PY|595,Peru|PE|51,Philippines|PH|63,Poland|PL|48,Portugal|PT|351,Qatar|QA|974,Romania|RO|40,Russia|RU|7,Rwanda|RW|250,Saudi Arabia|SA|966,Senegal|SN|221,Serbia|RS|381,Seychelles|SC|248,Singapore|SG|65,Slovakia|SK|421,Slovenia|SI|386,South Africa|ZA|27,South Korea|KR|82,Spain|ES|34,Sri Lanka|LK|94,Sweden|SE|46,Switzerland|CH|41,Taiwan|TW|886,Tanzania|TZ|255,Thailand|TH|66,Tunisia|TN|216,Turkey|TR|90,Turkmenistan|TM|993,Uganda|UG|256,Ukraine|UA|380,United Arab Emirates|AE|971,United Kingdom|GB|44,United States|US|1,Uruguay|UY|598,Uzbekistan|UZ|998,Vietnam|VN|84,Yemen|YE|967,Zambia|ZM|260,Zimbabwe|ZW|263";
  var COUNTRIES=C.split(',').map(function(r){var p=r.split('|');return{name:p[0],iso:p[1],dial:p[2]};});
  function flag(iso){try{return String.fromCodePoint.apply(null,iso.split('').map(function(c){return 127397+c.charCodeAt(0);}));}catch(e){return'';}}
  COUNTRIES.sort(function(a,b){return a.name.localeCompare(b.name);});

  var optsHTML=COUNTRIES.map(function(c){return'<option value="'+c.name+'">'+flag(c.iso)+' '+c.name+'</option>';}).join('');
  Array.prototype.forEach.call(document.querySelectorAll('[data-countries]'),function(s){
    s.innerHTML='<option value="">Select a country</option>'+optsHTML;
    var d=s.getAttribute('data-default'); if(d) s.value=d;
  });
  var dialHTML=COUNTRIES.map(function(c){return'<option value="+'+c.dial+'">'+flag(c.iso)+' +'+c.dial+'</option>';}).join('');
  Array.prototype.forEach.call(document.querySelectorAll('[data-dial]'),function(s){ s.innerHTML=dialHTML; s.value='+91'; });

  /* ---------- date pickers ---------- */
  var today=new Date().toISOString().slice(0,10);
  Array.prototype.forEach.call(document.querySelectorAll('[data-cal]'),function(d){
    d.min=today;
    d.addEventListener('focus',function(){ if(d.showPicker){try{d.showPicker();}catch(e){}} });
    d.addEventListener('click',function(){ if(d.showPicker){try{d.showPicker();}catch(e){}} });
  });
  function linkDates(a,b){
    a.addEventListener('change',function(){ b.min=a.value||today; if(b.value&&b.value<a.value) b.value=a.value; });
  }
  linkDates(document.getElementById('qb-start'),document.getElementById('qb-end'));
  linkDates(document.getElementById('m-start'),document.getElementById('m-end'));

  /* ---------- reveal on scroll ---------- */
  var io=('IntersectionObserver' in window)?new IntersectionObserver(function(es){
    es.forEach(function(e){ if(e.isIntersecting){ e.target.classList.add('in'); io.unobserve(e.target); } });
  },{threshold:.15}):null;
  if(io){ Array.prototype.forEach.call(document.querySelectorAll('.reveal, #how'),function(el){ io.observe(el); }); }
  else { Array.prototype.forEach.call(document.querySelectorAll('.reveal, #how'),function(el){ el.classList.add('in'); }); }

  /* ---------- mobile menu ---------- */
  var burger=document.getElementById('burger'), mnav=document.getElementById('mnav');
  burger.addEventListener('click',function(){
    var open=mnav.getAttribute('data-open')==='true';
    mnav.setAttribute('data-open',String(!open));
    burger.setAttribute('aria-expanded',String(!open));
    burger.setAttribute('aria-label',open?'Open menu':'Close menu');
    burger.innerHTML='<svg class="ico n"><use href="#'+(open?'i-menu':'i-x')+'"></use></svg>';
  });
  mnav.addEventListener('click',function(e){ if(e.target.closest('a')){mnav.setAttribute('data-open','false');burger.setAttribute('aria-expanded','false');} });

  /* ---------- drag carousel ---------- */
  var rail=document.getElementById('whyRail');
  (function(){
    var down=false,sx=0,sl=0,moved=0;
    rail.addEventListener('pointerdown',function(e){
      if(e.target.closest('button')) return;
      down=true;moved=0;sx=e.clientX;sl=rail.scrollLeft;rail.classList.add('drag');rail.setPointerCapture(e.pointerId);
    });
    rail.addEventListener('pointermove',function(e){
      if(!down) return; var dx=e.clientX-sx; moved=Math.abs(dx); rail.scrollLeft=sl-dx;
    });
    function up(){ down=false; rail.classList.remove('drag'); }
    rail.addEventListener('pointerup',up); rail.addEventListener('pointercancel',up);
    rail.addEventListener('click',function(e){ if(moved>8){e.preventDefault();e.stopPropagation();moved=0;} },true);
    Array.prototype.forEach.call(document.querySelectorAll('[data-rail]'),function(b){
      b.addEventListener('click',function(){
        var w=rail.firstElementChild?rail.firstElementChild.offsetWidth+20:320;
        rail.scrollBy({left:b.getAttribute('data-rail')==='next'?w:-w,behavior:'smooth'});
      });
    });
  })();

  /* ---------- FAQ ----------
     The questions are rendered by the server from the admin-managed help centre, so this only
     handles opening and closing them. */
  var list=document.getElementById('faqList');
  list.addEventListener('click',function(e){
    var b=e.target.closest('.fq-b'); if(!b) return;
    var box=b.parentNode,ans=box.querySelector('.fq-a'),open=b.getAttribute('aria-expanded')==='true';
    b.setAttribute('aria-expanded',String(!open)); box.classList.toggle('open',!open); ans.hidden=open;
    b.querySelector('.fq-i').innerHTML='<svg class="ico xs"><use href="#'+(open?'i-plus':'i-minus')+'"></use></svg>';
  });

  /* ---------- travellers popover in search bar ---------- */
  var travellers=2;
  var travBtn=document.getElementById('travBtn'),travPop=document.getElementById('travPop'),travText=document.getElementById('travText');
  function ageInputs(container,prefix,n,vals){
    var s='';
    for(var i=1;i<=n;i++){
      var v=vals&&vals[i-1]?' value="'+vals[i-1]+'"':'';
      s+='<p class="fg"><label class="tiny" for="'+prefix+i+'" style="display:block;margin-bottom:6px">Traveller '+i+'</label>'
       +'<input class="inp inp-s" id="'+prefix+i+'" type="number" min="0" max="110" inputmode="numeric" placeholder="Age"'+v+'></p>';
    }
    container.innerHTML=s;
  }
  function readAges(prefix,n){
    var out=[];
    for(var i=1;i<=n;i++){ var el=document.getElementById(prefix+i); out.push(el&&el.value?el.value:''); }
    return out;
  }
  function syncTrav(){
    document.getElementById('tOut').value=travellers;
    travText.textContent=travellers===1?'1 traveller':travellers+' travellers';
    document.getElementById('travOut').value=travText.textContent;
    ageInputs(document.getElementById('qbAges'),'qba',travellers,readAges('qba',travellers));
    ageInputs(document.getElementById('ageFields'),'age',travellers,readAges('age',travellers));
  }
  function popOpen(on){ travPop.hidden=!on; travBtn.setAttribute('aria-expanded',String(on)); }
  travBtn.addEventListener('click',function(){ popOpen(travPop.hidden); });
  document.getElementById('travDone').addEventListener('click',function(){ popOpen(false); travBtn.focus(); });
  document.addEventListener('click',function(e){ if(!travPop.hidden&&!e.target.closest('#travPop')&&!e.target.closest('#travBtn')) popOpen(false); });
  document.getElementById('tInc').addEventListener('click',function(){ if(travellers<6){travellers++;syncTrav();} });
  document.getElementById('tDec').addEventListener('click',function(){ if(travellers>1){travellers--;syncTrav();} });
  document.getElementById('inc').addEventListener('click',function(){ if(travellers<6){travellers++;syncTrav();} });
  document.getElementById('dec').addEventListener('click',function(){ if(travellers>1){travellers--;syncTrav();} });
  syncTrav();

  /* ---------- quote modal ---------- */
  var ov=document.getElementById('ov'),modal=document.getElementById('modal'),form=document.getElementById('qForm');
  var titles=['Tell us about your trip','Who is travelling?','Your quotes are ready'];
  var step=1,lastFocus=null;
  function show(n){
    step=n;
    document.getElementById('qTitle').textContent=titles[n-1];
    Array.prototype.forEach.call(form.querySelectorAll('[data-step]'),function(p){ p.hidden=Number(p.getAttribute('data-step'))!==n; });
    Array.prototype.forEach.call(document.querySelectorAll('#prog li'),function(li){
      var s=Number(li.getAttribute('data-s'));
      li.className=s<n?'done':(s===n?'now':'');
      li.querySelector('.pn').innerHTML=s<n?'<svg class="ico w xs"><use href="#i-check"></use></svg>':String(s);
    });
    modal.scrollTop=0;
  }
  function openQ(){
    lastFocus=document.activeElement;
    ov.hidden=false; document.body.style.overflow='hidden'; show(1);
    setTimeout(function(){ document.getElementById('m-dest').focus(); },60);
  }
  function closeQ(){ ov.hidden=true; document.body.style.overflow=''; if(lastFocus&&lastFocus.focus) lastFocus.focus(); }
  Array.prototype.forEach.call(document.querySelectorAll('[data-quote]'),function(b){ b.addEventListener('click',openQ); });
  document.getElementById('qClose').addEventListener('click',closeQ);
  ov.addEventListener('mousedown',function(e){ if(e.target===ov) closeQ(); });

  function val(id){ var el=document.getElementById(id); return el?String(el.value||'').trim():''; }
  function quoteURL(){
    var q=[], add=function(k,v){ if(v) q.push(encodeURIComponent(k)+'='+encodeURIComponent(v)); };
    var dest=val('m-dest');
    add('presection',presectionFor(dest,val('m-purp'),travellers));
    add(PARAMS.destination,dest);
    add(PARAMS.start,val('m-start'));
    add(PARAMS.end,val('m-end'));
    add(PARAMS.travellers,travellers);
    add(PARAMS.ages,readAges('age',travellers).filter(Boolean).join(','));
    add(PARAMS.citizenship,val('m-cit'));
    add(PARAMS.residence,val('m-res'));
    add(PARAMS.name,val('m-name'));
    add(PARAMS.email,val('m-mail'));
    var d=document.getElementById('m-dial');
    add(PARAMS.phone,val('m-tel')?((d?d.value:'')+' '+val('m-tel')).trim():'');
    add(PARAMS.purpose,val('m-purp'));
    var pre=form.querySelector('[data-pre].on');
    add(PARAMS.pre,pre?pre.getAttribute('data-pre'):'');
    add(PARAMS.source,'landing-page');
    return QUOTE_URL+(q.length?('?'+q.join('&')):'');
  }
  function goQuotes(){
    var url=quoteURL();
    /* Keep a copy of what the traveller entered, so the quote page (or a bridge
       script on that domain) can read it if query params are not enough. */
    try{
      sessionStorage.setItem('p360_quote',JSON.stringify({
        destination:val('m-dest'),start:val('m-start'),end:val('m-end'),
        travellers:travellers,ages:readAges('age',travellers),
        citizenship:val('m-cit'),residence:val('m-res'),name:val('m-name'),
        email:val('m-mail'),phone:val('m-tel'),purpose:val('m-purp'),at:Date.now()
      }));
    }catch(e){}
    document.getElementById('qGo').setAttribute('href',url);
    show(3);
    setTimeout(function(){ window.location.assign(url); },700);
  }

  /* search bar → modal (prefilled) or straight to quotes */
  document.getElementById('qbar').addEventListener('submit',function(e){
    e.preventDefault();
    var dest=val('qb-dest'), s=val('qb-start'), en=val('qb-end');
    if(dest) document.getElementById('m-dest').value=dest;
    if(s) document.getElementById('m-start').value=s;
    if(en) document.getElementById('m-end').value=en;
    var cit=val('qb-cit'); if(cit) document.getElementById('m-cit').value=cit;
    var qa=readAges('qba',travellers);
    for(var i=1;i<=travellers;i++){ var t=document.getElementById('age'+i); if(t&&qa[i-1]) t.value=qa[i-1]; }
    if(dest&&s&&en&&qa.filter(Boolean).length===travellers){ openQ(); goQuotes(); }
    else { openQ(); }
  });

  form.addEventListener('click',function(e){
    if(e.target.closest('[data-next]')) show(Math.min(3,step+1));
    if(e.target.closest('[data-back]')) show(Math.max(1,step-1));
    var pre=e.target.closest('[data-pre]');
    if(pre){ Array.prototype.forEach.call(form.querySelectorAll('[data-pre]'),function(b){ var on=b===pre; b.classList.toggle('on',on); b.setAttribute('aria-pressed',String(on)); }); }
  });
  form.addEventListener('submit',function(e){ e.preventDefault(); goQuotes(); });

  /* ---------- consultation popup (form -> WhatsApp) ---------- */
  var wel=document.getElementById('welOv');
  var welForm=document.getElementById('welForm');
  var welThanks=document.getElementById('welThanks');
  function cval(id){ var el=document.getElementById(id); return el?String(el.value).trim():''; }
  function openWel(){ if(!ov.hidden) return; welForm.hidden=false; welThanks.hidden=true; wel.hidden=false; document.body.style.overflow='hidden'; var _f=document.getElementById('waFab'); if(_f)_f.classList.add('wafab-right'); try{document.getElementById('c-name').focus();}catch(e){} }
  function closeWel(){ wel.hidden=true; if(ov.hidden) document.body.style.overflow=''; welForm.hidden=false; welThanks.hidden=true; var _f=document.getElementById('waFab'); if(_f)_f.classList.remove('wafab-right'); }
  document.getElementById('welClose').addEventListener('click',closeWel);
  wel.addEventListener('mousedown',function(e){ if(e.target===wel) closeWel(); });

  /* placeholder options for the two country dropdowns */
  [['c-country','Country'],['c-travel','Travel to']].forEach(function(p){
    var s=document.getElementById(p[0]); if(!s) return;
    var o=document.createElement('option'); o.value=''; o.textContent=p[1];
    o.disabled=true; o.selected=true; o.hidden=true;
    s.insertBefore(o,s.firstChild); s.value='';
  });

  welForm.addEventListener('submit',function(e){
    e.preventDefault();
    if(!welForm.checkValidity()){ welForm.reportValidity(); return; }
    var lines=['Hello! I would like a travel insurance consultation.','',
      'Name: '+cval('c-name'),
      'Country: '+cval('c-country'),
      'Mobile: '+cval('c-dial')+' '+cval('c-tel'),
      'Email: '+cval('c-mail'),
      'Travel to: '+cval('c-travel')];
    var url='https://api.whatsapp.com/send/?phone=918019111360&text='+encodeURIComponent(lines.join('\n'));
    document.getElementById('waBtn').setAttribute('href',url);
    welForm.hidden=true; welThanks.hidden=false;
  });

  /* auto-open exactly 7 seconds after load (once per session) */
  try{
    if(!sessionStorage.getItem('welShown')){
      setTimeout(function(){ openWel(); sessionStorage.setItem('welShown','1'); },7000);
    }
  }catch(err){
    setTimeout(openWel,7000);
  }
  Array.prototype.forEach.call(document.querySelectorAll('[data-consult]'),function(b){
    b.addEventListener('click',openWel);
  });

  /* ---------- "We're here to help you" expert form ---------- */
  (function(){
    var xf=document.getElementById('expertForm'); if(!xf) return;

    /* generic flag+search dropdown helper */
    function combo(ids,build,onPick){
      var box=document.getElementById(ids.box),btn=document.getElementById(ids.btn),
          pop=document.getElementById(ids.pop),search=document.getElementById(ids.search),
          list=document.getElementById(ids.list);
      function draw(q){
        q=(q||'').toLowerCase().replace(/\+/g,'').trim();
        var rows=COUNTRIES.filter(function(c){ return !q || c.name.toLowerCase().indexOf(q)>-1 || c.dial.indexOf(q)>-1; });
        list.innerHTML=rows.map(build).join('') || '<li style="justify-content:center;color:var(--slate);cursor:default">No match</li>';
      }
      function toggle(open){ pop.hidden=!open; btn.setAttribute('aria-expanded',String(open)); if(open){ search.value=''; draw(''); setTimeout(function(){search.focus();},20); } }
      btn.addEventListener('click',function(){ toggle(pop.hidden); });
      search.addEventListener('input',function(){ draw(search.value); });
      list.addEventListener('click',function(e){ var li=e.target.closest('li[data-val]'); if(!li) return; onPick(li); toggle(false); });
      document.addEventListener('click',function(e){ if(!box.contains(e.target)) toggle(false); });
      draw('');
    }

    /* mobile: flag + country code */
    var fEl=document.getElementById('x-itel-flag'),cEl=document.getElementById('x-itel-code'),dial=document.getElementById('x-dial');
    combo({box:'x-itel',btn:'x-itel-btn',pop:'x-itel-pop',search:'x-itel-search',list:'x-itel-list'},
      function(c){ return '<li role="option" data-val="+'+c.dial+'" data-flag="'+flag(c.iso)+'"><span class="itel-fl">'+flag(c.iso)+'</span><span class="itel-nm">'+c.name+'</span><span class="itel-dl">+'+c.dial+'</span></li>'; },
      function(li){ cEl.textContent=li.getAttribute('data-val'); fEl.textContent=li.getAttribute('data-flag'); dial.value=li.getAttribute('data-val'); document.getElementById('x-tel').focus(); });

    /* destination: searchable country picker */
    var dVal=document.getElementById('x-idest-val'),dInput=document.getElementById('x-dest'),dBtn=document.getElementById('x-idest-btn');
    combo({box:'x-idest',btn:'x-idest-btn',pop:'x-idest-pop',search:'x-idest-search',list:'x-idest-list'},
      function(c){ return '<li role="option" data-val="'+c.name+'"><span class="itel-fl">'+flag(c.iso)+'</span><span class="itel-nm">'+c.name+'</span></li>'; },
      function(li){ var nm=li.getAttribute('data-val'); dVal.textContent=nm; dVal.classList.remove('ph'); dInput.value=nm; dBtn.classList.remove('invalid'); });

    /* Submit: record the enquiry first, then offer WhatsApp.
       The original only built a WhatsApp link, so an enquiry existed nowhere until the person
       actually sent that message. Now it lands in the same inbox CS already works from and the
       WhatsApp hand-off is a convenience on top. */
    xf.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!xf.checkValidity()) { xf.reportValidity(); return; }
      if (!dInput.value) { dBtn.classList.add('invalid'); dBtn.focus(); return; }

      var phone = cval('x-dial') + ' ' + cval('x-tel');
      var lines = ['Hello! I would like to discuss travel insurance with an expert.', '',
        'Name: ' + cval('x-name'),
        'Email: ' + cval('x-mail'),
        'Mobile: ' + phone,
        'Destination: ' + cval('x-dest')];
      var wa = (xf.getAttribute('data-wa') || '').replace(/[^0-9]/g, '');
      if (wa) {
        document.getElementById('x-waBtn').setAttribute('href',
          'https://api.whatsapp.com/send/?phone=' + wa + '&text=' + encodeURIComponent(lines.join(String.fromCharCode(10))));
      }

      var btn = xf.querySelector('.xbtn'); if (btn) btn.disabled = true;
      function done() {
        xf.hidden = true;
        var th = document.getElementById('expertThanks');
        th.hidden = false;
        th.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
      var body = { name: cval('x-name'), email: cval('x-mail'), phone: phone, destination: cval('x-dest') };
      var req = window.apiFetch
        ? window.apiFetch('/api/insurance-enquiry', { method: 'POST', body: JSON.stringify(body) })
        : fetch((window.APP_ROOT || '') + '/api/insurance-enquiry', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': (document.querySelector('meta[name=csrf-token]') || {}).content || ''
            },
            body: JSON.stringify(body)
          });
      // The thank-you shows either way: a failed write is ours to chase in the logs, not a dead
      // end for somebody who has already typed their details in.
      req.then(done, done);
    });
  })();

  document.addEventListener('keydown',function(e){
    if(e.key!=='Escape') return;
    if(!ov.hidden) closeQ(); else if(!wel.hidden) closeWel(); else if(!travPop.hidden) popOpen(false);
  });
})();
