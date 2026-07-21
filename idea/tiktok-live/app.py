#!/usr/bin/env python3
"""
TikTok Live Studio Panel
Flow: Login → Setup (one-time) → QR scan → Dashboard → Go Live (GitHub Actions)
"""

import base64, hashlib, json, os, secrets, string, sys, time, urllib.parse, uuid
from functools import wraps
from pathlib import Path

from Mobile.metasec import Metasec
from curl_cffi import requests as curl_requests
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, session, redirect, url_for

load_dotenv()

PASSPORT_APP_KEY = "884c28a44b61b78f9d837fc8b0967178"
PASSPORT_WEB_SDK_VERSION = "2.1.9"
LIVE_STUDIO_AID = 8311
GITHUB_API = "https://api.github.com"

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
PANEL_PASSWORD = os.environ.get('PANEL_PASSWORD', 'admin')
DATA_FILE = Path(__file__).parent / 'panel_data.json'

# ---------------------------------------------------------------------------
# Data persistence
# ---------------------------------------------------------------------------
DEFAULTS = {
    "cookies": {},
    "tiktok_session": {},
    "current_qr": {},
    "setup_done": False,
    "setup_config": {
        "title": "My Live Stream",
        "game_id": "",
        "game_name": "",
        "topic_id": "",
        "topic_name": "",
        "extras": [],
        "extra_names": [],
    },
    "stream_config": {
        "source_url": "",
        "github_pat": "",
        "cookies_b64": "",
        "preview": "false",
    },
    "history": [],
    "game_tags_cache": {},
    "game_tags_fetched": 0,
}


def load_data():
    if DATA_FILE.exists():
        with open(DATA_FILE) as f:
            data = json.load(f)
        for k, v in DEFAULTS.items():
            data.setdefault(k, v)
        return data
    return dict(DEFAULTS)


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Auth decorators
# ---------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated(*a, **kw):
        if not session.get('authenticated'):
            return redirect(url_for('login'))
        return f(*a, **kw)
    return decorated


def api_auth(f):
    @wraps(f)
    def decorated(*a, **kw):
        if not session.get('authenticated'):
            return jsonify({"ok": False, "error": "Not authenticated"}), 401
        return f(*a, **kw)
    return decorated


# ---------------------------------------------------------------------------
# Passport SDK helpers
# ---------------------------------------------------------------------------
def _pv(v):
    return json.dumps(v, separators=(",", ":"), ensure_ascii=False) if isinstance(v, (dict, list, tuple)) else str(v)


def _pss(values, limit=-1):
    ignored = {"sign", "qs", "isResend", "baseURL", "extra_params"}
    keys = sorted(str(k) for k, v in values.items() if v is not None and str(k) not in ignored)
    if limit >= 0:
        keys = keys[:limit]
    return "&".join(f"{k}={_pv(values.get(k))}" for k in keys), keys


def _xor5(keys):
    return "".join(f"{b ^ 5:02x}" for b in ",".join(keys).encode("utf-8"))


def passport_sig(params, data=None):
    ps, sk = _pss(params or {}, limit=10)
    bs, _ = _pss(data or {})
    h = hashlib.md5(f"{ps}&{bs}&app_key={PASSPORT_APP_KEY}".encode()).hexdigest()
    return {"sign": h, "qs": _xor5(sk)}


def apply_ps(params, data=None):
    s = dict(params or {})
    s.pop("sign", None)
    s.pop("qs", None)
    s.update(passport_sig(s, data=data))
    return s


def gen_device_id():
    return "".join(secrets.choice(string.digits) for _ in range(19))


def gen_session_id():
    return secrets.token_hex(16)


def make_session():
    s = curl_requests.Session(impersonate="chrome")
    s.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) TikTokLIVEStudio/1.27.0 Chrome/136.0.7103.59 Electron/36.4.0-alpha.17 TTElectron/36.4.0-alpha.17 Safari/537.36",
    })
    return s


def tg_headers():
    return {
        "tt-ticket-guard-public-key": "BHTyDu4GfY+Se8QoOlL22ARkOv4aLE5BCk8eSiJ6K5N5m8Wg3cPeVYWVYNDrJ3hsRmaVCgNl/AKbMW67VBievw=",
        "tt-ticket-guard-version": "2",
        "tt-ticket-guard-web-version": "1",
        "tt-ticket-guard-iteration-version": "0",
    }


def enb(data):
    if data is None:
        return b""
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode()
    return urllib.parse.urlencode(data, doseq=True, quote_via=urllib.parse.quote).encode()


def xss(data):
    b = enb(data)
    return hashlib.md5(b).hexdigest() if b else None


def metasec_sign(url, params, body_data=None):
    ts = int(time.time())
    full_url = f"{url}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
    be = urllib.parse.urlencode(body_data, doseq=True, quote_via=urllib.parse.quote) if body_data else ""
    bh = be.encode().hex() if be else "00" * 16
    stub = hashlib.md5(be.encode()).hexdigest() if be else None
    signer = Metasec()
    sig = signer.sign(
        url=full_url, app_id=LIVE_STUDIO_AID, app_version="1.27.0",
        app_launch_time=ts, device_type="SM-G973N",
        sdk_version="v04.04.09-boa-hotfix", sdk_version_code=44409,
        license_id=1877999593, device_id=params.get("device_id", "0"),
        payload=bh, cookies="",
    )
    hdrs = {"x-khronos": str(sig["x-khronos"]), "x-ladon": sig["x-ladon"],
            "x-argus": sig["x-argus"], "x-gorgon": sig["x-gorgon"]}
    if stub:
        hdrs["x-ss-stub"] = stub
    return hdrs, ts


# ---------------------------------------------------------------------------
# Game tags
# ---------------------------------------------------------------------------
def fetch_game_tags():
    s = make_session()
    try:
        r = s.get("https://webcast16-normal-c-alisg.tiktokv.com/webcast/room/hashtag/list/", timeout=15)
        d = r.json()
        data = d.get("data", {})
        games = [{"id": str(t["id"]), "name": t.get("show_name", "")} for t in data.get("game_tag_list", [])]
        topics = [{"id": str(t["id"]), "name": t.get("title", "")} for t in data.get("live_studio_hashtag", [])]
        extras = [{"id": str(t["id"]), "name": t.get("title", "")} for t in data.get("hashtag", []) if t.get("id")]
        return {"games": games, "topics": topics, "extras": extras}
    except Exception:
        return {"games": [], "topics": [], "extras": []}


# ---------------------------------------------------------------------------
# QR Login
# ---------------------------------------------------------------------------
def api_hosts():
    return [
        "api16-normal-c-alisg.tiktokv.com",
        "api16-normal-no1a.tiktokv.eu",
        "api16-normal-useast8.tiktokv.us",
        "api16-normal-useast5.tiktokv.us",
    ]


def qr_step1(session):
    for host in api_hosts():
        url = f"https://{host}/passport/web/get_qrcode/"
        did = gen_device_id()
        params = apply_ps({
            "next": "https://www.tiktok.com", "device_id": did,
            "aid": str(LIVE_STUDIO_AID), "account_sdk_source": "web",
            "sdk_version": PASSPORT_WEB_SDK_VERSION, "verifyFp": f"verify_{did}",
        })
        headers = {
            "accept": "application/json, text/javascript",
            "content-type": "application/x-www-form-urlencoded",
            "referer": "https://www.tiktok.com/ucenter_web/live_studio/login",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...",
            **tg_headers(),
            "x-ss-stub": xss(None) or "",
        }
        try:
            r = session.get(url, params=params, headers=headers, impersonate="chrome", timeout=20)
            p = r.json()
            dp = p.get("data", {}) if isinstance(p, dict) else {}
            tok = dp.get("token")
            qurl = dp.get("qrcode_url") or dp.get("qrcode_index_url") or ""
            if not tok or not qurl:
                continue
            try:
                import io, qrcode as qr
                img = qr.make(qurl)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode()
            except Exception:
                b64 = ""
            return {"token": tok, "qrcode_url": qurl, "device_id": did, "domain": host, "qrcode_base64": b64}
        except Exception:
            continue
    raise RuntimeError("QR setup failed")


def qr_step2(session, token, device_id, domain):
    hosts = [domain] + api_hosts()
    for host in hosts:
        url = f"https://{host}/passport/web/check_qrconnect/"
        params = apply_ps({
            "next": "https://www.tiktok.com", "token": token, "multi_login": "1",
            "device_id": device_id, "aid": str(LIVE_STUDIO_AID),
            "account_sdk_source": "web", "sdk_version": PASSPORT_WEB_SDK_VERSION,
            "verifyFp": f"verify_{device_id}",
        })
        headers = {
            "accept": "application/json, text/javascript",
            "content-type": "application/x-www-form-urlencoded",
            "referer": "https://www.tiktok.com/ucenter_web/live_studio/login",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...",
            **tg_headers(),
            "x-ss-stub": xss(None) or "",
        }
        try:
            r = session.get(url, params=params, headers=headers, impersonate="chrome", timeout=15)
            data = r.json()
            if data.get("status_code") == 0:
                cookies = {}
                for c in session.cookies.jar:
                    cookies[c.name] = c.value
                return cookies
            elif data.get("status_code") == 3:
                return None
        except Exception:
            continue
    raise TimeoutError("QR not scanned")


# ---------------------------------------------------------------------------
# Session ID validation
# ---------------------------------------------------------------------------
def validate_session_id(sessionid_value, device_id=None):
    did = device_id or gen_device_id()
    s = make_session()
    s.cookies.set("sessionid", sessionid_value, domain=".tiktokv.com")
    s.cookies.set("sessionid", sessionid_value, domain=".tiktok.com")
    try:
        r = s.get(
            "https://www.tiktok.com/passport/web/user/info/",
            params={
                "aid": str(LIVE_STUDIO_AID), "device_id": did,
                "identity": "passport", "account_sdk_source": "web",
                "sdk_version": PASSPORT_WEB_SDK_VERSION,
            },
            headers={"accept": "application/json, text/plain, */*", "referer": "https://www.tiktok.com/", **tg_headers()},
            impersonate="chrome", timeout=15,
        )
        data = r.json()
        if data.get("status_code") == 0:
            user = data.get("data", {}).get("user", {})
            return {"valid": True, "username": user.get("username", ""), "nickname": user.get("nickname", ""), "uid": user.get("uid", "")}
    except Exception:
        pass
    return {"valid": False, "username": "", "nickname": "", "uid": ""}


# ---------------------------------------------------------------------------
# Room create/end
# ---------------------------------------------------------------------------
def build_params(did):
    return {
        "aid": str(LIVE_STUDIO_AID), "app_name": "tiktok_live_studio", "device_id": did,
        "install_id": "0", "channel": "studio", "version_code": "1.27.0",
        "device_platform": "windows", "timezone_name": "Africa/Tunis",
        "screen_width": "1920", "screen_height": "1080",
        "browser_language": "en-US", "browser_platform": "Win32",
        "browser_name": "Mozilla",
        "browser_version": "Mozilla/5.0 (Windows) TikTokLIVEStudio/1.27.0 Chrome/136 Safari/537.36",
        "language": "en", "app_language": "en", "webcast_language": "en",
        "webcast_sdk_version": "1270", "live_mode": "6",
    }


def build_body(opts):
    return {
        "title": opts.get("title", "Live Stream"),
        "description": opts.get("description", ""),
        "live_studio": "1",
        "gen_replay": str(opts.get("gen_replay", False)).lower(),
        "chat_auth": "0" if opts.get("no_chat") else "1",
        "age_restricted": "4" if opts.get("age_restricted") else "0",
        "cover_uri": "",
        "close_room_when_close_stream": "false",
        "hashtag_id": str(opts.get("topic_id", "42")),
        "game_tag_id": str(opts.get("game_tag_id", "0")),
        "game_bitrate_type": "high",
        "screenshot_cover_status": "1",
        "multi_stream_scene": "1" if opts.get("multi_stream") else "0",
        "gift_auth": "0" if opts.get("no_gifts") else "1",
        "chat_l2": "1", "star_comment_switch": "true",
        "multi_stream_source": "1", "is_group_live_session": "false",
        "open_commercial_content_toggle": str(opts.get("commercial", False)).lower(),
        "commercial_content_promote_me": str(opts.get("commercial", False)).lower(),
        "rtc_net_enabled": "false",
    }


def create_room(session, device_id, cookies, opts):
    params = build_params(device_id)
    body = build_body(opts)
    if opts.get("hashtags"):
        body["hash_tag"] = ",".join(t.strip() for t in opts["hashtags"].split(",") if t.strip())
    hosts = ["webcast16-normal-c-alisg.tiktokv.com", "webcast16-normal-useast5.tiktokv.us", "webcast16-normal-no1a.tiktokv.eu"]
    for host in hosts:
        api_url = f"https://{host}/webcast/room/create/"
        sig_headers, _ = metasec_sign(api_url, params, body)
        ss = make_session()
        for n, v in (cookies or {}).items():
            ss.cookies.set(n, v, domain=".tiktokv.com")
        ss.headers.update({
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://livecenter.tiktok.com",
            "webcast-ntp-t0": f"{time.perf_counter() * 1000:.3f}",
            **sig_headers,
        })
        try:
            r = ss.post(api_url, params=params, data=body, timeout=30)
            resp = r.json()
        except Exception:
            continue
        if resp.get("status_code") == 0:
            sd = resp.get("data", {})
            su = sd.get("stream_url", {}).get("rtmp_push_url", "")
            idx = su.rfind("/")
            return {
                "server_url": su[:idx] if idx >= 0 else su,
                "stream_key": su[idx + 1:] if idx >= 0 else su,
                "rtmp_url": su,
                "share_url": sd.get("share_url", ""),
                "room_id": sd.get("room_id", ""),
            }
        if resp.get("status_code") != 20800:
            break
    return None


def end_room(session, device_id, cookies, rid, sid):
    params = build_params(device_id)
    data = {"status": "4", "room_id": rid, "stream_id": sid}
    for host in ["webcast16-normal-c-alisg.tiktokv.com"]:
        api_url = f"https://{host}/webcast/room/ping/anchor/"
        sig_headers, _ = metasec_sign(api_url, params, data)
        ss = make_session()
        for n, v in (cookies or {}).items():
            ss.cookies.set(n, v, domain=".tiktokv.com")
        ss.headers.update({"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", **sig_headers})
        try:
            r = ss.post(api_url, params=params, data=data, timeout=30)
            if r.json().get("status_code") == 0:
                return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# GitHub Actions trigger
# ---------------------------------------------------------------------------
def trigger_github_workflow(stream_key, rtmp_url, source_url, title, github_pat, cookies_b64="false", preview="false"):
    owner = "zidanebarkat"
    repo = "8dca7ff25e47b8cc0e104b9f-tt"
    token = github_pat or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return None, "GitHub PAT not configured"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    wf_url = f"{GITHUB_API}/repos/{owner}/{repo}/actions/workflows/restream.yml/dispatches"
    wf_inputs = {
        "source_url": source_url,
        "output_url": rtmp_url,
        "title": title,
        "overlay_text": title,
        "github_token": token,
        "cookies_b64": cookies_b64,
        "preview": str(preview).lower(),
    }
    r = curl_requests.post(wf_url, json={"ref": "main", "inputs": wf_inputs}, headers=headers)
    if r.status_code not in (200, 204):
        return None, f"Workflow trigger failed: {r.status_code} {r.text[:200]}"
    return {"workflow": "triggered"}, None


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST' and request.form.get('password') == PANEL_PASSWORD:
        session['authenticated'] = True
        d = load_data()
        if d.get("setup_done") and d.get("tiktok_session"):
            return redirect(url_for('dashboard'))
        elif d.get("setup_done"):
            return redirect(url_for('qr_page'))
        else:
            return redirect(url_for('setup'))
    error = 'Wrong password' if request.method == 'POST' else None
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def root():
    d = load_data()
    if not d.get("setup_done"):
        return redirect(url_for('setup'))
    if not d.get("tiktok_session"):
        return redirect(url_for('qr_page'))
    return redirect(url_for('dashboard'))


@app.route('/setup', methods=['GET', 'POST'])
@login_required
def setup():
    d = load_data()
    if request.method == 'POST':
        sc = {
            "title": request.form.get("title", "My Live Stream"),
            "game_id": request.form.get("game_id", ""),
            "game_name": request.form.get("game_name", ""),
            "topic_id": request.form.get("topic_id", ""),
            "topic_name": request.form.get("topic_name", ""),
            "extras": request.form.getlist("extras"),
            "extra_names": request.form.getlist("extra_names"),
        }
        d["setup_config"] = sc
        d["setup_done"] = True
        save_data(d)
        if d.get("tiktok_session"):
            return redirect(url_for('dashboard'))
        return redirect(url_for('qr_page'))
    tags = fetch_game_tags()
    d["game_tags_cache"] = tags
    save_data(d)
    return render_template('setup.html', config=d.get("setup_config", {}), games=tags["games"], topics=tags["topics"], extras=tags["extras"])


@app.route('/qr')
@login_required
def qr_page():
    d = load_data()
    if d.get("tiktok_session"):
        return redirect(url_for('dashboard'))
    return render_template('qr.html')


@app.route('/dashboard')
@login_required
def dashboard():
    d = load_data()
    if not d.get("setup_done"):
        return redirect(url_for('setup'))
    if not d.get("tiktok_session"):
        return redirect(url_for('qr_page'))
    return render_template('dashboard.html', config=d.get("setup_config", {}), stream=d.get("stream_config", {}))


@app.route('/go-live')
@login_required
def go_live():
    d = load_data()
    if not d.get("tiktok_session"):
        return redirect(url_for('qr_page'))
    return render_template('go_live.html', config=d.get("setup_config", {}), stream=d.get("stream_config", {}))


@app.route('/change-setup')
@login_required
def change_setup():
    d = load_data()
    d["setup_done"] = False
    save_data(d)
    return redirect(url_for('setup'))


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------
@app.route('/api/qr/start', methods=['POST'])
@api_auth
def api_qr_start():
    try:
        qr = qr_step1(make_session())
        d = load_data()
        d["current_qr"] = qr
        save_data(d)
        return jsonify({"ok": True, **qr})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/qr/poll', methods=['POST'])
@api_auth
def api_qr_poll():
    body = request.get_json(force=True)
    d = load_data()
    cqr = d.get("current_qr", {}) or {}
    try:
        c = qr_step2(
            make_session(),
            body.get("token") or cqr.get("token", ""),
            body.get("device_id") or cqr.get("device_id", ""),
            body.get("domain") or cqr.get("domain", ""),
        )
        if c is None:
            return jsonify({"ok": False, "error": "expired"})
        d = load_data()
        d["cookies"] = c
        d["tiktok_session"] = c
        d["current_qr"] = {}
        save_data(d)
        return jsonify({"ok": True, "sessionid": c.get("sessionid", "")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/sessionid', methods=['POST'])
@api_auth
def api_sessionid():
    body = request.get_json(force=True)
    sid = (body.get("sessionid") or "").strip()
    if not sid:
        return jsonify({"ok": False, "error": "No session ID provided"})
    did = gen_device_id()
    info = validate_session_id(sid, did)
    if info.get("valid"):
        cookies = {"sessionid": sid, "device_id": did}
        d = load_data()
        d["cookies"] = cookies
        d["tiktok_session"] = cookies
        d["current_qr"] = {}
        save_data(d)
        return jsonify({"ok": True, "username": info.get("username", ""), "nickname": info.get("nickname", "")})
    return jsonify({"ok": False, "error": "Invalid session ID"})


@app.route('/api/cookies', methods=['POST'])
@api_auth
def api_set_cookies():
    body = request.get_json(force=True)
    raw = body.get("cookies", "")
    try:
        cp = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(cp, list):
            cp = {c["name"]: c["value"] for c in cp}
        d = load_data()
        d["cookies"] = cp
        d["tiktok_session"] = cp
        d["current_qr"] = {}
        save_data(d)
        return jsonify({"ok": True, "count": len(cp)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/cookies', methods=['DELETE'])
@api_auth
def api_clear_cookies():
    d = load_data()
    d["cookies"] = {}
    d["tiktok_session"] = {}
    save_data(d)
    return jsonify({"ok": True})


@app.route('/api/games')
@api_auth
def api_games():
    tags = fetch_game_tags()
    d = load_data()
    d["game_tags_cache"] = tags
    save_data(d)
    return jsonify({"ok": True, "games": tags["games"], "topics": tags["topics"], "extras": tags["extras"]})


@app.route('/api/setup/save', methods=['POST'])
@api_auth
def api_setup_save():
    body = request.get_json(force=True)
    d = load_data()
    d["setup_config"] = body
    d["setup_done"] = True
    save_data(d)
    return jsonify({"ok": True})


@app.route('/api/setup', methods=['GET'])
@api_auth
def api_setup_get():
    d = load_data()
    return jsonify({"ok": True, "setup": d.get("setup_config", {}), "done": d.get("setup_done", False)})


@app.route('/api/stream/save', methods=['POST'])
@api_auth
def api_stream_save():
    body = request.get_json(force=True)
    d = load_data()
    d["stream_config"] = {
        "source_url": body.get("source_url", ""),
        "github_pat": body.get("github_pat", ""),
        "cookies_b64": body.get("cookies_b64", ""),
        "preview": body.get("preview", "false"),
    }
    save_data(d)
    return jsonify({"ok": True})


@app.route('/api/stream', methods=['GET'])
@api_auth
def api_stream_get():
    d = load_data()
    return jsonify({"ok": True, "stream": d.get("stream_config", {})})


@app.route('/api/room/create', methods=['POST'])
@api_auth
def api_create():
    opts = request.get_json(force=True)
    d = load_data()
    sc = d.get("setup_config", {})
    c = d.get("tiktok_session", {})
    if not c:
        return jsonify({"ok": False, "error": "Not logged into TikTok"})
    did = d.get("current_device_id") or c.get("device_id", "") or gen_device_id()
    d["current_device_id"] = did
    room_opts = {
        "title": sc.get("title", "Live Stream"),
        "game_tag_id": sc.get("game_id", "0"),
        "topic_id": sc.get("topic_id", "42"),
        "no_chat": False,
    }
    try:
        r = create_room(make_session(), did, c, room_opts)
        if r:
            d["history"].insert(0, {
                "title": sc.get("title", "Stream"),
                "stream_key": r["stream_key"],
                "server_url": r["server_url"],
                "rtmp_url": r["rtmp_url"],
                "share_url": r.get("share_url", ""),
                "room_id": r.get("room_id", ""),
                "created": time.strftime("%Y-%m-%d %H:%M"),
            })
            if len(d["history"]) > 50:
                d["history"] = d["history"][:50]
            save_data(d)
            return jsonify({"ok": True, **r})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
    return jsonify({"ok": False, "error": "Room create failed. Account may lack live auth."})


@app.route('/api/room/end', methods=['POST'])
@api_auth
def api_end():
    body = request.get_json(force=True)
    d = load_data()
    c = d.get("tiktok_session", {})
    did = d.get("current_device_id", "") or c.get("device_id", "") or "0"
    try:
        ok = end_room(None, did, c, body.get("room_id", ""), body.get("stream_id", ""))
        return jsonify({"ok": ok})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/golive', methods=['POST'])
@api_auth
def api_golive():
    body = request.get_json(force=True)
    d = load_data()
    sc = d.get("stream_config", {})
    setup = d.get("setup_config", {})
    result, err = trigger_github_workflow(
        stream_key=body.get("stream_key", ""),
        rtmp_url=body.get("rtmp_url", ""),
        source_url=body.get("source_url", sc.get("source_url", "")),
        title=setup.get("title", "Live Stream"),
        github_pat=body.get("github_pat", sc.get("github_pat", "")),
        cookies_b64=body.get("cookies_b64", sc.get("cookies_b64", "")),
        preview=body.get("preview", sc.get("preview", "false")),
    )
    if err:
        return jsonify({"ok": False, "error": err})
    return jsonify({"ok": True, **result})


@app.route('/api/status')
@api_auth
def api_status():
    d = load_data()
    return jsonify({
        "ok": True,
        "logged_in": bool(d.get("tiktok_session")),
        "setup_done": d.get("setup_done", False),
        "history": len(d.get("history", [])),
    })


@app.route('/api/health')
def health():
    return jsonify({"ok": True})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG', '0') == '1')
