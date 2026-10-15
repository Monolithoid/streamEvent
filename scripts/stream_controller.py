#!/usr/bin/env python3
"""Clocked raw-media switch. Standard library only; FFmpeg does the media work."""
import collections
import dataclasses
import json
import hashlib
import logging
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import quote, urlsplit, urlunsplit

LOG = logging.getLogger("relay")
STOP = threading.Event()
HEALTH = Path("/tmp/relay-heartbeat")


@dataclasses.dataclass
class Config:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    bitrate: str = "6000k"
    preset: str = "veryfast"
    threads: int = 4
    waiting: str = "/app/assets/waiting.png"
    overlay: str = "/app/assets/overlay.png"
    input_url: str = "rtsp://mediamtx:8554/live"
    output_url: str = ""
    stale: float = 1.5
    ready_frames: int = 5
    stall: float = 20

    @classmethod
    def load(cls):
        base = os.getenv("INPUT_URL", cls.input_url)
        user, password = os.getenv("READ_USER", ""), os.getenv("READ_PASSWORD", "")
        if user:
            parts = urlsplit(base)
            base = urlunsplit(parts._replace(netloc=f"{quote(user, safe='')}:{quote(password, safe='')}@{parts.netloc}"))
        target = os.getenv("OUTPUT_URL", "")  # local testing; not exposed in production Compose
        if not target:
            key = os.environ.get("YOUTUBE_STREAM_KEY", "")
            if not key or key.startswith("replace-"):
                raise ValueError("Set YOUTUBE_STREAM_KEY")
            target = os.getenv("YOUTUBE_RTMPS_URL", "rtmps://a.rtmps.youtube.com:443/live2").rstrip("/") + "/" + key
            if urlsplit(target).scheme != "rtmps":
                raise ValueError("YouTube output must use RTMPS")
        cfg = cls(
            width=int(os.getenv("WIDTH", "1920")), height=int(os.getenv("HEIGHT", "1080")),
            fps=int(os.getenv("FPS", "30")), bitrate=os.getenv("VIDEO_BITRATE", "6000k"),
            preset=os.getenv("ENCODER_PRESET", "veryfast"), threads=int(os.getenv("ENCODER_THREADS", "4")),
            waiting=os.getenv("WAITING_IMAGE", cls.waiting), overlay=os.getenv("OVERLAY_IMAGE", cls.overlay),
            input_url=base, output_url=target, stale=float(os.getenv("STALE_SECONDS", "1.5")),
            ready_frames=int(os.getenv("READY_FRAMES", "5")), stall=float(os.getenv("OUTPUT_STALL_SECONDS", "20")),
        )
        if not (16 <= cfg.width <= 3840 and 16 <= cfg.height <= 2160) or cfg.width % 2 or cfg.height % 2:
            raise ValueError("WIDTH/HEIGHT must be even, between 16 and 3840/2160")
        if cfg.fps not in (25, 30, 50, 60):
            raise ValueError("FPS must be 25, 30, 50 or 60")
        if not re.fullmatch(r"[1-9][0-9]*[kM]?", cfg.bitrate):
            raise ValueError("Invalid VIDEO_BITRATE")
        if cfg.preset not in ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium"):
            raise ValueError("Invalid ENCODER_PRESET")
        if not (1 <= cfg.threads <= 16 and 0.2 <= cfg.stale <= 10 and 1 <= cfg.ready_frames <= 120 and 5 <= cfg.stall <= 120):
            raise ValueError("Invalid thread, stale, ready or stall setting")
        if urlsplit(base).scheme != "rtsp":
            raise ValueError("INPUT_URL must use RTSP")
        return cfg

    @property
    def frame_size(self):
        return self.width * self.height * 3 // 2

    @property
    def audio_size(self):
        return 48000 // self.fps * 2 * 2

    @property
    def scale(self):
        return (f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
                f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,setsar=1")


def sanitized(line, cfg):
    for secret in (cfg.input_url, cfg.output_url, os.getenv("READ_PASSWORD"), os.getenv("YOUTUBE_STREAM_KEY")):
        if secret:
            line = line.replace(secret, "[redacted]")
    return re.sub(r"(?:rtmps?|rtsps?)://\S+", "[redacted-url]", line).strip()


def background(target, *args):
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()
    return thread


def stderr_reader(proc, label, cfg):
    for line in proc.stderr:
        line = sanitized(line.decode(errors="replace"), cfg)
        if line:
            LOG.warning("%s: %s", label, line)


def terminate(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def read_exact(stream, size):
    result = bytearray(size)
    view = memoryview(result)
    offset = 0
    while offset < size:
        count = stream.readinto(view[offset:])
        if not count:
            return None
        offset += count
    return bytes(result)


class Source:
    """A single decoding generation. Old generations are never reused."""
    def __init__(self, cfg, audio):
        self.cfg = cfg
        self.lock = threading.Lock()
        self.frame = None
        self.updated = 0.0
        self.count = 0
        self.audio = collections.deque(maxlen=cfg.fps // 2)
        self.audio_updated = 0.0
        self.started = time.monotonic()
        read_fd, write_fd = os.pipe()
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin",
               "-filter_threads", "1",
               "-rtsp_transport", "tcp", "-timeout", "5000000", "-threads", "2", "-i", cfg.input_url,
               "-map", "0:v:0", "-an", "-vf", f"{cfg.scale},fps={cfg.fps}",
               "-threads", "1", "-pix_fmt", "yuv420p", "-f", "rawvideo", "pipe:1"]
        if audio:
            cmd += ["-map", "0:a:0", "-vn", "-af", "aresample=48000:async=1000:first_pts=0",
                    "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", "-f", "s16le", f"pipe:{write_fd}"]
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         pass_fds=(write_fd,), bufsize=0)
        finally:
            os.close(write_fd)
        self.readers = [background(self.read_video), background(stderr_reader, self.proc, "decoder", cfg)]
        if audio:
            self.readers.append(background(self.read_audio, os.fdopen(read_fd, "rb", buffering=0)))
        else:
            os.close(read_fd)
        LOG.info("decoder_started pid=%d audio=%s", self.proc.pid, audio)

    def read_video(self):
        while (frame := read_exact(self.proc.stdout, self.cfg.frame_size)) is not None:
            with self.lock:
                self.frame, self.updated = frame, time.monotonic()
                self.count += 1

    def read_audio(self, stream):
        with stream:
            while (chunk := read_exact(stream, self.cfg.audio_size)) is not None:
                with self.lock:
                    self.audio.append(chunk)
                    self.audio_updated = time.monotonic()

    def select(self, now):
        with self.lock:
            ready = self.count >= self.cfg.ready_frames and now - self.updated < self.cfg.stale
            if not ready:
                self.audio.clear()
                return None, None
            audio = self.audio.popleft() if self.audio and now - self.audio_updated < self.cfg.stale else None
            return self.frame, audio

    def close(self):
        terminate(self.proc)
        for thread in self.readers:
            thread.join(timeout=2)
        self.proc.stdout.close()
        self.proc.stderr.close()


class InputSupervisor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.source = None
        self.lock = threading.Lock()
        self.thread = background(self.run)

    def run(self):
        delay = 1
        while not STOP.is_set():
            cmd = ["ffprobe", "-v", "error", "-threads", "1", "-rtsp_transport", "tcp", "-timeout", "3000000",
                   "-show_entries", "stream=codec_type", "-of", "json", self.cfg.input_url]
            try:
                probe = subprocess.run(cmd, capture_output=True, timeout=7, check=True)
                streams = json.loads(probe.stdout)["streams"]
                if not any(s["codec_type"] == "video" for s in streams):
                    raise ValueError("no video")
                source = Source(self.cfg, any(s["codec_type"] == "audio" for s in streams))
                with self.lock:
                    self.source = source
                try:
                    while not STOP.wait(0.25) and source.proc.poll() is None:
                        with source.lock:
                            last = source.updated or source.started
                            healthy = source.count >= self.cfg.ready_frames
                        if healthy:
                            delay = 1
                        if time.monotonic() - last > max(8, self.cfg.stale * 2):
                            LOG.warning("decoder_stalled")
                            break
                finally:
                    with self.lock:
                        self.source = None
                    source.close()
            except (subprocess.SubprocessError, OSError, ValueError, KeyError):
                LOG.info("input_unavailable retry_in=%ds", delay)
            if STOP.wait(delay):
                break
            delay = min(delay * 2, 5)

    def select(self, now):
        with self.lock:
            source = self.source
        return source.select(now) if source else (None, None)



class Overlay:
    """Decode only changed PNGs off the video clock; keep the last good frame."""
    def __init__(self, cfg):
        self.cfg = cfg
        self.closed = threading.Event()
        self.snapshot = None
        self.signature = None
        self.reload()
        self.thread = background(self.run)

    @staticmethod
    def identity(stat):
        return stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns

    def reload(self):
        with Path(self.cfg.overlay).open("rb") as stream:
            signature = self.identity(os.fstat(stream.fileno()))
            png = stream.read()
        # Keep small legacy overlays at their native top-left position, and
        # support full-size RGBA images generated by the console.
        filters = (fr"format=rgba,crop=min(iw\,{self.cfg.width}):min(ih\,{self.cfg.height}):0:0:exact=1,"
                   f"pad={self.cfg.width}:{self.cfg.height}:0:0:color=black@0,format=yuva420p")
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-filter_threads", "1", "-threads", "1",
             "-f", "image2pipe", "-c:v", "png", "-i", "pipe:0", "-vf", filters,
             "-frames:v", "1", "-threads", "1", "-pix_fmt", "yuva420p", "-f", "rawvideo", "pipe:1"],
            input=png, capture_output=True, timeout=5, check=True,
        )
        if len(result.stdout) != self.cfg.width * self.cfg.height * 5 // 2:
            raise ValueError("Invalid decoded overlay size")
        # One assignment publishes the immutable image and its matching digest.
        self.snapshot = result.stdout, hashlib.sha256(png).hexdigest()
        self.signature = signature

    def run(self):
        attempted = self.signature
        warned = False
        while not self.closed.wait(0.25):
            try:
                signature = self.identity(Path(self.cfg.overlay).stat())
                if signature == attempted:
                    continue
                attempted = signature
                self.reload()
                attempted = self.signature
                warned = False
                LOG.info("overlay_reloaded")
            except (OSError, ValueError, subprocess.SubprocessError):
                if not warned:
                    LOG.warning("overlay_reload_failed keeping_previous_image")
                    warned = True

    def close(self):
        self.closed.set()
        self.thread.join(timeout=6)


class Output:
    def __init__(self, cfg):
        self.cfg = cfg
        self.video = queue.Queue(maxsize=cfg.fps * 2)
        self.audio = queue.Queue(maxsize=cfg.fps * 2)
        self.overlays = queue.Queue(maxsize=cfg.fps * 2)
        self.overlay = Overlay(cfg)
        self.failed = threading.Event()
        self.closed = threading.Event()
        self.last_progress = time.monotonic()
        self.last_output_time = -1
        self.progress_seen = False
        audio_read, audio_write = os.pipe()
        overlay_read, overlay_write = os.pipe()
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin", "-y",
               "-stats_period", "1", "-progress", "pipe:1", "-filter_complex_threads", "1",
               "-thread_queue_size", "8", "-probesize", "32", "-analyzeduration", "0",
               "-f", "rawvideo", "-pixel_format", "yuv420p", "-video_size", f"{cfg.width}x{cfg.height}",
               "-framerate", str(cfg.fps), "-i", "pipe:0",
               "-thread_queue_size", "8", "-probesize", "32", "-analyzeduration", "0",
               "-f", "s16le", "-ar", "48000", "-ac", "2", "-i", f"pipe:{audio_read}",
               "-thread_queue_size", "8", "-probesize", "32", "-analyzeduration", "0",
               "-f", "rawvideo", "-pixel_format", "yuva420p", "-video_size", f"{cfg.width}x{cfg.height}",
               "-framerate", str(cfg.fps), "-i", f"pipe:{overlay_read}",
               "-filter_complex", "[0:v][2:v]overlay=0:0:format=yuv420[v]",
               "-map", "[v]", "-map", "1:a:0", "-c:v", "libx264", "-preset", cfg.preset,
               "-threads", str(cfg.threads), "-tune", "zerolatency", "-b:v", cfg.bitrate,
               "-minrate", cfg.bitrate, "-maxrate", cfg.bitrate, "-bufsize", cfg.bitrate,
               "-x264-params", "nal-hrd=cbr:force-cfr=1", "-g", str(cfg.fps * 2),
               "-keyint_min", str(cfg.fps * 2), "-sc_threshold", "0",
               "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
               "-rw_timeout", "10000000", "-flush_packets", "1", "-flvflags", "no_duration_filesize"]
        if urlsplit(cfg.output_url).scheme == "rtmps":
            cmd += ["-tls_verify", "1", "-ca_file", "/etc/ssl/certs/ca-certificates.crt",
                    "-verifyhost", urlsplit(cfg.output_url).hostname]
        cmd += ["-f", "flv", cfg.output_url]
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, pass_fds=(audio_read, overlay_read), bufsize=0)
        except BaseException:
            os.close(audio_write)
            os.close(overlay_write)
            self.overlay.close()
            raise
        finally:
            os.close(audio_read)
            os.close(overlay_read)
        self.workers = [background(self.feed, self.video, self.proc.stdin),
                        background(self.feed, self.audio, os.fdopen(audio_write, "wb", buffering=0)),
                        background(self.feed, self.overlays, os.fdopen(overlay_write, "wb", buffering=0)),
                        background(self.progress), background(stderr_reader, self.proc, "encoder", cfg)]
        LOG.info("output_started pid=%d", self.proc.pid)

    def feed(self, chunks, stream):
        try:
            with stream:
                while not self.closed.is_set():
                    try:
                        chunk = chunks.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    remaining = memoryview(chunk)
                    while remaining:
                        count = stream.write(remaining)
                        if not count:
                            raise BrokenPipeError()
                        remaining = remaining[count:]
        except (BrokenPipeError, OSError, ValueError):
            self.failed.set()

    def progress(self):
        for line in self.proc.stdout:
            if line.startswith(b"out_time_us=") and line.strip() != b"out_time_us=N/A":
                value = int(line.split(b"=", 1)[1])
                if value > self.last_output_time:
                    self.last_progress = time.monotonic()
                    self.last_output_time = value
                    self.progress_seen = True

    def push(self, video, audio):
        try:
            self.video.put_nowait(video)
            self.audio.put_nowait(audio)
            self.overlays.put_nowait(self.overlay.snapshot[0])
        except queue.Full:
            self.failed.set()

    def alive(self):
        return (self.proc.poll() is None and not self.failed.is_set()
                and time.monotonic() - self.last_progress < self.cfg.stall)

    def close(self):
        self.closed.set()
        terminate(self.proc)
        for worker in self.workers:
            worker.join(timeout=2)
        self.proc.stdout.close()
        self.proc.stderr.close()
        self.overlay.close()


def waiting_frame(cfg):
    cmd = ["ffmpeg", "-v", "error", "-filter_threads", "1", "-i", cfg.waiting, "-vf", cfg.scale,
           "-frames:v", "1", "-threads", "1", "-pix_fmt", "yuv420p", "-f", "rawvideo", "pipe:1"]
    result = subprocess.run(cmd, capture_output=True, timeout=15, check=True).stdout
    if len(result) != cfg.frame_size:
        raise ValueError("Invalid waiting image")
    if not Path(cfg.overlay).is_file():
        raise ValueError("Missing overlay image")
    return result


def write_status(cfg, state, output, started):
    """Publish safe observed state only; never include URLs or credentials."""
    destination = os.getenv("RELAY_STATUS_FILE")
    if not destination:
        return
    now = time.monotonic()
    payload = {
        "updated_at": time.time(), "state": state or "waiting",
        "output_healthy": bool(output and output.alive() and output.progress_seen
                               and now - output.last_progress < 5),
        "width": cfg.width, "height": cfg.height, "fps": cfg.fps,
        "video_bitrate": cfg.bitrate, "uptime_seconds": int(now - started),
    }
    # The digest describes a successfully decoded image, without disk reads on
    # the clocked producer. Invalid replacements keep the previous digest/frame.
    payload["overlay_sha256"] = output.overlay.snapshot[1] if output else None
    path = Path(destination)
    try:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload))
        temporary.replace(path)
    except OSError:
        LOG.warning("status_write_failed")


def run(cfg):
    waiting = waiting_frame(cfg)
    silence = bytes(cfg.audio_size)
    inputs = InputSupervisor(cfg)
    output = None
    retry_at, delay = 0.0, 1
    state = None
    tick = time.monotonic()
    last_health = 0.0
    last_status = 0.0
    started = time.monotonic()
    try:
        while not STOP.is_set():
            now = time.monotonic()
            if output and not output.alive():
                LOG.warning("output_lost retry_in=%ds", delay)
                output.close()
                output = None
                # Closing a failed encoder can intentionally wait for termination.
                # There is no live output clock to catch up during this interval.
                tick = time.monotonic()
                HEALTH.unlink(missing_ok=True)
                retry_at = time.monotonic() + delay
                delay = min(delay * 2, 30)
            if output is None and now >= retry_at:
                output = Output(cfg)
                output_started = now
                tick = time.monotonic()
            if output:
                frame, audio = inputs.select(now)
                selected = "live" if frame else "waiting"
                if selected != state:
                    LOG.info("switch state=%s", selected)
                    state = selected
                output.push(frame if frame else waiting, audio if audio else silence)
                if now - output_started > 60:
                    delay = 1
                if now - last_health >= 2 and output.progress_seen and now - output.last_progress < 5:
                    HEALTH.touch()
                    last_health = now
            if now - last_status >= 2:
                write_status(cfg, state, output, started)
                last_status = now
            tick += 1 / cfg.fps
            if time.monotonic() - tick > 0.5:
                # Losing the clock cannot be hidden: restart rather than accumulate drift.
                LOG.error("scheduler_overrun")
                if output:
                    output.failed.set()
                tick = time.monotonic()
            STOP.wait(max(0, tick - time.monotonic()))
    finally:
        STOP.set()
        if output:
            output.close()
        inputs.thread.join(timeout=12)
        HEALTH.unlink(missing_ok=True)


def main():
    if "--healthcheck" in sys.argv:
        try:
            return 0 if time.time() - HEALTH.stat().st_mtime < 30 else 1
        except FileNotFoundError:
            return 1
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    try:
        run(Config.load())
    except ValueError as error:
        LOG.error("invalid_configuration: %s", error)
        return 1
    except (OSError, subprocess.SubprocessError) as error:
        # Exception text may include secret command arguments. Only emit its type.
        LOG.error("fatal_configuration_or_process_error type=%s", type(error).__name__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
