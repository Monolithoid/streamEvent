#!/usr/bin/env python3
"""Test production routing through an isolated Traefik TLS proxy.

Requires Docker Compose, OpenSSL and FFmpeg. Uses loopback 19361, fake secrets,
no relay/YouTube. Do not run multiple instances simultaneously.
"""
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
ENV = os.environ.copy()
for selector in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
    ENV.pop(selector, None)
DOCKER = ['docker', '--host=unix:///var/run/docker.sock']
NETWORK = 'streamevent-rtmps-check-proxy'
COMPOSE = DOCKER + ['compose', '-p', 'streamevent-rtmps-check', '-f', str(ROOT / 'docker-compose.yml')]


def run(args, **kwargs):
    return subprocess.run(args, env=ENV, cwd=ROOT, check=True, **kwargs)


with tempfile.TemporaryDirectory(prefix='streamevent-proxy-', dir='/tmp') as directory:
    directory = Path(directory)
    directory.chmod(0o755)
    ENV.update(RELAY_IMAGE='unused:test', PUBLISH_USER='phone', PUBLISH_PASSWORD='test-publish',
               READ_USER='relay', READ_PASSWORD='test-read', YOUTUBE_STREAM_KEY='test-unused',
               RTMPS_DOMAIN='localhost', RTMPS_ENTRYPOINT='rtmps', TRAEFIK_NETWORK=NETWORK,
               TRAEFIK_CERT_RESOLVER='letsencrypt')
    config = json.loads(run(COMPOSE + ['config', '--format', 'json'], capture_output=True, text=True).stdout)
    mtx = config['services']['mediamtx']
    assert not mtx.get('ports'), 'MediaMTX must not publish host ports'
    assert all(v['target'] != '/certs' for v in mtx['volumes'])
    labels = mtx['labels']
    router = 'traefik.tcp.routers.streamevent-rtmps.'
    backend = 'traefik.tcp.services.streamevent-rtmp.loadbalancer.server.port'
    assert labels['traefik.enable'] == 'true'
    assert labels['traefik.docker.network'] == NETWORK
    assert labels[router + 'tls'] == 'true'
    assert labels[router + 'tls.certresolver'] == 'letsencrypt'
    assert labels[backend] == '1935'
    assert not any('passthrough' in k for k in labels)
    print('PASS: production Compose routes TLS to private RTMP; no certificate mounts', flush=True)

    cert, key = directory / 'fullchain.pem', directory / 'privkey.pem'
    run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
         '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost',
         '-keyout', str(key), '-out', str(cert)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Disposable test material must be readable by the managed Docker daemon.
    cert.chmod(0o644)
    key.chmod(0o644)
    mtx_config = directory / 'mediamtx.yml'
    mtx_config.write_text((ROOT / 'config/mediamtx.yml').read_text())
    mtx_config.chmod(0o644)
    # Materialize the production TCP labels through the file provider so this
    # isolated proxy needs neither Docker socket access nor real ACME credentials.
    dynamic = {
        'tls': {'certificates': [{'certFile': '/test/fullchain.pem', 'keyFile': '/test/privkey.pem'}]},
        'tcp': {
            'routers': {'streamevent-rtmps': {
                'rule': labels[router + 'rule'],
                'entryPoints': labels[router + 'entrypoints'].split(','),
                'service': labels[router + 'service'], 'tls': {}}},
            'services': {'streamevent-rtmp': {'loadBalancer': {
                'servers': [{'address': 'mediamtx:' + labels[backend]}]}}}}}
    dynamic_file = directory / 'dynamic.json'
    dynamic_file.write_text(json.dumps(dynamic))
    dynamic_file.chmod(0o644)
    override = directory / 'compose.json'
    override.write_text(json.dumps({'services': {
        'mediamtx': {'volumes': [{'type': 'bind', 'source': str(mtx_config),
                                 'target': '/mediamtx.yml', 'read_only': True}]},
        'proxy': {
            'image': 'traefik:v3.5',
            'command': ['--entrypoints.rtmps.address=:1936',
                        '--providers.file.filename=/test/dynamic.json'],
            'ports': ['127.0.0.1:19361:1936'],
            'volumes': [str(directory) + ':/test:ro'],
            'networks': ['proxy']}}}))
    COMPOSE += ['-f', str(override)]
    run(DOCKER + ['network', 'create', NETWORK], stdout=subprocess.DEVNULL)
    publisher = None
    try:
        run(COMPOSE + ['up', '-d', '--no-deps', 'mediamtx', 'proxy'])
        context = ssl.create_default_context(cafile=str(cert))
        for attempt in range(60):
            try:
                with socket.create_connection(('127.0.0.1', 19361), timeout=1) as raw:
                    with context.wrap_socket(raw, server_hostname='localhost'):
                        pass
                break
            except OSError:
                time.sleep(.2)
        else:
            raise AssertionError('Traefik TLS listener unavailable')
        try:
            with socket.create_connection(('127.0.0.1', 19361), timeout=2) as raw:
                with context.wrap_socket(raw, server_hostname='wrong.invalid'):
                    pass
            raise AssertionError('Incorrect TLS hostname accepted')
        except ssl.SSLCertVerificationError:
            pass
        print('PASS: Traefik certificate verified; wrong hostname rejected', flush=True)
        publisher = subprocess.Popen([
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-re', '-f', 'lavfi',
            '-i', 'color=c=red:s=320x180:r=25', '-t', '6', '-c:v', 'libx264',
            '-threads', '1', '-preset', 'ultrafast', '-tune', 'zerolatency',
            '-tls_verify', '1', '-ca_file', str(cert), '-verifyhost', 'localhost',
            '-f', 'flv', 'rtmps://localhost:19361/live?user=phone&pass=test-publish'],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        _, errors = publisher.communicate(timeout=25)
        assert publisher.returncode == 0, errors.decode()
        cid = run(COMPOSE + ['ps', '-q', 'mediamtx'], capture_output=True, text=True).stdout.strip()
        info = json.loads(run(DOCKER + ['inspect', cid], capture_output=True, text=True).stdout)[0]
        assert not info['HostConfig']['PortBindings'], 'MediaMTX has a public port'
        logs = run(COMPOSE + ['logs', '--no-color', 'mediamtx'], capture_output=True, text=True).stdout
        assert "is publishing to path 'live'" in logs, logs
        assert '[RTMP] listener opened on :1935' in logs, logs
        assert '[RTMPS] listener opened' not in logs, logs
        print('PASS: authenticated RTMPS → Traefik → private RTMP → MediaMTX publication', flush=True)
    except Exception:
        run(COMPOSE + ['logs', '--no-color', 'mediamtx', 'proxy'])
        raise
    finally:
        if publisher and publisher.poll() is None:
            publisher.terminate()
            publisher.communicate(timeout=5)
        try:
            run(COMPOSE + ['down', '--remove-orphans'])
        finally:
            run(DOCKER + ['network', 'rm', NETWORK], stdout=subprocess.DEVNULL)
