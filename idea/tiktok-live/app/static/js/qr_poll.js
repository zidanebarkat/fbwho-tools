/* QR Polling — handles QR generation, polling, session ID, cookie upload */
var qrData = null;
function csrfHeaders() {
  var t = document.querySelector('meta[name="csrf-token"]');
  return t ? {'X-CSRF-Token': t.getAttribute('content')} : {};
}

function showTab(t) {
  document.querySelectorAll('.tab').forEach(function(e) { e.classList.remove('active') });
  document.querySelectorAll('.panel').forEach(function(e) { e.classList.remove('active') });
  document.querySelector('[data-tab="' + t + '"]').classList.add('active');
  document.getElementById('t' + t.charAt(0).toUpperCase() + t.slice(1)).classList.add('active');
  if (t === 'qr' && !qrData) startQR();
}

function startQR() {
  document.getElementById('qrBox').innerHTML = '<div class=status><span class=spinner></span> Generating QR code...</div>';
  fetch('/api/qr/start', {method: 'POST', headers: csrfHeaders()}).then(function(r) { return r.json() }).then(function(d) {
    if (d.ok) {
      qrData = d;
      document.getElementById('qrBox').innerHTML =
        '<img src="data:image/png;base64,' + d.qrcode_base64 + '" style="width:200px;border-radius:8px">' +
        '<div style="color:#888;font-size:.75rem;margin-top:10px">Scan with TikTok app</div>';
      pollQR();
    } else {
      document.getElementById('qrBox').innerHTML = '<div class=error>' + d.error + '</div>';
    }
  }).catch(function(e) {
    document.getElementById('qrBox').innerHTML = '<div class=error>' + e.message + '</div>';
  });
}

function pollQR() {
  if (!qrData) return;
  fetch('/api/qr/poll', {
    method: 'POST',
    headers: Object.assign({'Content-Type': 'application/json'}, csrfHeaders()),
    body: JSON.stringify({token: qrData.token, device_id: qrData.device_id, domain: qrData.domain})
  }).then(function(r) { return r.json() }).then(function(d) {
    if (d.ok) {
      document.getElementById('qrBox').innerHTML = '<div class=ok>Logged in! Redirecting...</div>';
      setTimeout(function() { window.location.href = '/dashboard' }, 800);
    } else if (d.error && d.error.indexOf('expired') !== -1) {
      qrData = null;
      document.getElementById('qrBox').innerHTML =
        '<div class=error>QR expired</div>' +
        '<button class="btn btn-primary" onclick="startQR()" style="margin-top:10px">New QR Code</button>';
    } else {
      setTimeout(pollQR, 3000);
    }
  }).catch(function() { setTimeout(pollQR, 3000) });
}

function submitSession() {
  var v = document.getElementById('sessionInput').value.trim();
  if (!v) return;
  var cookies = {};
  v.split(';').forEach(function(p) {
    var parts = p.trim().split('=');
    if (parts.length >= 2) cookies[parts[0].trim()] = parts.slice(1).join('=').trim();
  });
  fetch('/api/sessionid', {
    method: 'POST',
    headers: Object.assign({'Content-Type': 'application/json'}, csrfHeaders()),
    body: JSON.stringify({sessionid: cookies.sessionid || v})
  }).then(function(r) { return r.json() }).then(function(d) {
    if (d.ok) {
      document.getElementById('qrBox').innerHTML = '<div class=ok>Logged in as ' + d.nickname + '! Redirecting...</div>';
      setTimeout(function() { window.location.href = '/dashboard' }, 800);
    } else {
      alert(d.error);
    }
  }).catch(function(e) { alert(e.message) });
}

function uploadCookie() {
  var f = document.getElementById('cookieFile').files[0];
  if (!f) return;
  var r = new FileReader();
  r.onload = function() {
    fetch('/api/cookies', {
      method: 'POST',
      headers: Object.assign({'Content-Type': 'application/json'}, csrfHeaders()),
      body: JSON.stringify({cookies: r.result})
    }).then(function(r) { return r.json() }).then(function(d) {
      if (d.ok) {
        document.getElementById('qrBox').innerHTML = '<div class=ok>Logged in! Redirecting...</div>';
        setTimeout(function() { window.location.href = '/dashboard' }, 800);
      } else {
        alert(d.error);
      }
    }).catch(function(e) { alert(e.message) });
  };
  r.readAsText(f);
}

startQR();
