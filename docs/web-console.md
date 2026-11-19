# Web console and live overlay

Both Compose files now include a `web` service using the same image as the relay.
Publish/rebuild this image before redeploying. The interface is in French and is
reachable on internal port **8080** of the `web` service. It works with both the
RTMP and RTMPS configurations.

## One domain for the console and the stream ingest

The domain **`ingest.monolithoid.com`** can serve both the web console and the
video ingest on the same VPS. The services are told apart by their ports:

| Use | Public address | Destination |
| --- | --- | --- |
| Console and Google login | `https://ingest.monolithoid.com` (TCP 443) | Coolify HTTPS proxy → `web:8080` |
| RTMP ingest, standard Compose | `rtmp://ingest.monolithoid.com:1935` | MediaMTX TCP port 1935 |
| RTMPS ingest, alternative Compose | `rtmps://ingest.monolithoid.com:1936` | MediaMTX TCP port 1936 |

These are the default ports. Pick **only one** of the two Compose files, RTMP or
RTMPS; they are not meant to be merged. In Streamcaster, use `live` with the
publishing account for RTMP, or the secret value of `INGEST_STREAM_KEY` as the
stream key for RTMPS, as described in the [RTMPS guide](rtmps.md) or the README for
RTMP.

### DNS and firewall

- Create or check the DNS `A` record of `ingest.monolithoid.com` pointing to the
  VPS public IPv4. Only publish an `AAAA` record if the VPS IPv6 and its routing to
  these services also work.
- If DNS is managed by Cloudflare, select **DNS only** (grey cloud) for this shared
  name: the standard Cloudflare proxy does not carry RTMP/RTMPS. The HTTPS site stays
  encrypted thanks to the Coolify proxy certificate on the VPS.
- Allow TCP **443** for the console, and TCP **1935** for RTMP or **1936** for
  RTMPS, in both the provider and VPS firewalls. If Coolify uses ACME HTTP-01
  validation or the HTTP-to-HTTPS redirect, also allow TCP **80** to its proxy.
- Keep port **8080** internal to Docker: `web` declares it with `expose`, without
  publishing it on the VPS. No host port is reserved for the console.
  The RTSP port **8554** stays internal to the Docker network.

### HTTPS routing in Coolify and certificates

Attach the public domain `https://ingest.monolithoid.com` to the **`web`** service,
with **8080 as the internal target port**. If your Coolify version asks for the
target port in the Domains field, enter `https://ingest.monolithoid.com:8080`; this
suffix is used for internal routing. The public address and `WEB_PUBLIC_URL` stay
`https://ingest.monolithoid.com`, without `:8080`.

The Coolify proxy must share a Docker network with `web` to reach `web:8080`. Do not
route the RTMP/RTMPS ports through the HTTP proxy, and leave Domains empty for
`mediamtx` and `relay`.

The console HTTPS certificate is managed by Coolify on port 443.
For RTMPS, MediaMTX also needs a valid certificate for `ingest.monolithoid.com`,
mounted in `/certs` from `RTMPS_CERTS_DIR`. The Coolify certificate is not
automatically shared with MediaMTX. Follow the
[OVH Certbot and RTMPS renewal](rtmps.md) procedure; its DNS-01 challenge works
while Coolify holds ports 80/443.

The Google login protects the console and its APIs. Authentication of the video
publishing stays the one of the chosen Compose file; the repository's RTMPS variant
requires the secret stream key `INGEST_STREAM_KEY`, with no user name/password on
the Streamcaster side. The `live` path and wrong keys are refused there.

### Error "Bind for 0.0.0.0:8080 failed: port is already allocated"

This error means a deployment is trying to publish port 8080 on the VPS while
another container or process already uses it. Internal port 8080 can be used by
several containers; the conflict is about publishing it on the host.

For the console behind Coolify, keep only this declaration in the `web` service of
the selected Compose file:

```yaml
expose:
  - "8080"
```

Remove the `ports` block from `web` and any host port mapping added in Coolify,
then redeploy. The proxy must keep targeting `web:8080`.
`WEB_PUBLIC_URL=https://ingest.monolithoid.com` and the Google redirect URI do not
change. The old `WEB_PORT` and `WEB_BIND_IP` variables are no longer used. There is
no need to stop the service already holding port 8080 on the VPS.

If a proxy installed directly on the host must reach the console, explicitly add a
loopback mapping in a local Compose override:

```yaml
services:
  web:
    ports:
      - "127.0.0.1:18080:8080"
```

Pick a free host port (here 18080) and point that proxy at `127.0.0.1:18080`. The
internal port and the OAuth settings stay unchanged. This override is not needed
for the Coolify Docker proxy.

## Google login and HTTPS

1. Create a **Web application** OAuth client in Google Cloud / Google Auth Platform.
   Configure the consent screen and the test users if the app is in testing mode.
   No YouTube or Drive access is requested: only `openid email profile` are used.
2. Add the exact redirect URI:
   `https://ingest.monolithoid.com/auth/callback`.
3. In `.env` or the Coolify variables, set:

   ```dotenv
   WEB_PUBLIC_URL=https://ingest.monolithoid.com
   WEB_SECRET_KEY=<output of openssl rand -hex 32>
   GOOGLE_CLIENT_ID=<Google OAuth client>
   GOOGLE_CLIENT_SECRET=<Google OAuth secret>
   GOOGLE_ALLOWED_EMAILS=operator@gmail.com,other@example.com
   ```

4. Point an **HTTPS** domain to `web:8080` through the Coolify reverse proxy. The
   proxy must share the service's Docker network. No host port mapping is needed.
   Keep the secrets in protected variables, never in Git.
5. Redeploy, then open `https://ingest.monolithoid.com` and choose
   « Continuer avec Google » (continue with Google).

In Google Auth Platform, also enter `monolithoid.com` as an authorised domain if the
consent screen asks for it (verify ownership if Google requires it). If an
authorised JavaScript origin is requested, use `https://ingest.monolithoid.com`;
this server-side OAuth flow relies on the exact redirect URI
`https://ingest.monolithoid.com/auth/callback`, without port 8080.
`WEB_PUBLIC_URL` must contain neither a path nor `/auth/callback`.

Without a complete configuration or without a list of accounts, access stays closed
(login page with HTTP 503). The relay can run even if Google is not configured yet.
Only addresses that are explicitly allowed and verified by Google can access the
console and the APIs. Sessions expire after eight hours of inactivity;
HTTPS/HttpOnly/SameSite cookies and a CSRF token protect changes.
The static endpoints and `/healthz` are public, with no broadcast data.
The server must be able to reach `accounts.google.com`, `oauth2.googleapis.com`
and `www.googleapis.com` over HTTPS for the OpenID Connect exchanges.

## Checking that the domain is live

1. Check that the DNS of `ingest.monolithoid.com` resolves to the VPS and that
   `https://ingest.monolithoid.com/login` presents a valid certificate.
2. Log in with an account listed in `GOOGLE_ALLOWED_EMAILS` and, if the Google app
   is in testing mode, in its list of test users.
3. Check that another account cannot access the console. Without a session,
   `/api/status` and `/api/overlay.png` must answer HTTP 401.
4. Publish the stream to the same name on port 1935 or 1936 depending on the
   Compose file, then check the console status and the result in YouTube Studio.
5. Edit an area, validate it and check that it appears in the video output.

On `redirect_uri_mismatch`, compare the URI registered in Google Cloud with
`https://ingest.monolithoid.com/auth/callback` and check `WEB_PUBLIC_URL`.
An HTTP 502 error on the console means you should check the target port 8080, the
network shared with the proxy and the health of the `web` service. A login page
with HTTP 503 means a missing/invalid OAuth configuration, session key, public URL
or account list.

## Settings to copy into Streamcaster

The « Envoyer la vidéo vers la régie » panel (send the video to the control room)
shows the ingest settings with **Copier** (copy) buttons. The key and the password
are hidden by default and can be revealed with **Afficher** (show). The panel is
restricted to allowed Google accounts, like the rest of the console.

- RTMPS Compose: server `rtmps://ingest.monolithoid.com:1936`, key taken from
  `INGEST_STREAM_KEY`, and authentication disabled in Streamcaster.
- RTMP Compose: server `rtmp://ingest.monolithoid.com:1935`, key `live`, user name
  and password taken from `PUBLISH_USER` and `PUBLISH_PASSWORD`.

Both Compose files pass these settings to the `web` service automatically.
The host is taken from `WEB_PUBLIC_URL`; the protocol and port come from the
selected Compose file and from `RTMP_PORT` or `RTMPS_PORT`. If the ingest server
uses another public name, set `INGEST_PUBLIC_URL`, for example
`rtmps://video.example.com:1936`, with no credentials or key in the URL.
This variable is for display only and does not change the MediaMTX configuration.

The YouTube key and the relay's internal read password are not passed to this
panel. After an update, recreate `web` so that it receives the new Compose
variables. Check that copying works without publishing the values in logs or
screenshots.

## Starting and stopping YouTube

The services start with the YouTube broadcast **stopped**, even after a relay
restart. Camera ingest and overlay editing remain available. In the
« Contrôler le direct » panel (control the live stream):

- **Démarrer YouTube** (start) opens the output connection. Without a camera, the
  relay sends the waiting image and silence; with a ready camera, it sends its video.
- **Arrêter YouTube** (stop) closes the encoder and its YouTube connection without
  stopping the services. Wait for the « Diffusion YouTube arrêtée » status as
  confirmation.
- An output drop during a requested broadcast triggers the usual reconnection
  attempts. A restart of the process requires clicking « Démarrer YouTube » again.

These commands require the Google login and CSRF protection. They go through
`RELAY_CONTROL_FILE=/data/overlay/broadcast.json` in the shared `overlay-data`
volume (web writes, relay reads). They are tied to the relay process identifier; an
old persisted command does not restart a new instance. The service stays healthy
while it is deliberately waiting for a start.

To apply the update, rebuild/publish the image, then recreate **web and relay** with
that image and the updated Compose file (RTMP or RTMPS). The console needs neither
the YouTube key nor access to the Docker socket.

These buttons control the video feed, not the lifecycle of the YouTube event.
Depending on the auto-start/auto-stop options in YouTube Studio, you may need to
start or end the event in Studio. If auto-stop ends the event, a new relay start
does not guarantee that it resumes.

## Preparing and broadcasting an overlay

- Add areas or choose « Créer un tableau de score » (create a scoreboard).
- Enter the scores, teams and event information.
- Adjust X, Y, width, height, text size and colours.
- Colours use `#RRGGBBAA`: `00` for a transparent alpha, `FF` for opaque. Text is
  clipped at the edges of its area.
- The « Nom de la zone » field (area name) is only used to identify the area in the
  editor; edit « Texte affiché » (displayed text) to change the visible content.
- The preview is generated by the server with the same rendering as the published
  image. The checkerboard shows transparency and is not part of the PNG.
- Click **Valider et diffuser** (validate and broadcast) to write the RGBA PNG
  atomically. A background loader detects changes to the PNG, decodes it once and
  updates the image kept in memory, without restarting the encoder.
  The relay sends this image at the same rate as the video (25/30/50/60 fps).
  Allow a few seconds for it to take effect, on top of the YouTube delay.
- « Télécharger le PNG diffusé » (download the broadcast PNG) retrieves the latest
  validated version.

The original image `OVERLAY_BASE_IMAGE` (by default `/assets/overlay.png`) is used as
the base of the rendering, in the top left without resizing (parts outside the frame
are clipped). For an overlay that is fully empty apart from the text, provide a
transparent RGBA image. The areas are drawn on top of this base. To change the base
or the dimensions: adjust the variables/the file, then restart `web` and validate the
areas again (adapting them to the new format).

Drafts stay in the page until validated. Validated areas and the PNG are persisted
in the `overlay-data` volume, shared read-only with the relay. Do not delete this
volume during an update. Concurrent edits are detected: a console using an old
revision must reload the page before it can publish. A single Gunicorn instance with
four threads is configured to serialise writes; do not increase the number of
workers or replicate the service without adding an inter-process lock.

## Stream information

Every two seconds, the relay writes a JSON status into `relay-status`, read only by
the console. The interface polls this data every three seconds: camera or waiting
image, encoder progress, format and **configured** video bitrate. A status older
than ten seconds is shown as unavailable. No broadcast URL, YouTube key or password
is included in this status. The publishing settings shown in the connection panel
come from a separate private API.

« Encodage actif » (encoding active) means FFmpeg is making progress; this status
does not certify that YouTube has made the video public. There is no video player in
the console.

## If the overlay does not seem to change

### Migrating the old OVERLAY_IMAGE variable

If Coolify still contains `OVERLAY_IMAGE=/assets/overlay.png`, the relay may keep
broadcasting the static image despite validations in the console.
Use two separate variables:

```dotenv
OVERLAY_IMAGE=/data/overlay/overlay.png
OVERLAY_BASE_IMAGE=/assets/overlay.png
```

`OVERLAY_IMAGE` is the PNG generated in the shared volume, meant for the relay.
`OVERLAY_BASE_IMAGE` is only the static layer loaded by `web`.
The Compose configuration of `web` now reads `OVERLAY_BASE_IMAGE` directly, without
reusing `OVERLAY_IMAGE` as the variable name for the base.

Change the variables in Coolify, then recreate/redeploy **web and relay** to apply
their environment. This can interrupt the YouTube output. After redeploying, check
the effective value of `OVERLAY_IMAGE` in `relay`, then change a score and validate.
Do not edit the contents of `/assets/overlay.png` for each score, and keep the
`overlay-data` volume.

### Checking the preview and the PNG delivery

The editor shows « Éditeur prêt » (editor ready) once loaded. On each change, the
message becomes « Aperçu actualisé » (preview updated) once the new PNG is received.
HTTP, session and script errors are shown under the preview. The script and
stylesheet URLs carry a version computed from their content. If the message stays on
« Chargement de l’éditeur » (loading the editor), check in the browser that
JavaScript and `/static/app.js` are reachable and that no CSP added by the proxy
blocks the script, the API requests or `blob:` images.

After validation, the console compares the fingerprint of the saved PNG with that of
the last image successfully decoded by the relay from `/data/overlay/overlay.png`.
The confirmation means the file was loaded by the relay; it does not measure when it
appears on YouTube, which adds its own video delay.

- If the relay does not confirm the PNG: check the shared `overlay-data` volume and
  the resolved `OVERLAY_IMAGE` path in the `relay` service.
- If no confirmation is provided: check that `web` **and** `relay` were recreated
  with the same new Docker image. Changing only the Compose file does not replace an
  old image that is still running.
- If the downloaded PNG changes but the video does not despite the confirmation:
  keep the `relay` logs, check the image actually running and take the streaming
  platform's delay into account.
- If nothing happens in the editor: note the message under the preview and the
  errors in the browser console, then check the responses to the `/api/preview` and
  `/api/overlay` requests in the Network tab.

### Periodic video stutter

An FFmpeg overlay input limited to 1 frame per second can block the synchronisation
of the `overlay` filter, then release several video frames at once. Timestamps can
stay perfectly regular in the produced file despite these pauses in its output.

The relay now uses an uncompressed YUVA420P input at the same rate as the main video.
The PNG is decoded by a separate loader only when it changes; the in-memory images
are reused between validations. The PNG is no longer read/decoded in the path of
each video frame. The filter composites directly in YUV420 and the FLV writer flushes
its packets without waiting for a buffer to fill. The image fingerprint is also
computed at load time, outside the timed loop.

A missing or invalid PNG during an update keeps the last valid overlay and logs
`overlay_reload_failed keeping_previous_image`. A new valid image is picked up
automatically. On the very first start, a valid overlay is still required.

To apply this change, rebuild/publish the relay image, then recreate `relay` with
that version. No new environment setting is needed; recreating it temporarily drops
the output connection. The relay CPU/memory limits still apply: this fix addresses
the overlay synchronisation pauses and does not replace sizing the encoding.

## Local checks

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
node --check web/static/app.js
docker compose --env-file .env.example config --quiet
docker compose --env-file .env.example -f docker-compose.rtmps.yml config --quiet
```

FFmpeg and the DejaVu Sans Bold font are required for the rendering and reload
tests. The encoder test actually records an FLV, publishes a new PNG through the
console during encoding, then checks the colours, the transparency of the decoded
frames and the real spacing between the received video packets. The file timestamps
alone cannot detect bursty video output. The Google tests simulate the OAuth
callback; a real Google login needs the deployment's OAuth client and HTTPS domain.
