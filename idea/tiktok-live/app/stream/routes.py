"""Stream routes — dashboard, go-live form, stream key management."""
import json, time
from pathlib import Path
from flask import Blueprint, render_template, request, jsonify, redirect, url_for

from app.auth.qr_service import login_required, api_auth
from app.models.channel_config import load_channel_config
from app.models.session import TikTokSession, load_session
from app.storage.secure_store import SecureStore
from app.stream.stream_key import create_room, end_room
from app.stream.github_dispatch import trigger_workflow, check_workflow_status, cancel_workflow
from app.security import csrf_protect
from flask import current_app
from config import Config

stream_bp = Blueprint('stream', __name__)


def _get_store():
    return SecureStore(current_app.config['ENCRYPTION_KEY'], Config.SECURE_STORE_FILE)


def _get_history():
    path = Config.HISTORY_FILE
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


def _save_history(history):
    path = Config.HISTORY_FILE
    with open(path, 'w') as f:
        json.dump(history, f, indent=2)


@stream_bp.route('/dashboard')
@login_required
def dashboard():
    config = load_channel_config()
    if not config.is_setup_done:
        return redirect(url_for('setup.setup_page'))
    tok = load_session()
    if not tok.is_active:
        return redirect(url_for('auth.qr_page'))
    store = _get_store()
    return render_template('dashboard.html', config=config, store=store.all())


@stream_bp.route('/go-live')
@login_required
def go_live():
    tok = load_session()
    if not tok.is_active:
        return redirect(url_for('auth.qr_page'))
    config = load_channel_config()
    store = _get_store()
    return render_template('stream.html', config=config, stream=store.all())


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@stream_bp.route('/api/room/create', methods=['POST'])
@api_auth
@csrf_protect
def api_create():
    config = load_channel_config()
    tok = load_session()
    if not tok.is_active:
        return jsonify({"ok": False, "error": "Not logged into TikTok"})

    opts = {
        "title": config.title,
        "game_tag_id": config.game_id or "0",
        "topic_id": config.topic_id or "42",
    }

    try:
        r = create_room(tok, opts)
        if r:
            history = _get_history()
            history.insert(0, {
                "title": config.title,
                "stream_key": r["stream_key"],
                "server_url": r["server_url"],
                "rtmp_url": r["rtmp_url"],
                "share_url": r.get("share_url", ""),
                "room_id": r.get("room_id", ""),
                "created": time.strftime("%Y-%m-%d %H:%M"),
            })
            if len(history) > 50:
                history = history[:50]
            _save_history(history)
            return jsonify({"ok": True, **r})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
    return jsonify({"ok": False, "error": "Room create failed. Account may lack live auth."})


@stream_bp.route('/api/room/end', methods=['POST'])
@api_auth
@csrf_protect
def api_end():
    body = request.get_json(force=True)
    tok = load_session()
    if not tok.is_active:
        return jsonify({"ok": False, "error": "Not logged in"})
    try:
        ok = end_room(tok, body.get("room_id", ""), body.get("stream_id", ""))
        return jsonify({"ok": ok})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@stream_bp.route('/api/stream/save', methods=['POST'])
@api_auth
@csrf_protect
def api_stream_save():
    body = request.get_json(force=True)
    store = _get_store()
    for key in ["source_url", "github_pat", "cookies_b64", "preview"]:
        if key in body:
            store.set(key, body[key])
    return jsonify({"ok": True})


@stream_bp.route('/api/stream', methods=['GET'])
@api_auth
def api_stream_get():
    store = _get_store()
    return jsonify({"ok": True, "stream": store.all()})


@stream_bp.route('/api/golive', methods=['POST'])
@api_auth
@csrf_protect
def api_golive():
    body = request.get_json(force=True)
    config = load_channel_config()
    store = _get_store()

    result, err = trigger_workflow(
        stream_key=body.get("stream_key", ""),
        rtmp_url=body.get("rtmp_url", ""),
        source_url=body.get("source_url", store.get("source_url", "")),
        title=config.title,
        github_pat=body.get("github_pat", store.get("github_pat", "")),
        cookies_b64=body.get("cookies_b64", store.get("cookies_b64", "")),
        preview=body.get("preview", store.get("preview", "false")),
    )
    if err:
        return jsonify({"ok": False, "error": err})

    # Save settings for next time
    store.set("source_url", body.get("source_url", ""))
    if body.get("github_pat"):
        store.set("github_pat", body["github_pat"])
    if body.get("cookies_b64"):
        store.set("cookies_b64", body["cookies_b64"])
    store.set("preview", body.get("preview", "false"))

    return jsonify({"ok": True, **result})


@stream_bp.route('/api/status')
@api_auth
def api_status():
    config = load_channel_config()
    tok = load_session()
    history = _get_history()
    return jsonify({
        "ok": True,
        "logged_in": tok.is_active,
        "setup_done": config.is_setup_done,
        "history": len(history),
    })


@stream_bp.route('/api/workflow/status')
@api_auth
def api_workflow_status():
    return jsonify(check_workflow_status())


@stream_bp.route('/api/workflow/cancel', methods=['POST'])
@api_auth
@csrf_protect
def api_workflow_cancel():
    ok, err = cancel_workflow()
    return jsonify({"ok": ok, "error": err})
