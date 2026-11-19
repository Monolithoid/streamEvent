# Streamcaster → MediaMTX over RTMPS

The `docker-compose.rtmps.yml` file is a standalone alternative to the RTMP Compose
file. It only publishes RTMPS, on TCP 1936 by default, with a secret key
`INGEST_STREAM_KEY` as the publishing path. The relay's RTSP reading uses the same
path and stays private and authenticated.
The relay and its YouTube output are identical to those of the RTMP Compose file.

TLS encrypts the connection and lets the phone verify the server. The `any` account
allows publishing only on the exact path defined by this key; `live` and other keys
are refused. Knowing the key grants publishing access, like a YouTube stream key. TLS
alone does not authenticate the sender. `overridePublisher: no` stays enabled.

Generate a key with `openssl rand -hex 32`, then store its value in
`INGEST_STREAM_KEY` in Coolify (or in the `.env` file). Use only the 64 generated
hexadecimal characters, without `/`, `?` or a `~` prefix. Keep a key separate from
`YOUTUBE_STREAM_KEY` so they can be rotated independently. Do not store the real key
in Git. MediaMTX logs may contain the path: treat them as confidential. To change the
key, update the variable, redeploy both services and update Streamcaster.

## Automatic Let's Encrypt with OVH

The name `ingest.monolithoid.com` must point directly to the VPS, without an HTTP
proxy/CDN. The Certbot OVH plugin creates and deletes the DNS-01 challenge TXT records
automatically. No extra HTTP port nor stopping the Coolify proxy is needed. The
Coolify proxy's HTTPS certificate is not automatically provided to MediaMTX; leave the
Domains section of the MediaMTX service empty.

The same name can also serve the console on `https://ingest.monolithoid.com`
(port 443), while Streamcaster publishes to `rtmps://ingest.monolithoid.com:1936`.
Attach the HTTPS domain to the `web` service and target port 8080 in Coolify.
Set `WEB_PUBLIC_URL=https://ingest.monolithoid.com` and the Google URI
`https://ingest.monolithoid.com/auth/callback` as described in the
[full DNS, proxy and Google login guide](web-console.md). The Coolify HTTPS
certificate and the MediaMTX RTMPS certificate stay managed separately.

These commands run on the **target Docker VPS**, under Debian/Ubuntu. Use a single
Certbot installation: if Certbot is already installed through Snap or another method,
install the matching OVH plugin rather than mixing installations. For an installation
from Debian/Ubuntu packages:

```sh
sudo apt-get update
sudo apt-get install -y certbot python3-certbot-dns-ovh openssl
```

### OVH DNS access

Create API credentials in the [OVH Europe portal](https://eu.api.ovh.com/createToken/),
with rights limited to the `monolithoid.com` zone:

| Method | Path |
| --- | --- |
| GET | `/domain/zone/` |
| GET | `/domain/zone/monolithoid.com` |
| GET | `/domain/zone/monolithoid.com/*` |
| POST | `/domain/zone/monolithoid.com/record` |
| POST | `/domain/zone/monolithoid.com/refresh` |
| DELETE | `/domain/zone/monolithoid.com/record/*` |

The permissions must stay valid for future renewals; plan their rotation before
expiry if a limited duration is chosen. Keep the three values only on the VPS, never
in Git, Coolify or a chat. Create the protected file, then edit it directly:

```sh
sudo install -d -m 0700 /root/.secrets/certbot
sudo touch /root/.secrets/certbot/ovh.ini
sudo chmod 0600 /root/.secrets/certbot/ovh.ini
sudoedit /root/.secrets/certbot/ovh.ini
```

Content to fill in with the OVH values:

```ini
dns_ovh_endpoint = ovh-eu
dns_ovh_application_key = YOUR_APPLICATION_KEY
dns_ovh_application_secret = YOUR_APPLICATION_SECRET
dns_ovh_consumer_key = YOUR_CONSUMER_KEY
```

### Issuing, copying and renewal

From a copy of the repository on the VPS, install the provided hook before issuing:

```sh
sudo install -d -m 0755 /etc/letsencrypt/renewal-hooks/deploy
sudo install -m 0755 scripts/deploy_rtmps_certificate.sh \
  /etc/letsencrypt/renewal-hooks/deploy/streamevent-rtmps

sudo certbot certonly --dns-ovh \
  --dns-ovh-credentials /root/.secrets/certbot/ovh.ini \
  --dns-ovh-propagation-seconds 120 \
  --cert-name ingest.monolithoid.com \
  -d ingest.monolithoid.com
```

Certbot uses Let's Encrypt. The public certificate and the private key are stored
under `/etc/letsencrypt/live/ingest.monolithoid.com/`. The hook automatically copies
the real `fullchain.pem` and `privkey.pem` files to `/opt/basket-live/certs`
(directory `0700`, key `0600`), after checking the name and that the certificate and
key match. This avoids mounting symbolic links whose targets live outside the
container. MediaMTX uses its image's default user.

On every successful renewal, the hook copies the files again and restarts the
MediaMTX containers that mount this exact directory. The relay keeps running; the
ingest is briefly interrupted and the phone must reconnect. The hook ignores
certificates for other domains. For another domain or directory, adjust the hook's
default values before installing it, and the Compose file accordingly.

Enable periodic renewal and test the DNS challenge with the apt packages:

```sh
sudo systemctl enable --now certbot.timer
sudo certbot renew --cert-name ingest.monolithoid.com --dry-run
```

The `--dry-run` test checks renewal without running the deploy hook.
To also test the copy and the restart, outside a live broadcast:

```sh
sudo certbot renew --cert-name ingest.monolithoid.com --dry-run --run-deploy-hooks
```

Certbot then runs the hook with the active certificate, not the test certificate.
If a certificate was already issued with `--manual`, explicitly migrate its renewal
method to `dns-ovh` before considering the automation operational
(`certbot reconfigure` on versions that offer it). An existing manual certificate does
not become automatically renewable just by installing the plugin.

## Coolify deployment

1. Make the new repository files available to Coolify.
2. Choose `/docker-compose.rtmps.yml` as the Docker Compose Location. This file is
   standalone: do not merge it with `/docker-compose.yml`, which could keep an RTMP
   port published.
3. Keep `MEDIAMTX_CONFIG` pointing to the persistent file on the VPS, which must keep
   `authMethod: internal` and `authInternalUsers: []`, then the relay variables,
   notably `RELAY_IMAGE`, `READ_USER`, `READ_PASSWORD`, `YOUTUBE_STREAM_KEY` and the
   image/video settings.
4. Add `INGEST_STREAM_KEY` with the key generated above (required, with no `live`
   default) and `RTMPS_CERTS_DIR=/opt/basket-live/certs`. Optionally, set
   `RTMPS_BIND_IP=0.0.0.0` and `RTMPS_PORT=1936`.
5. Remove the old JSON variable `MTX_AUTHINTERNALUSERS` and any separately defined
   numbered authentication variable that would contradict the Compose file.
   `PUBLISH_USER` and `PUBLISH_PASSWORD` are not used by this variant.
6. Allow TCP 1936 in the provider and VPS firewalls. Port 443 can stay held by the
   Coolify HTTPS proxy. Close the old RTMP 1935 rule once no other service uses it.
7. Save and redeploy. Recreating the relay can drop the YouTube output.

The default certificate path is `/opt/basket-live/certs`, overridable with
`RTMPS_CERTS_DIR`. The source uses `${RTMPS_CERTS_DIR:-/opt/basket-live/certs}`: the
Coolify volume validator accepts this default value, but not the Compose syntax
`${RTMPS_CERTS_DIR:?message}`.
The mount fails explicitly if the certificate directory does not exist.
In the MediaMTX logs, check that the RTMPS listener opens on `:1936` and that there is
no certificate/key loading error.

For Compose on the command line:

```sh
docker compose --env-file .env -f docker-compose.rtmps.yml config --quiet
docker compose --env-file .env -f docker-compose.rtmps.yml up -d
```

## Streamcaster and verification

```text
Server: rtmps://ingest.monolithoid.com:1936
Key: value of INGEST_STREAM_KEY
Authentication: disabled
```

The app must support a custom RTMPS destination.
First check TLS from an outside machine, with OpenSSL:

```sh
openssl s_client -connect ingest.monolithoid.com:1936 \
  -servername ingest.monolithoid.com \
  -verify_hostname ingest.monolithoid.com -verify_return_error </dev/null
```

A successful connection with `Verify return code: 0 (ok)` validates the chain and the
name against the test machine's trusted authorities. It does not validate RTMP
publishing: then start Streamcaster and check the switch to `live` in the relay logs
and the picture in YouTube Studio. Keep `logLevel: info` in production.
Also check that publishing with the `live` key or a wrong key is refused.
