# Cloud Run public-demo deployment record

## Current status

The deterministic public-demo image is deployed as a **private** Cloud Run
service in Tokyo. The service has one ready revision,
`ride-storyteller-public-demo-00001-x62`, receives 100% of traffic, and has no
`allUsers` IAM binding. Unauthenticated public access has not been approved or
enabled. No project IAM role was granted to the dedicated runtime identity and
no user-managed service-account key was created.

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
| Image | `public-demo:candidate` |
| Runtime service account | `ride-storyteller-public` in the project, with no application roles |
| CPU / memory | 1 CPU / 512 MiB |
| Instances | minimum 0 / maximum 1 |
| Container concurrency | 4 |
| Request timeout | 30 seconds |
| Port | Cloud Run supplied `PORT` / container default 8080 |
| UI language | English |

The application environment contains only non-secret mode and worker settings.
The public image contains no Google SDK and has no route that can make a Google,
Agent Platform, Box, GPX, or video request.

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

The hosted `/healthz` request returned a Google-generated HTTP 404 through the
Cloud Run frontend/proxy even though the same path returns 200 in the local
container. The precise hosted cause has not been proven. Therefore hosted health
verification remains unresolved and must not be reported as passed.

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
5. **Partly complete:** authenticated synthetic-demo and all five 403 boundaries
   passed. Hosted `/healthz` still returns a Google-generated 404 and is a known
   issue.
6. Separately approve unauthenticated public access. The command plan uses
   `--no-allow-unauthenticated` until that approval is explicit.
7. Verify the public URL, response headers, abuse/cost controls, and budget
   alerts before treating hosting as complete.

Real GPX, route coordinates, GoPro media, Box content, credentials, and model
requests remain outside this service at every stage.

## Official Google Cloud references

- [Container runtime contract](https://docs.cloud.google.com/run/docs/container-contract)
- [Configure Cloud Run services](https://docs.cloud.google.com/run/docs/configuring)
- [Maximum instances](https://docs.cloud.google.com/run/docs/configuring/max-instances-limits)
- [Ingress restrictions](https://docs.cloud.google.com/run/docs/securing/ingress)
- [Public access](https://docs.cloud.google.com/run/docs/authenticating/public)
- [Test a private service with the Cloud Run proxy](https://docs.cloud.google.com/sdk/gcloud/reference/run/services/proxy)
