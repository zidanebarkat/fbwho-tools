"""QR login service — generates QR tokens, polls for scan, extracts cookies."""
import base64, hashlib, json, secrets, string, time, urllib.parse
from functools import wraps
from flask import session as flask_session, redirect, url_for, jsonify

from Mobile.metasec import Metasec
from curl_cffi import requests as curl_requests
from config import Config

# QR tokens expire after this many seconds (3 min)
QR_TOKEN_TTL = 300


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
    h = hashlib.md5(f"{ps}&{bs}&app_key={Config.PASSPORT_APP_KEY}".encode()).hexdigest()
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
        url=full_url, app_id=Config.LIVE_STUDIO_AID, app_version="1.27.0",
        app_launch_time=ts, device_type="SM-G973N",
        sdk_version="v04.04.09-boa-hotfix", sdk_version_code=44409,
        license_id=1877999593, device_id=params.get("device_id", "0"),
        payload=bh, cookies="",
    )
    hdrs = {
        "x-khronos": str(sig["x-khronos"]),
        "x-ladon": sig["x-ladon"],
        "x-argus": sig["x-argus"],
        "x-gorgon": sig["x-gorgon"],
    }
    if stub:
        hdrs["x-ss-stub"] = stub
    return hdrs, ts


# ---------------------------------------------------------------------------
# Auth decorators
# ---------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated(*a, **kw):
        if not flask_session.get('authenticated'):
            return redirect(url_for('auth.login'))
        return f(*a, **kw)
    return decorated


def api_auth(f):
    @wraps(f)
    def decorated(*a, **kw):
        if not flask_session.get('authenticated'):
            return jsonify({"ok": False, "error": "Not authenticated"}), 401
        return f(*a, **kw)
    return decorated


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


def qr_step1():
    session = make_session()
    for host in api_hosts():
        url = f"https://{host}/passport/web/get_qrcode/"
        did = gen_device_id()
        params = apply_ps({
            "next": "https://www.tiktok.com",
            "device_id": did,
            "aid": str(Config.LIVE_STUDIO_AID),
            "account_sdk_source": "web",
            "sdk_version": Config.PASSPORT_WEB_SDK_VERSION,
            "verifyFp": f"verify_{did}",
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
            # Stamp creation time + consumed flag on session
            flask_session['_qr_created'] = time.time()
            flask_session['_qr_consumed'] = False
            return {
                "token": tok,
                "qrcode_url": qurl,
                "device_id": did,
                "domain": host,
                "qrcode_base64": b64,
            }
        except Exception:
            continue
    raise RuntimeError("QR setup failed")


def qr_step2(token, device_id, domain):
    # --- security: reject expired or already-used tokens ---
    created = flask_session.get('_qr_created', 0)
    if time.time() - created > QR_TOKEN_TTL:
        raise TimeoutError("QR token expired")
    if flask_session.get('_qr_consumed'):
        raise RuntimeError("QR token already used")
    session = make_session()
    hosts = [domain] + api_hosts()
    for host in hosts:
        url = f"https://{host}/passport/web/check_qrconnect/"
        params = apply_ps({
            "next": "https://www.tiktok.com",
            "token": token,
            "multi_login": "1",
            "device_id": device_id,
            "aid": str(Config.LIVE_STUDIO_AID),
            "account_sdk_source": "web",
            "sdk_version": Config.PASSPORT_WEB_SDK_VERSION,
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
                flask_session['_qr_consumed'] = True
                return cookies
            elif data.get("status_code") == 3:
                return "pending"
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
                "aid": str(Config.LIVE_STUDIO_AID),
                "device_id": did,
                "identity": "passport",
                "account_sdk_source": "web",
                "sdk_version": Config.PASSPORT_WEB_SDK_VERSION,
            },
            headers={"accept": "application/json, text/plain, */*", "referer": "https://www.tiktok.com/", **tg_headers()},
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
    return {"valid": False, "username": "", "nickname": "", "uid": ""}
