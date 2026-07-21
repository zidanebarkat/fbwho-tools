"""Setup routes — one-time stream config (title, game, topic, extras)."""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for

from app.auth.qr_service import login_required, api_auth
from app.models.channel_config import ChannelConfig, load_channel_config, save_channel_config
from app.auth.qr_service import make_session
from config import Config

setup_bp = Blueprint('setup', __name__)


def _fetch_game_tags():
    from app.auth.qr_service import make_session
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


@setup_bp.route('/setup', methods=['GET', 'POST'])
@login_required
def setup_page():
    if request.method == 'POST':
        config = ChannelConfig(
            title=request.form.get("title", "My Live Stream"),
            game_id=request.form.get("game_id", ""),
            game_name=request.form.get("game_name", ""),
            topic_id=request.form.get("topic_id", ""),
            topic_name=request.form.get("topic_name", ""),
            extras=request.form.getlist("extras"),
            extra_names=request.form.getlist("extra_names"),
            is_setup_done=True,
        )
        save_channel_config(config)
        return redirect(url_for('root'))

    config = load_channel_config()
    tags = _fetch_game_tags()
    return render_template('setup.html', config=config, games=tags["games"], topics=tags["topics"], extras=tags["extras"])


@setup_bp.route('/change-setup')
@login_required
def change_setup():
    config = load_channel_config()
    config.is_setup_done = False
    save_channel_config(config)
    return redirect(url_for('setup.setup_page'))


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@setup_bp.route('/api/setup', methods=['GET'])
@api_auth
def api_setup_get():
    config = load_channel_config()
    return jsonify({"ok": True, "setup": config.to_dict(), "done": config.is_setup_done})


@setup_bp.route('/api/setup/save', methods=['POST'])
@api_auth
def api_setup_save():
    body = request.get_json(force=True)
    config = ChannelConfig(
        title=body.get("title", "My Live Stream"),
        game_id=body.get("game_id", ""),
        game_name=body.get("game_name", ""),
        topic_id=body.get("topic_id", ""),
        topic_name=body.get("topic_name", ""),
        extras=body.get("extras", []),
        extra_names=body.get("extra_names", []),
        is_setup_done=True,
    )
    save_channel_config(config)
    return jsonify({"ok": True})


@setup_bp.route('/api/games')
@api_auth
def api_games():
    tags = _fetch_game_tags()
    return jsonify({"ok": True, **tags})
