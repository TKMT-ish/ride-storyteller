# Cloud Run public-demo deployment record

## Current status

The deterministic public-demo image is deployed as a **private** Cloud Run
service in Tokyo. The current ready revision,
`ride-storyteller-public-demo-00004-2cr`, receives 100% of traffic and has no
`allUsers` IAM binding. Unauthenticated public access has not been approved or
enabled. Its authenticated English UI exposes the validated AGPL Source link
to the public repository. No project IAM role was granted to the dedicated runtime identity and
no user-managed service-account key was created. Its HTTP startup probe uses
`/health` and Cloud Run reports the container healthy.

Run the local, non-mutating plan display with:

```text
.venv/bin/python -m app.web.cloud_run
```

The output is a credential-free plan display; it deliberately performs no
deployment or IAM mutation.

## Reviewed target

| Setting | Proposed value |
|---|---|
| Project | `ride-storyteller` |
| Region | `asia-northeast1` (Tokyo) |
| Service | `ride-storyteller-public-demo` |
| Artifact Registry repository | `ride-storyteller` |
| Image | immutable deployed tag `public-demo:64adfed` |
| Runtime service account | `ride-storyteller-public` in the project, with no application roles |
| CPU / memory | 1 CPU / 512 MiB |
| Instances | minimum 0 / maximum 1 |
| Container concurrency | 4 |
| Request timeout | 30 seconds |
| Port | Cloud Run supplied `PORT` / container default 8080 |
| UI language | English |
| Source repository | Required, validated public repository root before public IAM |

Cloud Run currently reports a service-level maximum of 1 and a revision-level
maximum of 20. Google documents that the effective maximum is the lower of the
two values, so the effective cap is **1 instance**. The project intentionally
uses the service-level cap because Google recommends it as the cost-safety
boundary. Minimum instances remains unset at both levels, which means zero.

The application environment contains only non-secret mode and worker settings.
The public image contains no Google SDK and has no route that can make a Google,
Agent Platform, Box, GPX, or video request.

The next source candidate also rejects request bodies and non-GET methods in
`public_demo` mode and applies a dependency-free fixed-window limit of 60
non-health requests per minute per worker. Gunicorn now accepts at most two
workers and two threads, so one Cloud Run instance admits at most approximately
120 non-health requests per minute before 429 responses. Health is exempt so
the platform probe cannot be blocked. This is a process-local baseline guard,
not a distributed DDoS control; it is not hosted until a newly reviewed image is
separately pushed and deployed.

The local `linux/amd64` verification image is 44,271,065 bytes, runs healthy as
user `ride`, preserves the exact AGPL Source link and five private/Google 403
boundaries, and returns 405/413 for invalid public request shapes. A rapid local
sequence produced 429 with `Retry-After: 60`; the temporary containers were
stopped and auto-removed.

## Local Cloud Run compatibility evidence

On 2026-08-17, the repository produced a `linux/amd64` image with an actual
size of **44,497,520 bytes**. It contained Gunicorn but no importable `google`
package. Under Docker's Apple Silicon emulation it:

- started as non-root `uid=999(ride)` and became healthy;
- listened on `0.0.0.0:8080`;
- returned 200 from `/healthz` and the English synthetic demo;
- returned 403 from the private-GPX, Google-runtime, local-ADK, Agent Platform
  preflight, and hosted-Runtime execution endpoints.

The temporary validation container was stopped and removed. After the later
approved push, the local and remote OCI index digest matched exactly.

Reproducible build target:

```text
docker build --platform linux/amd64 \
  --tag ride-storyteller:public-demo-cloud-run .
```

## Google Cloud management-plane status

An initial read-only check on 2026-08-17 found the Cloud Run Admin, Artifact
Registry, and Cloud Build APIs disabled in project `ride-storyteller`. After the
owner explicitly approved only the first two, they were enabled successfully
and immediately re-listed as enabled. Cloud Build remains disabled and is
optional for the selected local-build-and-push path.

After a second explicit approval, repository `ride-storyteller` was created as a
standard Docker repository in `asia-northeast1` with Google-managed encryption.
It reported 0.000 MB and no images. Service account
`ride-storyteller-public@ride-storyteller.iam.gserviceaccount.com` was created
with no direct project IAM role and no user-managed key.

After a third explicit approval, the local Docker credential helper was
configured for the Tokyo host and exactly one tagged image was pushed:

```text
asia-northeast1-docker.pkg.dev/ride-storyteller/ride-storyteller/public-demo:candidate
```

The remote OCI index digest is
`sha256:353ca0f87c281ee9d852ae997570fe21491640dda16bb20570e41c6cfd3112af`.
Its executable manifest is `linux/amd64`; Docker also attached an untagged
attestation manifest. Repository usage became 44.500 MB. The image contains no
private media or Google SDK.

After a fourth explicit approval, the candidate was deployed with the reviewed
1 CPU / 512 MiB, minimum zero / maximum one instance, concurrency four,
30-second timeout, port 8080, and dedicated no-role service account. The first
revision became Ready and receives all traffic. The service remains private.

Authenticated verification used Google's local Cloud Run proxy. The synthetic
English demo returned HTTP 200. The private-GPX summary, Google runtime, local
ADK, Agent Platform preflight, and hosted-Runtime execution routes each returned
HTTP 403. Cloud Run request logs independently recorded the same 200 and five
403 results and showed no application startup error.

The first revision's hosted `/healthz` request returned a Google-generated HTTP
404. Google Cloud's current known-issues page warns that some paths ending in
`z` are reserved. The application now exposes `/health` as the canonical hosted
endpoint, keeps `/healthz` only as a local compatibility alias, and uses
`/health` for both the Docker health check and Cloud Run HTTP startup probe.

After another explicit approval, the replacement `linux/amd64` candidate was
built and pushed. Its remote OCI index digest is
`sha256:22fd60d9067c678e878c1d11c08de71dfa1d065f36a72062365afcc0350d2fe3`;
the executable manifest digest is
`sha256:0c5842d77ac53c90644951b60a3cfa15b4561b3ffa8a9473311f1a82777c4163`.
The local image size is 44,513,334 bytes. The second private revision became
Ready, reported `ContainerHealthy`, and receives 100% of traffic.

Authenticated hosted verification returned 200 from `/health` and the English
synthetic demo, while all five private/Google execution routes returned 403.
The health response retained `no-store`, frame denial, MIME-sniffing denial,
no-referrer, and camera/microphone/geolocation denial headers. An unauthenticated
`/health` request returned 403. The legacy `/healthz` remains 404 at the Cloud
Run frontend as expected and is not the hosted health contract.

After the public repository was created, the Source-link implementation was
built as `linux/amd64`, pushed under immutable tag `public-demo:64adfed`, and
deployed as the fourth private revision. The remote OCI index and executable
manifest matched the inspected local image. Authenticated hosted verification
returned `source_repository_configured=true`, rendered the exact bilingual AGPL
Source link, preserved the five-step accepted demo and security headers, and
kept all five private/Google routes at 403. The unauthenticated service URL also
returned 403, and the verification proxy was stopped.

## Staged approval gates

Each stage requires a separate exact-target review. Do not combine the stages
into one unattended command.

1. **Complete:** Cloud Run and Artifact Registry APIs were explicitly approved,
   enabled, and verified. Cloud Build remains disabled.
2. **Complete:** the empty Tokyo Docker repository and dedicated no-role,
   no-user-key runtime service account were created and verified.
3. **Complete:** the inspected `linux/amd64` candidate was authenticated,
   pushed once, and verified by remote digest, platform, tag, and repository
   usage.
4. **Complete:** the owner approved creation and cost, and one private Cloud Run
   service/revision was created with the reviewed limits.
5. **Complete:** the canonical hosted `/health`, authenticated synthetic demo,
   all five 403 boundaries, security headers, startup probe, revision digest,
   and unauthenticated 403 were verified. `/healthz` is no longer the hosted
   contract.
6. **Complete:** create and verify the reviewed public repository, then set its exact root URL
   as `RIDE_SOURCE_REPOSITORY_URL`. The plan rejects non-HTTPS, unsupported-host,
   credential-bearing, query, fragment, and subpage URLs.
7. Implement and locally verify the public request-shape and process-local rate
   guard, then push and deploy the reviewed immutable image under a separate
   external-change approval.
8. Separately approve unauthenticated public access. Following Google's current
   recommended method, the command plan refuses to produce
   `--no-invoker-iam-check` unless both approval and a validated Source URL are
   present; private deployment explicitly uses `--invoker-iam-check`.
9. Verify the public URL, bilingual Source link, response headers, abuse/cost controls, and budget
   alerts before treating hosting as complete.

## Budget-monitoring gate

A repeated read-only check on 2026-08-25 found that project billing is enabled
but the Cloud Billing Budget API is still not enabled for this project. The CLI
offered to enable it during the earlier check; that prompt was declined and no
change was made. No budget value should be invented because it is a
financial operating limit chosen by the owner.

Before public IAM is enabled:

1. choose a monthly budget amount and notification destination;
2. separately approve enabling `billingbudgets.googleapis.com`;
3. create alert thresholds only after reviewing the exact amount, currency,
   billing account scope, recipients, forecast behavior, and notification
   limitations;
4. verify the budget exists, but do not describe it as a hard spending cap;
5. retain service-level maximum one and minimum zero even after alerts exist.

Real GPX, route coordinates, GoPro media, Box content, credentials, and model
requests remain outside this service at every stage.

## Official Google Cloud references

- [Container runtime contract](https://docs.cloud.google.com/run/docs/container-contract)
- [Configure Cloud Run services](https://docs.cloud.google.com/run/docs/configuring)
- [Maximum instances](https://docs.cloud.google.com/run/docs/configuring/max-instances-limits)
- [Set maximum instances](https://docs.cloud.google.com/run/docs/configuring/max-instances)
- [Budgets and alerts](https://docs.cloud.google.com/billing/docs/how-to/budgets)
- [Ingress restrictions](https://docs.cloud.google.com/run/docs/securing/ingress)
- [Public access](https://docs.cloud.google.com/run/docs/authenticating/public)
- [Test a private service with the Cloud Run proxy](https://docs.cloud.google.com/sdk/gcloud/reference/run/services/proxy)
- [Cloud Run known issues: reserved URL paths](https://docs.cloud.google.com/run/docs/known-issues)
- [Configure container health checks](https://docs.cloud.google.com/run/docs/configuring/healthchecks)
