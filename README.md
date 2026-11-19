<h1>
  <img src="./assets/streamEvent-icon.png" alt="" width="48" height="48" align="middle">
  Basket Live Stream
</h1>

![streamEvent — A phone on a tripod films a 3×3 basketball court](./assets/streamEvent-social.jpg)

# Basket Live Stream

Headless relay for streaming 3×3 basketball:

**Phone → MediaMTX → FFmpeg ingest → Python switching → FFmpeg output → YouTube RTMPS.**

The control room offers **Démarrer YouTube** (start YouTube) and **Arrêter YouTube**
(stop YouTube). When the services start and after every relay restart, the broadcast
stays stopped until it is explicitly started from the console
([details](docs/web-console.md#starting-and-stopping-youtube)).

During a broadcast, with no phone connected, the output continues with a waiting image
and silence. Switching keeps the output encoder and its connection. An outage of the
outgoing network or a restart, however, requires a new connection; whether the same
YouTube event is kept must be checked on YouTube.

## Images to pull

The production Compose file only uses `image:`, never `build:`:

| Service | Image | Origin |
| --- | --- | --- |
| Ingest | `bluenviron/mediamtx:1.15.3` | Official image of the MediaMTX project |
| Relay | `monolithoid/streamevent-relay:<version>` | This project's image, containing Python, FFmpeg and the controller |

The relay is built **in GitHub Actions**, not on the VPS. Its base is the official
Python image; FFmpeg comes from the Debian repositories with their security fixes.
No GPU, OBS, display server or third-party Python package is required. The multimedia
libraries of the Debian FFmpeg package are included in the image.

**The relay image must be published first.** Having this repository does not mean a
Docker Hub image is already available.

1. Create or pick the **`monolithoid/streamevent-relay`** repository on Docker Hub.
   Create a Docker Hub access token with read/write rights on that repository. Do not
   use the account password in the workflow.
2. In GitHub → Settings → Secrets and variables → Actions, add:
   - secret `DOCKERHUB_USERNAME`: `monolithoid`;
   - secret `DOCKERHUB_TOKEN`: the Docker Hub token. Enter it directly in GitHub,
     never in Git, Coolify or a chat message.
   The `DOCKERHUB_IMAGE` repository variable is optional: it replaces the default
   destination `monolithoid/streamevent-relay`, without tag or registry.
3. Push/merge to `main` and allow GitHub Actions.
   The `Test and publish relay` workflow builds and tests the container, then publishes
   the `main` and `sha-<full SHA>` tags. A Git tag `v…` publishes the same image tag.
   An invalid destination explicitly blocks publishing.
4. Make the Docker Hub repository public to allow anonymous pulls.
   For a private repository, configure access to `docker.io` in Coolify with a
   read-only account/token. With local Compose, use `docker login` if needed.
5. Set `RELAY_IMAGE` to the SHA tag, a version, or ideally the digest shown by
   Actions. `main` is a mutable shortcut for first trials.

For a fork or another Docker Hub repository, set `DOCKERHUB_IMAGE` and adjust
`RELAY_IMAGE` to the same `account/repo`, for example `account/repo:main`.
Pull requests build/test without publishing. Initial target: Linux amd64.

## Docker Compose installation

Requirements: Linux, Docker Engine, Compose v2 and Git. Python/FFmpeg on the host are
only needed for development tests.

```sh
git clone https://github.com/Monolithoid/streamEvent.git
cd streamEvent
cp .env.example .env
chmod 600 .env
openssl rand -hex 24
openssl rand -hex 24
```

Copy the two different passwords into `.env`, replace the YouTube key and pick the
published Docker Hub image. For MediaMTX users/passwords, use only letters, digits,
hyphens and underscores: they are passed through the Compose variables. Do not use
`any` as a user name.

```sh
docker compose config --quiet
docker compose pull
docker compose up -d
docker compose ps
docker compose logs -f --tail=100 relay mediamtx
```

`config --quiet` validates without printing the resolved secrets. Never commit `.env`,
a YouTube key or configuration screenshots. The broadcast stays stopped until
« Démarrer YouTube » is clicked in the control room.

## Coolify deployment from Git

The [Coolify and VPS storage guide](docs/coolify.md) details every deployment field,
the variables to set, the persistent mounts and the checks to run before a game.

1. Publish the Docker Hub image as described above.
2. Create a resource from the Git repository, choose **Docker Compose** with
   `/docker-compose.yml`. Do not select Dockerfile/Nixpacks.
3. Fill in the variables from `.env.example`, especially `RELAY_IMAGE`, the two
   MediaMTX accounts and the YouTube settings. Secrets are stored in Coolify.
4. Copy `config/mediamtx.yml` to `/opt/basket-live/config/mediamtx.yml` on the
   VPS and set `MEDIAMTX_CONFIG` to that absolute path in Coolify. This persistent
   path is also the Compose default. To keep the images independent of redeployments,
   put them on the VPS, for example in `/opt/basket-live/assets`, and set
   `ASSETS_DIR=/opt/basket-live/assets`. The directory and files must already exist
   and be traversable/readable by UID 10001, for example with permissions `755`/`644`.
5. In the Coolify volumes, check that `/mediamtx.yml` points to the persistent file
   on the VPS and `/assets` to the right directory. The MediaMTX mount refuses a
   missing path instead of creating an empty directory.
6. Open `1935/TCP` in the OVH firewall and the VPS firewall, then deploy.
7. Check the logs and the YouTube Studio preview.

RTMP ingest alone does not need an HTTP domain. For the console, configure
`https://ingest.monolithoid.com` on the Coolify proxy to `web:8080` and Google OAuth
as described in the [console guide](docs/web-console.md). The same domain can receive
the stream on a separate port. The RTMP port must be free; `RTMP_PORT` changes it.
No host network, Docker socket or extended privileges. The initial limits are
5 CPU/1.5 GB for the relay and 1 CPU/512 MB for MediaMTX; adjust after measuring
alongside the other services.

`MEDIAMTX_CONFIG` refers to a file on the Docker server, not a path inside the
container nor a Docker volume name. Locally, `.env.example` uses the Git file
`./config/mediamtx.yml`. The accounts stay configured through the numbered
`MTX_AUTHINTERNALUSERS_*` variables.

## YouTube and session management

Enable YouTube Live in advance: the initial activation can be delayed. Create an
event and pick its reusable key in YouTube Studio.

```dotenv
YOUTUBE_RTMPS_URL=rtmps://a.rtmps.youtube.com:443/live2
YOUTUBE_STREAM_KEY=your-secret-key
```

Use the RTMPS URL provided by YouTube if it differs. **Disable auto-stop** in Studio.
Click « Démarrer YouTube » in the control room, check the preview, then click
"Go live" if manual start is enabled.

Between two games, only stop publishing from the phone: the waiting screen continues
as long as the broadcast is active. To cut the video feed, click « Arrêter YouTube »
in the control room, then explicitly end the event in Studio. To also stop the
services:

```sh
docker compose stop relay
# Resume the service, then click « Démarrer YouTube » in the control room.
# YouTube may ask for a new event.
docker compose start relay
# Stop the services without deleting mounted files or volumes.
docker compose down
```

In Coolify, use the resource's commands. Redeploying the relay or changing its
configuration drops the RTMPS connection.

## Android phone

Use an app that supports custom RTMP publishing, for example Larix Broadcaster
(check the features and terms of the installed version). Configure an RTMP
connection:

```text
rtmp://VPS_ADDRESS:1935/live?user=phone&pass=YOUR_PASSWORD
```

Replace `phone` with `PUBLISH_USER`. If the app separates server and key:
server `rtmp://VPS_ADDRESS:1935`, key `live?user=phone&pass=YOUR_PASSWORD`.
App-specific authentication fields may differ; this URL uses the MediaMTX mechanism
verified by the synthetic test.

Choose H.264, AAC, landscape, 1080p30 at about 6 Mbit/s if the uplink allows it,
otherwise 720p30 at 3–4 Mbit/s. Disable the app's battery saving and test on site.
RTMP encrypts neither the credentials nor the video. Never use the YouTube key or a
password reused elsewhere on the phone.

## RTMPS ingest for Streamcaster

The standalone variant [`docker-compose.rtmps.yml`](docker-compose.rtmps.yml)
allows publishing without a user name/password using a secret key
`INGEST_STREAM_KEY`, with TLS encryption and authenticated internal reading by the
relay. It requires a valid certificate mounted from the VPS; the Coolify proxy's
HTTPS certificate is not automatically available.
See the [RTMPS, certificates and renewal guide](docs/rtmps.md).

## Images and settings

The provided PNGs are neutral examples. Replace `waiting.png` with a 1920×1080
image and `overlay.png` with a transparent RGBA PNG. The console uses this overlay
as the base in the top left, then adds the text areas. The result covers both the
game and the waiting screen.

The waiting image and the video are resized while keeping their aspect ratio.
Restart the relay after replacing the waiting image, which is preloaded.
Areas validated in the console are reloaded live without a restart.
After replacing the `overlay.png` base file, restart `web` and validate the areas
again to regenerate the broadcast image.

```dotenv
WIDTH=1280
HEIGHT=720
FPS=30
VIDEO_BITRATE=3500k
ENCODER_PRESET=veryfast
ENCODER_THREADS=4
WAITING_IMAGE=/assets/waiting.png
OVERLAY_IMAGE=/data/overlay/overlay.png
OVERLAY_BASE_IMAGE=/assets/overlay.png
```

Accepted FPS: 25, 30, 50, 60; start with 30. H.264/YUV420p output, two-second GOP,
constant target video bitrate. AAC always present, stereo 48 kHz/128 kbit/s, even
when the phone has no audio track.

## Network and future SRT

| Direction | Port | Use |
| --- | --- | --- |
| Public inbound | TCP 1935 by default | RTMP phone |
| Private Docker | TCP 8554 | RTSP reading by the relay |
| Outbound | TCP 443 | YouTube RTMPS and HTTPS images |
| Outbound | DNS depending on the host | Name resolution |

API, metrics, HLS, WebRTC and SRT are disabled. RTSP uses TCP only, with no RTP/UDP
port. Docker ports can bypass some UFW rules: check the OVH filtering and the
DOCKER-USER chain.

SRT remains a configuration change to validate: enable `srt: yes`, publish
`8890:8890/udp`, configure the MediaMTX `streamid`
`publish:live:user:password` in the phone. For encryption, set
`srtPublishPassphrase` on the path and the same passphrase in the app.
Check the settings with the pinned version before opening the port.
The internal RTSP reading and the relay stay the same.

## Tests without YouTube

Test requirements: Docker Compose, Python ≥3.10, FFmpeg/ffprobe with libx264 on the
host. The test project is independent and only uses loopback ports 19350 and 18554,
with dummy credentials. Do not run two tests at the same time.

```sh
python3 -m unittest discover -s tests -v
docker compose --env-file .env.example config --quiet
python3 tests/integration.py
# Test exactly the published container, its FFmpeg and its non-root UID:
python3 tests/integration.py --image monolithoid/streamevent-relay:YOUR_TAG
```

Logs and `continuous.flv` stay in `test-results/`, ignored by Git. The test checks
switching, timestamps, pixels, sound/silence and recovery after an ingest outage.
It cleans up its containers when done.
See [the full procedure](docs/validation.md).

Manual synthetic source to test the VPS:

```sh
ffmpeg -re -f lavfi -i 'testsrc2=size=1280x720:rate=30' \
  -re -f lavfi -i 'sine=frequency=880:sample_rate=48000' \
  -c:v libx264 -preset veryfast -tune zerolatency -g 60 \
  -c:a aac -f flv \
  'rtmp://VPS_ADDRESS:1935/live?user=phone&pass=PASSWORD'
```

Ctrl-C simulates the phone leaving. Without audio: remove the `sine` input and
replace `-c:a aac` with `-an`. Do not share the shell history containing the password.

## Logs, health and resources

```sh
docker compose logs --tail=100 -f relay
docker compose logs --tail=100 -f mediamtx
docker stats --no-stream
docker compose top relay
```

In Coolify: Logs and Metrics, or the same commands from the deployment directory.
`switch state=live/waiting` indicates a switch; `output_started` must stay unique
during normal transitions. `output_lost` indicates an outgoing break;
`decoder_stalled` a stuck ingest; `scheduler_overrun` an inability to keep up with
the frame rate. Reduce the resolution/load in that last case.
Log rotation: three 10 MB files per service.

The healthcheck verifies encoding progress during a broadcast, or that the relay
loop is running when YouTube is deliberately stopped. Docker Compose does not
restart a container that is merely "unhealthy": the controller manages its own
processes. `unless-stopped` restarts a dead main process, not a closed YouTube event.

The relay logs mask known URLs and secrets. Docker variables and FFmpeg arguments
remain visible to the host administrators: protect VPS/Coolify access and do not
publish an inspection dump.

## Limits

An outage of the VPS, the outgoing network or YouTube requires a reconnection, with
a progressive delay from 1 to 30 seconds. YouTube decides whether to keep the event.
Real-world stability, 1080p load and lip sync must be measured before a public game.

Picking the latest frame and the half-second audio buffer favour bounded
memory/latency. They do not guarantee precise lip sync for every phone. A change of
audio tracks mid-stream requires a reconnection. A frozen image whose packets keep
arriving is not detected as an outage.

See [the architecture](docs/architecture.md). MIT licence.

The [local results](docs/test-report.md) detail what was verified and the limits of
synthetic sources.

## Private web console and editable overlay

A built-in console lets you define text areas (score, teams, event), preview and
then validate a PNG with an alpha channel, reloaded live by FFmpeg. It also shows
the relay status and requires a Google login with a list of allowed accounts. See
[the console configuration](docs/web-console.md) for the HTTPS domain, the OAuth
variables and how the persistent volumes work.
