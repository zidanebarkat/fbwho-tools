/* Stream form — go-live page logic */
var keyData = null;
function csrfHeaders() {
  var t = document.querySelector('meta[name="csrf-token"]');
  return t ? {'X-CSRF-Token': t.getAttribute('content')} : {};
}

function $(s) { return document.querySelector(s) }

function getKey() {
  return fetch('/api/room/create', {method: 'POST', headers: Object.assign({'Content-Type': 'application/json'}, csrfHeaders()), body: JSON.stringify({})})
    .then(function(r) { return r.json() })
    .then(function(d) {
      if (d.ok) {
        keyData = d;
        $('#rtmpUrl').value = d.rtmp_url;
        $('#streamKey').value = d.stream_key;
      }
      return d;
    });
}

function saveSettings() {
  var data = {
    source_url: $('#sourceUrl').value,
    github_pat: $('#githubPat').value,
    cookies_b64: $('#cookiesB64').value,
    preview: $('#previewMode').value
  };
  return fetch('/api/stream/save', {method: 'POST', headers: Object.assign({'Content-Type': 'application/json'}, csrfHeaders()), body: JSON.stringify(data)})
    .then(function(r) { return r.json() });
}

function saveOnly() {
  saveSettings().then(function(d) {
    if (d.ok) showStatus('Saved!', 'ok');
    else showStatus(d.error, 'err');
  });
}

function goLive() {
  var btn = $('#goLiveBtn');
  var src = $('#sourceUrl').value.trim();
  var pat = $('#githubPat').value.trim();
  if (!src) { showStatus('Enter a source URL', 'err'); return; }
  if (!pat) { showStatus('Enter GitHub PAT', 'err'); return; }

  btn.disabled = true;
  btn.innerHTML = '<span class=spinner></span> Getting key & triggering...';

  getKey().then(function(d) {
    if (!d.ok) {
      showStatus('Failed to get key: ' + d.error, 'err');
      btn.disabled = false;
      btn.innerHTML = '🚀 Push to Stream';
      return;
    }
    saveSettings().then(function() {
      var body = {
        stream_key: keyData.stream_key,
        rtmp_url: keyData.rtmp_url,
        source_url: src,
        github_pat: pat,
        cookies_b64: $('#cookiesB64').value,
        preview: $('#previewMode').value
      };
      return fetch('/api/golive', {method: 'POST', headers: Object.assign({'Content-Type': 'application/json'}, csrfHeaders()), body: JSON.stringify(body)});
    }).then(function(r) { return r.json() }).then(function(d) {
      if (d.ok) {
        showStatus('Workflow triggered! <a href="https://github.com/zidanebarkat/8dca7ff25e47b8cc0e104b9f-tt/actions" target="_blank" style="color:#60a5fa">View runs</a>', 'ok');
      } else {
        showStatus(d.error, 'err');
      }
      btn.disabled = false;
      btn.innerHTML = '🚀 Push to Stream';
    }).catch(function(e) {
      showStatus(e.message, 'err');
      btn.disabled = false;
      btn.innerHTML = '🚀 Push to Stream';
    });
  });
}

function showStatus(msg, type) {
  var box = $('#statusBox');
  box.style.display = '';
  box.className = 'status-box status-' + type;
  box.innerHTML = msg;
}

getKey();
