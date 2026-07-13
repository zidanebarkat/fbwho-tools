"""
Render Deploy: YouTube → Direct URL with Real-Time Progress
=============================================================
Deploy to Render (free, no credit card).
Panel: https://your-app.onrender.com/
"""

import os, subprocess, json, time, glob, hashlib, threading, re, shutil
from flask import Flask, request, jsonify, send_file

app = Flask(__name__)
VIDEO_DIR = '/tmp/videos'
COOKIE_FILE = '/tmp/cookies.txt'
os.makedirs(VIDEO_DIR, exist_ok=True)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# Auto-load cookies from env var (set COOKIES_B64 on Render once)
if not os.path.exists(COOKIE_FILE):
    b64 = os.environ.get('COOKIES_B64', '')
    if b64:
        import base64
        try:
            data = base64.b64decode(b64)
            with open(COOKIE_FILE, 'wb') as f:
                f.write(data)
            log(f"Cookies loaded from COOKIES_B64 env ({len(data)} bytes)")
        except Exception as e:
            log(f"Failed to decode COOKIES_B64: {e}")

download_progress = {}
progress_lock = threading.Lock()

DENO_PATHS = [
    os.path.expanduser('~/.deno/bin'),
    '/root/.deno/bin',
    '/usr/local/bin',
    '/usr/bin',
]

def find_deno():
    for p in DENO_PATHS:
        dp = os.path.join(p, 'deno')
        if os.path.exists(dp):
            return dp
    return shutil.which('deno')

def get_video_info(path):
    name = os.path.basename(path)
    size = os.path.getsize(path)
    return {'name': name, 'size_mb': round(size / 1024 / 1024, 1), 'url': f'/video/{name}'}


def run_download(task_id, url, output_path):
    global download_progress

    env = os.environ.copy()
    deno = find_deno()
    if deno:
        deno_dir = os.path.dirname(deno)
        env['PATH'] = deno_dir + ':' + env.get('PATH', '')
        env['DENO_INSTALL'] = os.path.dirname(deno_dir)
        log(f"Deno: {deno}")
    else:
        log("WARNING: deno not found!")

    cmd = [
        'yt-dlp',
        '--no-check-certificates',
        '--socket-timeout', '30',
        '-f', 'best[height<=480]/bestvideo[height<=480]+bestaudio/best',
        '--merge-output-format', 'mp4',
        '--remux-video', 'mp4',
        '--newline',
        '-o', output_path,
        '--no-part',
    ]

    if os.path.exists(COOKIE_FILE):
        cmd.extend(['--cookies', COOKIE_FILE])
        log(f"Using cookies: {os.path.getsize(COOKIE_FILE)} bytes")
    else:
        log("No cookies uploaded - YouTube may block")

    cmd.append(url)

    with progress_lock:
        download_progress[task_id] = {
            'status': 'starting', 'percent': 0, 'speed': '', 'eta': '',
            'size': '', 'filename': '', 'error': None,
        }

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env
        )

        all_lines = []
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            all_lines.append(line)
            log(f"yt-dlp: {line}")

            match = re.search(r'\[download\]\s+([\d.]+)%\s+of\s+~?([\d.]+\w+)\s+at\s+([\d.]+\w+/s)\s+ETA\s+(\S+)', line)
            if match:
                with progress_lock:
                    download_progress[task_id].update({
                        'status': 'downloading', 'percent': float(match.group(1)),
                        'size': match.group(2), 'speed': match.group(3), 'eta': match.group(4),
                    })
                continue

            match = re.search(r'\[download\]\s+100%\s+of\s+~?([\d.]+\w+)', line)
            if match:
                with progress_lock:
                    download_progress[task_id].update({
                        'status': 'merging', 'percent': 100, 'size': match.group(1),
                    })
                continue

            if '[Merger]' in line or 'merger' in line.lower():
                with progress_lock:
                    download_progress[task_id]['status'] = 'merging'

            match = re.search(r'\[download\]\s+Destination:\s+(.+)', line)
            if match:
                with progress_lock:
                    download_progress[task_id]['filename'] = match.group(1)

        proc.wait()

        if proc.returncode == 0 and os.path.exists(output_path):
            size_mb = round(os.path.getsize(output_path) / 1024 / 1024, 1)
            render_url = os.environ.get('RENDER_EXTERNAL_URL', '')
            video_url = f"{render_url}/video/{os.path.basename(output_path)}" if render_url else f"/video/{os.path.basename(output_path)}"
            with progress_lock:
                download_progress[task_id].update({
                    'status': 'done', 'percent': 100, 'size_mb': size_mb, 'video_url': video_url,
                })
            log(f"Downloaded: {os.path.basename(output_path)} ({size_mb} MB)")
            # cleanup partial files
            base = output_path.rsplit('.', 1)[0]
            for f in glob.glob(base + '.f*') + glob.glob(base + '.m4a') + glob.glob(base + '.part'):
                try: os.remove(f)
                except: pass
        else:
            # check if partial file exists (merge failed but video-only downloaded)
            partials = glob.glob(os.path.join(VIDEO_DIR, f'{url_hash}.f*.mp4'))
            if partials:
                partial = partials[0]
                os.rename(partial, output_path)
                size_mb = round(os.path.getsize(output_path) / 1024 / 1024, 1)
                render_url = os.environ.get('RENDER_EXTERNAL_URL', '')
                video_url = f"{render_url}/video/{os.path.basename(output_path)}" if render_url else f"/video/{os.path.basename(output_path)}"
                with progress_lock:
                    download_progress[task_id].update({
                        'status': 'done', 'percent': 100, 'size_mb': size_mb, 'video_url': video_url,
                    })
                log(f"Downloaded (no audio): {os.path.basename(output_path)} ({size_mb} MB)")
            else:
                error_lines = [l for l in all_lines if 'ERROR' in l]
                error_msg = error_lines[-1] if error_lines else ' | '.join(all_lines[-3:]) if all_lines else 'No output'
                with progress_lock:
                    download_progress[task_id].update({'status': 'error', 'error': error_msg})
                log(f"Failed: {error_msg}")

    except subprocess.TimeoutExpired:
        with progress_lock:
            download_progress[task_id].update({'status': 'error', 'error': 'Download timed out (240s)'})
    except Exception as e:
        with progress_lock:
            download_progress[task_id].update({'status': 'error', 'error': str(e)})


@app.route('/health')
def health():
    videos = glob.glob(os.path.join(VIDEO_DIR, '*.mp4'))
    deno = find_deno()
    has_cookies = os.path.exists(COOKIE_FILE)
    return jsonify({'ok': True, 'video_count': len(videos), 'deno': deno or 'not found', 'cookies': has_cookies})


@app.route('/api/upload_cookies', methods=['POST'])
def upload_cookies():
    if 'cookies' in request.files:
        f = request.files['cookies']
        f.save(COOKIE_FILE)
        size = os.path.getsize(COOKIE_FILE)
        log(f"Cookies uploaded: {size} bytes")
        return jsonify({'ok': True, 'size': size})

    data = request.get_json(force=True) if request.is_json else None
    if data and data.get('cookies'):
        with open(COOKIE_FILE, 'w') as f:
            f.write(data['cookies'])
        size = os.path.getsize(COOKIE_FILE)
        log(f"Cookies saved from text: {size} bytes")
        return jsonify({'ok': True, 'size': size})

    return jsonify({'ok': False, 'error': 'Send cookies as file or JSON {"cookies": "..."}'}), 400


@app.route('/api/cookies_b64')
def get_cookies_b64():
    import base64
    if not os.path.exists(COOKIE_FILE):
        return jsonify({'ok': False, 'error': 'No cookies uploaded'}), 404
    b64 = base64.b64encode(open(COOKIE_FILE, 'rb').read()).decode()
    return jsonify({'ok': True, 'b64': b64, 'size': len(b64)})


@app.route('/cookies_b64')
def cookies_b64_page():
    import base64
    if not os.path.exists(COOKIE_FILE):
        return '<html><body style="background:#0d1117;color:#c9d1d9;font-family:sans-serif;padding:40px;text-align:center"><h2>No cookies uploaded yet</h2><p>Go back, upload cookies.txt first.</p><a href="/" style="color:#58a6ff">Back to Panel</a></body></html>'
    b64 = base64.b64encode(open(COOKIE_FILE, 'rb').read()).decode()
    return f'''<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>COOKIES_B64</title></head>
<body style="background:#0d1117;color:#c9d1d9;font-family:sans-serif;padding:20px">
<div style="max-width:700px;margin:0 auto">
<h2 style="color:#f0f6fc;margin-bottom:16px">COOKIES_B64 Value</h2>
<p style="color:#8b949e;margin-bottom:8px">Copy this value and paste it as <code style="color:#58a6ff">COOKIES_B64</code> env var on Render.</p>
<textarea id="b64box" readonly style="width:100%;height:200px;background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:10px;font-size:12px;font-family:monospace;resize:vertical" onclick="this.select()">{b64}</textarea>
<br><br>
<button onclick="navigator.clipboard.writeText(document.getElementById('b64box').value).then(function(){{document.getElementById('msg').textContent='Copied!';setTimeout(function(){{document.getElementById('msg').textContent='';}},3000);}})" style="width:100%;padding:12px;background:#238636;color:#fff;border:none;border-radius:6px;font-size:16px;font-weight:600;cursor:pointer">Copy to Clipboard</button>
<p id="msg" style="color:#238636;margin-top:8px;min-height:20px"></p>
<br>
<a href="/" style="color:#58a6ff">Back to Panel</a>
</div></body></html>'''


@app.route('/api/cookies')
def check_cookies():
    if os.path.exists(COOKIE_FILE):
        size = os.path.getsize(COOKIE_FILE)
        return jsonify({'ok': True, 'exists': True, 'size': size})
    return jsonify({'ok': True, 'exists': False})


@app.route('/api/download', methods=['POST'])
def download():
    data = request.get_json(force=True)
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'ok': False, 'error': 'Missing "url"'}), 400

    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    output_path = os.path.join(VIDEO_DIR, f'{url_hash}.mp4')
    if os.path.exists(output_path):
        os.remove(output_path)

    task_id = url_hash
    log(f"Starting download: {url}")
    thread = threading.Thread(target=run_download, args=(task_id, url, output_path), daemon=True)
    thread.start()
    return jsonify({'ok': True, 'task_id': task_id})


@app.route('/api/progress/<task_id>')
def progress(task_id):
    with progress_lock:
        prog = download_progress.get(task_id)
    if not prog:
        return jsonify({'ok': False, 'error': 'Unknown task'}), 404
    return jsonify({'ok': True, **prog})


@app.route('/api/videos')
def list_videos():
    videos = [get_video_info(p) for p in sorted(glob.glob(os.path.join(VIDEO_DIR, '*.mp4')))]
    return jsonify({'ok': True, 'videos': videos, 'count': len(videos)})


@app.route('/api/videos/<name>', methods=['DELETE'])
def delete_video(name):
    path = os.path.join(VIDEO_DIR, name)
    if not os.path.exists(path):
        return jsonify({'ok': False, 'error': 'Not found'}), 404
    os.remove(path)
    log(f"Deleted: {name}")
    return jsonify({'ok': True})


@app.route('/video/<name>')
def serve_video(name):
    path = os.path.join(VIDEO_DIR, name)
    if not os.path.exists(path):
        return 'Not found', 404
    return send_file(path, mimetype='video/mp4')


@app.route('/api/search')
def search_yt():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'ok': False, 'error': 'Missing query'}), 400

    env = os.environ.copy()
    deno = find_deno()
    if deno:
        deno_dir = os.path.dirname(deno)
        env['PATH'] = deno_dir + ':' + env.get('PATH', '')

    cmd = [
        'yt-dlp', '--no-check-certificates', '--flat-playlist', '--dump-json',
        '--socket-timeout', '15',
        f'ytsearch8:{query}',
    ]
    if os.path.exists(COOKIE_FILE):
        cmd.extend(['--cookies', COOKIE_FILE])

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        results = []
        for line in proc.stdout.strip().split('\n'):
            if not line:
                continue
            try:
                info = json.loads(line)
                thumb = info.get('thumbnails', [{}])
                thumb_url = thumb[-1]['url'] if thumb else info.get('thumbnail', '')
                results.append({
                    'id': info.get('id', ''),
                    'title': info.get('title', 'Unknown'),
                    'duration': info.get('duration_string', str(info.get('duration', ''))),
                    'url': info.get('url', f"https://www.youtube.com/watch?v={info.get('id', '')}"),
                    'thumbnail': thumb_url,
                    'channel': info.get('channel', info.get('uploader', '')),
                    'views': info.get('view_count', 0),
                })
            except json.JSONDecodeError:
                continue
        return jsonify({'ok': True, 'results': results})
    except subprocess.TimeoutExpired:
        return jsonify({'ok': False, 'error': 'Search timed out'}), 504
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/')
def index():
    return PANEL_HTML


PANEL_HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>YouTube to Direct URL</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--text2:#8b949e;--green:#238636;--blue:#1f6feb;--red:#da3633;--accent:#58a6ff;--white:#f0f6fc}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;padding:12px;min-height:100vh}
.wrap{max-width:800px;margin:0 auto}
h1{font-size:clamp(16px,4vw,22px);margin-bottom:12px;color:var(--white);text-align:center}
.card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;margin-bottom:10px;min-width:0}
.card h2{font-size:13px;margin-bottom:8px;color:var(--text2);text-transform:uppercase;letter-spacing:.5px}
input[type=text]{width:100%;padding:10px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:14px}
.btn{padding:10px 16px;border:none;border-radius:6px;font-size:14px;font-weight:600;cursor:pointer;transition:background .2s}
.btn:disabled{opacity:.4;cursor:default}
.btn-g{background:var(--green);color:#fff;width:100%}.btn-g:hover:not(:disabled){background:#2ea043}
.btn-b{background:var(--blue);color:#fff;font-size:11px;padding:5px 10px}.btn-b:hover{background:#388bfd}
.btn-r{background:var(--red);color:#fff;font-size:11px;padding:5px 10px}.btn-r:hover{background:#f85149}
.btn-sm{font-size:11px;padding:4px 8px;border-radius:4px}
.cookie-btn{display:inline-block;padding:8px 20px;background:var(--blue);color:#fff;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer}
.cookie-btn:hover{background:#388bfd}
.pbar-wrap{display:none;border-radius:6px;overflow:hidden;margin:8px 0;background:#21262d;height:22px;position:relative}
.pbar-wrap.show{display:block}
.pbar{height:100%;width:0;background:var(--green);border-radius:6px;transition:width .3s}
.pbar.merge{background:var(--blue)}.pbar.done{background:var(--green)}.pbar.err{background:var(--red)}
.ptxt{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff}
.pinfo{display:none;justify-content:space-between;font-size:11px;color:var(--text2);margin-top:4px}
.result{margin-top:8px;padding:8px 10px;background:var(--bg);border:1px solid var(--border);border-radius:6px;display:none;word-break:break-all}
.result.show{display:block}.result.ok{border-color:var(--green)}.result.err{border-color:var(--red)}
.rurl{font-family:monospace;font-size:12px;color:var(--accent);word-break:break-all;cursor:pointer;user-select:all}
.errtxt{color:#f85149;font-size:11px;font-family:monospace;word-break:break-all}
.hint{margin-top:10px;padding:12px;background:var(--bg);border:1px solid #f0883e;border-radius:6px;font-size:12px;color:var(--text);line-height:1.5}
.hint b{color:#f0883e}
.hint code{color:var(--accent);background:#1c2128;padding:1px 4px;border-radius:3px;font-size:11px}
.hint .copy-btn{display:block;width:100%;margin-top:10px;padding:10px;background:var(--green);color:#fff;border:none;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer}
.hint .copy-btn:hover{background:#2ea043}
.hint .copy-msg{margin-top:6px;color:var(--green);font-size:11px;min-height:16px}
.srow{display:flex;gap:6px}.srow input{flex:1;margin-bottom:0}
.srow .btn{width:auto;flex-shrink:0;padding:10px 14px}
.sr{display:flex;gap:10px;padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:6px;margin-bottom:6px;cursor:pointer;transition:border-color .2s}
.sr:hover{border-color:var(--accent)}
.sr img{width:110px;height:62px;object-fit:cover;border-radius:4px;flex-shrink:0;background:#21262d}
.sr .si{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;overflow:hidden}
.sr .st{font-size:13px;color:var(--white);font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sr .sm{font-size:11px;color:var(--text2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sr .sd{font-size:11px;color:var(--text2);margin-top:auto}
.sr .sd b{color:var(--green)}
.vitem{display:flex;align-items:center;gap:10px;padding:10px;background:var(--bg);border:1px solid var(--border);border-radius:6px;margin-bottom:6px;min-width:0}
.vitem .vi{flex:1;min-width:0;overflow:hidden}
.vitem .vn{font-size:13px;color:var(--text);word-break:break-all}
.vitem .vs{font-size:11px;color:var(--text2)}
.vitem .vu{font-family:monospace;font-size:11px;color:var(--accent);word-break:break-all;cursor:pointer;user-select:all}
.vitem .va{display:flex;gap:4px;flex-shrink:0}
.empty{text-align:center;padding:16px;color:var(--text2);font-size:13px}
@media(max-width:480px){
  body{padding:8px}
  .card{padding:10px}
  input[type=text]{font-size:16px;padding:12px}
  .sr img{width:80px;height:45px}
  .sr .st{font-size:12px}
  .vitem{flex-wrap:wrap}
  .vitem .va{width:100%;justify-content:flex-end;margin-top:4px}
}
</style>
</head>
<body>
<div class="wrap">
<h1>YouTube to Direct URL</h1>

<div class="card">
<h2>Cookies</h2>
<div id="cookieStatus" style="margin-bottom:8px">Loading...</div>
<div id="cookieHint"></div>
<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
<div class="cookie-btn" onclick="document.getElementById('cookieInput').click()">Upload cookies.txt</div>
<a href="/cookies_b64" target="_blank" class="cookie-btn" style="background:#238636;text-decoration:none;color:#fff">Show COOKIES_B64</a>
</div>
<input type="file" id="cookieInput" accept=".txt" style="display:none">
</div>

<div class="card">
<h2>Download</h2>
<input type="text" id="urlInput" placeholder="Paste YouTube URL here...">
<button class="btn btn-g" id="btnDL" onclick="startDownload()">Download</button>
<div class="pbar-wrap" id="pbarBg"><div class="pbar" id="pbar"></div><div class="ptxt" id="ptxt">0%</div></div>
<div class="pinfo" id="pinfo"><span id="pSize">--</span><span id="pSpeed">--</span><span id="pEta">--</span></div>
<div class="result" id="resBox"><div id="resLabel"></div><div class="rurl" id="resUrl" onclick="copyUrl(this)"></div></div>
</div>

<div class="card">
<h2>Search YouTube</h2>
<div class="srow">
<input type="text" id="searchInput" placeholder="Search videos...">
<button class="btn btn-g" id="btnSearch" onclick="doSearch()">Search</button>
</div>
<div id="searchResults"></div>
</div>

<div class="card">
<h2>Videos (<span id="vcount">0</span>)</h2>
<div id="vlist"><div class="empty">No videos yet</div></div>
</div>
</div>
<script>
var curTask=localStorage.getItem('curTask')||null,pollTm=null,lastB64='';

function save(k,v){try{localStorage.setItem(k,v);}catch(e){}}
function load(k){try{return localStorage.getItem(k);}catch(e){return null;}}
function copyB64(){if(!lastB64)return;navigator.clipboard.writeText(lastB64);}

fetch('/api/cookies').then(function(r){return r.json();}).then(function(d){
  var el=document.getElementById('cookieStatus');
  el.innerHTML=d.exists?'<span style="color:#238636">Cookies loaded ('+d.size+' bytes)</span>':'<span style="color:#f0883e">No cookies - upload cookies.txt</span>';
}).catch(function(){});

document.getElementById('cookieInput').addEventListener('change',function(){
  var f=this.files[0];if(!f)return;
  var fd=new FormData();fd.append('cookies',f);
  fetch('/api/upload_cookies',{method:'POST',body:fd}).then(function(r){return r.json();}).then(function(d){
    if(!d.ok)return;
    document.getElementById('cookieStatus').innerHTML='<span style="color:#238636">Cookies saved ('+d.size+' bytes)</span>';
    document.getElementById('cookieHint').innerHTML='<div class="hint" style="border-color:#238636"><b style="color:#238636">Cookies uploaded!</b> Click <b>Show COOKIES_B64</b> above to get the env var value for Render.</div>';
  });
});

function startDownload(){
  var url=document.getElementById('urlInput').value.trim();
  if(!url)return;
  var btn=document.getElementById('btnDL');
  btn.disabled=true;btn.textContent='Starting...';
  document.getElementById('pbarBg').className='pbar-wrap show';
  document.getElementById('pinfo').style.display='flex';
  document.getElementById('pbar').className='pbar';
  document.getElementById('pbar').style.width='0%';
  document.getElementById('ptxt').textContent='Starting...';
  document.getElementById('pSize').textContent='--';
  document.getElementById('pSpeed').textContent='--';
  document.getElementById('pEta').textContent='--';
  document.getElementById('resBox').className='result';

  fetch('/api/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:url})})
  .then(function(r){return r.json();}).then(function(d){
    if(d.ok){curTask=d.task_id;save('curTask',curTask);btn.textContent='Downloading...';pollProg();}
    else{showErr(d.error||'Failed');}
  }).catch(function(e){showErr(e.message);});
}

function pollProg(){
  if(!curTask)return;
  pollTm=setInterval(function(){
    fetch('/api/progress/'+curTask).then(function(r){return r.json();}).then(function(d){
      if(!d.ok){if(d.error==='Unknown task'){clearInterval(pollTm);curTask=null;save('curTask','');resetUI();}return;}
      var pb=document.getElementById('pbar'),pt=document.getElementById('ptxt');
      document.getElementById('pbarBg').className='pbar-wrap show';
      document.getElementById('pinfo').style.display='flex';
      if(d.status==='downloading'){
        pb.style.width=d.percent+'%';pt.textContent=d.percent.toFixed(1)+'%';pb.className='pbar';
        document.getElementById('pSize').textContent=d.size||'--';
        document.getElementById('pSpeed').innerHTML=d.speed?'<b>'+d.speed+'</b>':'--';
        document.getElementById('pEta').textContent=d.eta?'ETA '+d.eta:'--';
      }else if(d.status==='merging'){
        pb.style.width='100%';pt.textContent='Merging...';pb.className='pbar merge';
      }else if(d.status==='done'){
        clearInterval(pollTm);
        pb.style.width='100%';pt.textContent='Done!';pb.className='pbar done';
        document.getElementById('pSize').textContent=d.size_mb+' MB';
        document.getElementById('pSpeed').textContent='';document.getElementById('pEta').textContent='';
        setTimeout(function(){document.getElementById('pinfo').style.display='none';},2000);
        document.getElementById('resBox').className='result show ok';
        document.getElementById('resLabel').textContent='Click URL to copy:';
        document.getElementById('resUrl').textContent=d.video_url;
        document.getElementById('btnDL').disabled=false;document.getElementById('btnDL').textContent='Download';
        curTask=null;save('curTask','');loadVids();
      }else if(d.status==='error'){showErr(d.error);}
    }).catch(function(){});
  },500);
}

function resetUI(){
  document.getElementById('btnDL').disabled=false;document.getElementById('btnDL').textContent='Download';
  document.getElementById('pbarBg').className='pbar-wrap';
  document.getElementById('pinfo').style.display='none';
  document.getElementById('resBox').className='result';
}

function showErr(msg){
  clearInterval(pollTm);
  var pb=document.getElementById('pbar');pb.style.width='100%';pb.className='pbar err';
  document.getElementById('ptxt').textContent='Error';
  document.getElementById('pinfo').style.display='none';
  document.getElementById('resBox').className='result show err';
  document.getElementById('resLabel').textContent='Error:';
  document.getElementById('resUrl').innerHTML='<span class="errtxt">'+msg+'</span>';
  document.getElementById('btnDL').disabled=false;document.getElementById('btnDL').textContent='Download';
  curTask=null;save('curTask','');
}

function loadVids(){
  fetch('/api/videos').then(function(r){return r.json();}).then(function(d){
    document.getElementById('vcount').textContent=d.count;
    var el=document.getElementById('vlist');
    if(!d.videos.length){el.innerHTML='<div class="empty">No videos yet</div>';return;}
    var h='';
    for(var i=0;i<d.videos.length;i++){
      var v=d.videos[i];
      h+='<div class="vitem"><div class="vi">';
      h+='<div class="vn">'+v.name+'</div>';
      h+='<div class="vs">'+v.size_mb+' MB</div>';
      h+='<div class="vu" onclick="copyUrl(this)">'+window.location.origin+v.url+'</div>';
      h+='</div><div class="va">';
      h+='<button class="btn btn-b btn-sm" onclick="copyUrl(this.closest(\'.vitem\').querySelector(\'.vu\'))">Copy</button> ';
      h+='<button class="btn btn-r btn-sm" onclick="delVid(\''+v.name+'\')">Delete</button>';
      h+='</div></div>';
    }
    el.innerHTML=h;
  }).catch(function(){});
}

function delVid(n){if(!confirm('Delete?'))return;fetch('/api/videos/'+n,{method:'DELETE'}).then(function(){loadVids();});}
function copyUrl(el){navigator.clipboard.writeText(el.textContent).then(function(){el.style.color='#238636';setTimeout(function(){el.style.color='';},800);});}
document.getElementById('urlInput').addEventListener('keydown',function(e){if(e.key==='Enter')startDownload();});
document.getElementById('searchInput').addEventListener('keydown',function(e){if(e.key==='Enter')doSearch();});

var savedUrl=load('urlInput');if(savedUrl)document.getElementById('urlInput').value=savedUrl;
var savedQuery=load('searchQuery');if(savedQuery)document.getElementById('searchInput').value=savedQuery;
var savedResults=load('searchResults');if(savedResults)document.getElementById('searchResults').innerHTML=savedResults;
if(curTask)pollProg();
loadVids();
document.getElementById('urlInput').addEventListener('input',function(){save('urlInput',this.value);});

function doSearch(){
  var q=document.getElementById('searchInput').value.trim();
  if(!q)return;
  save('searchQuery',q);
  var el=document.getElementById('searchResults');
  el.innerHTML='<div class="empty">Searching...</div>';
  document.getElementById('btnSearch').disabled=true;
  fetch('/api/search?q='+encodeURIComponent(q)).then(function(r){return r.json();}).then(function(d){
    document.getElementById('btnSearch').disabled=false;
    if(!d.ok){el.innerHTML='<div class="empty">'+d.error+'</div>';save('searchResults','');return;}
    if(!d.results.length){el.innerHTML='<div class="empty">No results</div>';save('searchResults','');return;}
    var h='';
    for(var i=0;i<d.results.length;i++){
      var r=d.results[i];
      var dur=r.duration||'--:--';
      var views=r.views?(r.views>=1e6?(r.views/1e6).toFixed(1)+'M':r.views>=1e3?(r.views/1e3).toFixed(0)+'K':r.views)+' views':'';
      var urlAttr=r.url.replace(/"/g,'&quot;');
      h+='<div class="sr" onclick="pickSearch(this)" data-url="'+urlAttr+'">';
      h+='<img src="'+(r.thumbnail||'')+'" onerror="this.style.display=\'none\'" loading="lazy">';
      h+='<div class="si"><div class="st">'+escH(r.title)+'</div>';
      h+='<div class="sm">'+escH(r.channel)+'</div>';
      h+='<div class="sd"><b>'+dur+'</b> \u00b7 '+views+'</div>';
      h+='</div></div>';
    }
    el.innerHTML=h;
    save('searchResults',h);
  }).catch(function(e){document.getElementById('btnSearch').disabled=false;el.innerHTML='<div class="empty">Error: '+e.message+'</div>';save('searchResults','');});
}

function pickSearch(el){
  var url=el.getAttribute('data-url');
  document.getElementById('urlInput').value=url;
  save('urlInput',url);
  startDownload();
}
function escH(s){var d=document.createElement('div');d.textContent=s;return d.innerHTML;}
</script>
</body>
</html>'''


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    log(f"Deno: {find_deno() or 'NOT FOUND'}")
    log(f"Cookies: {'YES' if os.path.exists(COOKIE_FILE) else 'NO'}")
    log(f"Starting on port {port}")
    app.run(host='0.0.0.0', port=port)
