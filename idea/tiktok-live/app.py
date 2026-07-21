#!/usr/bin/env python3
"""
TikTok Live Studio Panel - Web UI for QR login, room creation, and stream key management.
Hosted on Render.com. Full parameter control for TikTok Live Studio.
"""

import base64, hashlib, json, os, secrets, string, sys, time, urllib.parse, uuid
from functools import wraps
from pathlib import Path

from Mobile.metasec import Metasec
from curl_cffi import requests
from dotenv import load_dotenv
from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for

load_dotenv()

PASSPORT_APP_KEY = "884c28a44b61b78f9d837fc8b0967178"
PASSPORT_WEB_SDK_VERSION = "2.1.9"
LIVE_STUDIO_AID = 8311

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
PANEL_PASSWORD = os.environ.get('PANEL_PASSWORD', 'admin')
DATA_FILE = Path(__file__).parent / 'panel_data.json'

TOPICS = {"42":"Chat &amp; Interview","5":"Gaming","6":"Music","9":"Beauty &amp; Fashion","3":"Dance","13":"Fitness &amp; Sports","4":"Food","43":"News &amp; Event","45":"Education"}

# ---------------------------------------------------------------------------
# Data persistence
# ---------------------------------------------------------------------------
def load_data():
    defaults = {"cookies":{},"history":[],"game_tags_cache":{},"game_tags_fetched":0,"current_qr":{}}
    if DATA_FILE.exists():
        with open(DATA_FILE) as f:
            return {**defaults, **json.load(f)}
    return defaults

def save_data(data):
    with open(DATA_FILE,"w") as f:
        json.dump(data,f,indent=2)

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated(*a,**kw):
        if not session.get('authenticated'):
            return redirect(url_for('login'))
        return f(*a,**kw)
    return decorated

# ---------------------------------------------------------------------------
# Passport SDK helpers
# ---------------------------------------------------------------------------
def _pv(v):
    return json.dumps(v,separators=(",",":"),ensure_ascii=False) if isinstance(v,(dict,list,tuple)) else str(v)

def _pss(values,limit=-1):
    ignored={"sign","qs","isResend","baseURL","extra_params"}
    keys=sorted(str(k) for k,v in values.items() if v is not None and str(k) not in ignored)
    if limit>=0: keys=keys[:limit]
    return "&".join(f"{k}={_pv(values.get(k))}" for k in keys),keys

def _xor5(keys):
    return "".join(f"{b^5:02x}" for b in ",".join(keys).encode("utf-8"))

def passport_sig(params,data=None):
    ps,sk=_pss(params or {},limit=10)
    bs,_=_pss(data or {})
    h=hashlib.md5(f"{ps}&{bs}&app_key={PASSPORT_APP_KEY}".encode()).hexdigest()
    return {"sign":h,"qs":_xor5(sk)}

def apply_ps(params,data=None):
    s=dict(params or {})
    s.pop("sign",None); s.pop("qs",None)
    s.update(passport_sig(s,data=data))
    return s

def gen_device_id():
    return "".join(secrets.choice(string.digits) for _ in range(19))

def gen_session_id():
    return secrets.token_hex(16)

def make_session():
    s=requests.Session(impersonate="chrome")
    s.headers.update({"Accept":"application/json, text/plain, */*","Accept-Language":"en-US","User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) TikTokLIVEStudio/1.27.0 Chrome/136.0.7103.59 Electron/36.4.0-alpha.17 TTElectron/36.4.0-alpha.17 Safari/537.36"})
    return s

def tg_headers():
    return {"tt-ticket-guard-public-key":"BHTyDu4GfY+Se8QoOlL22ARkOv4aLE5BCk8eSiJ6K5N5m8Wg3cPeVYWVYNDrJ3hsRmaVCgNl/AKbMW67VBievw=","tt-ticket-guard-version":"2","tt-ticket-guard-web-version":"1","tt-ticket-guard-iteration-version":"0"}

def enb(data):
    if data is None: return b""
    if isinstance(data,bytes): return data
    if isinstance(data,str): return data.encode()
    return urllib.parse.urlencode(data,doseq=True,quote_via=urllib.parse.quote).encode()

def xss(data):
    b=enb(data)
    return hashlib.md5(b).hexdigest() if b else None

def metasec_sign(url,params,body_data=None):
    ts=int(time.time())
    full_url=f"{url}?{'&'.join(f'{k}={v}' for k,v in params.items())}"
    be=urllib.parse.urlencode(body_data,doseq=True,quote_via=urllib.parse.quote) if body_data else ""
    bh=be.encode().hex() if be else "00"*16
    stub=hashlib.md5(be.encode()).hexdigest() if be else None
    signer=Metasec()
    sig=signer.sign(url=full_url,app_id=LIVE_STUDIO_AID,app_version="1.27.0",app_launch_time=ts,device_type="SM-G973N",sdk_version="v04.04.09-boa-hotfix",sdk_version_code=44409,license_id=1877999593,device_id=params.get("device_id","0"),payload=bh,cookies="")
    hdrs={"x-khronos":str(sig["x-khronos"]),"x-ladon":sig["x-ladon"],"x-argus":sig["x-argus"],"x-gorgon":sig["x-gorgon"]}
    if stub: hdrs["x-ss-stub"]=stub
    return hdrs,ts

# ---------------------------------------------------------------------------
# Game tags
# ---------------------------------------------------------------------------
def fetch_game_tags():
    s=make_session()
    try:
        r=s.get("https://webcast16-normal-c-alisg.tiktokv.com/webcast/room/hashtag/list/",timeout=15)
        d=r.json()
        data=d.get("data",{})
        games={str(t["id"]):t.get("show_name","") for t in data.get("game_tag_list",[])}
        topics={str(t["id"]):t.get("title","") for t in data.get("live_studio_hashtag",[])}
        extras={str(t["id"]):t.get("title","") for t in data.get("hashtag",[]) if t.get("id")}
        return {"games":games,"topics":topics,"extras":extras}
    except Exception:
        return {"games":{},"topics":{},"extras":{}}

# ---------------------------------------------------------------------------
# QR Login
# ---------------------------------------------------------------------------
def api_hosts():
    return ["api16-normal-c-alisg.tiktokv.com","api16-normal-no1a.tiktokv.eu","api16-normal-useast8.tiktokv.us","api16-normal-useast5.tiktokv.us"]

def qr_step1(session):
    for host in api_hosts():
        url=f"https://{host}/passport/web/get_qrcode/"
        did=gen_device_id()
        params=apply_ps({"next":"https://www.tiktok.com","device_id":did,"aid":str(LIVE_STUDIO_AID),"account_sdk_source":"web","sdk_version":PASSPORT_WEB_SDK_VERSION,"verifyFp":f"verify_{did}"})
        headers={"accept":"application/json, text/javascript","content-type":"application/x-www-form-urlencoded","referer":"https://www.tiktok.com/ucenter_web/live_studio/login","user-agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...",**tg_headers(),"x-ss-stub":xss(None) or ""}
        try:
            r=session.get(url,params=params,headers=headers,impersonate="chrome",timeout=20)
            p=r.json()
            dp=p.get("data",{}) if isinstance(p,dict) else {}
            tok=dp.get("token")
            qurl=dp.get("qrcode_url") or dp.get("qrcode_index_url") or ""
            if not tok or not qurl: continue
            try:
                import io,qrcode as qr
                img=qr.make(qurl); buf=io.BytesIO(); img.save(buf,format="PNG")
                b64=base64.b64encode(buf.getvalue()).decode()
            except Exception:
                b64=""
            return {"token":tok,"qrcode_url":qurl,"device_id":did,"domain":host,"qrcode_base64":b64}
        except Exception:
            continue
    raise RuntimeError("QR setup failed")

def qr_step2(session,token,device_id,domain):
    hosts=[domain]+api_hosts()
    for host in hosts:
        url=f"https://{host}/passport/web/check_qrconnect/"
        params=apply_ps({"next":"https://www.tiktok.com","token":token,"multi_login":"1","device_id":device_id,"aid":str(LIVE_STUDIO_AID),"account_sdk_source":"web","sdk_version":PASSPORT_WEB_SDK_VERSION,"verifyFp":f"verify_{device_id}"})
        headers={"accept":"application/json, text/javascript","content-type":"application/x-www-form-urlencoded","referer":"https://www.tiktok.com/ucenter_web/live_studio/login","user-agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...",**tg_headers(),"x-ss-stub":xss(None) or ""}
        try:
            r=session.get(url,params=params,headers=headers,impersonate="chrome",timeout=15)
            data=r.json()
            if data.get("status_code")==0:
                cookies={}
                for c in session.cookies.jar: cookies[c.name]=c.value
                return cookies
            elif data.get("status_code")==3:
                return None
        except Exception:
            continue
    raise TimeoutError("QR not scanned")

# ---------------------------------------------------------------------------
# TikTok Web Login (passport/web/login endpoint)
# ---------------------------------------------------------------------------
def web_login_step1():
    did = gen_device_id()
    sid = gen_session_id()
    referer = f"https://www.tiktok.com/login/phone-or-email?lang=en"
    return {"device_id": did, "session_id": sid, "referer": referer}

def web_login_step2(device_id, session_id, login_ticket, redirect_data):
    """Exchange the login ticket for session cookies via passport/web/login/v2/."""
    s = make_session()
    did = device_id or gen_device_id()
    cookies_dict = {}
    for host in api_hosts():
        url = f"https://{host}/passport/web/login/v2/"
        params = apply_ps({
            "aid": str(LIVE_STUDIO_AID),
            "app_name": "tiktok_web_sdk",
            "device_platform": "web",
            "channel": "channel_pc_web",
            "version_code": "170400",
            "version_name": "17.4.0",
            "cookie_enabled": "true",
            "screen_width": "1920",
            "screen_height": "1080",
            "browser_language": "en-US",
            "browser_platform": "Win32",
            "browser_name": "Mozilla",
            "browser_version": "5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "browser_online": "true",
            "tz_name": "America/New_York",
            "cursor": redirect_data or "",
            "request_id": str(int(time.time() * 1000)),
            "identity": "passport",
            "account_sdk_source": "web",
            "sdk_version": PASSPORT_WEB_SDK_VERSION,
            "device_id": did,
            "verifyFp": f"verify_{did}",
        })
        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/x-www-form-urlencoded",
            "referer": "https://www.tiktok.com/login/phone-or-email",
            **tg_headers(),
            "x-ss-stub": xss(None) or "",
        }
        try:
            r = s.post(url, params=params, headers=headers, impersonate="chrome", timeout=20)
            data = r.json()
            if data.get("status_code") == 0:
                for c in s.cookies.jar:
                    cookies_dict[c.name] = c.value
                return cookies_dict
        except Exception:
            continue
    return cookies_dict

# ---------------------------------------------------------------------------
# Session ID validation
# ---------------------------------------------------------------------------
def validate_session_id(sessionid_value, device_id=None):
    """Validate a sessionid by fetching user info from TikTok."""
    did = device_id or gen_device_id()
    s = make_session()
    s.cookies.set("sessionid", sessionid_value, domain=".tiktokv.com")
    s.cookies.set("sessionid", sessionid_value, domain=".tiktok.com")
    try:
        r = s.get(
            "https://www.tiktok.com/passport/web/user/info/",
            params={
                "aid": str(LIVE_STUDIO_AID),
                "device_id": did,
                "identity": "passport",
                "account_sdk_source": "web",
                "sdk_version": PASSPORT_WEB_SDK_VERSION,
            },
            headers={
                "accept": "application/json, text/plain, */*",
                "referer": "https://www.tiktok.com/",
                **tg_headers(),
            },
            impersonate="chrome",
            timeout=15,
        )
        data = r.json()
        if data.get("status_code") == 0:
            user = data.get("data", {}).get("user", {})
            return {
                "valid": True,
                "username": user.get("username", ""),
                "nickname": user.get("nickname", ""),
                "uid": user.get("uid", ""),
            }
    except Exception:
        pass
    # Fallback: try creating a minimal room to check auth
    return {"valid": False, "username": "", "nickname": "", "uid": ""}

# ---------------------------------------------------------------------------
# Room create/end
# ---------------------------------------------------------------------------
def build_params(did):
    return {
        "aid":str(LIVE_STUDIO_AID),"app_name":"tiktok_live_studio","device_id":did,
        "install_id":"0","channel":"studio","version_code":"1.27.0","device_platform":"windows",
        "timezone_name":"Africa/Tunis","screen_width":"1920","screen_height":"1080",
        "browser_language":"en-US","browser_platform":"Win32","browser_name":"Mozilla",
        "browser_version":"Mozilla/5.0 (Windows) TikTokLIVEStudio/1.27.0 Chrome/136 Safari/537.36",
        "language":"en","app_language":"en","webcast_language":"en","webcast_sdk_version":"1270","live_mode":"6",
    }

def build_body(opts):
    return {
        "title":opts.get("title","Live Stream"),"description":opts.get("description",""),
        "live_studio":"1","gen_replay":str(opts.get("gen_replay",False)).lower(),
        "chat_auth":"0" if opts.get("no_chat") else "1",
        "age_restricted":"4" if opts.get("age_restricted") else "0","cover_uri":"",
        "close_room_when_close_stream":"false","hashtag_id":str(opts.get("topic_id","42")),
        "game_tag_id":str(opts.get("game_tag_id","0")),"game_bitrate_type":"high",
        "screenshot_cover_status":"1","multi_stream_scene":"1" if opts.get("multi_stream") else "0",
        "gift_auth":"0" if opts.get("no_gifts") else "1","chat_l2":"1","star_comment_switch":"true",
        "multi_stream_source":"1","is_group_live_session":"false",
        "open_commercial_content_toggle":str(opts.get("commercial",False)).lower(),
        "commercial_content_promote_me":str(opts.get("commercial",False)).lower(),
        "rtc_net_enabled":"false",
    }

def create_room(session,device_id,cookies,opts):
    params=build_params(device_id)
    body=build_body(opts)
    if opts.get("hashtags"):
        body["hash_tag"]=",".join(t.strip() for t in opts["hashtags"].split(",") if t.strip())
    hosts=["webcast16-normal-c-alisg.tiktokv.com","webcast16-normal-useast5.tiktokv.us","webcast16-normal-no1a.tiktokv.eu"]
    for host in hosts:
        api_url=f"https://{host}/webcast/room/create/"
        sig_headers,_=metasec_sign(api_url,params,body)
        ss=make_session()
        for n,v in (cookies or {}).items():
            ss.cookies.set(n,v,domain=".tiktokv.com")
        ss.headers.update({"Content-Type":"application/x-www-form-urlencoded; charset=UTF-8","Origin":"https://livecenter.tiktok.com","webcast-ntp-t0":f"{time.perf_counter()*1000:.3f}",**sig_headers})
        try:
            r=ss.post(api_url,params=params,data=body,timeout=30)
            resp=r.json()
        except Exception:
            continue
        if resp.get("status_code")==0:
            sd=resp.get("data",{}); su=sd.get("stream_url",{}).get("rtmp_push_url",""); idx=su.rfind("/")
            return {"server_url":su[:idx] if idx>=0 else su,"stream_key":su[idx+1:] if idx>=0 else su,"rtmp_url":su,"share_url":sd.get("share_url",""),"room_id":sd.get("room_id","")}
        if resp.get("status_code")!=20800: break
    return None

def end_room(session,device_id,cookies,rid,sid):
    params=build_params(device_id)
    data={"status":"4","room_id":rid,"stream_id":sid}
    for host in ["webcast16-normal-c-alisg.tiktokv.com"]:
        api_url=f"https://{host}/webcast/room/ping/anchor/"
        sig_headers,_=metasec_sign(api_url,params,data)
        ss=make_session()
        for n,v in (cookies or {}).items():
            ss.cookies.set(n,v,domain=".tiktokv.com")
        ss.headers.update({"Content-Type":"application/x-www-form-urlencoded; charset=UTF-8",**sig_headers})
        try:
            r=ss.post(api_url,params=params,data=data,timeout=30)
            if r.json().get("status_code")==0: return True
        except Exception:
            continue
    return False

# ---------------------------------------------------------------------------
# 24h Stream - push key to repo + trigger workflow
# ---------------------------------------------------------------------------
GITHUB_API = "https://api.github.com"

def push_to_24h_repo(server_url, stream_key, rtmp_url, share_url, room_id, title):
    """Push stream key to 8dca7ff25e47b8cc0e104b9f-tt repo and trigger workflow."""
    from os import environ
    token = environ.get("GITHUB_TOKEN", "")
    owner = environ.get("GITHUB_OWNER", "zidanebarkat")
    repo = "8dca7ff25e47b8cc0e104b9f-tt"
    if not token:
        # Try from data storage
        d = load_data()
        token = d.get("github_token", "")
    if not token:
        return None, "GitHub token not configured. Set GITHUB_TOKEN env var or add in panel settings."
    
    # Save stream info to repo using GitHub API
    api_url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/stream_info.json"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    
    stream_data = json.dumps({
        "server_url": server_url,
        "stream_key": stream_key,
        "rtmp_url": rtmp_url,
        "share_url": share_url,
        "room_id": room_id,
        "title": title,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "source_url": "",  
    }, indent=2)
    
    # Check if file exists
    r = requests.get(api_url, headers=headers)
    sha = None
    if r.status_code == 200:
        sha = r.json().get("sha")
    
    put_data = {"message": f"Update stream key for {title}", "content": base64.b64encode(stream_data.encode()).decode()}
    if sha:
        put_data["sha"] = sha
    
    r = requests.put(api_url, json=put_data, headers=headers)
    if r.status_code not in (200, 201):
        return None, f"GitHub push failed: {r.status_code} {r.text[:200]}"
    
    # Trigger workflow
    wf_url = f"{GITHUB_API}/repos/{owner}/{repo}/actions/workflows/restream.yml/dispatches"
    wf_inputs = {
        "source_url": "",
        "output_url": rtmp_url,
        "title": title,
        "overlay_text": title,
        "github_token": token,
        "cookies_b64": "",
        "preview": "false",
    }
    if not wf_inputs["source_url"]:
        del wf_inputs["source_url"]
        wf_inputs["source_url"] = ""
    
    wf_data = {"ref": "main", "inputs": wf_inputs}
    r = requests.post(wf_url, json=wf_data, headers=headers)
    if r.status_code not in (200, 204):
        return None, f"Workflow trigger failed: {r.status_code} {r.text[:200]}"
    
    return {"stream_info_url": api_url, "workflow": "triggered"}, None

def get_24h_stream_status():
    """Check if 24h stream is running."""
    from os import environ
    token = environ.get("GITHUB_TOKEN", "")
    owner = environ.get("GITHUB_OWNER", "zidanebarkat")
    repo = "8dca7ff25e47b8cc0e104b9f-tt"
    if not token:
        d = load_data()
        token = d.get("github_token", "")
    if not token:
        return {"active": False}
    
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    r = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}/actions/runs?status=in_progress&per_page=1", headers=headers)
    if r.status_code == 200:
        runs = r.json().get("workflow_runs", [])
        if runs:
            return {"active": True, "run_id": runs[0]["id"], "status": runs[0]["status"], "created_at": runs[0]["created_at"]}
    return {"active": False}

def stop_24h_stream():
    """Cancel the 24h workflow run."""
    from os import environ
    token = environ.get("GITHUB_TOKEN", "")
    owner = environ.get("GITHUB_OWNER", "zidanebarkat")
    repo = "8dca7ff25e47b8cc0e104b9f-tt"
    if not token:
        d = load_data()
        token = d.get("github_token", "")
    if not token:
        return False, "No GitHub token"
    
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    r = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}/actions/runs?status=in_progress&per_page=1", headers=headers)
    if r.status_code == 200:
        runs = r.json().get("workflow_runs", [])
        if not runs:
            return False, "No active run found"
        run_id = runs[0]["id"]
        r = requests.post(f"{GITHUB_API}/repos/{owner}/{repo}/actions/runs/{run_id}/cancel", headers=headers)
        if r.status_code in (202, 204):
            return True, None
        return False, f"Cancel failed: {r.status_code}"
    return False, "No active runs"

# ---------------------------------------------------------------------------
# Flask Routes
# ---------------------------------------------------------------------------

LOGIN_HTML = r'''<!DOCTYPE html><html><head><title>TikTok Live Panel - Login</title>
<style>
body{background:#0a0a0a;color:#fff;font-family:system-ui;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}
.login-box{background:#111;padding:40px;border-radius:12px;width:340px;box-shadow:0 0 30px rgba(139,92,246,.15)}
h1{text-align:center;font-size:1.4rem;margin-bottom:8px}
p{text-align:center;color:#888;font-size:.85rem;margin-bottom:24px}
input{width:100%;padding:12px;border:1px solid #333;border-radius:8px;background:#1a1a2e;color:#fff;font-size:1rem;margin-bottom:16px;box-sizing:border-box}
button{width:100%;padding:12px;background:#7c3aed;color:#fff;border:none;border-radius:8px;font-size:1rem;cursor:pointer;font-weight:600}
button:hover{background:#6d28d9}
.err{color:#ef4444;text-align:center;margin-bottom:12px;font-size:.85rem}
</style></head><body>
<div class="login-box">
<h1>TikTok Panel</h1><p>Enter password</p>
{% if error %}<div class="err">{{ error }}</div>{% endif %}
<form method=POST><input name=password type=password placeholder=Password autofocus>
<button type=submit>Login</button></form></div></body></html>'''

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST' and request.form.get('password')==PANEL_PASSWORD:
        session['authenticated']=True
        return redirect(url_for('dashboard'))
    return render_template_string(LOGIN_HTML,error='Wrong password' if request.method=='POST' else None)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    d=load_data()
    gtc=d.get("game_tags_cache",{})
    if isinstance(gtc,dict) and "games" in gtc:
        game_tags=gtc.get("games",{})
        live_topics=gtc.get("topics",{})
        extra_tags=gtc.get("extras",{})
    else:
        game_tags=gtc if isinstance(gtc,dict) else {}
        live_topics=TOPICS
        extra_tags={}
    return render_template_string(DASHBOARD_HTML,topics=live_topics,game_tags=game_tags,extra_tags=extra_tags,history=list(reversed(d.get("history",[]))))

# -------------------------------------------------------------------------
# API - QR Login
# -------------------------------------------------------------------------
@app.route('/api/qr/start',methods=['POST'])
@login_required
def api_qr_start():
    try:
        qr=qr_step1(make_session())
        d=load_data(); d["current_qr"]=qr; save_data(d)
        return jsonify({"ok":True,**qr})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})

@app.route('/api/qr/poll',methods=['POST'])
@login_required
def api_qr_poll():
    body=request.get_json(force=True)
    d=load_data(); cqr=d.get("current_qr",{}) or {}
    try:
        c=qr_step2(make_session(),body.get("token") or cqr.get("token",""),body.get("device_id") or cqr.get("device_id",""),body.get("domain") or cqr.get("domain",""))
        if c is None: return jsonify({"ok":False,"error":"expired"})
        d=load_data(); d["cookies"]=c; d["current_qr"]={}; save_data(d)
        return jsonify({"ok":True,"cookies":c,"sessionid":c.get("sessionid",""),"sid_tt":c.get("sid_tt","")})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})

# -------------------------------------------------------------------------
# API - Web Login
# -------------------------------------------------------------------------
@app.route('/api/weblogin/start',methods=['POST'])
@login_required
def api_weblogin_start():
    try:
        info = web_login_step1()
        d = load_data()
        d["weblogin_state"] = {"device_id": info["device_id"], "session_id": info["session_id"]}
        save_data(d)
        return jsonify({"ok": True, "login_url": info["referer"], "device_id": info["device_id"]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route('/api/weblogin/complete',methods=['POST'])
@login_required
def api_weblogin_complete():
    body = request.get_json(force=True)
    d = load_data()
    state = d.get("weblogin_state", {}) or {}
    did = state.get("device_id") or body.get("device_id", "")
    try:
        cookies = web_login_step2(did, state.get("session_id", ""), body.get("ticket", ""), body.get("redirect_data", ""))
        if cookies and cookies.get("sessionid"):
            d["cookies"] = cookies
            d["weblogin_state"] = {}
            d["current_qr"] = {}
            save_data(d)
            return jsonify({"ok": True, "cookies": cookies, "sessionid": cookies.get("sessionid", ""), "sid_tt": cookies.get("sid_tt", "")})
        return jsonify({"ok": False, "error": "Login failed - no session cookie received. Try another method."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route('/api/weblogin/callback',methods=['GET','POST'])
def api_weblogin_callback():
    """Handle redirect from TikTok login if using OAuth redirect flow."""
    if not session.get('authenticated'):
        return redirect(url_for('login'))
    code = request.args.get("code", "")
    redirect_data = request.args.get("redirect_data", "")
    ticket = request.args.get("ticket", "")
    d = load_data()
    state = d.get("weblogin_state", {}) or {}
    did = state.get("device_id", "")
    try:
        cookies = web_login_step2(did, state.get("session_id", ""), ticket, redirect_data or code)
        if cookies and cookies.get("sessionid"):
            d["cookies"] = cookies
            d["weblogin_state"] = {}
            d["current_qr"] = {}
            save_data(d)
        return redirect(url_for('dashboard'))
    except Exception:
        return redirect(url_for('dashboard'))

# -------------------------------------------------------------------------
# API - Session ID
# -------------------------------------------------------------------------
@app.route('/api/sessionid',methods=['POST'])
@login_required
def api_sessionid():
    body = request.get_json(force=True)
    sid = (body.get("sessionid") or "").strip()
    if not sid:
        return jsonify({"ok": False, "error": "No session ID provided"})
    device_id = body.get("device_id") or gen_device_id()
    info = validate_session_id(sid, device_id)
    if info.get("valid"):
        did = gen_device_id()
        cookies = {
            "sessionid": sid,
            "device_id": did,
        }
        d = load_data()
        d["cookies"] = cookies
        d["current_device_id"] = did
        d["current_qr"] = {}
        save_data(d)
        return jsonify({
            "ok": True,
            "sessionid": sid,
            "username": info.get("username", ""),
            "nickname": info.get("nickname", ""),
            "uid": info.get("uid", ""),
            "device_id": did,
        })
    else:
        return jsonify({"ok": False, "error": "Invalid or expired session ID. Please log in to TikTok first and copy a valid sessionid cookie."})

# -------------------------------------------------------------------------
# API - Cookies (load/paste/clear)
# -------------------------------------------------------------------------
@app.route('/api/cookies',methods=['GET'])
@login_required
def api_get_cookies():
    d=load_data()
    return jsonify({"ok":True,"loaded":bool(d.get("cookies")),"count":len(d.get("cookies",{})),"sessionid":(d.get("cookies") or {}).get("sessionid","")})

@app.route('/api/cookies',methods=['POST'])
@login_required
def api_set_cookies():
    body=request.get_json(force=True)
    raw=body.get("cookies","")
    try:
        cp=json.loads(raw) if isinstance(raw,str) else raw
        if isinstance(cp,list):
            cp={c["name"]:c["value"] for c in cp}
        d=load_data(); d["cookies"]=cp; d["current_qr"]={}; save_data(d)
        return jsonify({"ok":True,"count":len(cp)})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})

@app.route('/api/cookies',methods=['DELETE'])
@login_required
def api_clear_cookies():
    d=load_data(); d["cookies"]={}; save_data(d)
    return jsonify({"ok":True})

@app.route('/api/games',methods=['GET'])
@login_required
def api_games():
    tags=fetch_game_tags()
    d=load_data(); d["game_tags_cache"]=tags; save_data(d)
    return jsonify({"ok":True,"games":tags.get("games",{}),"topics":tags.get("topics",{}),"extras":tags.get("extras",{})})

@app.route('/api/room/create',methods=['POST'])
@login_required
def api_create():
    opts=request.get_json(force=True)
    opts.setdefault("no_chat",opts.pop("chat","1")=="0")
    d=load_data(); c=d.get("cookies",{})
    if not c: return jsonify({"ok":False,"error":"No cookies"})
    did=d.get("current_device_id") or c.get("device_id","") or gen_device_id()
    d["current_device_id"]=did
    try:
        r=create_room(make_session(),did,c,opts)
        if r:
            d["history"].insert(0,{"title":opts.get("title","Stream"),"stream_key":r["stream_key"],"server_url":r["server_url"],"rtmp_url":r["rtmp_url"],"share_url":r.get("share_url",""),"room_id":r.get("room_id",""),"created":time.strftime("%Y-%m-%d %H:%M")})
            if len(d["history"])>50: d["history"]=d["history"][:50]
            save_data(d)
            return jsonify({"ok":True,**r})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})
    return jsonify({"ok":False,"error":"Room create failed. Account may lack live auth."})

@app.route('/api/room/end',methods=['POST'])
@login_required
def api_end():
    body=request.get_json(force=True)
    d=load_data(); c=d.get("cookies",{}); did=d.get("current_device_id","") or c.get("device_id","") or "0"
    try:
        ok=end_room(None,did,c,body.get("room_id",""),body.get("stream_id",""))
        return jsonify({"ok":ok})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})

@app.route('/api/status')
@login_required
def api_status():
    d=load_data()
    return jsonify({"ok":True,"logged_in":bool(d.get("cookies")),"games":bool(d.get("game_tags_cache")),"history":len(d.get("history",[]))})


@app.route('/api/24h/push', methods=['POST'])
@login_required
def api_24h_push():
    body = request.get_json(force=True)
    result, err = push_to_24h_repo(
        body.get("server_url", ""),
        body.get("stream_key", ""),
        body.get("rtmp_url", ""),
        body.get("share_url", ""),
        body.get("room_id", ""),
        body.get("title", "Live Stream"),
    )
    if err:
        return jsonify({"ok": False, "error": err})
    return jsonify({"ok": True, **result})

@app.route('/api/24h/status')
@login_required
def api_24h_status():
    return jsonify(get_24h_stream_status())

@app.route('/api/24h/stop', methods=['POST'])
@login_required
def api_24h_stop():
    ok, err = stop_24h_stream()
    return jsonify({"ok": ok, "error": err})

@app.route('/api/health')
def health():
    return jsonify({"ok":True})

# ---------------------------------------------------------------------------
# Dashboard HTML (inline template)
# ---------------------------------------------------------------------------
DASHBOARD_HTML = open(Path(__file__).parent / 'templates' / 'dashboard.html').read()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG', '0') == '1')
