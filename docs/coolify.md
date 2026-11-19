# Coolify deployment and persistent storage on the VPS

This guide matches the repository's production `docker-compose.yml`: three services,
`mediamtx`, `relay` and `web`, with no build on the VPS. Coolify section names may
vary with the installed version. "Host" paths refer to the target Docker VPS, even
if Coolify is installed on another server.

To receive Streamcaster over **RTMPS with a secret stream key**, use the standalone
variant described in the [RTMPS guide](rtmps.md) instead; it includes the certificate
mount and TCP port 1936. The steps below cover the RTMP Compose file with publishing
authentication.

## 1. Preparing the deployment

- Have a Linux amd64 VPS with Docker and a working target server in Coolify. The
  relay image is currently published for Linux amd64.
- Publish the `monolithoid/streamevent-relay` image following the
  [README](../README.md#images-to-pull) procedure. Pick its version tag, its
  `sha-<full SHA>` tag or its digest to get exactly the same release back.
- Plan the services' resources on top of Coolify and the other applications:
  initial quotas of 5 CPU and 1,536 MiB for `relay`, 1 CPU and 512 MiB for
  `mediamtx`. These are limits, not a measure of the required capacity; validate the
  load on the VPS, especially in 1080p.
- Enable YouTube Live and create an event in YouTube Studio. Get its RTMPS URL and
  stream key. Disable the event's auto-stop to allow waiting phases.
- Prepare the persistent files described in section 4 before the first start.

## 2. Coolify resource fields

Create an application from Git in the desired project and environment.

| Field / section | Value to enter |
| --- | --- |
| Server / destination | The VPS and the Docker destination that will run the services. |
| Git repository | `https://github.com/Monolithoid/streamEvent` or your fork; grant Git access if the repository is private. |
| Branch | `main`, or the branch holding the Compose file to deploy. |
| Build Pack / type | **Docker Compose**. |
| Base Directory | `/`: repository root. |
| Docker Compose Location | `/docker-compose.yml`. |
| Domains | Leave empty for `mediamtx` and `relay`; attach `https://ingest.monolithoid.com` to target port 8080 of `web` (see [console](web-console.md)). |
| HTTP proxy / HTTP port | Route the console to `web:8080`. Do not attach the RTMP/RTMPS ports to the HTTP proxy. |
| Build / start commands | Keep the Compose behaviour; the images already contain their commands. |
| Environment variables | Fill in the values from section 3 before deploying. |
| Storage / Persistent Storage | Check the bind mounts from section 4; do not add a second mount on the same destination. |
| Healthcheck | Keep the Compose one for `relay`; no HTTP endpoint to enter. |
| Automatic deployment | Your choice; every relay redeployment drops the YouTube connection. For games, prefer manual deployment outside live broadcasts. |

The Git repository and the relay image are two separate sources: a Git update does
not build the image in Coolify. Update `RELAY_IMAGE` to deploy a new relay version.
If its Docker Hub repository is private, configure authentication to the `docker.io`
registry in Coolify with a read-only token. The GitHub Actions secrets
`DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` are used to publish the image and are not
application variables to copy over.

Keep the Compose file's private `stream` network, limits, log rotation and
`restart: unless-stopped` policy. The relay already has its Docker healthcheck; an
`unhealthy` state alone does not make Docker Compose restart it.

## 3. Variables to enter in Coolify

In **Environment Variables**, enter the values without surrounding quotes. They must
be available for interpolation of the production Compose file at deployment time.
If Coolify distinguishes preview environments, do not give them the production
YouTube key: a preview can start streaming as soon as it starts. No image build
argument is required.

The values below are those of the Compose file and `.env.example`, except
`ASSETS_DIR` and `MEDIAMTX_CONFIG`, which use absolute persistent paths on the VPS
here. Replace all example secrets. For the two MediaMTX accounts, use only letters,
digits, hyphens and underscores: their values are passed through the Compose
variables. Do not use `any` as a user name.

### Image, authentication and YouTube

| Variable | Value / example | Role |
| --- | --- | --- |
| `RELAY_IMAGE` | `monolithoid/streamevent-relay:main` for a first trial; then prefer a version, a SHA tag or `monolithoid/streamevent-relay@sha256:<published digest>` | Required, already published relay image. |
| `PUBLISH_USER` | `phone` | Required, publishing account used by the phone. |
| `PUBLISH_PASSWORD` | A first secret generated with `openssl rand -hex 24` | Required, the phone's password. |
| `READ_USER` | `relay` | Internal read account; default value if omitted. |
| `READ_PASSWORD` | A second secret generated with `openssl rand -hex 24` | Required, different from the publishing password; the phone does not need it. |
| `YOUTUBE_RTMPS_URL` | `rtmps://a.rtmps.youtube.com:443/live2` | Server URL provided by Studio, without the key; the relay requires RTMPS. |
| `YOUTUBE_STREAM_KEY` | The YouTube event key | Required, the key alone, without URL or leading `/`. |

Mark the passwords and the YouTube key as secrets in Coolify when the interface
allows it. Do not write them in Git, the PNGs or the MediaMTX configuration.
Docker/Coolify administrators can read the runtime configuration: restrict that
access. No manual `.env` file is needed on the VPS for a deployment driven by Coolify
variables.

### Network, video and resources

| Variable | Initial value | Role / accepted values |
| --- | --- | --- |
| `RTMP_BIND_IP` | `0.0.0.0` | Listens on the VPS interfaces. `127.0.0.1` prevents a direct connection from the phone. A specific IP must belong to the VPS. |
| `RTMP_PORT` | `1935` | TCP port published on the VPS; must be free. The container port stays `1935`. |
| `WIDTH` | `1920` | Output width, even, from 16 to 3840. |
| `HEIGHT` | `1080` | Output height, even, from 16 to 2160. |
| `FPS` | `30` | `25`, `30`, `50` or `60`. Start with 30. |
| `VIDEO_BITRATE` | `6000k` | Target video bitrate; positive integer with optional `k` or `M` suffix. |
| `ENCODER_PRESET` | `veryfast` | `ultrafast`, `superfast`, `veryfast`, `faster`, `fast` or `medium`. Slower presets need more CPU. |
| `ENCODER_THREADS` | `4` | Number of encoder threads, from 1 to 16. |
| `RELAY_CPUS` | `5.0` | Relay CPU quota, separate from the thread count. Adjust to the available capacity. |

To start in 720p, enter `WIDTH=1280`, `HEIGHT=720`, `FPS=30` and
`VIDEO_BITRATE=3500k`. Prepare an overlay suited to that resolution. The memory
limits (1,536 MiB / 512 MiB) and the MediaMTX CPU quota (`1.0`) are set in the Compose
file: no dedicated variable can currently change them.

### Files and switching

| Variable | Recommended initial value | Role / accepted values |
| --- | --- | --- |
| `MEDIAMTX_CONFIG` | `/opt/basket-live/config/mediamtx.yml` | Absolute path of the file on the VPS, mounted in `mediamtx` at `/mediamtx.yml`. Compose default; replace the local value from `.env.example` in Coolify. |
| `ASSETS_DIR` | `/opt/basket-live/assets` | Absolute path of the directory on the VPS, mounted in `relay` at `/assets`. The repository value `./assets` uses the Git files. |
| `WAITING_IMAGE` | `/assets/waiting.png` | Path inside the container, never the `/opt/...` path on the VPS. |
| `OVERLAY_IMAGE` | `/data/overlay/overlay.png` | PNG generated by `web` and read live by `relay`. Do not use `/assets/overlay.png` here. |
| `OVERLAY_BASE_IMAGE` | `/assets/overlay.png` | Transparent static image used by `web` as the rendering base. |
| `STALE_SECONDS` | `1.5` | Maximum age in seconds of the last frame before switching to waiting, from `0.2` to `10`. |
| `READY_FRAMES` | `5` | Number of frames received before going live, from `1` to `120`. |
| `OUTPUT_STALL_SECONDS` | `20` | Time without encoder progress before restarting it, from `5` to `120` seconds. |

The Compose file sets `INPUT_URL=rtsp://mediamtx:8554/live` itself and builds
`MTX_AUTHINTERNALUSERS_*` from the two accounts. Do not enter them separately in
Coolify. `OUTPUT_URL` is reserved for controller tests and is not exposed by the
production Compose file.

## 4. Volumes and persistent files on the VPS

The application has no database, no video recording and no session state to keep on
disk. The files to keep are the images and the MediaMTX configuration copied to the
VPS. A volume cannot preserve the YouTube connection across a restart.

| Service | Source on the VPS | Destination in the container | Mode | Configuration |
| --- | --- | --- | --- | --- |
| `relay` | `/opt/basket-live/assets` | `/assets` | Bind mount, read-only | Set `ASSETS_DIR=/opt/basket-live/assets`; mount already declared in the Compose file. |
| `mediamtx` | `/opt/basket-live/config/mediamtx.yml` | `/mediamtx.yml` | File bind mount, read-only | Set `MEDIAMTX_CONFIG` to the path of the existing persistent file; Compose default. |

For the recommended deployment, create the images directory and the configuration
file outside Coolify's Git directory. Do not mount an empty named volume at
`/assets`: both PNGs must be present from the start. Do not create a persistent volume
at `/tmp`: the Compose file provides a 32 MiB `tmpfs` there for temporary files and the
heartbeat. Logs go to stdout/stderr, with Docker rotation of three 10 MB files per
service; no application log volume is needed.

### Preparing the images directory

Run on the target VPS, from a copy of the repository containing the PNGs (or adapt
the source paths to the location of your own files):

```sh
sudo install -d -m 0755 /opt/basket-live /opt/basket-live/assets
sudo install -m 0644 assets/waiting.png /opt/basket-live/assets/waiting.png
sudo install -m 0644 assets/overlay.png /opt/basket-live/assets/overlay.png
sudo ls -ld /opt/basket-live /opt/basket-live/assets
sudo ls -l /opt/basket-live/assets/waiting.png /opt/basket-live/assets/overlay.png
```

These commands copy the examples and replace files with the same name: on an existing
installation, keep your custom images. Use a 1920×1080 waiting image for the default
profile and a transparent RGBA PNG overlay. The console places this base in the top
left and adds the text.

The relay runs as UID/GID `10001:10001`. Permissions `0755` on the directories and
`0644` on the PNGs allow reading without granting write access; also check that any
parent directories can be traversed. There is no need to change the owner to `10001`
or to grant `777`.

In Coolify, check after Compose resolution that the `relay` service really uses the
intended absolute source. The files must exist on the Docker server, not only on the
machine hosting the Coolify interface. After changing the waiting image, restart the
relay: it is preloaded. This drops the RTMPS connection. Text validated in the console
is reloaded without a restart. After replacing the overlay base, restart `web` and
validate the areas to regenerate the shared PNG.

The `web` service keeps this PNG and its areas in the `overlay-data` volume.
Configure its Google login and HTTPS domain as described in the
[console guide](web-console.md).

### Preparing the persistent MediaMTX configuration

On the target VPS, from a copy of the repository, copy the initial configuration
only if you do not already have your own custom file:

```sh
sudo install -d -m 0755 /opt/basket-live/config
sudo test -e /opt/basket-live/config/mediamtx.yml || sudo install -m 0644 config/mediamtx.yml /opt/basket-live/config/mediamtx.yml
sudo test -f /opt/basket-live/config/mediamtx.yml
```

In Coolify, set `MEDIAMTX_CONFIG=/opt/basket-live/config/mediamtx.yml`, or the
absolute path of your existing persistent file. The Compose file uses this variable
directly; no YAML change is needed:

```yaml
volumes:
  - type: bind
    source: ${MEDIAMTX_CONFIG:-/opt/basket-live/config/mediamtx.yml}
    target: /mediamtx.yml
    read_only: true
    bind:
      create_host_path: false
```

The source is a file on the Docker server, not a directory nor a Docker volume name.
`create_host_path: false` prevents Docker from creating a directory if the file is
missing. If an earlier attempt created a directory at that location, inspect it and
use `rmdir` only if it is empty, then create the file. Do not add a second Coolify
mount on `/mediamtx.yml`. A named volume is a directory: mounting it directly at
`/mediamtx.yml` causes a directory/file mismatch.

For a local start with the Git file, `.env.example` sets
`MEDIAMTX_CONFIG=./config/mediamtx.yml`. A relative path is resolved on the host
relative to the Compose file, never inside the container. For Coolify, use the
absolute persistent path above. Keep authentication through
`MTX_AUTHINTERNALUSERS_*`, with no real passwords in the YAML. Redeploy after
changing the file; a Git update does not replace this copy.

### Backups

Back up `/opt/basket-live/assets`, the file set in `MEDIAMTX_CONFIG`, and the Coolify
configuration and secrets according to your backup procedure. Keep a copy off the
VPS: a bind mount survives redeployments but not the loss of the disk. Also keep the
exact `RELAY_IMAGE` reference. When restoring, put the files and their permissions
back on the target server before deploying.

## 5. Network and first start

| Direction | Port | Action |
| --- | --- | --- |
| Public inbound | TCP `1935`, or the value of `RTMP_PORT` | Allow in the provider/VPS firewall and Docker filtering; no other application may use this port. |
| Public inbound | TCP `443` (and `80` if used by ACME HTTP-01/redirect) | Route the HTTPS console to `web:8080` through Coolify. |
| Docker internal | TCP `8080` on `web` | Reachable by the proxy through the Docker network; not published on VPS port 8080. |
| Docker internal | TCP `8554` on `mediamtx` | Keep private; no host port to open. |
| Outbound | TCP `443` | Allow the registries, YouTube RTMPS streaming and Google OAuth exchanges. |
| Outbound | DNS depending on the VPS configuration | Allow name resolution. |

Filtering of ports published by Docker can bypass UFW rules; also check the provider
firewall (OVH if used) and `DOCKER-USER`. Coolify/SSH administration access to the
VPS remains to be managed according to your installation. The console needs an HTTPS
domain; `ingest.monolithoid.com` can be shared with the video ingest thanks to the
separate ports (see the [domain and Google OAuth guide](web-console.md)). No extra UDP
port is required. Inbound RTMP is unencrypted: the phone only gets its publishing
account, never the YouTube key.

1. Save the variables, check the mounts and click **Deploy**.
2. Check the pull logs of both images, then the service logs.
   The relay immediately sends the waiting image and silence to YouTube.
3. Check that `relay` becomes healthy after the start period (30 seconds in the
   Compose file), then check the preview in YouTube Studio. Click "Go live" if manual
   start is enabled.
4. Configure the phone with
   `rtmp://VPS_ADDRESS:1935/live?user=phone&pass=PASSWORD`, replacing the port, user
   and password with your values. The path stays `live`.
5. Publish, then stop publishing from the phone. Check the game/waiting transitions
   in Studio and the `switch state=live` / `switch state=waiting` logs.
   `output_started` must stay unique during these normal transitions.
6. Watch CPU and memory in Coolify during a representative trial before a game.
   `scheduler_overrun` suggests reducing the resolution or the CPU load.

To end a session, stop the relay, then explicitly end the event in YouTube Studio. A
redeployment or a variable change that recreates the relay requires a new connection;
a closed event does not reopen automatically.

## 6. Checks when something fails

| Symptom | Check |
| --- | --- |
| `Set ...` during Compose resolution | Required variable missing or empty in the Coolify production environment. |
| Image not found / access denied | Image published, exact `RELAY_IMAGE` reference and Docker Hub access configured if private. |
| PNGs cannot be read | `ASSETS_DIR` absolute on the right VPS, both files present, correct names and permissions; `/assets/...` paths inside the container. |
| MediaMTX refuses `/mediamtx.yml` | `MEDIAMTX_CONFIG` must point to an existing file on the VPS; no competing mount on this destination. |
| Phone refused or unreachable | IP/port, firewall, publishing account, `live` path; no other phone may already be publishing on this path. |
| Game received but missing on YouTube | Relay logs, RTMPS key and URL, outbound access, Studio event state. |
| `output_lost` or unhealthy relay | Outbound connection, encoder progress and available resources; volumes do not fix these breaks. |

For synthetic tests and continuity limits, see the [README](../README.md), the
[validation](validation.md) and the [architecture](architecture.md). Do not share a
resolved Compose output, a Docker dump or logs containing connection URLs with
secrets.
