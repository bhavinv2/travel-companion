"""Live chat, the visitor's side (services/livechat.py): the bubble's script and the four calls it makes. Public, no
sign-in: a chat's secret (token) is the only key to it.

    GET  /live-chat.js                  the bubble (static/js/live-chat.js with its words), for any page of ours or a
                                        website listed under Set-up › Integrations › Website lead forms
    GET  /api/live-chat/hello           who of us is here to answer (the window's head, before a chat)
    POST /api/live-chat/start           {name, contact, message, topic, page, title} -> {token, ...news}
    GET  /api/live-chat/<token>         ?after=<id>&open=1 -> news: messages after that one, typing, who is here
    POST /api/live-chat/<token>/send    {text}
    POST /api/live-chat/<token>/end

The bubble sends its JSON as text/plain, so another website's page needs no preflight; the answer carries
Access-Control-Allow-Origin for the websites listed (the lead forms' list, integrations.intake_origins).
"""
import json
import os

from flask import current_app, jsonify, make_response, request

from app import csrf
from app.routes.crm import crm_public_bp
from app.services import crm_scope, livechat
from app.services.ratelimit import rate_limit

SCRIPT = os.path.join('js', 'live-chat.js')


def _cors(resp):
    from app.services import integrations
    origin = (request.headers.get('Origin') or '').rstrip('/')
    if origin and origin in integrations.intake_origins():
        resp.headers['Access-Control-Allow-Origin'] = origin
        resp.headers['Vary'] = 'Origin'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    resp.headers['Cache-Control'] = 'no-store'
    return resp


def _answer(body, status=200):
    return _cors(make_response(jsonify(body), status))


def _data():
    data = request.get_json(force=True, silent=True)
    return data if isinstance(data, dict) else request.form.to_dict()


def _chat(token):
    chat = livechat.by_token(token)
    return chat if chat is not None and chat.person_id else None


@crm_public_bp.route('/live-chat.js')
def live_chat_script():
    """The bubble, with its words. An empty script while live chat is switched off, so a page carrying it stays quiet."""
    cfg = livechat.config()
    if not cfg['on']:
        body = '/* live chat is switched off */\n'
    else:
        with open(os.path.join(current_app.static_folder, SCRIPT), encoding='utf-8') as fh:
            words = {k: cfg[k] for k in ('title', 'greeting', 'away', 'color')}
            words['topics'] = [{'key': k, 'label': w} for k, w in livechat.TOPICS]
            body = 'window.__liveChat = %s;\n%s' % (json.dumps(words), fh.read())
    resp = make_response(body)
    resp.headers['Content-Type'] = 'application/javascript; charset=utf-8'
    resp.headers['Cache-Control'] = 'public, max-age=300'
    return resp


@crm_public_bp.route('/api/live-chat/hello')
def live_chat_hello():
    return _answer({'ok': True, 'online': livechat.online() if livechat.enabled() else []})


@crm_public_bp.route('/api/live-chat/start', methods=['POST', 'OPTIONS'])
@csrf.exempt
@rate_limit(8, 3600)
def live_chat_start():
    if request.method == 'OPTIONS':
        return _cors(make_response('', 204))
    if not livechat.enabled():
        return _answer({'ok': False, 'error': 'The chat is closed just now. Please write to us on WhatsApp.'}, 404)
    data = _data()
    if (data.get('website') or '').strip():          # the field only a bot fills in
        return _answer({'ok': False, 'error': 'Please try again.'}, 400)
    with crm_scope.use(None):                     # a visitor is nobody's workspace; the source decides
        try:
            chat = livechat.start(data.get('name'), data.get('contact'), data.get('message'), data.get('topic') or '',
                                  page_url=data.get('page'), page_title=data.get('title'))
        except livechat.ChatError as exc:
            return _answer({'ok': False, 'error': str(exc)}, 400)
        return _answer({'ok': True, 'token': chat.token, **livechat.news(chat, reading=True)}, 201)


@crm_public_bp.route('/api/live-chat/<token>', methods=['GET', 'OPTIONS'])
def live_chat_news(token):
    if request.method == 'OPTIONS':
        return _cors(make_response('', 204))
    with crm_scope.use(None):
        chat = _chat(token)
        if chat is None:
            return _answer({'ok': False, 'gone': True}, 404)
        return _answer({'ok': True, **livechat.news(chat, request.args.get('after', type=int) or 0,
                                                     reading=request.args.get('open') == '1')})


@crm_public_bp.route('/api/live-chat/<token>/send', methods=['POST', 'OPTIONS'])
@csrf.exempt
@rate_limit(40, 600)
def live_chat_send(token):
    if request.method == 'OPTIONS':
        return _cors(make_response('', 204))
    with crm_scope.use(None):
        chat = _chat(token)
        if chat is None:
            return _answer({'ok': False, 'gone': True, 'error': 'This chat has ended. Start a new one.'}, 404)
        try:
            tp = livechat.said(chat, _data().get('text'))
        except livechat.ChatError as exc:
            return _answer({'ok': False, 'error': str(exc)}, 400)
        return _answer({'ok': True, 'id': tp.id})


@crm_public_bp.route('/api/live-chat/<token>/end', methods=['POST', 'OPTIONS'])
@csrf.exempt
def live_chat_end(token):
    if request.method == 'OPTIONS':
        return _cors(make_response('', 204))
    with crm_scope.use(None):
        chat = _chat(token)
        if chat is not None:
            livechat.end(chat)
        return _answer({'ok': True})
