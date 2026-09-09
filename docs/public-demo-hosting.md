# Public demo hosting safety boundary

## Status

The safe public demo is deployed to one Cloud Run service in Tokyo and, since
2026-09-09, **reachable by judges**: its seventh revision,
`ride-storyteller-public-demo-00007-r5f` (image tag `cb43326`), carries the
judge Basic credential; the owner disabled the service's invoker IAM check
(`--no-invoker-iam-check`) after the organisation's domain-restricted-sharing
policy refused an `allUsers` binding ("One or more users named in the policy
do not belong to a permitted customer"). Verified from outside at
<https://ride-storyteller-public-demo-q53n7masba-an.a.run.app>: `/health` 200 without a credential;
the page 401 without or with a wrong credential and 200 with the judge's, in
both languages; POST 405; a request body 413; every private route 403; the
five protective headers; 429 with `Retry-After` after sixty requests in a
minute. The credential is shared only through the Devpost testing
instructions and lives in `private-media/hosting/judge-credential.yaml`. There is no public
deployment evidence yet. Authenticated hosted verification confirms the exact
GitHub AGPL Source link and the private/Google route blocks.

## Judge-gated public access decision (2026-09-08)

The official Agentic Cinema rules require only "a URL to the hosted Project
for judging and testing" -- they do not require unauthenticated public access.
Since IAM-private hosting (the current state) would require pre-registering
each judge's Google account, and this project must control Cloud Run cost
risk before the 2026-09-09 21:00 UTC deadline, the chosen shape is: enable
IAM `--no-invoker-iam-check` (unauthenticated at the Cloud Run layer) *and*
require an application-level HTTP Basic credential on every request, shared
with judges only through the Devpost submission form's testing-instructions
field, never committed to the repository. `public_demo` mode's existing
fail-closed design (no billable calls, 60 req/min limiter, one instance,
budget alerts) is unchanged and still the primary cost control; Basic Auth is
an additional access-control layer on top of it, not a replacement.

Set both `RIDE_PUBLIC_DEMO_BASIC_AUTH_USER` and
`RIDE_PUBLIC_DEMO_BASIC_AUTH_PASSWORD` together to turn the gate on; leaving
both blank keeps `public_demo` mode open, which is still useful for local
testing before a judge credential is chosen. `/health` stays exempt so the
Cloud Run startup/liveness probe is never blocked by the credential. A missing,
malformed, or wrong credential returns `401 Unauthorized` with a
`WWW-Authenticate: Basic` header; the comparison uses `hmac.compare_digest` so
a wrong guess cannot be distinguished by timing. See
[`app/web/deployment.py`](../app/web/deployment.py) and
[`app/web/server.py`](../app/web/server.py) for the implementation, and
[`docs/cloud-run-public-demo.md`](cloud-run-public-demo.md) for the deploy-time
gate that now also requires `basic_auth_configured=True` before
`CloudRunPublicDemoPlan` will produce the unauthenticated-IAM argument set.

Public commit `6998221` contains the abuse safeguards. Its image and active
private revision were verified by digest and hosted behavior; IAM still has no
public binding.

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
- when both `RIDE_PUBLIC_DEMO_BASIC_AUTH_USER` and
  `RIDE_PUBLIC_DEMO_BASIC_AUTH_PASSWORD` are set, every non-health request
  must carry that HTTP Basic credential or is rejected with 401; leaving both
  blank keeps the mode open;
- `/health` reports only mode and boolean capability flags, including whether a
  source repository is configured and whether the judge credential is
  configured (never the credential itself). `/healthz` remains a
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
limiter or DDoS service. The current private revision contains this limiter;
authenticated hosted checks observed 429 and `Retry-After` during a rapid
request sequence.

## Example hosted environment

```text
RIDE_WEB_MODE=public_demo
RIDE_WEB_HOST=0.0.0.0
RIDE_WEB_PORT=8080
RIDE_UI_DEFAULT_LANGUAGE=en
RIDE_SOURCE_REPOSITORY_URL=https://github.com/TKMT-ish/ride-storyteller
```

`RIDE_SOURCE_REPOSITORY_URL` accepts only an HTTPS GitHub, GitLab, or Bitbucket
repository-root URL with no credentials, query, fragment, or subpage. Leave it
blank only when no reviewed repository exists. The reviewed public repository
now exists at the exact URL above; the private service can still be tested with
the value blank, but unauthenticated public-access arguments then fail closed.

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

- domain and distributed abuse controls;
- actually flipping IAM to `--no-invoker-iam-check` and deploying with a real
  judge Basic Auth credential set. The shape is decided (see "Judge-gated
  public access decision" above) and the code/plan-level gates exist and are
  tested; the revision has not yet been redeployed with them applied. One
  private service with five revisions (only the fifth receives traffic),
  immutable `linux/amd64` images, the Tokyo repository, and the dedicated
  no-role service account now exist; Cloud Build remains disabled and optional;
- whether judges need a real cloud call from the public page;
- unauthenticated verification of the redeployed service once public IAM and
  Basic Auth are both live.

The effective Cloud Run maximum is one instance. Google applies the lower of
the service-level limit (1) and revision-level limit (20). On 2026-08-27, JPY
billing currency, the enabled Budget API, and exactly one project-only monthly
JPY 1,000 budget were verified. It has actual-spend alerts at 50%, 80%, and
100%, a forecast alert at 100%, default IAM recipients and Project Owners
enabled, and no Pub/Sub or Monitoring notification channel. It is an alert, not
a hard spending cap.

The public safe mode intentionally does **not** make billable calls. Existing
Gemini, local ADK, and hosted Agent Platform evidence must be shown separately
until an authenticated, rate-limited live-demo design is explicitly approved.
