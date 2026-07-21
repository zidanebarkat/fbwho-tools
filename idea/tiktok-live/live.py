#!/usr/bin/env python3
"""
TikTok Live Stream Key Generator

Flow:
  1. QR code login via passport/web/get_qrcode/ + check_qrconnect/
  2. Extract tiktokv.com session cookies
  3. Metasec-signed POST to webcast/room/create/
  4. Output RTMP server + stream key

Options:
  --title          Stream title
  --topic          Topic category (hashtag_id): 5=Gaming, 6=Music, 42=Chat, etc.
  --game           Game tag ID (fetched from API, use --list-games to see)
  --list-games     Fetch and display available game tags
  --no-chat        Disable chat
  --no-gifts       Disable gifts
  --age-restricted Mark as 18+
  --gen-replay     Generate replay after stream ends
  --multi-stream   Enable multi-stream scene
  --commercial     Enable commercial content promotion
"""
import hashlib
import json
import os
import secrets
import string
import sys
import time
import urllib.parse
from pathlib import Path

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
METASEC_PATH = Path("/home/dev/code_test/test/tiktok-api/Mobile")
sys.path.insert(0, str(METASEC_PATH))
os.chdir(str(METASEC_PATH))
from metasec import Metasec
from curl_cffi import requests as cffi_requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PASSPORT_APP_KEY = "884c28a44b61b78f9d837fc8b0967178"
PASSPORT_WEB_SDK_VERSION = "2.1.9"
LIVE_STUDIO_AID = 8311
DEVICE_ID_LEN = 19

TOPICS = {
    "5": "Gaming",
    "6": "Music",
    "42": "Chat & Interview",
    "9": "Beauty & Fashion",
    "3": "Dance",
    "13": "Fitness & Sports",
    "4": "Food",
    "43": "News & Event",
    "45": "Education",
}

# ---------------------------------------------------------------------------
# Passport SDK signing
# ---------------------------------------------------------------------------
def _passport_stringify_value(v):
    if isinstance(v, (dict, list, tuple)):
        return json.dumps(v, separators=(",", ":"), ensure_ascii=False)
    return str(v)


def _passport_sorted_string(values, limit=-1):
    ignored = {"sign", "qs", "isResend", "next", "baseURL", "extra_params"}
    keys = sorted(
        str(k) for k, v in values.items() if v is not None and str(k) not in ignored
    )
    if limit >= 0:
        keys = keys[:limit]
    parts = [f"{k}={_passport_stringify_value(values.get(k))}" for k in keys]
    return "&".join(parts), keys


def _passport_xor5_qs(keys):
    raw = ",".join(keys).encode("utf-8")
    return "".join(f"{b ^ 5:02x}" for b in raw)


def passport_sig(params, data=None):
    param_string, signed_keys = _passport_sorted_string(params or {}, limit=10)
    body_string, _ = _passport_sorted_string(data or {})
    base = f"{param_string}&{body_string}&app_key={PASSPORT_APP_KEY}"
    return {
        "sign": hashlib.md5(base.encode("utf-8")).hexdigest(),
        "qs": _passport_xor5_qs(signed_keys),
    }


def apply_passport_sig(params, data=None):
    signed = dict(params or {})
    signed.pop("sign", None)
    signed.pop("qs", None)
    signed.update(passport_sig(signed, data=data))
    return signed


# ---------------------------------------------------------------------------
# Metasec signing (for webcast/room/create/)
# ---------------------------------------------------------------------------
def metasec_sign(url, params, body_data=None):
    ts = int(time.time())
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    full_url = f"{url}?{qs}"
    body_enc = (
        urllib.parse.urlencode(body_data, doseq=True, quote_via=urllib.parse.quote)
        if body_data
        else ""
    )
    body_hex = body_enc.encode().hex() if body_enc else "00" * 16
    x_ss_stub = hashlib.md5(body_enc.encode()).hexdigest() if body_enc else None
    signer = Metasec()
    sig = signer.sign(
        url=full_url,
        app_id=LIVE_STUDIO_AID,
        app_version="1.27.0",
        app_launch_time=ts,
        device_type="SM-G973N",
        sdk_version="v04.04.09-boa-hotfix",
        sdk_version_code=44409,
        license_id=1877999593,
        device_id=params.get("device_id", "0"),
        payload=body_hex,
        cookies="",
    )
    headers = {
        "x-khronos": str(sig["x-khronos"]),
        "x-ladon": sig["x-ladon"],
        "x-argus": sig["x-argus"],
        "x-gorgon": sig["x-gorgon"],
    }
    if x_ss_stub:
        headers["x-ss-stub"] = x_ss_stub
    return headers, ts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def gen_device_id():
    return "".join(secrets.choice(string.digits) for _ in range(DEVICE_ID_LEN))


def fetch_game_tags():
    """Fetch available game tags from TikTok API."""
    s = make_session()
    url = "https://webcast16-normal-c-alisg.tiktokv.com/webcast/room/hashtag/list/"
    try:
        r = s.get(url, timeout=15)
        data = r.json()
        tags = data.get("data", {}).get("game_tag_list", [])
        return {str(t["id"]): t.get("show_name", "") for t in tags}
    except Exception as e:
        print(f"  Failed to fetch game tags: {e}")
        return {}


def list_game_tags():
    """Print available game tags."""
    print("[*] Fetching game tags...")
    tags = fetch_game_tags()
    if not tags:
        print("[!] No game tags available")
        return
    print(f"\n{'ID':<8} {'Name'}")
    print("-" * 40)
    for tid, name in sorted(tags.items(), key=lambda x: int(x[0])):
        print(f"{tid:<8} {name}")
    print(f"\nTotal: {len(tags)} game tags")
    print("Use --game <ID> to select one")


def make_session():
    s = cffi_requests.Session(impersonate="chrome")
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) TikTokLIVEStudio/1.27.0 Chrome/136.0.7103.59 "
            "Electron/36.4.0-alpha.17 TTElectron/36.4.0-alpha.17 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US",
    })
    return s


def build_passport_params(device_id):
    verify_fp = f"verify_{device_id}"
    return {
        "next": "https://www.tiktok.com",
        "device_id": device_id,
        "aid": str(LIVE_STUDIO_AID),
        "account_sdk_source": "web",
        "sdk_version": PASSPORT_WEB_SDK_VERSION,
        "verifyFp": verify_fp,
    }


# ---------------------------------------------------------------------------
# Step 1: QR code login
# ---------------------------------------------------------------------------
def qr_login(s, device_id, poll_interval=3, poll_timeout=120):
    params = apply_passport_sig(build_passport_params(device_id))
    hosts = [
        "api16-normal-c-alisg.tiktokv.com",
        "api16-normal-no1a.tiktokv.eu",
        "api16-normal-useast8.tiktokv.us",
    ]

    token = None
    qr_url = None
    for host in hosts:
        try:
            r = s.get(
                f"https://{host}/passport/web/get_qrcode/",
                params=params,
                headers={
                    "accept": "application/json, text/javascript",
                    "content-type": "application/x-www-form-urlencoded",
                    "referer": "https://www.tiktok.com/ucenter_web/live_studio/login",
                },
                timeout=15,
            )
            data = r.json()
            d = data.get("data", {})
            if d.get("token"):
                token = d["token"]
                qr_url = d.get("qrcode_index_url", "")
                print(f"[+] QR token from {host}")
                break
        except Exception as e:
            print(f"  [{host}] {e}")
            continue

    if not token:
        print("[!] Failed to get QR code from any host")
        return None

    print(f"[+] Token: {token[:30]}...")
    print(f"[+] Scan this URL with your TikTok app:")
    print(f"    {qr_url}")
    print(f"    (also saved to qrcode.png)")

    # Save QR as PNG
    try:
        import qrcode as qr_lib
        img = qr_lib.make(qr_url)
        img.save("qrcode.png")
        print("    [qrcode.png saved]")
        try:
            os.system("xdg-open qrcode.png 2>/dev/null &")
        except Exception:
            pass
    except ImportError:
        print("    [qrcode lib not installed, install with: pip install qrcode[pil]]")

    # Poll check_qrconnect
    poll_params_template = build_passport_params(device_id)
    poll_params_template["token"] = token
    poll_params_template["multi_login"] = "1"

    start = time.time()
    while time.time() - start < poll_timeout:
        poll_params = apply_passport_sig(dict(poll_params_template))
        for host in hosts:
            try:
                r = s.get(
                    f"https://{host}/passport/web/check_qrconnect/",
                    params=poll_params,
                    headers={
                        "accept": "application/json, text/javascript",
                        "content-type": "application/x-www-form-urlencoded",
                        "referer": "https://www.tiktok.com/ucenter_web/live_studio/login",
                    },
                    timeout=15,
                )
                resp = r.json()
                status = resp.get("data", {}).get("status", "")
                elapsed = int(time.time() - start)
                if status == "new":
                    print(f"  [{elapsed}s] waiting for scan...")
                elif status == "scanned":
                    print(f"  [{elapsed}s] scanned! confirm on phone...")
                elif status == "confirmed":
                    print(f"  [{elapsed}s] confirmed!")
                    # curl_cffi: iterating s.cookies yields strings, use .jar for objects
                    cookies = {}
                    for c in s.cookies.jar:
                        cookies[c.name] = c.value
                    # Also parse raw Set-Cookie headers as fallback
                    for k, v in r.headers.items():
                        if k.lower() == "set-cookie":
                            parts = v.split(";")[0].split("=", 1)
                            if len(parts) == 2:
                                cookies[parts[0].strip()] = parts[1].strip()
                    return cookies
                elif status == "expired":
                    print(f"  [{elapsed}s] QR expired!")
                    return None
                break
            except Exception:
                continue
        time.sleep(poll_interval)

    print("[!] QR poll timeout")
    return None


# ---------------------------------------------------------------------------
# Step 2: Create stream
# ---------------------------------------------------------------------------
def create_stream(
    s,
    session_cookies,
    device_id,
    title="Live Stream",
    topic_id="42",
    game_tag_id="0",
    chat_auth="1",
    gift_auth="1",
    age_restricted=False,
    gen_replay=False,
    multi_stream_scene=False,
    commercial_content=False,
):
    # Build params
    params = {
        "aid": str(LIVE_STUDIO_AID),
        "app_name": "tiktok_live_studio",
        "device_id": device_id,
        "install_id": "0",
        "channel": "studio",
        "version_code": "1.27.0",
        "device_platform": "windows",
        "timezone_name": "Africa/Tunis",
        "screen_width": "1920",
        "screen_height": "1080",
        "browser_language": "en-US",
        "browser_platform": "Win32",
        "browser_name": "Mozilla",
        "browser_version": (
            "5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) TikTokLIVEStudio/1.27.0 Chrome/136.0.7103.59 "
            "Electron/36.4.0-alpha.17 TTElectron/36.4.0-alpha.17 Safari/537.36"
        ),
        "language": "en",
        "app_language": "en",
        "webcast_language": "en",
        "webcast_sdk_version": "1270",
        "live_mode": "6",
    }

    body = {
        "title": title,
        "live_studio": "1",
        "gen_replay": str(gen_replay).lower(),
        "chat_auth": chat_auth,
        "age_restricted": "4" if age_restricted else "0",
        "cover_uri": "",
        "close_room_when_close_stream": "false",
        "hashtag_id": str(topic_id),
        "game_tag_id": str(game_tag_id),
        "game_bitrate_type": "high",
        "screenshot_cover_status": "1",
        "multi_stream_scene": "1" if multi_stream_scene else "0",
        "gift_auth": gift_auth,
        "chat_l2": "1",
        "star_comment_switch": "true",
        "multi_stream_source": "1",
        "is_group_live_session": "false",
        "open_commercial_content_toggle": str(commercial_content).lower(),
        "commercial_content_promote_myself": str(commercial_content).lower(),
        "commercial_content_promote_third_party": str(commercial_content).lower(),
        "rtc_net_enabled": "false",
    }

    # Build hosts to try
    hosts = [
        "webcast16-normal-c-alisg.tiktokv.com",
        "webcast16-normal-useast5.tiktokv.us",
        "webcast16-normal-no1a.tiktokv.eu",
    ]

    for host in hosts:
        base_url = f"https://{host}/"
        api_url = base_url + "webcast/room/create/"
        sig_headers, _ = metasec_sign(api_url, params, body)

        # New session with tiktokv cookies
        stream_s = make_session()
        for name, value in session_cookies.items():
            stream_s.cookies.set(name, value, domain=".tiktokv.com")

        stream_s.headers.update({
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://livecenter.tiktok.com",
            "Referer": "https://livecenter.tiktok.com/",
            "webcast-ntp-t0": f"{time.perf_counter() * 1000:.3f}",
            **sig_headers,
        })

        try:
            r = stream_s.post(api_url, params=params, data=body, timeout=30)
            print(f"  [{host}] HTTP {r.status_code}")
            resp = r.json()
        except Exception as e:
            print(f"  [{host}] {e}")
            continue

        if resp.get("status_code") == 0:
            return resp.get("data", {})

        sc = resp.get("status_code")
        msg = resp.get("data", {}).get("prompts") or resp.get("data", {}).get("message") or str(resp)
        print(f"  [{host}] status_code={sc}: {msg[:100]}")
        if sc != 20800:
            break

    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    import argparse

    parser = argparse.ArgumentParser(description="TikTok Live Stream Key Generator")
    parser.add_argument("--title", default="Live Stream", help="Stream title")
    parser.add_argument("--topic", default="42", help="Topic ID (hashtag_id): 5=Gaming, 6=Music, 42=Chat, 9=Fashion, 3=Dance, 13=Fitness, 4=Food, 43=News, 45=Education")
    parser.add_argument("--game", default="0", help="Game tag ID (use --list-games to see available)")
    parser.add_argument("--list-games", action="store_true", help="List available game tags and exit")
    parser.add_argument("--search-games", default="", help="Search game tags by name")
    parser.add_argument("--no-chat", action="store_true", help="Disable chat")
    parser.add_argument("--no-gifts", action="store_true", help="Disable gifts")
    parser.add_argument("--age-restricted", action="store_true", help="Mark stream as 18+")
    parser.add_argument("--gen-replay", action="store_true", help="Generate replay after stream ends")
    parser.add_argument("--multi-stream", action="store_true", help="Enable multi-stream scene")
    parser.add_argument("--commercial", action="store_true", help="Enable commercial content promotion")
    parser.add_argument("--device-id", default="", help="Device ID (auto-generated if empty)")
    parser.add_argument("--poll-interval", type=int, default=3, help="QR poll interval (seconds)")
    parser.add_argument("--poll-timeout", type=int, default=120, help="QR poll timeout (seconds)")
    parser.add_argument("--session-cookies", default="", help="Path to JSON file with session cookies (skips QR login)")
    parser.add_argument("--json-output", action="store_true", help="Output RTMP URL as JSON to stdout")
    args = parser.parse_args()

    # List games and exit
    if args.list_games:
        list_game_tags()
        sys.exit(0)

    # Search games and exit
    if args.search_games:
        print(f"[*] Searching game tags for '{args.search_games}'...")
        tags = fetch_game_tags()
        query = args.search_games.lower()
        matches = [(tid, name) for tid, name in tags.items() if query in name.lower()]
        if not matches:
            print(f"[!] No matches for '{args.search_games}'")
        else:
            print(f"\n{'ID':<8} {'Name'}")
            print("-" * 40)
            for tid, name in sorted(matches, key=lambda x: x[1].lower()):
                print(f"{tid:<8} {name}")
            print(f"\n{len(matches)} matches found")
        sys.exit(0)

    device_id = args.device_id or gen_device_id()
    s = make_session()

    # Resolve topic name for display
    topic_name = TOPICS.get(args.topic, f"ID:{args.topic}")

    if not args.json_output:
        print("=" * 60)
        print("  TikTok Live Stream Key Generator")
        print("=" * 60)
        print(f"  Title:       {args.title}")
        print(f"  Topic:       {topic_name} (ID:{args.topic})")
        print(f"  Game Tag:    {args.game}")
        print(f"  Chat:        {'ON' if not args.no_chat else 'OFF'}")
        print(f"  Gifts:       {'ON' if not args.no_gifts else 'OFF'}")
        print(f"  Age 18+:     {'YES' if args.age_restricted else 'NO'}")
        print(f"  Replay:      {'YES' if args.gen_replay else 'NO'}")
        print(f"  Multi-Stream:{'YES' if args.multi_stream else 'NO'}")
        print(f"  Commercial:  {'YES' if args.commercial else 'NO'}")
        print("=" * 60)

    # Step 1: Login (QR or stored session cookies)
    if args.session_cookies:
        if not args.json_output:
            print(f"[*] Loading session cookies from {args.session_cookies}")
        with open(args.session_cookies) as f:
            session_cookies = json.load(f)
        if "sessionid" not in session_cookies:
            if args.json_output:
                print(json.dumps({"error": "No sessionid in cookies file"}))
            else:
                print("[!] No sessionid in cookies file")
            sys.exit(1)
        if not args.json_output:
            print(f"[+] Loaded {len(session_cookies)} cookies")
    else:
        if not args.json_output:
            print("\n[*] Step 1: QR Code Login")
        qr_data = qr_login(s, device_id, args.poll_interval, args.poll_timeout)
        if not qr_data:
            if args.json_output:
                print(json.dumps({"error": "QR login failed"}))
            else:
                print("[!] QR login failed")
            sys.exit(1)
        session_cookies = qr_data
        # Save cookies for reuse
        cookies_out = Path(__file__).parent / "session_cookies.json"
        with open(cookies_out, "w") as f:
            json.dump(session_cookies, f, indent=2)
        if not args.json_output:
            print(f"[+] Session cookies saved to {cookies_out}")

    if "sessionid" not in session_cookies:
        if args.json_output:
            print(json.dumps({"error": "No sessionid in cookies", "got": list(session_cookies.keys())[:10]}))
        else:
            print("[!] No sessionid in cookies")
            print(f"    Got: {list(session_cookies.keys())[:10]}")
        sys.exit(1)

    for name in ["sessionid", "sessionid_ss", "sid_tt", "sid_guard", "multi_sids"]:
        val = session_cookies.get(name, "")
        if val:
            if not args.json_output:
                print(f"  {name}: {val[:30]}...")

    # Step 2: Create stream
    if not args.json_output:
        print(f"\n[*] Step 2: Creating live room '{args.title}'")
    else:
        # Suppress verbose output in JSON mode
        import io
        _old_stdout = sys.stdout
        sys.stdout = io.StringIO()

    stream_data = create_stream(
        s,
        session_cookies,
        device_id,
        title=args.title,
        topic_id=args.topic,
        game_tag_id=args.game,
        chat_auth="0" if args.no_chat else "1",
        gift_auth="0" if args.no_gifts else "1",
        age_restricted=args.age_restricted,
        gen_replay=args.gen_replay,
        multi_stream_scene=args.multi_stream,
        commercial_content=args.commercial,
    )
    if not args.json_output:
        if not stream_data:
            print("[!] Failed to create stream")
            sys.exit(1)
    else:
        sys.stdout = _old_stdout
        if not stream_data:
            print(json.dumps({"error": "Failed to create stream"}))
            sys.exit(1)

    stream_url = stream_data.get("stream_url", {}).get("rtmp_push_url", "")
    share_url = stream_data.get("share_url", "")

    if not stream_url:
        if args.json_output:
            print(json.dumps({"error": "No RTMP URL in response"}))
        else:
            print("[!] No RTMP URL in response")
            print(json.dumps(stream_data, indent=2)[:500])
        sys.exit(1)

    idx = stream_url.rfind("/")
    rtmp_server = stream_url[:idx]
    stream_key = stream_url[idx + 1:]

    # Build result
    result = {
        "rtmp_server": rtmp_server,
        "stream_key": stream_key,
        "rtmp_url": stream_url,
        "share_url": share_url,
        "room_id": stream_data.get("room_id", ""),
        "title": args.title,
        "topic_id": args.topic,
        "topic_name": topic_name,
        "game_tag_id": args.game,
        "chat_auth": not args.no_chat,
        "gift_auth": not args.no_gifts,
        "age_restricted": args.age_restricted,
    }

    if args.json_output:
        # Output clean JSON to stdout for workflow consumption
        print(json.dumps(result))
    else:
        print("\n" + "=" * 60)
        print("  STREAM KEY GENERATED")
        print("=" * 60)
        print(f"  Server:  {rtmp_server}")
        print(f"  Key:     {stream_key}")
        print(f"  RTMP:    {stream_url}")
        print(f"  Share:   {share_url}")
        print(f"  Topic:   {topic_name} (ID:{args.topic})")
        if args.game != "0":
            print(f"  Game:    Tag ID {args.game}")
        print()
        print("  OBS: Settings -> Stream -> Custom")
        print(f"    Server: {rtmp_server}")
        print(f"    Key:    {stream_key}")
        print("=" * 60)

        # Save to file
        out = Path(__file__).parent / "stream_key.json"
        with open(out, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\n[+] Saved to {out}")


if __name__ == "__main__":
    main()
