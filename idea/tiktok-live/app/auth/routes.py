"""Authentication routes — login, QR, session ID, cookie upload, logout."""
import json
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, current_app

from config import Config
from app.models.session import TikTokSession, load_session, save_session, clear_session
from app.auth.qr_service import (
    login_required, api_auth, qr_step1, qr_step2,
    validate_session_id, gen_device_id,
)
from app.security import csrf_protect

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
@csrf_protect
def login():
    if request.method == 'POST' and request.form.get('password') == current_app.config['PANEL_PASSWORD']:
        session['authenticated'] = True
        return redirect(url_for('root'))
    error = 'Wrong password' if request.method == 'POST' else None
    return render_template('login.html', error=error)


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


@auth_bp.route('/qr')
@login_required
def qr_page():
    tok = load_session()
    if tok.is_active:
        return redirect(url_for('stream.dashboard'))
    return render_template('login_qr.html')


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@auth_bp.route('/api/qr/start', methods=['POST'])
@api_auth
@csrf_protect
def api_qr_start():
    try:
        qr = qr_step1()
        return jsonify({"ok": True, **qr})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@auth_bp.route('/api/qr/poll', methods=['POST'])
@api_auth
@csrf_protect
def api_qr_poll():
    body = request.get_json(force=True)
    try:
        cookies = qr_step2(body.get("token", ""), body.get("device_id", ""), body.get("domain", ""))
        if cookies is None:
            return jsonify({"ok": False, "error": "expired"})
        tok = TikTokSession(
            cookies=cookies,
            device_id=cookies.get("device_id", gen_device_id()),
            is_active=True,
        )
        save_session(tok)
        return jsonify({"ok": True, "sessionid": cookies.get("sessionid", "")})
    except TimeoutError:
        return jsonify({"ok": False, "error": "expired"})
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@auth_bp.route('/api/sessionid', methods=['POST'])
@api_auth
@csrf_protect
def api_sessionid():
    body = request.get_json(force=True)
    sid = (body.get("sessionid") or "").strip()
    if not sid:
        return jsonify({"ok": False, "error": "No session ID provided"})
    did = gen_device_id()
    info = validate_session_id(sid, did)
    if info.get("valid"):
        tok = TikTokSession(
            cookies={"sessionid": sid, "device_id": did},
            device_id=did,
            is_active=True,
            username=info.get("username", ""),
            nickname=info.get("nickname", ""),
        )
        save_session(tok)
        return jsonify({"ok": True, "username": info["username"], "nickname": info["nickname"]})
    return jsonify({"ok": False, "error": "Invalid session ID"})


@auth_bp.route('/api/cookies', methods=['POST'])
@api_auth
@csrf_protect
def api_set_cookies():
    body = request.get_json(force=True)
    raw = body.get("cookies", "")
    try:
        cp = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(cp, list):
            cp = {c["name"]: c["value"] for c in cp}
        tok = TikTokSession(cookies=cp, device_id=cp.get("device_id", gen_device_id()), is_active=True)
        save_session(tok)
        return jsonify({"ok": True, "count": len(cp)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@auth_bp.route('/api/health')
def api_health():
    return jsonify({"ok": True})


@auth_bp.route('/api/cookies', methods=['DELETE'])
@api_auth
@csrf_protect
def api_clear_cookies():
    clear_session()
    return jsonify({"ok": True})
