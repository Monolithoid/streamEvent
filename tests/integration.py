#!/usr/bin/env python3
"""Real FFmpeg + MediaMTX test, no YouTube, isolated Docker project/loopback ports.

Run from the repository root: python3 tests/integration.py
Results (including the continuous FLV recording) are kept in test-results/.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "test-results"
RUNTIME = RESULTS / "relay-state"
COMPOSE = ["docker", "compose", "-p", "basket-live-test", "-f", str(ROOT / "tests/compose.yml")]
INPUT = "rtmp://127.0.0.1:19350/live?user=phone&pass=test-publish-only"
PROGRAM = "rtsp://sink:test-sink-only@127.0.0.1:18554/program"
PROGRAM_RTMP = "rtmp://127.0.0.1:19350/program?user=sink&pass=test-sink-only"


def stop(proc):
    if proc and proc.poll() is None:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def wait_for(check, label, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.2)
    raise AssertionError("Timeout: " + label)


def probe():
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-rtsp_transport", "tcp", "-timeout", "2000000",
                                 "-show_entries", "stream=codec_name", "-of", "json", PROGRAM],
                                capture_output=True, timeout=5)
        return result.returncode == 0 and len(json.loads(result.stdout).get("streams", [])) == 2
    except (subprocess.TimeoutExpired, ValueError):
        return False


def main():
    RESULTS.mkdir(exist_ok=True)
    RUNTIME.mkdir(exist_ok=True)
    # The image runs as UID 10001; only this isolated test control directory is writable.
    RUNTIME.chmod(0o777)
    subprocess.run(COMPOSE + ["up", "-d", "--wait"], check=True)
    controller = publisher = recorder = None
    log = RESULTS / "controller.log"
    env = dict(os.environ, INPUT_URL="rtsp://relay:test-read-only@127.0.0.1:18554/live",
               READ_USER="", READ_PASSWORD="", OUTPUT_URL="rtmp://127.0.0.1:19350/program?user=sink&pass=test-sink-only",
               WIDTH=os.getenv("TEST_WIDTH", "320"), HEIGHT=os.getenv("TEST_HEIGHT", "180"),
               FPS="30", VIDEO_BITRATE=os.getenv("TEST_BITRATE", "600k"),
               ENCODER_PRESET=os.getenv("TEST_PRESET", "ultrafast"),
               ENCODER_THREADS=os.getenv("TEST_THREADS", "2"), WAITING_IMAGE=str(ROOT / "assets/waiting.png"),
               OVERLAY_IMAGE=str(ROOT / "assets/overlay.png"), READY_FRAMES="3", STALE_SECONDS="1",
               OUTPUT_STALL_SECONDS="10", RELAY_STATUS_FILE=str(RUNTIME / "relay.json"),
               RELAY_CONTROL_FILE=str(RUNTIME / "broadcast.json"))
    handles = []
    image = sys.argv[2] if len(sys.argv) == 3 and sys.argv[1] == "--image" else None
    def launch(handle):
        (RUNTIME / "relay.json").unlink(missing_ok=True)
        if not image:
            return subprocess.Popen([sys.executable, str(ROOT / "scripts/stream_controller.py")],
                                    env=env, stdout=handle, stderr=handle)
        container_env = dict(env, INPUT_URL="rtsp://relay:test-read-only@mediamtx:8554/live",
                             OUTPUT_URL="rtmp://mediamtx:1935/program?user=sink&pass=test-sink-only",
                             WAITING_IMAGE="/assets/waiting.png", OVERLAY_IMAGE="/assets/overlay.png",
                             RELAY_STATUS_FILE="/results/relay.json", RELAY_CONTROL_FILE="/results/broadcast.json")
        available = int(subprocess.check_output(["docker", "info", "--format", "{{.NCPU}}"], text=True).strip())
        cpus = os.getenv("TEST_CPUS", str(min(5, available)))
        cmd = ["docker", "run", "--rm", "--init", "--name", "basket-live-test-relay",
               "--network", "basket-live-test_default", "--read-only", "--tmpfs", "/tmp:size=32m,mode=1777",
               "--memory", "1536m", "--cpus", cpus, "--pids-limit", "128",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
               "-v", f"{ROOT / 'assets'}:/assets:ro", "-v", f"{RUNTIME}:/results"]
        for key in ("INPUT_URL", "OUTPUT_URL", "READ_USER", "READ_PASSWORD", "WIDTH", "HEIGHT", "FPS",
                    "VIDEO_BITRATE", "ENCODER_PRESET", "ENCODER_THREADS", "WAITING_IMAGE", "OVERLAY_IMAGE",
                    "READY_FRAMES", "STALE_SECONDS", "OUTPUT_STALL_SECONDS", "RELAY_STATUS_FILE", "RELAY_CONTROL_FILE"):
            cmd += ["-e", f"{key}={container_env[key]}"]
        return subprocess.Popen(cmd + [image], stdout=handle, stderr=handle)
    def start_broadcast():
        status_path = RUNTIME / 'relay.json'
        wait_for(status_path.exists, 'idle relay status')
        observed = json.loads(status_path.read_text())
        assert observed['broadcast_enabled'] is False, 'Relay must start idle'
        assert not probe(), 'Output must remain disconnected until start'
        command = RUNTIME / 'broadcast.json'
        temporary = command.with_suffix('.tmp')
        temporary.write_text(json.dumps({'run_id': observed['run_id'], 'enabled': True}))
        temporary.replace(command)

    try:
        handle = log.open("w")
        handles.append(handle)
        controller = launch(handle)
        start_broadcast()
        wait_for(probe, "waiting stream with H264/AAC")
        denied = subprocess.run(["ffprobe", "-v", "error", "-rtsp_transport", "tcp", "-timeout", "2000000",
                                 "-show_streams", "rtsp://127.0.0.1:18554/program"],
                                capture_output=True, timeout=5)
        assert denied.returncode != 0 and b"401" in denied.stderr, "Anonymous read must be denied"
        recording = RESULTS / "continuous.flv"
        rec_log = (RESULTS / "recorder.log").open("w")
        handles.append(rec_log)
        recorder = subprocess.Popen(["ffmpeg", "-v", "warning", "-y", "-rw_timeout", "5000000",
                                     "-i", PROGRAM_RTMP, "-map", "0", "-c", "copy",
                                     "-f", "flv", str(recording)], stdout=rec_log, stderr=rec_log)
        time.sleep(3)
        for cycle, audio in enumerate((True, False, True), start=1):
            before = log.read_text().count("switch state=live")
            pub_log = (RESULTS / f"publisher-{cycle}.log").open("w")
            handles.append(pub_log)
            cmd = ["ffmpeg", "-v", "warning", "-re", "-f", "lavfi", "-i", "color=red:s=320x180:r=30"]
            if audio:
                cmd += ["-re", "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000"]
            cmd += ["-c:v", "libx264", "-threads", "1", "-preset", "ultrafast", "-tune", "zerolatency", "-g", "30"]
            cmd += ["-c:a", "aac"] if audio else ["-an"]
            publisher = subprocess.Popen(cmd + ["-f", "flv", INPUT], stdout=pub_log, stderr=pub_log)
            wait_for(lambda: log.read_text().count("switch state=live") > before, f"cycle {cycle} live")
            time.sleep(3)
            if cycle == 1:
                # Connected publisher with no new packets, rather than a clean EOF.
                waiting_before = log.read_text().count("switch state=waiting")
                publisher.send_signal(signal.SIGSTOP)
                wait_for(lambda: log.read_text().count("switch state=waiting") > waiting_before, "stalled phone fallback", 20)
                time.sleep(2)
                live_before = log.read_text().count("switch state=live")
                publisher.send_signal(signal.SIGCONT)
                wait_for(lambda: log.read_text().count("switch state=live") > live_before, "phone network recovery")
                time.sleep(2)
            waiting_before = log.read_text().count("switch state=waiting")
            stop(publisher)
            publisher = None
            wait_for(lambda: log.read_text().count("switch state=waiting") > waiting_before, f"cycle {cycle} fallback")
            time.sleep(3)
            assert controller.poll() is None and recorder.poll() is None, "Persistent processes died"
            assert log.read_text().count("output_started") == 1, "Encoder restarted on source transition"
            assert "scheduler_overrun" not in log.read_text(), "Output clock overran during source transitions"
            print(f"PASS cycle {cycle}, audio={audio}", flush=True)
        stop(recorder)
        recorder = None
        validate_recording(recording)
        # Receiver outage: a separate connection is expected and explicitly measured.
        started = log.read_text().count("output_started")
        subprocess.run(COMPOSE + ["stop"], check=True, stdout=subprocess.DEVNULL)
        time.sleep(3)
        subprocess.run(COMPOSE + ["start"], check=True, stdout=subprocess.DEVNULL)
        wait_for(lambda: log.read_text().count("output_started") > started, "output reconnection", 45)
        wait_for(probe, "recovered H264/AAC output", 45)
        print("PASS receiver outage and automatic reconnection", flush=True)
        observed = json.loads((RUNTIME / 'relay.json').read_text())
        command = RUNTIME / 'broadcast.json'
        temporary = command.with_suffix('.tmp')
        temporary.write_text(json.dumps({'run_id': observed['run_id'], 'enabled': False}))
        temporary.replace(command)
        wait_for(lambda: not json.loads((RUNTIME / 'relay.json').read_text())['broadcast_enabled'],
                 'manual stop acknowledged')
        assert not probe(), 'Output must disconnect after manual stop'
        started = log.read_text().count('output_started')
        time.sleep(3)
        assert log.read_text().count('output_started') == started, 'Stopped output reconnected'
        start_broadcast()
        wait_for(probe, 'manual restart')
        print('PASS manual stop and restart', flush=True)
        stop(controller)
        handle = (RESULTS / "controller-restart.log").open("w")
        handles.append(handle)
        controller = launch(handle)
        start_broadcast()
        wait_for(probe, "controller restart into waiting")
        print("PASS controller restart", flush=True)
    finally:
        if publisher and publisher.poll() is None:
            publisher.send_signal(signal.SIGCONT)
        for proc in (publisher, recorder, controller):
            stop(proc)
        if image:
            subprocess.run(["docker", "rm", "-f", "basket-live-test-relay"], capture_output=True)
        for handle in handles:
            handle.close()
        subprocess.run(COMPOSE + ["down"], check=True)


def validate_recording(path):
    probe_result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_packets",
                                   "-of", "json", str(path)], check=True, capture_output=True)
    data = json.loads(probe_result.stdout)
    streams = {s["codec_type"]: s for s in data["streams"]}
    assert streams["video"]["codec_name"] == "h264"
    assert streams["audio"]["codec_name"] == "aac"
    assert streams["video"]["width"] == int(os.getenv("TEST_WIDTH", "320"))
    assert streams["video"]["height"] == int(os.getenv("TEST_HEIGHT", "180"))
    assert streams["video"]["r_frame_rate"] == "30/1"
    for kind, max_gap in (("video", 0.08), ("audio", 0.05)):
        index = streams[kind]["index"]
        times = [float(p["dts_time"]) for p in data["packets"] if p["stream_index"] == index and "dts_time" in p]
        gaps = [b - a for a, b in zip(times, times[1:])]
        assert len(times) > 100 and all(0 < gap < max_gap for gap in gaps), (kind, max(gaps, default=0))
        print(f"PASS {kind} DTS strictly increasing; maximum gap {max(gaps):.3f}s", flush=True)
    # Sample below the overlay and classify actual decoded pixels, not just logs.
    frames = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf",
                             "fps=2,crop=32:32:280:140,scale=1:1", "-pix_fmt", "rgb24",
                             "-threads", "1", "-f", "rawvideo", "pipe:1"], check=True, capture_output=True).stdout
    states = []
    labels = []
    for n in range(0, len(frames), 3):
        red, green, blue = frames[n:n+3]
        state = "live" if red > 150 and green < 60 and blue < 60 else "waiting" if blue > red and blue > green else "unknown"
        labels.append(state)
        if not states or states[-1] != state:
            states.append(state)
    assert "unknown" not in states and states.count("live") >= 3 and states.count("waiting") >= 4, states
    overlay = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", "crop=128:64:0:0",
                              "-frames:v", "1", "-pix_fmt", "rgb24", "-threads", "1",
                              "-f", "rawvideo", "pipe:1"], check=True, capture_output=True).stdout
    white = sum(all(channel > 190 for channel in overlay[n:n+3]) for n in range(0, len(overlay), 3))
    assert white > 100, "Default overlay text was not composited onto the waiting image"
    samples = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1",
                              "-ar", "48000", "-f", "s16le", "pipe:1"], check=True, capture_output=True).stdout
    import array
    audio = array.array("h", samples)
    rms = [sum(x*x for x in audio[n:n+48000]) / 48000 for n in range(0, len(audio)-48000, 48000)]
    assert any(level > 10000 for level in rms) and any(level < 10 for level in rms), "Missing tone or silence"
    segments = []
    for n, state in enumerate(labels):
        if state == "live":
            if n == 0 or labels[n-1] != "live":
                segments.append([n, n])
            else:
                segments[-1][1] = n
    # RTMP readers can receive audio before the next video keyframe. Account for
    # the actual first packet times when locating the middle of live segments.
    first = {}
    for packet in data["packets"]:
        if "dts_time" in packet:
            first.setdefault(packet["stream_index"], float(packet["dts_time"]))
    offset = first[streams["video"]["index"]] - first[streams["audio"]["index"]]
    def energy(segment):
        middle = (segment[0] + segment[1]) / 4 + offset
        block = audio[max(0, int((middle-0.3)*48000)):int((middle+0.3)*48000)]
        return sum(x*x for x in block) / max(1, len(block))
    assert len(segments) >= 4, segments  # first cycle has a stall/resume
    assert energy(segments[-2]) < 10, "Video-only live source must have silent audio"
    assert energy(segments[-1]) > 10000, "Live audio must return after video-only cycle"
    print("PASS decoded waiting/live alternation, PNG overlay, live tone and video-only silence", flush=True)


if __name__ == "__main__":
    main()
