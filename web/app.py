"""Private overlay console. The relay only reads the atomically replaced PNG."""
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from datetime import timedelta
from urllib.parse import urlsplit

from authlib.integrations.flask_client import OAuth
from authlib.integrations.base_client.errors import OAuthError
from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, session
from PIL import Image, ImageDraw, ImageFont


def atomic_write(path, content):
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('wb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def validate(document, width, height):
    if not isinstance(document, dict) or not isinstance(document.get('zones'), list) or len(document['zones']) > 24:
        raise ValueError('Utilisez au maximum 24 zones de texte.')
    zones = []
    for zone in document['zones']:
        if not isinstance(zone, dict):
            raise ValueError('Zone invalide.')
        cleaned = {}
        for key, limit in [('label', 60), ('text', 500)]:
            value = zone.get(key)
            if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 and c != '\n' for c in value):
                raise ValueError(f'Champ {key} invalide (maximum {limit} caractères).')
            cleaned[key] = value
        for key, low, high in [('x', 0, width - 1), ('y', 0, height - 1), ('width', 1, width), ('height', 1, height), ('size', 8, 160)]:
            value = zone.get(key)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'Valeur {key} invalide : {low} à {high}.')
            cleaned[key] = value
        if cleaned['x'] + cleaned['width'] > width or cleaned['y'] + cleaned['height'] > height:
            raise ValueError('Une zone dépasse les limites de l’image.')
        for key in ('color', 'background'):
            value = zone.get(key)
            if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{8}', value):
                raise ValueError('Couleur attendue au format #RRGGBBAA.')
            cleaned[key] = value
        zones.append(cleaned)
    return {'zones': zones}


def render(document, base, width, height, font_path):
    image = Image.new('RGBA', (width, height))
    with Image.open(base) as source:
        image.alpha_composite(source.convert('RGBA'))
    for zone in document['zones']:
        layer = Image.new('RGBA', (zone['width'], zone['height']), zone['background'])
        draw = ImageDraw.Draw(layer)
        font = ImageFont.truetype(font_path, zone['size'])
        draw.multiline_text((8, 4), zone['text'], font=font, fill=zone['color'], spacing=4)
        image.alpha_composite(layer, (zone['x'], zone['y']))
    result = io.BytesIO()
    image.save(result, format='PNG')
    return result.getvalue()


def create_app(settings=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.getenv('WEB_SECRET_KEY') or secrets.token_hex(32),
        GOOGLE_CLIENT_ID=os.getenv('GOOGLE_CLIENT_ID', ''),
        GOOGLE_CLIENT_SECRET=os.getenv('GOOGLE_CLIENT_SECRET', ''),
        WEB_PUBLIC_URL=os.getenv('WEB_PUBLIC_URL', '').rstrip('/'),
        ALLOWED_EMAILS=os.getenv('GOOGLE_ALLOWED_EMAILS', ''),
        AUTH_CONFIGURED=bool(os.getenv('WEB_SECRET_KEY')),
        DATA_DIR=os.getenv('OVERLAY_DATA_DIR', '/data/overlay'),
        BASE_IMAGE=os.getenv('OVERLAY_BASE_IMAGE', '/assets/overlay.png'),
        STATUS_FILE=os.getenv('RELAY_STATUS_FILE', '/data/status/relay.json'),
        FONT_PATH=os.getenv('OVERLAY_FONT', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
        WIDTH=int(os.getenv('WIDTH', '1920')), HEIGHT=int(os.getenv('HEIGHT', '1080')),
        MAX_CONTENT_LENGTH=65536, SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    if settings:
        app.config.update(settings)
    cfg = app.config
    if not (16 <= cfg['WIDTH'] <= 3840 and 16 <= cfg['HEIGHT'] <= 2160):
        raise ValueError('Invalid overlay dimensions')
    allowed = {email.strip().lower() for email in cfg['ALLOWED_EMAILS'].split(',') if email.strip()}
    public = urlsplit(cfg['WEB_PUBLIC_URL'])
    configured = bool(cfg['AUTH_CONFIGURED'] and cfg['GOOGLE_CLIENT_ID'] and cfg['GOOGLE_CLIENT_SECRET'] and allowed
                      and public.scheme == 'https' and public.netloc and public.path == '')
    oauth = OAuth(app)
    google = oauth.register('google', client_id=cfg['GOOGLE_CLIENT_ID'], client_secret=cfg['GOOGLE_CLIENT_SECRET'],
                            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
                            client_kwargs={'scope': 'openid email profile'})
    app.extensions['google_client'] = google
    directory = Path(cfg['DATA_DIR'])
    directory.mkdir(parents=True, exist_ok=True)
    state_file, png = directory / 'state.json', directory / 'overlay.png'
    lock = threading.Lock()
    if not state_file.exists():
        initial = {'zones': [], 'revision': 0}
        atomic_write(png, render(initial, cfg['BASE_IMAGE'], cfg['WIDTH'], cfg['HEIGHT'], cfg['FONT_PATH']))
        atomic_write(state_file, json.dumps(initial).encode())

    @app.before_request
    def protect():
        if request.endpoint in ('health', 'login', 'callback', 'static'):
            return None
        if not configured or session.get('email') not in allowed:
            if request.path.startswith('/api/'):
                return jsonify(error='Connexion Google requise.'), 401
            return redirect('/login')
        if request.method == 'POST' and not hmac.compare_digest(request.headers.get('X-CSRF-Token', ''), session.get('csrf', '') or 'missing'):
            abort(403)

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.get('/healthz')
    def health():
        return {'ok': png.is_file()}

    @app.get('/login')
    def login():
        if not configured:
            return render_template('login.html', unavailable=True), 503
        if request.args.get('google') == '1':
            return google.authorize_redirect(cfg['WEB_PUBLIC_URL'] + '/auth/callback')
        return render_template('login.html', unavailable=False)

    @app.get('/auth/callback')
    def callback():
        if not configured:
            abort(503)
        try:
            token = google.authorize_access_token()
            user = token.get('userinfo', {})
            email = user.get('email', '').lower()
            if user.get('email_verified') is not True or email not in allowed:
                session.clear()
                abort(403)
        except (OAuthError, ValueError, KeyError):
            session.clear()
            return 'Connexion Google invalide ou expirée. Réessayez depuis /login.', 400
        session.clear()
        session.permanent = True
        session.update(email=email, csrf=secrets.token_urlsafe(32))
        return redirect('/')

    @app.post('/logout')
    def logout():
        session.clear()
        return {'ok': True}

    @app.get('/')
    def index():
        return render_template('index.html', email=session['email'], csrf=session['csrf'])

    @app.get('/api/overlay')
    def overlay():
        with lock:
            state = json.loads(state_file.read_text())
        return dict(state, width=cfg['WIDTH'], height=cfg['HEIGHT'])

    @app.get('/api/overlay.png')
    def image():
        return send_file(png, mimetype='image/png', download_name='overlay.png')

    @app.post('/api/preview')
    @app.post('/api/overlay')
    def update():
        document = request.get_json(silent=True)
        try:
            cleaned = validate(document, cfg['WIDTH'], cfg['HEIGHT'])
            content = render(cleaned, cfg['BASE_IMAGE'], cfg['WIDTH'], cfg['HEIGHT'], cfg['FONT_PATH'])
        except (ValueError, TypeError) as error:
            return jsonify(error=str(error)), 400
        if request.path == '/api/preview':
            return send_file(io.BytesIO(content), mimetype='image/png')
        with lock:
            current = json.loads(state_file.read_text())
            if document.get('revision') != current['revision']:
                return jsonify(error='Une autre console a modifié l’overlay. Rechargez la page pour récupérer sa version.'), 409
            cleaned.update(revision=current['revision'] + 1, updated_at=time.time())
            atomic_write(png, content)
            atomic_write(state_file, json.dumps(cleaned, ensure_ascii=False).encode())
        return cleaned

    @app.get('/api/status')
    def status():
        try:
            value = json.loads(Path(cfg['STATUS_FILE']).read_text())
            age = time.time() - value['updated_at']
            value['stale'] = not 0 <= age < 10
            return value
        except (OSError, ValueError, KeyError, TypeError):
            return {'stale': True, 'state': 'unknown'}

    return app
