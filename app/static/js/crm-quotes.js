/* Quotes & payments card (lead page). "Copy text" copies the words; "Put in the message box" fills the
   lead's message box with them -- the agent still reads, edits and presses Send. Nothing here sends anything. */
(function () {
  'use strict';
  function toast(msg, bad) {
    if (window.CRM && window.CRM.toast) { window.CRM.toast(msg, bad); return; }
    window.alert(msg);
  }
  function copy(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var ta = document.createElement('textarea');
      ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy') ? resolve() : reject(); } catch (e) { reject(e); }
      document.body.removeChild(ta);
    });
  }
  function noCopy() { toast('Could not copy. Select the text and copy it by hand.', true); }
  document.addEventListener('click', function (e) {
    var c = e.target.closest('[data-qp-copy]');
    if (c) {
      copy(c.getAttribute('data-text') || '').then(function () { toast('Copied'); }, noCopy);
      return;
    }
    var b = e.target.closest('[data-qp-box]');
    if (b) {
      // the box is in the Conversation tab: open it first (crm.js)
      if (window.CRM && window.CRM.showPane) window.CRM.showPane('conversation');
      var box = document.getElementById('box');
      var ta = box && box.querySelector('[data-box-input]');
      var text = b.getAttribute('data-text') || '';
      if (!ta) { copy(text).then(function () { toast('There is no message box here, so the text was copied.'); }, noCopy); return; }
      var modeText = box.querySelector('[data-box-mode="text"]');
      if (modeText && !modeText.hidden) modeText.click();
      ta.value = ta.value.trim() ? ta.value.replace(/\s+$/, '') + '\n\n' + text : text;
      box.scrollIntoView({ behavior: 'smooth', block: 'center' });
      if (ta.offsetParent === null) {
        copy(text).then(function () { toast('The message box is not open for this chat, so the text was copied.'); }, noCopy);
      } else { ta.focus(); toast('In the message box. Check it, then press Send.'); }
    }
  });
})();
