"""Exercise the actual relay encoder: atomic image changes without restarting it."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from PIL import Image

spec = importlib.util.spec_from_file_location('live_controller', Path(__file__).parents[1] / 'scripts/stream_controller.py')
c = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = c
spec.loader.exec_module(c)


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
class LiveOverlayTests(unittest.TestCase):
    def test_atomic_reload_keeps_encoder_and_alpha(self):
        with tempfile.TemporaryDirectory() as directory:
            overlay = Path(directory) / 'overlay.png'
            output_path = Path(directory) / 'output.flv'
            def replace(color):
                image = Image.new('RGBA', (64, 64))
                image.paste(color, (0, 0, 32, 32))
                temporary = overlay.with_suffix('.tmp')
                image.save(temporary, format='PNG')
                temporary.replace(overlay)
            replace((255, 0, 0, 255))
            cfg = c.Config(width=64, height=64, fps=30, bitrate='200k', threads=1,
                           preset='ultrafast', overlay=str(overlay), output_url=str(output_path))
            encoder = c.Output(cfg)
            try:
                # Black YUV420P, studio range, with silent PCM audio.
                frame = bytes([16])*4096 + bytes([128])*2048
                started = time.monotonic()
                for index in range(240):
                    if index == 50:
                        replace((0, 0, 255, 255))
                    encoder.push(frame, bytes(cfg.audio_size))
                    time.sleep(max(0, started + (index+1)/30 - time.monotonic()))
                self.assertTrue(encoder.alive())
                self.assertTrue(encoder.progress_seen)
            finally:
                encoder.close()
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
