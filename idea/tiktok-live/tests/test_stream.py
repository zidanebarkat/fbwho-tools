"""Tests for stream routes."""
import pytest
from app import create_app
from app.models.channel_config import save_channel_config, ChannelConfig
from app.models.session import save_session, TikTokSession


@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    app.config['PANEL_PASSWORD'] = 'testpass'
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['authenticated'] = True
        yield c


def _auth_headers(client):
    """Make a GET that renders a template (triggering csrf_token()) then extract it."""
    client.get('/api/status')
    client.get('/login')
    with client.session_transaction() as sess:
        token = sess.get('_csrf_token', '')
    return {'X-CSRF-Token': token, 'Content-Type': 'application/json'}


def test_dashboard_requires_setup(client):
    r = client.get('/dashboard', follow_redirects=False)
    assert r.status_code == 302
    assert '/setup' in r.headers['Location']


def test_dashboard_requires_tiktok(client):
    save_channel_config(ChannelConfig(title='Test', is_setup_done=True))
    save_session(TikTokSession(cookies={}, device_id='', is_active=False))
    r = client.get('/dashboard', follow_redirects=False)
    assert r.status_code == 302
    assert '/qr' in r.headers['Location']


def test_dashboard_loads(client):
    save_channel_config(ChannelConfig(title='Test Stream', is_setup_done=True, game_name='Gaming'))
    save_session(TikTokSession(cookies={'sessionid': 'test'}, device_id='123', is_active=True))
    r = client.get('/dashboard')
    assert r.status_code == 200
    assert b'Stream Config' in r.data


def test_go_live_loads(client):
    save_channel_config(ChannelConfig(title='Test', is_setup_done=True))
    save_session(TikTokSession(cookies={'sessionid': 'test'}, device_id='123', is_active=True))
    r = client.get('/go-live')
    assert r.status_code == 200
    assert b'GitHub Actions' in r.data


def test_api_status(client):
    r = client.get('/api/status')
    assert r.status_code == 200
    data = r.get_json()
    assert data['ok'] is True
    assert 'logged_in' in data


def test_api_stream_save(client):
    r = client.post('/api/stream/save', json={'source_url': 'https://example.com', 'preview': 'false'}, headers=_auth_headers(client))
    assert r.status_code == 200
    assert r.get_json()['ok'] is True


def test_api_stream_get(client):
    r = client.get('/api/stream')
    assert r.status_code == 200
    assert r.get_json()['ok'] is True


def test_api_stream_save_no_csrf_rejected(client):
    r = client.post('/api/stream/save', json={'source_url': 'https://example.com'})
    assert r.status_code == 403
