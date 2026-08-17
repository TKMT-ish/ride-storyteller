# Cloud Run public-demo deployment preflight

## Current status

The deployment target is **not deployed**. This page records an inspectable,
credential-free proposal for a later Cloud Run deployment of the deterministic
public demo. After explicit approval on 2026-08-17, only the Cloud Run Admin API
and Artifact Registry API were enabled. No registry was created, image pushed,
service account created, Cloud Run service created, IAM policy changed, or
public URL issued.

Run the local, non-mutating plan display with:

```text
.venv/bin/python -m app.web.cloud_run
```

The output deliberately reports `deployment_approved=false`,
`public_access_approved=false`, and `mutation_performed=false`.

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

The temporary validation container was stopped and removed. The local image is
not a registry upload or hosted-deployment result.

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

Post-change list operations returned no Cloud Run service and no Artifact
Registry repository in `asia-northeast1`. The dedicated no-role runtime service
account also has not been created or assigned. API enablement is therefore not
deployment evidence and does not create a public or billable workload by itself.

## Staged approval gates

Each stage requires a separate exact-target review. Do not combine the stages
into one unattended command.

1. **Complete:** Cloud Run and Artifact Registry APIs were explicitly approved,
   enabled, and verified. Cloud Build remains disabled.
2. Approve creation of the Tokyo Artifact Registry repository and dedicated
   no-role runtime service account.
3. Rebuild `linux/amd64`, inspect the image, authenticate Docker, and approve
   the one image push.
4. Approve creating a **private** Cloud Run service with zero minimum and one
   maximum instance. `CloudRunPublicDemoPlan.gcloud_deploy_arguments()` refuses
   to produce arguments until this resource-creation gate is explicit.
5. Verify the private service through authenticated health and synthetic-demo
   requests, including all 403 boundaries.
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
