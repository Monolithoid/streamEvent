# Validation

## Local automation and CI

```sh
python3 -m unittest discover -s tests -v
docker compose --env-file .env.example config --quiet
python3 tests/integration.py
python3 tests/integration.py --image monolithoid/streamevent-relay:YOUR_TAG
```

The test creates a dedicated MediaMTX, an FFmpeg source and a player recording the
program. With `--image`, the controller runs in the candidate image, with its non-root
UID, read-only. Loopback ports 19350/18554, dummy credentials, no YouTube. Duration: a
few minutes; do not run two instances at the same time.

The capture uses **a single RTMP read connection**, without automatic reconnection.
This checks the output in the broadcast protocol, without adding an RTSP conversion on
the capture side. The player and the encoder must stay active during every source
change.

| Scenario | Criterion |
| --- | --- |
| No phone | Waiting image, H.264 and AAC |
| Arrival/departure/reconnection | Red game pixels and blue waiting pixels |
| Source connected but sending no packets | Waiting after SIGSTOP, recovery after SIGCONT |
| Video without audio | Encoder kept, silent AAC output |
| Three cycles | A single `output_started`, player still active |
| Timestamps | Strictly increasing DTS; video gap <80 ms and audio <50 ms |
| Audio content | Decoded tone and silent intervals |
| PNG overlay | White overlay text visible on the first waiting frame |
| Ingest unavailable then restored | Automatic new connection, both codecs received |
| Controller restarted | Automatic return to the waiting image |

The files are kept in `test-results/`; Docker resources are cleaned up. CI tests the
container before publishing and attaches the results as a temporary artifact. The
synthetic resolution is 320×180/30 FPS: this test does not validate the VPS power in
1080p nor every network blackhole.

To rerun the scenario at the target resolution (on a powerful enough machine):

```sh
TEST_WIDTH=1920 TEST_HEIGHT=1080 TEST_BITRATE=6000k TEST_PRESET=veryfast TEST_THREADS=4 \
  python3 tests/integration.py --image monolithoid/streamevent-relay:YOUR_TAG
```

The test limits the relay to 1.5 GB, 128 processes/threads and at most five CPUs,
adapting to the number of CPUs of the Docker daemon. `TEST_CPUS` lets you pick a lower
quota. The production VPS must have the quota configured in Compose.

## Field trials before a public game

1. Create an unlisted YouTube event and disable its auto-stop.
2. Check the initial waiting image, the silence, then the phone, framing and logo.
3. Film a hand clap to measure the audio/video offset; repeat at 30 minutes and two
   hours. Suggested initial target: under 250 ms with no growing drift. This threshold
   has to be measured; the local test does not guarantee it.
4. Stop/resume publishing ten times; check the same YouTube event, a single
   `output_started`, the audio coming back and no prolonged freeze.
5. Cut mobile data for 5, 15, then 60 seconds; note the waiting and recovery delays.
   Check the behaviour of the Android app.
6. Publish a video without an audio track, then reconnect a source with audio.
7. In pre-production, stop/restore only the ingest; check the backoff and recovery.
   Do not cut the whole network of a VPS hosting other services.
8. Restart the relay container; a new connection is expected. Check separately
   whether YouTube kept the event.
9. Monitor for two hours with `docker stats` and Coolify: stable memory, CPU headroom,
   no `scheduler_overrun`, saturation or encoder restarts.
10. Repeat in 720p if needed and with the final PNGs.

Record the image digests, phone/app model, network, settings, switching delays,
audio/video sync, CPU/RAM and YouTube status.

## Diagnostics

- `input_unavailable` is normal without a phone; otherwise check the URL, credentials,
  OVH port, `live` path, codec and Docker network.
- `output_lost`: check the YouTube key/URL, the event, the network and resources.
- `scheduler_overrun`: reduce the resolution/frame rate or use a faster preset.
- Unreadable PNG: check existence, permissions, internal `/assets` paths and format.
- Closed event: resume/create the event in Studio; restarting FFmpeg cannot undo a
  YouTube closure.

Keep the test logs on failure. Do not publish production logs or a Docker inspection
without checking that they contain no secrets.
