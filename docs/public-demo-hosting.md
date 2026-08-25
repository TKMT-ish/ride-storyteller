# Public demo hosting safety boundary

## Status

The safe public demo is deployed to one **private** Cloud Run service in Tokyo.
Its fourth revision is Ready, ContainerHealthy, and receives all traffic, but
unauthenticated access has not been approved or enabled. There is no public
deployment evidence yet. Authenticated hosted verification confirms the exact
GitHub AGPL Source link and the private/Google route blocks.

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
- a validated public repository URL produces a bilingual, visible AGPL Source
  link; a missing URL produces a not-public-ready warning;
- `/health` reports only mode and boolean capability flags, including whether a
  source repository is configured. `/healthz` remains a
  local compatibility alias but is not used as a Cloud Run endpoint.

Local mode rejects a wildcard bind. This prevents accidentally exposing the
billable or private-input endpoints by changing only the host address.

## Response protection

All responses use `no-store`, deny framing, disable MIME sniffing, send no
referrer, and disable camera, microphone, and geolocation permissions. The app
does not use browser geolocation.

In `public_demo`, all non-disabled public routes accept body-free GET requests
only. A fixed-window limiter permits 60 non-health requests per minute in each
worker, then returns HTTP 429 and `Retry-After`. Health is exempt for platform
probes. Gunicorn allows no more than two workers and two threads, while Cloud
Run remains at one instance and concurrency four. The limiter is intentionally
process-local: it is a low-dependency abuse baseline, not a distributed rate
limiter or DDoS service. The current private revision predates this limiter; a
new immutable image must be separately approved and deployed before claiming
hosted coverage.

## Example hosted environment

```text
RIDE_WEB_MODE=public_demo
RIDE_WEB_HOST=0.0.0.0
RIDE_WEB_PORT=8080
RIDE_UI_DEFAULT_LANGUAGE=en
RIDE_SOURCE_REPOSITORY_URL=https://github.com/OWNER/REPOSITORY
```

`RIDE_SOURCE_REPOSITORY_URL` accepts only an HTTPS GitHub, GitLab, or Bitbucket
repository-root URL with no credentials, query, fragment, or subpage. Leave it
blank until the reviewed repository exists; the private service can still be
tested, but unauthenticated public-access arguments then fail closed.

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
- uses `/health` as the container health check.

Local verification on 2026-08-17 proved that both the host-native image and a
Cloud Run-compatible `linux/amd64` image build. The current candidate is
44,271,065 bytes,
contains Gunicorn but no Google SDK, starts as
`uid=999(ride)`, becomes Docker-healthy, returns HTTP 200 from `/health`, serves
the five-step English synthetic demo, and returns HTTP 403 for every private or
Google execution endpoint. It also returned 405/413 for disallowed public
request shapes and 429 with `Retry-After: 60` after a rapid local sequence.
The temporary containers were removed after the tests.
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

Google documents that some Cloud Run paths ending in `z` are reserved. The
canonical health endpoint is therefore `/health`; the legacy `/healthz` is kept
only for local compatibility. The current image uses `/health` in Docker and the
private Cloud Run revision has an HTTP startup probe on the same path.

Authenticated hosted verification returned HTTP 200 for `/health` and the
English synthetic demo, and HTTP 403 for all five private/Google execution
routes. The health response retained all safe headers. Cloud Run reported the
container healthy, the same requests appear in logs, and no application startup
error was recorded. An unauthenticated `/health` request returned 403.

## Deliberately unresolved

- domain, abuse controls, and budget alerts;
- unauthenticated public-access authorization. One private service with four
  revisions (only the fourth receives traffic), immutable `linux/amd64`
  images, the Tokyo repository, and
  the dedicated no-role service account now exist; Cloud Build remains disabled
  and optional;
- exact current hackathon requirement for a hosted application;
- whether judges need a real cloud call from the public page;
- deployment and hosted verification of the new process-local request limiter;
- public-access authorization and unauthenticated verification.

The effective Cloud Run maximum is one instance. The Cloud Billing Budget API
was rechecked on 2026-08-25 and remains disabled, while project billing is
enabled. Google applies the lower of the service-level limit (1) and
revision-level limit (20). A read-only budget listing cannot proceed until that
API is enabled. It was not auto-enabled. The owner must choose the exact monthly amount and recipients
before that API and any alert are separately approved.

The public safe mode intentionally does **not** make billable calls. Existing
Gemini, local ADK, and hosted Agent Platform evidence must be shown separately
until an authenticated, rate-limited live-demo design is explicitly approved.
