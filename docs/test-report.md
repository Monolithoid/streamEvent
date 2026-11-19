# Local results of 15 October 2026

These results describe the development environment, not the OVH VPS nor YouTube.
No secret or YouTube event was used.

## Environment

- Docker Engine 28.4, Compose 2.40, Linux amd64; three CPUs available to the daemon.
- Official MediaMTX 1.15.3.
- Relay image built locally from Python 3.13.12 slim bookworm.
- Debian FFmpeg 5.1.9 in the image; FFmpeg 7.1.5 on the host for the generator/player.
- Relay read-only, UID 10001, no Linux capabilities, 32 MB tmpfs, memory limited to
  1.5 GB, 128 processes/threads and a quota of three CPUs.

## Checks performed

- Five unit tests: selection/warm-up, stale data, missing audio, partial pipe reads,
  configuration validation and secret masking.
- Validation of the production Compose file with `config --quiet`.
- Start of the production MediaMTX YAML with the accounts injected by Compose.
- Actual build of the Dockerfile and running without root.
- Full integration scenario with the host FFmpeg, then inside the relay image.
- 320×180/30 output and 1920×1080/30 output, 6 Mbit/s, veryfast preset, four encoding
  threads for the 1080p scenario.
- Initial waiting screen, three publishing cycles, packet interruption with
  SIGSTOP/SIGCONT, source without audio, ingest outage/recovery and restart.
- Anonymous read connection refused by MediaMTX.
- During source transitions: same encoding process and same read connection, with
  no player reconnection mechanism.
- Analysis of decoded pixels: waiting/game alternation, presence of the PNG overlay.
- Analysis of decoded audio: tone on sources with audio, silence in the middle of the
  video-only game, then the tone back on the next cycle.

On the 1080p recording, video/audio DTS are strictly increasing.
Maximum observed gaps: **34 ms video**, **22 ms audio**. No encoder restart during
source changes. The ingest outage opens, as expected, a new connection after a delay.

A one-off reading during the 1080p scenario showed about **181 MiB** and
**31 processes/threads**, with a valid healthcheck. This is neither an average nor a
capacity measurement. The red source is synthetic at 320×180, then resized; it is
much easier to encode than a real game and does not measure the cost of decoding a
1080p phone stream.

## Scope and next steps

The initial test using an RTSP capture had detected a timestamp anomaly and missing
AAC packets in the capture. The program validation therefore uses an RTMP read,
matching the output transport, and really analyses the packets and the sound; the
phone ingest stays on RTSP and end-to-end audio has been verified.

The trials also revealed a false clock-overrun log while deliberately waiting for a
failed output to close. The controller now resets its deadline after this close; the
output was already cut.

Remote publishing to Docker Hub, pulling from Coolify, a real RTMPS connection,
keeping a YouTube event alive, phones and lip sync over several hours remain to be
validated separately with [the field procedure](validation.md). The workflow is ready
to build, test and publish on the first authorised push to GitHub.
