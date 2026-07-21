"""Tests for auth routes."""
import re
import pytest
from app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    app.config['PANEL_PASSWORD'] = 'testpass'
    with app.test_client() as c:
        yield c


def _csrf(client, path='/login'):
    r = client.get(path)
    m = re.search(r'name=_csrf_token value="([^"]+)"', r.data.decode())
    return m.group(1) if m else None


def test_login_page_loads(client):
    r = client.get('/login')
    assert r.status_code == 200
    assert b'Enter password' in r.data


def test_login_wrong_password(client):
    token = _csrf(client)
    r = client.post('/login', data={'password': 'wrong', '_csrf_token': token}, follow_redirects=False)
    assert r.status_code == 200
    assert b'Wrong password' in r.data


def test_login_correct_password(client):
    token = _csrf(client)
    r = client.post('/login', data={'password': 'testpass', '_csrf_token': token}, follow_redirects=False)
    assert r.status_code == 302
    assert '/' in r.headers['Location']


def test_login_no_csrf_rejected(client):
    r = client.post('/login', data={'password': 'testpass'}, follow_redirects=False)
    assert r.status_code == 403


def test_root_requires_auth(client):
    r = client.get('/', follow_redirects=False)
    assert r.status_code == 302
    assert '/login' in r.headers['Location']


def test_api_requires_auth(client):
    r = client.get('/api/status')
    assert r.status_code == 401
    assert b'Not authenticated' in r.data


def test_logout_clears_session(client):
    with client.session_transaction() as sess:
        sess['authenticated'] = True
    r = client.get('/logout', follow_redirects=False)
    assert r.status_code == 302
    assert '/login' in r.headers['Location']
