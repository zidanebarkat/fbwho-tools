/* Dashboard — stream key generation + copy */
var keyData = null;

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
  fetch('/api/room/create', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({})})
    .then(function(r) { return r.json() })
    .then(function(d) {
      if (d.ok) {
        keyData = d;
        $('#keyServer').textContent = d.server_url;
        $('#keyStream').textContent = d.stream_key;
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
