# syntax=docker/dockerfile:1
FROM python:3.13.12-slim-bookworm
ARG SOURCE_URL=https://github.com/Monolithoid/streamEvent
LABEL org.opencontainers.image.source=$SOURCE_URL \
      org.opencontainers.image.licenses=MIT
# The optional CA is only used in managed development environments, never baked in.
RUN --mount=type=secret,id=proxy_ca \
    set -eu; \
    set --; \
    if [ -s /run/secrets/proxy_ca ]; then \
      set -- -o Acquire::https::CaInfo=/run/secrets/proxy_ca; \
    fi; \
    apt-get "$@" update && apt-get "$@" install -y --no-install-recommends ffmpeg ca-certificates fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --chmod=0444 requirements.txt /app/requirements.txt
RUN --mount=type=secret,id=proxy_ca \
    if [ -s /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /data/overlay /data/status && chown -R 10001:10001 /data
COPY --chmod=0555 web /app/web
COPY --chmod=0444 scripts/stream_controller.py /app/stream_controller.py
COPY --chmod=0444 assets/*.png /app/assets/
RUN chmod 0755 /app/assets
COPY --chmod=0444 LICENSE /app/LICENSE
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
STOPSIGNAL SIGTERM
ENTRYPOINT ["python", "/app/stream_controller.py"]
