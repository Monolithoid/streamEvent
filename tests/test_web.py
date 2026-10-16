import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PIL import Image
from web.app import create_app, render

ROOT = Path(__file__).resolve().parents[1]


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / 'base.png'
        Image.new('RGBA', (320, 180)).save(self.base)
        self.settings = dict(TESTING=True, SECRET_KEY='test-only', AUTH_CONFIGURED=True,
                             GOOGLE_CLIENT_ID='test', GOOGLE_CLIENT_SECRET='test',
                             WEB_PUBLIC_URL='https://console.example', ALLOWED_EMAILS='admin@example.com',
                             DATA_DIR=self.temp.name, BASE_IMAGE=str(self.base), WIDTH=320, HEIGHT=180,
                             CONTROL_FILE=str(Path(self.temp.name) / 'broadcast.json'),
                             STATUS_FILE=str(Path(self.temp.name) / 'status.json'))
        self.app = create_app(self.settings)
        self.client = self.app.test_client()
        self.zone = dict(label='Score', text='Équipe 12 – 8', x=10, y=10, width=280, height=60,
                         size=20, color='#FFFFFFFF', background='#12345680')

    def get_bytes(self, path):
        with self.client.get(path) as response:
            return response.data

    def authenticate(self):
        with self.client.session_transaction() as session:
            session.update(email='admin@example.com', csrf='test-csrf')

    def post(self, path, document):
        return self.client.post(path, json=document, headers={'X-CSRF-Token': 'test-csrf'})

    def test_all_sensitive_routes_require_auth(self):
        for path in ['/api/status', '/api/overlay', '/api/overlay.png', '/api/ingest']:
            self.assertEqual(self.client.get(path).status_code, 401)
        for path in ['/api/preview', '/api/overlay', '/api/broadcast', '/logout']:
            self.assertIn(self.client.post(path, json={}).status_code, (302, 401))
        self.assertEqual(self.client.get('/').status_code, 302)
        with self.client.session_transaction() as session:
            session['email'] = 'outsider@example.com'
        self.assertEqual(self.client.get('/api/status').status_code, 401)

    def test_csrf_and_logout(self):
        self.authenticate()
        self.assertEqual(self.client.post('/api/overlay', json={'zones': []}).status_code, 403)
        self.assertEqual(self.post('/logout', {}).status_code, 200)
        self.assertEqual(self.client.get('/api/overlay').status_code, 401)

    def test_preview_alpha_publish_persistence_and_conflict(self):
        self.authenticate()
        document = dict(zones=[self.zone], revision=0)
        preview = self.post('/api/preview', document)
        self.assertEqual(preview.status_code, 200)
        image = Image.open(io.BytesIO(preview.data))
        self.assertEqual(image.mode, 'RGBA')
        self.assertEqual(image.getpixel((0, 0))[3], 0)
        self.assertEqual(image.getpixel((11, 11)), (18, 52, 86, 128))
        self.assertEqual(self.client.get('/api/overlay').json['revision'], 0)
        published = self.post('/api/overlay', document)
        self.assertEqual(published.status_code, 200)
        self.assertEqual(published.json['sha256'], self.client.get('/api/overlay').json['sha256'])
        self.assertEqual(self.get_bytes('/api/overlay.png'), preview.data)
        self.assertEqual(self.post('/api/overlay', document).status_code, 409)
        restarted = create_app(self.settings)
        with restarted.test_client() as client:
            with client.session_transaction() as session:
                session['email'] = 'admin@example.com'
            self.assertEqual(client.get('/api/overlay').json['zones'], [self.zone])

    def test_invalid_input_preserves_published_image(self):
        self.authenticate()
        before = self.get_bytes('/api/overlay.png')
        for document in [None, {}, {'zones': [dict(self.zone, x=319)]},
                         {'zones': [dict(self.zone, color='red')]}, {'zones': [self.zone]*25},
                         {'zones': [dict(self.zone, text='x'*501)]}]:
            self.assertEqual(self.post('/api/overlay', document).status_code, 400)
        self.assertEqual(self.get_bytes('/api/overlay.png'), before)

    def test_base_image_keeps_native_size_on_full_transparent_canvas(self):
        Image.new('RGBA', (20, 10), (255, 0, 0, 255)).save(self.base)
        image = Image.open(io.BytesIO(render({'zones': []}, self.base, 320, 180, self.app.config['FONT_PATH'])))
        self.assertEqual(image.size, (320, 180))
        self.assertEqual(image.getpixel((19, 9)), (255, 0, 0, 255))
        self.assertEqual(image.getpixel((20, 10))[3], 0)

    def test_ingest_settings_match_selected_protocol(self):
        for protocol, port, key in [('rtmp', '1935', 'live'), ('rtmps', '1936', 'test-private-key')]:
            app = create_app(dict(self.settings, INGEST_PROTOCOL=protocol, INGEST_PORT=port,
                                  INGEST_STREAM_KEY=key, PUBLISH_USER='phone', PUBLISH_PASSWORD='test-publish-only'))
            client = app.test_client()
            self.assertEqual(client.get('/api/ingest').status_code, 401)
            with client.session_transaction() as session:
                session['email'] = 'admin@example.com'
            response = client.get('/api/ingest')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            value = response.json
            self.assertEqual(value['server_url'], f'{protocol}://console.example:{port}')
            self.assertEqual(value['stream_key'], key)
            self.assertEqual(value['authentication'], protocol == 'rtmp')
            if protocol == 'rtmp':
                self.assertEqual(value['username'], 'phone')
                self.assertEqual(value['password'], 'test-publish-only')
            else:
                self.assertNotIn('password', value)
                self.assertNotIn('username', value)
            self.assertNotIn('youtube', str(value).lower())

    def test_ingest_url_override_and_invalid_configuration(self):
        for url, expected in [('rtmps://video.example:1940', 200), ('https://video.example', 503), ('rtmps://user:pass@video.example:1936', 503)]:
            app = create_app(dict(self.settings, INGEST_PROTOCOL='rtmps', INGEST_PUBLIC_URL=url))
            client = app.test_client()
            with client.session_transaction() as session:
                session['email'] = 'admin@example.com'
            response = client.get('/api/ingest')
            self.assertEqual(response.status_code, expected)
            if expected == 200:
                self.assertEqual(response.json['server_url'], url)

    def test_broadcast_requires_csrf_fresh_relay_and_boolean_command(self):
        self.authenticate()
        path = Path(self.settings['CONTROL_FILE'])
        self.assertEqual(self.client.post('/api/broadcast', json={'enabled': True}).status_code, 403)
        self.assertEqual(self.post('/api/broadcast', {'enabled': True}).status_code, 503)
        for bad in [None, {}, {'enabled': 'true'}, {'enabled': 1}]:
            self.assertEqual(self.post('/api/broadcast', bad).status_code, 400)
        status = Path(self.settings['STATUS_FILE'])
        for value in [{}, {'updated_at': time.time() - 30, 'run_id': 'old'},
                      {'updated_at': time.time(), 'run_id': None}]:
            status.write_text(json.dumps(value))
            self.assertEqual(self.post('/api/broadcast', {'enabled': True}).status_code, 503)
        self.assertFalse(path.exists())
        status.write_text(json.dumps({'updated_at': time.time(), 'run_id': 'current'}))
        for enabled in (True, True, False):
            self.assertEqual(self.post('/api/broadcast', {'enabled': enabled}).status_code, 202)
            self.assertEqual(json.loads(path.read_text()), {'enabled': enabled, 'run_id': 'current'})

    def test_status_staleness(self):
        self.authenticate()
        self.assertTrue(self.client.get('/api/status').json['stale'])
        path = Path(self.settings['STATUS_FILE'])
        for offset, expected in [(0, False), (30, True)]:
            path.write_text(json.dumps({'updated_at': time.time()-offset, 'state': 'live'}))
            self.assertEqual(self.client.get('/api/status').json['stale'], expected)

    def test_login_closed_without_config_and_verified_allowlist(self):
        other = create_app(dict(self.settings, ALLOWED_EMAILS=''))
        self.assertEqual(other.test_client().get('/login').status_code, 503)
        google = self.app.extensions['google_client']
        for email, verified, expected in [('other@example.com', True, 403), ('admin@example.com', False, 403), ('admin@example.com', True, 302)]:
            with patch.object(google, 'authorize_access_token', return_value={'userinfo': {'email': email, 'email_verified': verified}}):
                self.assertEqual(self.client.get('/auth/callback').status_code, expected)
        self.assertEqual(self.client.get('/api/status').status_code, 200)

    def test_editor_and_assets_render(self):
        self.authenticate()
        self.assertEqual(self.client.get('/').status_code, 200)
        with self.client.get('/static/app.js') as response:
            self.assertEqual(response.status_code, 200)
        self.assertIn("frame-ancestors 'none'", self.client.get('/').headers['Content-Security-Policy'])
