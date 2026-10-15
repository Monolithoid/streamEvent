"""Exercise the actual relay encoder: atomic image changes without restarting it."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch
import time
import unittest

from PIL import Image
from web.app import create_app

spec = importlib.util.spec_from_file_location('live_controller', Path(__file__).parents[1] / 'scripts/stream_controller.py')
c = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = c
spec.loader.exec_module(c)


class FlvArrivals:
    """Observe actual packet arrival times, not just the encoded DTS values."""
    def __init__(self, path):
        self.path = path
        self.samples = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run)
        self.thread.start()

    def run(self):
        buffer, offset, stream = bytearray(), 0, None
        try:
            while not self.stop.is_set():
                if stream is None:
                    try:
                        stream = self.path.open('rb')
                    except FileNotFoundError:
                        self.stop.wait(0.005)
                        continue
                buffer.extend(stream.read())
                if offset == 0 and len(buffer) >= 13:
                    offset = 13
                while offset and len(buffer) >= offset + 11:
                    size = int.from_bytes(buffer[offset+1:offset+4], 'big')
                    if len(buffer) < offset + 11 + size + 4:
                        break
                    # AVC NALU packet, excluding codec headers and end markers.
                    if buffer[offset] == 9 and size > 1 and buffer[offset+12] == 1:
                        stamp = int.from_bytes(buffer[offset+4:offset+7], 'big') + (buffer[offset+7] << 24)
                        self.samples.append((time.monotonic(), stamp))
                    offset += 11 + size + 4
                self.stop.wait(0.005)
        finally:
            if stream:
                stream.close()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)

    def assert_smooth(self, test):
        samples = [sample for sample in self.samples if sample[1] >= 2000]
        test.assertGreater(len(samples), 100)
        gaps = [b[0]-a[0] for a, b in zip(samples, samples[1:])]
        # A 1 Hz overlay produces recurring ~0.6-1 s stalls despite valid DTS.
        test.assertLess(max(gaps), 0.5, f'Video output paused for {max(gaps):.3f}s')
        test.assertLess(sum(gap > 0.2 for gap in gaps), 3, 'Recurring output bursts')


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
class LiveOverlayTests(unittest.TestCase):
    def test_web_updates_preserve_alpha_and_output_pacing(self):
        with tempfile.TemporaryDirectory() as directory:
            overlay = Path(directory) / 'overlay.png'
            output_path = Path(directory) / 'output.flv'
            base = Path(directory) / 'base.png'
            Image.new('RGBA', (64, 64)).save(base)
            app = create_app(dict(TESTING=True, SECRET_KEY='encoder-test-only', AUTH_CONFIGURED=True,
                                  GOOGLE_CLIENT_ID='test', GOOGLE_CLIENT_SECRET='test',
                                  WEB_PUBLIC_URL='https://console.example', ALLOWED_EMAILS='admin@example.com',
                                  DATA_DIR=directory, BASE_IMAGE=str(base), WIDTH=64, HEIGHT=64))
            client = app.test_client()
            with client.session_transaction() as session:
                session.update(email='admin@example.com', csrf='test-csrf')
            def replace(color):
                document = client.get('/api/overlay').json
                document['zones'] = [dict(label='Score', text='', x=0, y=0, width=32, height=32,
                                          size=12, color='#FFFFFFFF', background='#' + ''.join(f'{channel:02X}' for channel in color))]
                headers = {'X-CSRF-Token': 'test-csrf'}
                preview = client.post('/api/preview', json=document, headers=headers)
                self.assertEqual(preview.status_code, 200)
                published = client.post('/api/overlay', json=document, headers=headers)
                self.assertEqual(published.status_code, 200)
                self.assertEqual(overlay.read_bytes(), preview.data)
                self.assertEqual(published.json['sha256'], c.hashlib.sha256(preview.data).hexdigest())
            replace((255, 0, 0, 255))
            cfg = c.Config(width=64, height=64, fps=30, bitrate='200k', threads=1,
                           preset='ultrafast', overlay=str(overlay), output_url=str(output_path))
            arrivals = FlvArrivals(output_path)
            self.addCleanup(arrivals.close)
            encoder = c.Output(cfg)
            try:
                # Black YUV420P, studio range, with silent PCM audio.
                frame = bytes([16])*4096 + bytes([128])*2048
                started = time.monotonic()
                for index in range(240):
                    if index == 90:
                        replace((0, 0, 255, 255))
                    encoder.push(frame, bytes(cfg.audio_size))
                    time.sleep(max(0, started + (index+1)/30 - time.monotonic()))
                self.assertTrue(encoder.alive())
                self.assertTrue(encoder.progress_seen)
            finally:
                encoder.close()
                arrivals.close()
            arrivals.assert_smooth(self)
            decoded = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(output_path), '-vf', 'fps=1',
                                      '-threads', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                                     capture_output=True, check=True, timeout=15).stdout
            size = 64*64*3
            frames = [decoded[i:i+size] for i in range(0,len(decoded),size)]
            self.assertGreaterEqual(len(frames), 7)
            def pixel(frame, x, y):
                start = (y*64+x)*3
                return tuple(frame[start:start+3])
            first, last = pixel(frames[0], 10, 10), pixel(frames[-1], 10, 10)
            self.assertGreater(first[0], 220)
            self.assertGreater(last[2], 220)
            self.assertLess(last[0], 30)
            self.assertLess(max(pixel(frames[-1], 50, 50)), 15)


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
class OverlayCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'overlay.png'
        self.cfg = c.Config(width=64, height=64, overlay=str(self.path))

    def save(self, color, size=(64, 64)):
        temporary = self.path.with_suffix('.tmp')
        Image.new('RGBA', size, color).save(temporary, format='PNG')
        temporary.replace(self.path)

    def wait_for(self, check):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(0.02)
        self.fail('Overlay reload timed out')

    def test_unchanged_png_is_not_decoded_again(self):
        self.save((255, 0, 0, 255))
        overlay = c.Overlay(self.cfg)
        self.addCleanup(overlay.close)
        with patch.object(overlay, 'reload', wraps=overlay.reload) as reload:
            time.sleep(0.6)
            reload.assert_not_called()

    def test_invalid_replacement_keeps_last_good_frame_and_recovers(self):
        self.save((255, 0, 0, 255))
        overlay = c.Overlay(self.cfg)
        self.addCleanup(overlay.close)
        before = overlay.snapshot
        with patch.object(overlay, 'reload', wraps=overlay.reload) as reload:
            with self.assertLogs(c.LOG, level='WARNING') as captured:
                temporary = self.path.with_suffix('.tmp')
                temporary.write_bytes(b'not-a-png')
                temporary.replace(self.path)
                self.wait_for(lambda: bool(captured.records))
            self.assertIs(overlay.snapshot, before)
            self.save((0, 0, 255, 255))
            self.wait_for(lambda: overlay.snapshot[1] != before[1])
            self.assertEqual(overlay.snapshot[1], c.hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_small_legacy_png_is_padded_with_alpha(self):
        self.save((255, 0, 0, 255), size=(16, 16))
        overlay = c.Overlay(self.cfg)
        self.addCleanup(overlay.close)
        pixels = overlay.snapshot[0]
        alpha = pixels[64*64*3//2:]
        self.assertEqual(len(pixels), 64*64*5//2)
        self.assertEqual(alpha[5*64+5], 255)
        self.assertEqual(alpha[40*64+40], 0)
