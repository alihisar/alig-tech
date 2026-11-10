/* alig.tech portal demosu: onay kuyrugu ve SHA-256 zincirli denetim kaydi. ES5, bagimlilik yok. */
(function () {
  'use strict';
  var root = document.getElementById('portal');
  if (!root) { return; }
  function d(n) { return root.getAttribute('data-' + n) || ''; }
  var canHash = !!(window.crypto && window.crypto.subtle && window.TextEncoder);
  var chainEl = document.getElementById('chain');
  var statusEl = document.getElementById('aud-status');
  var tamperBtn = document.getElementById('tamper');
  var queue = document.getElementById('queue');
  var entries = [];
  var tampered = false;
  var chainJob = Promise.resolve();

  function sha(t) {
    return window.crypto.subtle.digest('SHA-256', new TextEncoder().encode(t)).then(function (b) {
      var a = new Uint8Array(b), s = '', i;
      for (i = 0; i < a.length; i++) { s += (a[i] < 16 ? '0' : '') + a[i].toString(16); }
      return s;
    });
  }
  function payload(e) { return [e.seq, e.actor, e.text, e.prev].join('|'); }
  function pad(n) { return n < 10 ? '0' + n : '' + n; }
  function stamp() { var t = new Date(); return pad(t.getUTCHours()) + ':' + pad(t.getUTCMinutes()) + ':' + pad(t.getUTCSeconds()) + 'Z'; }

  function render(badSeq) {
    chainEl.innerHTML = '';
    entries.forEach(function (e) {
      var li = document.createElement('li');
      if (badSeq === e.seq) { li.className = 'bad'; }
      var a = document.createElement('span'); a.textContent = '#' + e.seq + ' ' + e.time;
      var b = document.createElement('span'); b.textContent = e.actor + ': ' + e.text;
      var h = document.createElement('span'); h.className = 'c-h'; h.textContent = e.hash ? e.hash.slice(0, 16) : '';
      li.appendChild(a); li.appendChild(b); li.appendChild(h);
      chainEl.appendChild(li);
    });
  }
  function verify() {
    if (!canHash) { statusEl.className = 'aud-status'; statusEl.textContent = d('nohash'); return Promise.resolve(); }
    return Promise.all(entries.map(function (e, i) {
      return sha(payload(e)).then(function (h) {
        return h === e.hash && (i === 0 ? e.prev === '' : e.prev === entries[i - 1].hash);
      });
    })).then(function (res) {
      var bad = -1, i;
      for (i = 0; i < res.length; i++) { if (!res[i]) { bad = entries[i].seq; break; } }
      render(bad);
      statusEl.className = 'aud-status' + (bad > 0 ? ' bad' : '');
      statusEl.textContent = bad > 0 ? d('bad') + ' #' + bad : d('ok');
    });
  }
  function add(actor, text) {
    chainJob = chainJob.then(function () {
      var e = { seq: entries.length + 1, time: stamp(), actor: actor, text: text, prev: entries.length ? entries[entries.length - 1].hash : '', hash: '' };
      return (canHash ? sha(payload(e)) : Promise.resolve('')).then(function (h) { e.hash = h; entries.push(e); return verify(); });
    });
    return chainJob;
  }
  function pending() { return queue.querySelectorAll('.prop:not(.done)').length; }
  function decide(li, kind) {
    var v = li.querySelector('.verdict');
    li.className += ' done';
    li.querySelector('.btns').hidden = true;
    v.hidden = false;
    v.textContent = (kind === 'ok' ? d('e-ok') : d('e-no'));
    add(d('actor-you'), li.getAttribute('data-title') + ': ' + (kind === 'ok' ? d('e-ok') : d('e-no')));
    if (!pending()) { document.getElementById('queue-empty').hidden = false; }
  }
  Array.prototype.forEach.call(queue.querySelectorAll('button[data-act]'), function (btn) {
    btn.addEventListener('click', function () {
      var li = btn; while (li && li.className.indexOf('prop') < 0) { li = li.parentNode; }
      decide(li, btn.getAttribute('data-act'));
    });
  });
  function setTamperLabel() { tamperBtn.textContent = tampered ? d('btn-restore') : d('btn-tamper'); }
  tamperBtn.addEventListener('click', function () {
    chainJob = chainJob.then(function () {
      if (!entries.length) { return; }
      var e = entries[0];
      if (!tampered) { e.orig = e.text; e.text = e.text + ' (!)'; } else { e.text = e.orig; }
      tampered = !tampered; setTamperLabel();
      return verify();
    });
  });
  document.documentElement.className += ' demo-ready';
  setTamperLabel();
  add(d('actor-agent'), d('e-start'));
}());
