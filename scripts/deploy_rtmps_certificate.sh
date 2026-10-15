#!/bin/sh
# Certbot deploy hook. Install on the Docker host, not inside a container.
set -eu

domain=${STREAMEVENT_TLS_DOMAIN:-ingest.monolithoid.com}
certs_dir=${STREAMEVENT_TLS_CERTS_DIR:-/opt/basket-live/certs}

# Certbot may renew other certificates on the same host.
case " ${RENEWED_DOMAINS:-} " in
    *" $domain "*) ;;
    *) exit 0 ;;
esac
: "${RENEWED_LINEAGE:?Certbot must supply RENEWED_LINEAGE}"

# Validate both inputs before replacing either deployed file.
openssl x509 -in "$RENEWED_LINEAGE/fullchain.pem" -noout -checkhost "$domain" >/dev/null
cert_public=$(openssl x509 -in "$RENEWED_LINEAGE/fullchain.pem" -pubkey -noout)
key_public=$(openssl pkey -in "$RENEWED_LINEAGE/privkey.pem" -pubout)
if [ "$cert_public" != "$key_public" ]; then
    echo 'Certificate and private key do not match' >&2
    exit 1
fi

install -d -m 0700 "$certs_dir"
staging=$(mktemp -d "$certs_dir/.renewal.XXXXXX")
trap 'rm -rf "$staging"' EXIT HUP INT TERM
install -m 0644 "$RENEWED_LINEAGE/fullchain.pem" "$staging/fullchain.pem"
install -m 0600 "$RENEWED_LINEAGE/privkey.pem" "$staging/privkey.pem"
mv -f "$staging/fullchain.pem" "$certs_dir/fullchain.pem"
mv -f "$staging/privkey.pem" "$certs_dir/privkey.pem"

# Scope restarts to MediaMTX containers mounting this certificate directory.
# At first issuance there may be no running receiver yet.
containers=$(docker ps -q \
    --filter "volume=$certs_dir" \
    --filter 'label=com.docker.compose.service=mediamtx')
for container in $containers; do
    docker restart "$container" >/dev/null
done
