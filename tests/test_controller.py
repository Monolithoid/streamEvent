import importlib.util
import io
import os
from pathlib import Path
import sys
import time
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("controller", Path(__file__).parents[1] / "scripts/stream_controller.py")
c = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = c
spec.loader.exec_module(c)


class SwitchTests(unittest.TestCase):
    def source(self):
        source = c.Source.__new__(c.Source)
        source.cfg = c.Config(ready_frames=3, stale=1)
        source.lock = c.threading.Lock()
        source.frame = b"frame"
        source.count = 3
        source.updated = time.monotonic()
        source.audio_updated = source.updated
        source.audio = c.collections.deque([b"audio"])
        return source

    def test_ready_and_stale_audio_is_never_replayed(self):
        source = self.source()
        self.assertEqual(source.select(time.monotonic()), (b"frame", b"audio"))
        self.assertEqual(source.select(time.monotonic()), (b"frame", None))
        source.audio.append(b"old")
        self.assertEqual(source.select(time.monotonic() + 2), (None, None))
        self.assertFalse(source.audio)

    def test_warmup_and_missing_audio(self):
        source = self.source()
        source.count = 2
        self.assertEqual(source.select(time.monotonic()), (None, None))
        source.count = 3
        self.assertEqual(source.select(time.monotonic()), (b"frame", None))

    def test_partial_pipe_reads_and_truncated_frames(self):
        class Fragmented(io.BytesIO):
            def readinto(self, view):
                return super().readinto(view[:7])
        stream = Fragmented(b"a" * 100 + b"b" * 30)
        self.assertEqual(c.read_exact(stream, 100), b"a" * 100)
        self.assertIsNone(c.read_exact(stream, 100))

    def test_validation_and_credential_escaping(self):
        with patch.dict(os.environ, {"OUTPUT_URL": "rtmp://localhost/test", "READ_USER": "u", "READ_PASSWORD": "a@b:c"}, clear=True):
            cfg = c.Config.load()
            self.assertIn("u:a%40b%3Ac@", cfg.input_url)
            with patch.dict(os.environ, {"WIDTH": "1919"}):
                self.assertRaises(ValueError, c.Config.load)

    def test_status_reports_progress_without_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "relay.json"
            class Encoder:
                progress_seen = True
                last_progress = time.monotonic()
                def alive(self):
                    return True
            cfg = c.Config(input_url="rtsp://u:secret@host/live", output_url="rtmps://host/key")
            with patch.dict(os.environ, {"RELAY_STATUS_FILE": str(path)}):
                c.write_status(cfg, "live", Encoder(), time.monotonic() - 10)
            payload = c.json.loads(path.read_text())
            self.assertTrue(payload["output_healthy"])
            self.assertEqual(payload["state"], "live")
            self.assertNotIn("secret", path.read_text())
            self.assertNotIn("rtmp", path.read_text())

    def test_logs_redact_secrets(self):
        cfg = c.Config(input_url="rtsp://u:secret@host/live", output_url="rtmps://host/key")
        self.assertNotIn("secret", c.sanitized("error " + cfg.input_url, cfg))
        self.assertNotIn("/key", c.sanitized("error " + cfg.output_url, cfg))


if __name__ == "__main__":
    unittest.main()
