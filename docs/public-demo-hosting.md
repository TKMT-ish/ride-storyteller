# Public demo hosting safety boundary

## Status

The repository is prepared for a **safe public demo mode** and now includes a
production container. Cloud Run in Tokyo is the proposed target, but no domain,
public URL, registry, service account, or external deployment has been created.
This document is not public-deployment evidence.

## Modes

`RIDE_WEB_MODE=local` is the development default. It must bind to a loopback
address and can expose the explicitly triggered local Gemini/ADK, hosted Runtime,
Agent Platform preflight, private GPX summary, and optional Google Maps paths.

`RIDE_WEB_MODE=public_demo` may bind to `0.0.0.0` or `::`, but it fails closed:

- private GPX summary input is rejected with HTTP 403;
- Google Maps is not loaded, even if a local key is present;
- local ADK/Gemini execution is rejected;
- hosted Agent Runtime execution is rejected;
- Google runtime configuration and Agent Platform preflight are rejected;
- the corresponding UI controls are disabled;
- deterministic synthetic decision, Story Plan, candidate-plan, and client-only
  video-inventory views remain available;
- `/healthz` reports only mode and boolean capability flags.

Local mode rejects a wildcard bind. This prevents accidentally exposing the
billable or private-input endpoints by changing only the host address.

## Response protection

All responses use `no-store`, deny framing, disable MIME sniffing, send no
referrer, and disable camera, microphone, and geolocation permissions. The app
does not use browser geolocation.

## Example hosted environment

```text
RIDE_WEB_MODE=public_demo
RIDE_WEB_HOST=0.0.0.0
RIDE_WEB_PORT=8080
RIDE_UI_DEFAULT_LANGUAGE=en
```

Some providers supply `PORT`; it is used only when `RIDE_WEB_PORT` is absent.
Invalid modes, hosts, and ports stop startup instead of falling back to a public
bind.

## Production container

`Dockerfile` runs the WSGI application with Gunicorn 26 under an unprivileged
`ride` user. It copies an explicit allowlist (`app`, `pyproject.toml`, `README.md`,
and `gunicorn.conf.py`) rather than copying the repository. `.dockerignore`
independently excludes environment files, private-media directories, GPX/FIT and
GoPro formats, local inventory output, tests, and documentation.

The Gunicorn configuration:

- refuses to start unless `RIDE_WEB_MODE=public_demo`;
- bounds worker and thread counts;
- applies request-line and header-count limits;
- writes access and error logs to standard output/error;
- disables the optional control socket, so the non-root application does not
  need a writable home directory;
- uses `/healthz` as the container health check.

Local verification on 2026-08-17 proved that both the host-native image and a
Cloud Run-compatible `linux/amd64` image build. The latter is 44,497,520 bytes,
contains Gunicorn but no Google SDK, starts as
`uid=999(ride)`, becomes Docker-healthy, returns HTTP 200 from `/healthz`, serves
the five-step English synthetic demo, and returns HTTP 403 for every private or
Google execution endpoint. The temporary container was removed after the test.
The local image tag is not a publication or cloud deployment.

Reproducible local build commands:

```text
docker build --check .
docker build --platform linux/amd64 \
  --tag ride-storyteller:public-demo-cloud-run .
docker run --rm --publish 127.0.0.1:8767:8080 \
  ride-storyteller:public-demo-cloud-run
```

The credential-free Cloud Run plan is printed with
`python -m app.web.cloud_run`. It performs no external action and keeps private
service creation separate from unauthenticated public access. See
[`cloud-run-public-demo.md`](cloud-run-public-demo.md).

## Deliberately unresolved

- domain, access logs, abuse controls, and budget alerts;
- private deployment and public-access authorization. One 44.500 MB tagged
  `linux/amd64` candidate image, the Tokyo repository, and the dedicated no-role
  service account now exist; Cloud Build remains disabled and optional;
- exact current hackathon requirement for a hosted application;
- whether judges need a real cloud call from the public page;
- public repository review and deployment authorization.

The public safe mode intentionally does **not** make billable calls. Existing
Gemini, local ADK, and hosted Agent Platform evidence must be shown separately
until an authenticated, rate-limited live-demo design is explicitly approved.
