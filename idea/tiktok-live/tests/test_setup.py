"""Tests for setup routes."""
import re
import pytest
from app import create_app
from app.models.channel_config import save_channel_config, ChannelConfig


@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    app.config['PANEL_PASSWORD'] = 'testpass'
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['authenticated'] = True
        yield c


def _csrf(client, path='/setup'):
    r = client.get(path)
    m = re.search(r'name=_csrf_token value="([^"]+)"', r.data.decode())
    return m.group(1) if m else None


def _api_csrf(client):
    with client.session_transaction() as sess:
        return sess.get('_csrf_token', '')


def test_setup_page_loads(client):
    r = client.get('/setup')
    assert r.status_code == 200
    assert b'Stream Setup' in r.data


def test_setup_save_redirects(client):
    token = _csrf(client)
    r = client.post('/setup', data={
        'title': 'Test Stream',
        'game_id': '5',
        'game_name': 'Gaming',
        'topic_id': '',
        'topic_name': '',
        '_csrf_token': token,
    }, follow_redirects=False)
    assert r.status_code == 302


def test_api_setup_get(client):
    r = client.get('/api/setup')
    assert r.status_code == 200
    data = r.get_json()
    assert data['ok'] is True


def test_api_setup_save(client):
    r = client.post('/api/setup/save', json={
        'title': 'API Test',
        'game_id': '10',
        'game_name': 'Music',
    })
    assert r.status_code == 200
    assert r.get_json()['ok'] is True


def test_change_setup_resets(client):
    save_channel_config(ChannelConfig(title='Old', is_setup_done=True))
    r = client.get('/change-setup', follow_redirects=False)
    assert r.status_code == 302
    assert '/setup' in r.headers['Location']
