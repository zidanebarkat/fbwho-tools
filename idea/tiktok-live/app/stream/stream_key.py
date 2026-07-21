"""Stream key generation — creates TikTok live rooms via Metasec-signed API."""
import time
from app.auth.qr_service import make_session, metasec_sign, Config
from app.models.session import TikTokSession


def build_params(did):
    return {
        "aid": str(Config.LIVE_STUDIO_AID),
        "app_name": "tiktok_live_studio",
        "device_id": did,
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
        "browser_version": "Mozilla/5.0 (Windows) TikTokLIVEStudio/1.27.0 Chrome/136 Safari/537.36",
        "language": "en",
        "app_language": "en",
        "webcast_language": "en",
        "webcast_sdk_version": "1270",
        "live_mode": "6",
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
        "chat_l2": "1",
        "star_comment_switch": "true",
        "multi_stream_source": "1",
        "is_group_live_session": "false",
        "open_commercial_content_toggle": str(opts.get("commercial", False)).lower(),
        "commercial_content_promote_me": str(opts.get("commercial", False)).lower(),
        "rtc_net_enabled": "false",
    }


def create_room(session: TikTokSession, opts: dict):
    did = session.device_id
    cookies = session.cookies
    params = build_params(did)
    body = build_body(opts)

    hosts = [
        "webcast16-normal-c-alisg.tiktokv.com",
        "webcast16-normal-useast5.tiktokv.us",
        "webcast16-normal-no1a.tiktokv.eu",
    ]

    for host in hosts:
        api_url = f"https://{host}/webcast/room/create/"
        sig_headers, _ = metasec_sign(api_url, params, body)
        ss = make_session()
        for n, v in cookies.items():
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


def end_room(session: TikTokSession, rid, sid):
    params = build_params(session.device_id)
    data = {"status": "4", "room_id": rid, "stream_id": sid}

    for host in ["webcast16-normal-c-alisg.tiktokv.com"]:
        api_url = f"https://{host}/webcast/room/ping/anchor/"
        sig_headers, _ = metasec_sign(api_url, params, data)
        ss = make_session()
        for n, v in session.cookies.items():
            ss.cookies.set(n, v, domain=".tiktokv.com")
        ss.headers.update({"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", **sig_headers})
        try:
            r = ss.post(api_url, params=params, data=data, timeout=30)
            if r.json().get("status_code") == 0:
                return True
        except Exception:
            continue
    return False
