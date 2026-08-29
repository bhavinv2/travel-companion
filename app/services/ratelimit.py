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
    return (request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or request.remote_addr or 'anon')


def _hit(key, limit, per_seconds):
    now = time.monotonic()
    with _lock:
        q = _buckets.setdefault(key, deque())
        while q and now - q[0] > per_seconds:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def reset():
    with _lock:
        _buckets.clear()


MUTATING = ('POST', 'PUT', 'PATCH', 'DELETE')


def rate_limit(limit, per_seconds, scope=None, methods=MUTATING):
    """Allow `limit` calls per `per_seconds` per client for the decorated view.

    Only the listed HTTP methods are counted (by default the mutating ones), so merely viewing a form never
    consumes the budget.
    """
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_app.config.get('RATELIMIT_ENABLED', True) or request.method not in methods:
                return f(*args, **kwargs)
            key = f"{scope or request.endpoint}:{_client_key()}"
            if not _hit(key, limit, per_seconds):
                if request.is_json or request.path.startswith('/api/'):
                    return jsonify({'error': 'Too many requests — please slow down and try again shortly.'}), 429
                flash('Too many attempts — please wait a minute and try again.', 'danger')
                return redirect(request.referrer or url_for('main.index')), 429
            return f(*args, **kwargs)
        return wrapper
    return deco
