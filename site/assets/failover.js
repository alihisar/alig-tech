/* alig.tech ana sayfa konsolu: failover ornegi ve hash zincirli denetim kaydi.
   Hicbir ag istegi yapmaz. JavaScript kapaliyken sayfa son durumu gosterir. */
(function () {
  'use strict';

  var root = document.getElementById('console');
  if (!root) return;

  var reduce = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  var steps = Array.prototype.slice.call(root.querySelectorAll('.timeline li'));
  var chainEl = document.getElementById('chain');
  var statusEl = document.getElementById('aud-status');
  var tamperBtn = document.getElementById('aud-tamper');
  var stopBtn = document.getElementById('con-stop');
  var canHash = !!(window.crypto && window.crypto.subtle && window.TextEncoder);
  var ZERO = new Array(65).join('0');
  var STEP_MS = 700;

  var entries = [];
  var queue = Promise.resolve();
  var gen = 0;
  var timer = null;
  var tampered = false;
  var original = '';

  function d(name) { return root.getAttribute('data-' + name) || ''; }
  function setState(s) { root.setAttribute('data-state', s); }
  function setTable(t) { root.setAttribute('data-table', t); }

  function focusEl(el) {
    if (!el) return;
    el.setAttribute('tabindex', '-1');
    el.focus({ preventScroll: true });
  }

  function sha(text) {
    return window.crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)).then(function (buf) {
      var bytes = new Uint8Array(buf);
      var out = '';
      for (var i = 0; i < bytes.length; i++) out += ('0' + bytes[i].toString(16)).slice(-2);
      return out;
    });
  }

  function payload(e) { return [e.seq, e.actor, e.text, e.prev].join('|'); }

  function renderEntry(e) {
    var li = document.createElement('li');
    var parts = [
      ['c-n', String(e.seq)],
      ['c-a', e.actor],
      ['c-x', e.text]
    ];
    parts.forEach(function (p) {
      var s = document.createElement('span');
      s.className = p[0];
      s.textContent = p[1];
      li.appendChild(s);
    });
    var h = document.createElement('span');
    h.className = 'c-h';
    var code = document.createElement('code');
    code.textContent = canHash ? e.hash.slice(0, 16) : d('nohash');
    h.appendChild(code);
    li.appendChild(h);
    chainEl.appendChild(li);
  }

  function verify() {
    if (!canHash) {
      statusEl.textContent = d('nohash-note');
      return Promise.resolve();
    }
    var items = chainEl.children;
    return Promise.all(entries.map(function (e) {
      return sha(payload(e)).then(function (h) { return h === e.hash; });
    })).then(function (res) {
      var bad = 0;
      res.forEach(function (ok, i) {
        if (items[i]) items[i].classList.toggle('bad', !ok);
        if (!ok && !bad) bad = i + 1;
      });
      statusEl.textContent = bad ? d('audit-broken').replace('{n}', String(bad)) : d('audit-ok');
      statusEl.classList.toggle('bad', !!bad);
    });
  }

  function addEntry(actorKey, text) {
    var myGen = gen;
    queue = queue.then(function () {
      if (myGen !== gen) return null;
      var prev = entries.length ? entries[entries.length - 1].hash : ZERO;
      var e = { seq: entries.length + 1, actor: d('actor-' + actorKey), text: text, prev: prev, hash: '' };
      return (canHash ? sha(payload(e)) : Promise.resolve('')).then(function (h) {
        if (myGen !== gen) return;
        e.hash = h;
        entries.push(e);
        renderEntry(e);
        return verify();
      });
    });
  }

  function resetAudit() {
    gen += 1;
    entries = [];
    queue = Promise.resolve();
    tampered = false;
    original = '';
    while (chainEl.firstChild) chainEl.removeChild(chainEl.firstChild);
    statusEl.textContent = '';
    statusEl.classList.remove('bad');
    tamperBtn.textContent = d('btn-tamper');
    tamperBtn.hidden = !canHash;
  }

  function toggleTamper() {
    if (entries.length < 2) return;
    var e = entries[1];
    if (!tampered) {
      original = e.text;
      e.text = d('ev-forged');
      tampered = true;
      tamperBtn.textContent = d('btn-restore');
    } else {
      e.text = original;
      tampered = false;
      tamperBtn.textContent = d('btn-tamper');
    }
    chainEl.children[1].querySelector('.c-x').textContent = e.text;
    verify();
  }

  function init() {
    window.clearTimeout(timer);
    resetAudit();
    steps.forEach(function (li) { li.classList.remove('on'); });
    root.removeAttribute('data-decision');
    setTable('before');
    setState('idle');
  }

  function finish() {
    setState('done');
    addEntry('agent', d('ev-finding'));
  }

  function run() {
    resetAudit();
    root.removeAttribute('data-decision');
    steps.forEach(function (li) { li.classList.remove('on'); });
    setTable('before');
    setState('run');
    focusEl(root.querySelector('.stream h3'));
    var i = 0;
    (function next() {
      if (i >= steps.length) { finish(); return; }
      var li = steps[i++];
      li.classList.add('on');
      var ev = li.getAttribute('data-ev');
      if (ev) addEntry('system', d('ev-' + ev));
      if (li.getAttribute('data-swap')) setTable('after');
      timer = window.setTimeout(next, reduce ? 0 : STEP_MS);
    })();
  }

  function decide(kind) {
    root.setAttribute('data-decision', kind);
    setState('decided');
    addEntry('you', d(kind === 'approved' ? 'ev-approved' : 'ev-rejected'));
    focusEl(root.querySelector('.decision'));
  }

  stopBtn.addEventListener('click', run);
  document.getElementById('con-reset').addEventListener('click', function () {
    init();
    stopBtn.focus();
  });
  document.getElementById('con-approve').addEventListener('click', function () { decide('approved'); });
  document.getElementById('con-reject').addEventListener('click', function () { decide('rejected'); });
  tamperBtn.addEventListener('click', toggleTamper);

  init();
})();
