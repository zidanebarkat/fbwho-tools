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
        return {str(t["id"]):t.get("show_name","") for t in d.get("data",{}).get("game_tag_list",[])}
    except Exception:
        return {}

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
    return render_template_string(DASHBOARD_HTML,topics=TOPICS,game_tags=d.get("game_tags_cache",{}),history=list(reversed(d.get("history",[]))))

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
    return jsonify({"ok":True,"games":tags})

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

@app.route('/api/health')
def health():
    return jsonify({"ok":True})

# ---------------------------------------------------------------------------
# Dashboard HTML (inline template)
# ---------------------------------------------------------------------------
DASHBOARD_HTML = r'''
<!DOCTYPE html><html><head>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>TikTok Live Studio Panel</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:linear-gradient(135deg,#0a0a0a,#1a0a2e);color:#e0e0e0;font-family:system-ui;min-height:100vh}
.header{background:rgba(17,17,17,.95);padding:16px 24px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #222;backdrop-filter:blur(10px);position:sticky;top:0;z-index:100}
.header h1{font-size:1.15rem;background:linear-gradient(135deg,#7c3aed,#22c55e);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.header a{color:#888;text-decoration:none;font-size:.8rem}
.mainer{display:flex;gap:24px;padding:24px;max-width:1400px;margin:0 auto}
.col{flex:1;min-width:0}
.section{background:rgba(17,17,17,.9);border-radius:14px;padding:22px;margin-bottom:20px;border:1px solid rgba(124,58,237,.2)}
.section h2{font-size:1rem;margin-bottom:16px;color:#7c3aed;display:flex;align-items:center;gap:8px}
label{font-size:.75rem;color:#888;display:block;margin-bottom:4px;margin-top:12px}
input,select{width:100%;padding:10px 12px;border:1px solid #333;border-radius:8px;background:rgba(26,26,46,.8);color:#e0e0e0;font-size:.85rem;transition:border .2s}
input:focus,select:focus{outline:none;border-color:#7c3aed}
select{appearance:auto;cursor:pointer}
.trow{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}
.titem{display:flex;align-items:center;gap:6px;background:rgba(26,26,46,.6);padding:7px 12px;border-radius:8px;border:1px solid #333}
.titem input[type=checkbox]{width:16px;height:16px;accent-color:#7c3aed;cursor:pointer}
.titem label{font-size:.75rem;margin:0;cursor:pointer;color:#ccc}
.btn{padding:11px 22px;border:none;border-radius:8px;font-size:.82rem;cursor:pointer;font-weight:600;display:inline-flex;align-items:center;gap:6px;transition:all .2s}
.btn-primary{background:linear-gradient(135deg,#7c3aed,#6d28d9);color:#fff}.btn-primary:hover{transform:translateY(-1px);box-shadow:0 4px 15px rgba(124,58,237,.3)}
.btn-start{background:linear-gradient(135deg,#22c55e,#16a34a);color:#000}.btn-start:hover{transform:translateY(-1px);box-shadow:0 4px 15px rgba(34,197,94,.3)}
.btn-stop{background:linear-gradient(135deg,#ef4444,#dc2626);color:#fff}.btn-stop:hover{transform:translateY(-1px)}
.btn:disabled{opacity:.5;cursor:not-allowed}
.btn-full{width:100%;justify-content:center;margin-top:16px}
.btn-sm{font-size:.74rem;padding:5px 12px}
.btn-ghost{background:rgba(255,255,255,.06);color:#ccc;border:1px solid #333}
.btn-ghost:hover{background:rgba(255,255,255,.1)}
.rbox{background:rgba(26,26,46,.6);border:1px solid #333;border-radius:10px;padding:16px;margin-top:10px;word-break:break-all;font-size:.82rem}
.rbox .lbl{color:#888;font-size:.7rem;margin-top:8px}
.rbox .lbl:first-of-type{margin-top:0}
.rbox .val{color:#22c55e;font-weight:500;font-family:monospace}
.rbox .url{color:#60a5fa}
.logbox{background:rgba(13,13,13,.9);border:1px solid #222;border-radius:10px;padding:12px;height:250px;overflow-y:auto;font-family:monospace;font-size:.75rem;line-height:1.6}
.logbox div{padding:3px 0;border-bottom:1px solid rgba(255,255,255,.03)}
.logbox .info{color:#60a5fa}.logbox .ok{color:#22c55e}.logbox .err{color:#ef4444}
.sp{display:inline-block;width:16px;height:16px;border:2px solid #333;border-top-color:#7c3aed;border-radius:50%;animation:s .8s linear infinite}
@keyframes s{to{transform:rotate(360deg)}}
.hidden{display:none}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.dot.g{background:#22c55e;box-shadow:0 0 6px rgba(34,197,94,.5)}
.dot.r{background:#ef4444;box-shadow:0 0 6px rgba(239,68,68,.5)}
.hitem{padding:8px;border-bottom:1px solid rgba(255,255,255,.04);cursor:pointer;transition:background .15s}
.hitem:hover{background:rgba(124,58,237,.1)}
.hitem .ht{color:#60a5fa}.hitem .hs{color:#666;font-size:.72rem}
@media(max-width:800px){.mainer{flex-direction:column}}
.help{font-size:.68rem;color:#666;margin-top:2px}
.small{font-size:.72rem;color:#888}
.grp{display:flex;gap:6px;flex-wrap:wrap}
.auth-tabs{display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap}
.auth-tab{padding:8px 14px;border-radius:8px;border:1px solid #333;background:rgba(26,26,46,.4);color:#888;font-size:.78rem;cursor:pointer;font-weight:500;transition:all .2s}
.auth-tab:hover{background:rgba(124,58,237,.15);color:#ccc}
.auth-tab.active{background:rgba(124,58,237,.25);border-color:#7c3aed;color:#7c3aed;font-weight:600}
.auth-panel{border:1px solid rgba(124,58,237,.15);border-radius:10px;padding:16px;background:rgba(26,26,46,.3)}
.auth-panel.hidden{display:none}
.auth-divider{display:flex;align-items:center;gap:12px;margin:14px 0;color:#555;font-size:.72rem}
.auth-divider::before,.auth-divider::after{content:'';flex:1;height:1px;background:#333}
.or-label{color:#666;font-size:.68rem;text-align:center;margin:6px 0}
</style></head>
<body>
<div class=header>
<h1>TikTok Live Studio Panel</h1>
<div style=display:flex;gap:14px;align-items:center>
<span id=ls style=font-size:.76rem></span>
<a href=/logout>Logout</a>
</div>
</div>
<div class=mainer>
<div class=col>
<!-- Auth Section -->
<div class=section id=authsect>
<h2>Authentication</h2>
<div class=auth-tabs>
<div class="auth-tab active" onclick=switchAuth('qr') id=atab_qr>QR Login</div>
<div class="auth-tab" onclick=switchAuth('web') id=atab_web>Web Login</div>
<div class="auth-tab" onclick=switchAuth('sid') id=atab_sid>Session ID</div>
<div class="auth-tab" onclick=switchAuth('cookie') id=atab_cookie>Load Cookies</div>
</div>

<!-- QR Login Panel -->
<div class=auth-panel id=apanel_qr>
<div id=qrp style=text-align:center>
<button class="btn btn-primary" onclick=sq()>Get QR Code</button>
<div class=or-label>Scan with TikTok mobile app</div>
</div>
<div id=qs class=hidden style=text-align:center>
<div id=qt class=small style=color:#f59e0b;margin-bottom:4px></div>
<img id=qi style=max-width:180px;border-radius:10px;border:2px solid #333>
<div class=small style=word-break:break-all;margin-top:4px id=qu></div>
</div>
<div id=qp class=hidden style=text-align:center;padding:16px><div class=sp></div><div class=small style=margin-top:6px;color:#60a5fa>Waiting...</div></div>
<div id=qd class=hidden style=text-align:center;padding:10px><span style=color:#22c55e>Logged in!</span><div class=small id=qci></div></div>
</div>

<!-- Web Login Panel -->
<div class=auth-panel hidden id=apanel_web>
<div style=text-align:center>
<div class=small style=margin-bottom:12px;color:#888">Opens TikTok login page. Enter credentials there, then paste the redirect info below.</div>
<button class="btn btn-primary" onclick=wl_open() id=wl_open_btn>Open TikTok Login</button>
<div class=or-label>After logging in, paste the callback URL or redirect data:</div>
<label style=margin-top:12px>Paste redirect URL or code</label>
<input id=wl_redirect placeholder="Paste full redirect URL or code here..." style=margin-top:4px>
<label>Or paste cookies JSON from browser after login</label>
<textarea id=wl_cookies placeholder='{"sessionid":"...","sid_tt":"..."}' rows=3 style=margin-top:4px;width:100%;padding:10px;border:1px solid #333;border-radius:8px;background:rgba(26,26,46,.8);color:#e0e0e0;font-size:.82rem;font-family:monospace;resize:vertical"></textarea>
<div style=display:flex;gap:8px;margin-top:12px>
<button class="btn btn-primary" onclick=wl_complete() style=flex:1 id=wl_complete_btn>Complete Login</button>
</div>
<div id=wl_status class=small style=margin-top:8px></div>
</div>
</div>

<!-- Session ID Panel -->
<div class=auth-panel hidden id=apanel_sid>
<div class=small style=margin-bottom:10px;color:#888">Paste your <code style="color:#7c3aed">sessionid</code> cookie value from TikTok.</div>
<label>Session ID</label>
<input id=sid_input placeholder="e.g. abc123def456..." style=margin-top:4px>
<label>Device ID (optional, auto-generated if empty)</label>
<input id=sid_did placeholder="Auto-generated">
<div style=display:flex;gap:8px;margin-top:12px>
<button class="btn btn-primary" onclick=sid_submit() style=flex:1 id=sid_submit_btn>Validate & Save</button>
</div>
<div class=help style=margin-top:8px">How to get sessionid: Open TikTok in browser, open DevTools (F12) &rarr; Application &rarr; Cookies &rarr; copy the value of <code>sessionid</code>.</div>
<div id=sid_status class=small style=margin-top:8px></div>
</div>

<!-- Load Cookies Panel -->
<div class=auth-panel hidden id=apanel_cookie>
<div style=text-align:center>
<button class="btn btn-primary" onclick=lc()>Load Cookies File</button>
<div class=or-label>or</div>
<button class="btn btn-ghost" onclick=pc()>Paste Cookies JSON</button>
</div>
</div>

<!-- Cookie Status (shared) -->
<div id=cs style=margin-top:12px class=hidden>
<div style=display:flex;align-items:center;gap:6px><span class="dot g"></span>Cookies: <span id=cc>0</span></div>
<button class="btn btn-sm btn-ghost" onclick=clc()>Clear</button>
</div>
</div>

<!-- Config -->
<div class=section>
<h2>Stream Config</h2>
<div style=display:grid;grid-template-columns:1fr 1fr;gap:0 14px>
<div><label>Title</label><input id=ft value="Live Stream" placeholder=Title></div>
<div><label>Description</label><input id=fd value="" placeholder=Optional></div>
</div>
<label>Topic Category</label>
<select id=ftpc>
{% for id,name in topics.items() %}
<option value="{{id}}"{% if id=="42"%}selected{% endif %}>{{name}} ({{id}})</option>
{% endfor %}
</select>
<label>Game Tag</label>
<div style=display:flex;gap:6px>
<select id=fgm style=flex:1><option value=0>None</option>
{% for id,name in game_tags.items() %}
<option value="{{id}}">{{name}} ({{id}})</option>
{% endfor %}</select>
<button class="btn btn-ghost btn-sm" onclick=rg() title=Refresh>&#x21bb;</button>
</div>
<label>Hashtags</label>
<input id=ftag value="" placeholder="freefire,ewc2026">
<label>Device ID</label>
<input id=fdid value="" placeholder="Auto-generated">
</div>
<div class=trow>
<div class=titem><input type=checkbox id=fc checked><label for=fc>Chat</label></div>
<div class=titem><input type=checkbox id=fg checked><label for=fg>Gifts</label></div>
<div class=titem><input type=checkbox id=fm><label for=fm>Multi-Stream</label></div>
<div class=titem><input type=checkbox id=fr><label for=fr>Replay</label></div>
<div class=titem><input type=checkbox id=fa><label for=fa>18+</label></div>
<div class=titem><input type=checkbox id=ff><label for=ff>Commercial</label></div>
</div>
<button class="btn btn-start btn-full" onclick=cr()>Generate Stream Key</button>
</div>
<div class=col>
<!-- Result -->
<div class=section id=ri style=display:none>
<h2>Stream Key</h2>
<div class=rbox id=sr></div>
<div class=grp style=margin-top:10px>
<button class="btn btn-stop" onclick=es()>End Stream</button>
<button class="btn btn-ghost" onclick=ca()>Copy All</button>
</div>
</div>
<!-- Log -->
<div class=section>
<h2>Log</h2>
<div class=logbox id=lb><div style=color:#666>Ready</div></div>
<div class=grp style=margin-top:6px><button class="btn btn-ghost btn-sm" onclick=cls()>Clear</button></div>
</div>
<!-- History -->
<div class=section>
<h2>History</h2>
<div id=hb style=font-size:.76rem>
{% for item in history %}
<div class=hitem onclick="rh({{loop.index0}})">
<div class=ht>{{item.title}} <span class=hs>{{item.stream_key}} &middot; {{item.created}}</span></div>
</div>
{% else %}
<div style=color:#666;padding:6px>No history</div>
{% endfor %}
</div>
</div>
</div>
</div>
<script>
let pi=null,lastCookies={},currentAuth='qr';

function lg(m,t='info'){let b=document.getElementById('lb'),d=document.createElement('div');d.className=t;d.textContent='['+new Date().toLocaleTimeString()+'] '+m;b.appendChild(d);b.scrollTop=b.scrollHeight}
function cls(){document.getElementById('lb').innerHTML='<div style=color:#666>Cleared</div>'}
function ls(h,s){document.getElementById('ls').innerHTML=(h?'<span class="dot g"></span>'+s:'<span class="dot r"></span>Not logged in')}

function switchAuth(method){
currentAuth=method;
['qr','web','sid','cookie'].forEach(m=>{
document.getElementById('atab_'+m).classList.toggle('active',m===method);
document.getElementById('apanel_'+m).classList.toggle('hidden',m!==method);
});
}

// ---- QR Login ----
function sq(){document.getElementById('qrp').hidden=1;document.getElementById('qs').classList.remove('hidden');document.getElementById('qp').classList.remove('hidden');document.getElementById('qd').classList.add('hidden');lg('Getting QR...','info')
fetch('/api/qr/start',{method:'POST'}).then(r=>r.json()).then(d=>{if(!d.ok){lg(d.error,'err');return}
document.getElementById('qp').classList.add('hidden');document.getElementById('qs').classList.remove('hidden');
document.getElementById('qi').src=d.qrcode_base64?'data:image/png;base64,'+d.qrcode_base64:'';document.getElementById('qt').textContent=d.expires_sec+'s';
lg('QR ready, scan with TikTok','ok')
let st=Date.now(),dur=60000;pi=setInterval(()=>{
let r=Math.max(0,60-((Date.now()-st)/1000|0));document.getElementById('qt').textContent=r+'s';
if(r<=0){clearInterval(pi);lg('QR expired','err')}
fetch('/api/qr/poll',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:d.token,device_id:d.device_id,domain:d.domain})}).then(r=>r.json()).then(d2=>{if(d2.ok){clearInterval(pi);lg('Logged in!','ok');document.getElementById('qs').classList.add('hidden');document.getElementById('qd').classList.remove('hidden');document.getElementById('qci').textContent='sessionid: '+d2.sessionid.slice(0,20)+'...';lastCookies=d2.cookies;uc()}
else if(d2.error!='expired'&&r>0)lg('Poll: '+d2.error,'err')
}).catch(e=>{})
},2000)}).catch(e=>{lg(e,'err')})}

// ---- Web Login ----
function wl_open(){
lg('Opening TikTok login page...','info');
let btn=document.getElementById('wl_open_btn');
btn.disabled=true;btn.textContent='Opening...';
fetch('/api/weblogin/start',{method:'POST'}).then(r=>r.json()).then(d=>{
btn.disabled=false;btn.textContent='Open TikTok Login';
if(!d.ok){lg(d.error,'err');return}
lg('Login URL ready. Opening in new tab...','ok');
let w=window.open(d.login_url,'_blank','width=500,height=700');
if(!w||w.closed){lg('Popup blocked. Please allow popups and try again, or open the URL manually.','err');
document.getElementById('wl_status').innerHTML='<span style=color:#ef4444>Popup blocked - allow popups or open TikTok login manually</span>';}
}).catch(e=>{btn.disabled=false;btn.textContent='Open TikTok Login';lg('Error: '+e,'err')})}

function wl_complete(){
let redirect=document.getElementById('wl_redirect').value.trim();
let cookiesJson=document.getElementById('wl_cookies').value.trim();
let statusEl=document.getElementById('wl_status');
let btn=document.getElementById('wl_complete_btn');
if(cookiesJson){
lg('Importing cookies from browser...','info');
btn.disabled=true;btn.textContent='Validating...';
fetch('/api/cookies',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cookies:cookiesJson})}).then(r=>r.json()).then(d=>{
btn.disabled=false;btn.textContent='Complete Login';
if(d.ok){lg('Cookies imported!','ok');uc();statusEl.innerHTML='<span style=color:#22c55e>Login successful!</span>';}
else{lg('Error: '+d.error,'err');statusEl.innerHTML='<span style=color:#ef4444>'+d.error+'</span>';}
}).catch(e=>{btn.disabled=false;btn.textContent='Complete Login';lg('Error: '+e,'err')});
return;
}
if(redirect){
lg('Completing web login...','info');
btn.disabled=true;btn.textContent='Validating...';
fetch('/api/weblogin/complete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({redirect_data:redirect})}).then(r=>r.json()).then(d=>{
btn.disabled=false;btn.textContent='Complete Login';
if(d.ok){lg('Web login successful!','ok');lastCookies=d.cookies;uc();statusEl.innerHTML='<span style=color:#22c55e>Login successful! sessionid: '+d.sessionid.slice(0,20)+'...</span>';}
else{lg('Error: '+d.error,'err');statusEl.innerHTML='<span style=color:#ef4444>'+d.error+'</span>';}
}).catch(e=>{btn.disabled=false;btn.textContent='Complete Login';lg('Error: '+e,'err')});
return;
}
statusEl.innerHTML='<span style=color:#ef4444>Please paste the redirect URL/code, or paste cookies JSON above.</span>';
}

// ---- Session ID ----
function sid_submit(){
let sid=document.getElementById('sid_input').value.trim();
let did=document.getElementById('sid_did').value.trim();
let statusEl=document.getElementById('sid_status');
let btn=document.getElementById('sid_submit_btn');
if(!sid){statusEl.innerHTML='<span style=color:#ef4444>Please enter a session ID</span>';return;}
lg('Validating session ID...','info');
btn.disabled=true;btn.textContent='Validating...';
fetch('/api/sessionid',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sessionid:sid,device_id:did||undefined})}).then(r=>r.json()).then(d=>{
btn.disabled=false;btn.textContent='Validate & Save';
if(d.ok){
lg('Session ID valid! User: @'+d.username,'ok');
statusEl.innerHTML='<span style=color:#22c55e>Logged in as @'+d.username+' ('+d.nickname+')</span>';
uc();
}else{lg('Session ID invalid: '+d.error,'err');statusEl.innerHTML='<span style=color:#ef4444>'+d.error+'</span>';}
}).catch(e=>{btn.disabled=false;btn.textContent='Validate & Save';lg('Error: '+e,'err');statusEl.innerHTML='<span style=color:#ef4444>Network error</span>'})}

// ---- Load/Paste Cookies ----
function lc(){let e=document.createElement('input');e.type='file';e.accept='.json';e.onchange=async ev=>{let f=ev.target.files[0];if(!f)return;lg('Loading cookies file...','info');try{let t=await f.text();let d=JSON.parse(t);if(Array.isArray(d))d=d.reduce((a,c)=>{a[c.name]=c.value;return a},{});r=await fetch('/api/cookies',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cookies:d})});rd=await r.json();if(rd.ok){lg('Cookies loaded','ok');uc()}else lg('Error: '+rd.error,'err')}catch(e2){lg('Parse error: '+e2,'err')}};e.click()}
function pc(){let v=prompt('Paste cookies JSON (dict or array)');if(!v)return
fetch('/api/cookies',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cookies:v})}).then(r=>r.json()).then(d=>{if(d.ok){lg('Cookies loaded','ok');uc()}else lg('Error: '+d.error,'err')}).catch(e=>{})}

// ---- Shared ----
function uc(){fetch('/api/cookies').then(r=>r.json()).then(d=>{if(d.ok&&d.loaded){document.getElementById('cs').classList.remove('hidden');document.getElementById('cc').textContent=d.count;ls(1,'sessionid: '+d.sessionid.slice(0,20)+'...')}else{document.getElementById('cs').classList.add('hidden');ls(0)};lastCookies=d.cookies||lastCookies}).catch(e=>{})}
function clc(){fetch('/api/cookies',{method:'DELETE'}).then(()=>{lg('Cookies cleared','ok');uc()}).catch(e=>{})}
function rg(){lg('Refreshing game tags...','info');fetch('/api/games').then(r=>r.json()).then(d=>{if(d.ok){lg('Game tags updated','ok');location.reload()}else lg('Error: '+d.error,'err')}).catch(e=>{})}
function cr(){let opts={title:document.getElementById("ft").value||'Live Stream',description:document.getElementById("fd").value,topic_id:document.getElementById("ftpc").value,game_tag_id:document.getElementById("fgm").value,hashtags:document.getElementById("ftag").value,device_id:document.getElementById("fdid").value,chat:document.getElementById("fc").checked,gifts:document.getElementById("fg").checked,multi_stream:document.getElementById("fm").checked,gen_replay:document.getElementById("fr").checked,age_restricted:document.getElementById("fa").checked,commercial:document.getElementById("ff").checked}
lg('Creating room: '+opts.title,'info')
fetch('/api/room/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(opts)}).then(r=>r.json()).then(d=>{if(d.ok){lg('Stream key generated!','ok')
let h='<div class=lbl>Server URL</div><div class="val url">'+d.server_url+'</div><div class=lbl>Stream Key</div><div class=val>'+d.stream_key+'</div><div class=lbl>RTMP URL</div><div class=val>'+d.rtmp_url+'</div><div class=lbl>Share URL</div><div class=val>'+d.share_url+'</div><div class=lbl>Room ID: '+d.room_id+'</div>'
document.getElementById('sr').innerHTML=h;document.getElementById('ri').style.display='';document.getElementById('ri').scrollIntoView({behavior:'smooth'})
}else{lg('Failed: '+d.error,'err')}
}).catch(e=>{lg('Error: '+e,'err')})}
function es(){let rid=prompt('Room ID:');let sid=prompt('Stream ID (optional):');if(!rid)return
lg('Ending stream...','info');fetch('/api/room/end',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({room_id:rid,stream_id:sid})}).then(r=>r.json()).then(d=>{lg(d.ok?'Stream ended':'Failed: '+d.error,d.ok?'ok':'err')}).catch(e=>{})}
function ca(){let el=document.getElementById('sr');let t=el.innerText;navigator.clipboard.writeText(t);lg('Copied','ok')}
uc()
</script></body></html>
'''

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG', '0') == '1')
