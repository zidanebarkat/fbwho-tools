/* Dashboard — stream key generation + copy */
var keyData = null;
var keyMasked = true;

function csrfHeaders() {
  var t = document.querySelector('meta[name="csrf-token"]');
  return t ? {'X-CSRF-Token': t.getAttribute('content')} : {};
}

function maskKey(k) {
  if (!k || k.length <= 8) return '••••••••';
  return k.substring(0, 4) + '••••' + k.substring(k.length - 4);
}

function toggleKeyMask() {
  keyMasked = !keyMasked;
  var el = $('#keyStream');
  var btn = $('#keyToggle');
  if (keyMasked) {
    el.textContent = maskKey(keyData.stream_key);
    btn.textContent = 'show';
  } else {
    el.textContent = keyData.stream_key;
    btn.textContent = 'hide';
  }
}

function $(s) { return document.querySelector(s) }

function lg(m, t) {
  var d = document.createElement('div');
  d.className = 'log' + t;
  d.textContent = '[' + new Date().toLocaleTimeString() + '] ' + m;
  var lb = $('#lb');
  lb.appendChild(d);
  lb.scrollTop = lb.scrollHeight;
  if (lb.children.length > 100) lb.removeChild(lb.firstChild);
}

function getKey() {
  var btn = $('#getKeyBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class=spinner></span> Creating room...';
  lg('Creating live room...', 'info');
  fetch('/api/room/create', {method: 'POST', headers: Object.assign({'Content-Type': 'application/json'}, csrfHeaders()), body: JSON.stringify({})})
    .then(function(r) { return r.json() })
    .then(function(d) {
      if (d.ok) {
        keyData = d;
        keyMasked = true;
        $('#keyServer').textContent = d.server_url;
        $('#keyStream').textContent = maskKey(d.stream_key);
        $('#keyToggle').textContent = 'show';
        $('#keyRtmp').textContent = d.rtmp_url;
        $('#keyRoom').textContent = d.room_id;
        $('#keyBox').style.display = '';
        $('#keyActions').style.display = '';
        $('#goLiveCard').style.display = '';
        btn.innerHTML = '🔄 New Key';
        btn.disabled = false;
        lg('Stream key ready!', 'ok');
      } else {
        lg('Failed: ' + d.error, 'err');
        btn.innerHTML = '🔑 Get Key';
        btn.disabled = false;
      }
    })
    .catch(function(e) {
      lg('Error: ' + e.message, 'err');
      btn.innerHTML = '🔑 Get Key';
      btn.disabled = false;
    });
}

function copyKey() {
  if (!keyData) return;
  navigator.clipboard.writeText(keyData.stream_key);
  lg('Stream key copied', 'ok');
}

function copyRTMP() {
  if (!keyData) return;
  navigator.clipboard.writeText(keyData.rtmp_url);
  lg('RTMP URL copied', 'ok');
}

function copyAll() {
  if (!keyData) return;
  var t = 'Server: ' + keyData.server_url + '\nKey: ' + keyData.stream_key + '\nRTMP: ' + keyData.rtmp_url + '\nRoom: ' + keyData.room_id;
  navigator.clipboard.writeText(t);
  lg('All info copied', 'ok');
}
