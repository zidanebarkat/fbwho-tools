"""CSRF protection — token generation + validation for all mutating routes."""
import hmac
import os
import time
from functools import wraps
from flask import session, request, abort


def _b64url(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def generate_csrf_token() -> str:
    """Return a fresh CSRF token (stored in session)."""
    token = session.get('_csrf_token')
    if not token:
        token = _b64url(os.urandom(32))
        session['_csrf_token'] = token
    return token


def validate_csrf():
    """Validate the _csrf_token from form data or X-CSRF-Token header."""
    token = (
        request.form.get('_csrf_token')
        or request.headers.get('X-CSRF-Token')
        or ''
    )
    expected = session.get('_csrf_token', '')
    if not expected or not token or not hmac.compare_digest(token, expected):
        abort(403)


def csrf_protect(f):
    """Decorator — validates CSRF on POST/PUT/DELETE/PATCH."""
    @wraps(f)
    def decorated(*a, **kw):
        if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            validate_csrf()
        return f(*a, **kw)
    return decorated
