/* Files card (lead page and contact page): drag files onto the box, or pick them; they upload at once.
   Without JavaScript the box is a normal file picker with an Upload button. */
(function () {
  'use strict';
  document.querySelectorAll('[data-files-form]').forEach(function (form) {
    var drop = form.querySelector('[data-files-drop]');
    var input = form.querySelector('[data-files-input]');
    var go = form.querySelector('[data-files-go]');
    if (!drop || !input) return;
    if (go) go.hidden = true;
    ['dragenter', 'dragover'].forEach(function (ev) {
      drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add('over'); });
    });
    ['dragleave', 'drop'].forEach(function (ev) {
      drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove('over'); });
    });
    drop.addEventListener('drop', function (e) {
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
        input.files = e.dataTransfer.files;
        form.submit();
      }
    });
    input.addEventListener('change', function () { if (input.files.length) form.submit(); });
  });
})();
