"""Small in-process rate limiter (per client IP + endpoint).

Good enough to blunt brute force and spam on a 1-2 worker deployment; each Gunicorn worker keeps its own
counters, so real limits are `limit × workers`. Move to Flask-Limiter + Redis when scaling out.
"""
import time
from collections import deque
from functools import wraps
from threading import Lock

from flask import request, jsonify, current_app, flash, redirect, url_for

_buckets = {}
_lock = Lock()


def _client_key():
    """The address the request really came from.

    remote_addr, not the X-Forwarded-For header: ProxyFix (app/__init__) has already taken the
    entry our own proxy appended. The first entry of the raw header is whatever the client chose to
    send, so keying on it let anybody reset their own limit by sending a different made-up address
    with every attempt.
    """
    return request.remote_addr or 'anon'


def _full(key, limit, per_seconds):
    """Whether `key` has used its budget. Drops attempts that have aged out on the way."""
    now = time.monotonic()
    with _lock:
        q = _buckets.setdefault(key, deque())
        while q and now - q[0] > per_seconds:
            q.popleft()
        return len(q) >= limit


def _record(key):
    with _lock:
        _buckets.setdefault(key, deque()).append(time.monotonic())


def _hit(key, limit, per_seconds):
    if _full(key, limit, per_seconds):
        return False
    _record(key)
    return True


def reset():
    with _lock:
        _buckets.clear()


MUTATING = ('POST', 'PUT', 'PATCH', 'DELETE')


def _refuse():
    if request.is_json or request.path.startswith('/api/'):
        return jsonify({'error': 'Too many requests — please slow down and try again shortly.'}), 429
    flash('Too many attempts — please wait a minute and try again.', 'danger')
    return redirect(request.referrer or url_for('main.index')), 429


def rate_limit(limit, per_seconds, scope=None, methods=MUTATING, counts=None):
    """Allow `limit` calls per `per_seconds` per client for the decorated view.

    Only the listed HTTP methods are counted (by default the mutating ones), so merely viewing a form never
    consumes the budget. `counts(response)`, when given, decides after the view has run whether this call
    used any budget -- sign-in passes one that counts only failed attempts, so an office of agents behind
    one address can all sign in while a password guesser is still stopped.
    """
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_app.config.get('RATELIMIT_ENABLED', True) or request.method not in methods:
                return f(*args, **kwargs)
            key = f"{scope or request.endpoint}:{_client_key()}"
            if counts is not None:
                if _full(key, limit, per_seconds):
                    return _refuse()
                response = current_app.make_response(f(*args, **kwargs))
                if counts(response):
                    _record(key)
                return response
            if not _hit(key, limit, per_seconds):
                return _refuse()
            return f(*args, **kwargs)
        return wrapper
    return deco
