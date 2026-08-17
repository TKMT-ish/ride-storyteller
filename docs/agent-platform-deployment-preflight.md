# Agent Platform deployment preflight

## Scope

This repository constructs the official `vertexai.agent_engines.AdkApp` wrapper
around the private-media-safe ADK app. After explicit approval, one
synthetic-only Agent Runtime was created and verified. The local preflight
endpoint remains read-only and does not create, update, or delete resources.

The wrapper remains limited to the fixed synthetic tool already used by the
local ADK demo. It has no route, media, Box, credential, or user-input tool.

## Two locations, two purposes

The local Gemini inference probe continues to use `GOOGLE_CLOUD_LOCATION=global`.
This is separate from the selected Agent Platform deployment location
`AGENT_PLATFORM_LOCATION=asia-northeast1` (Tokyo). Do not copy `global` into
the Agent Runtime location.

The selected object-style ADK deployment uses a dedicated Tokyo Cloud Storage
staging bucket. Its exact value is stored only in the ignored local `.env`
file:

```text
AGENT_PLATFORM_LOCATION=asia-northeast1
AGENT_PLATFORM_STAGING_BUCKET=gs://...
AGENT_PLATFORM_RUNTIME_NAME=projects/.../locations/asia-northeast1/reasoningEngines/...
```

Do not put the bucket name, service-account value, or other project details
into source code or Notion.

## Deployment-method boundary

The project has selected the object-style `AdkApp` deployment path, so a staging
bucket is required. The source-file path remains unimplemented and is not the
selected deployment method. The approved Runtime uses 4 CPU / 4 GiB, minimum
zero and maximum one instance, and container concurrency nine in Tokyo.

## What the local preflight checks

The **設定状態を確認** control in the local UI, and
`AgentPlatformDeploymentSettings`, report only whether the following local
values are present:

- Google Cloud project ID
- a non-`global` Agent Platform location
- a `gs://...` staging-bucket path

Even with all values present, its result remains
`awaiting_external_verification`. It never means that deployment is ready or
approved.

## Boundary for any additional deployment

The project owner must separately confirm all of the following:

1. Billing is enabled for the selected Google Cloud project. **Confirmed by a
   read-only check on 2026-08-16.**
2. Agent Platform and Cloud Storage APIs are enabled. **Confirmed by a
   read-only check on 2026-08-16.**
3. The deploying identity has the required Agent Platform and Cloud Storage
   permissions. Google Cloud documents `roles/aiplatform.user` and, for the
   object-style staging-bucket path, `roles/storage.admin`. A read-only check
   on 2026-08-16 found a directly assigned project-level `roles/owner` for the
   active deployment identity, which is broader than those roles. No IAM change
   was made; use least-privilege roles before a production release.
4. The runtime identity, regional data location, retention, and expected cost
   are acceptable.
5. The Agent Runtime resource creation and its synthetic-only test request are
   explicitly approved.

On 2026-08-16, `gcloud auth login` and ADC were already complete. Read-only
management-plane checks confirmed project access, billing, and the two required
APIs without creating, updating, uploading, or deleting a cloud resource.
Those checks do not create an Agent Runtime resource or authorize a deployment.

## Selected configuration (2026-08-16)

- Deployment method: object-style `AdkApp`
- Agent Runtime region: `asia-northeast1` (Tokyo)
- Gemini inference endpoint: `global` (unchanged)
- Staging bucket: dedicated empty bucket in `asia-northeast1`, Standard storage
  class, uniform bucket-level access enabled; its name is held only in `.env`
- Default soft-delete retention: seven days. It affects only future staging
  artifacts; real GPX and GoPro media must never be placed in this bucket.
- Real GPX and GoPro media: still not approved for cloud transfer

The initial hosted gate is complete. The one existing Runtime has returned both
the fixed tool call and final response. Any additional Runtime creation,
resource-size change, or deletion remains a separate explicit approval step.
Real GPX, route coordinates, GoPro media, Box content, and user input remain
outside the hosted Runtime boundary.

## Local UI hosted call

The **クラウドRuntime合成テストを実行** control sends an empty POST to
`/api/agent-platform-synthetic-demo`. The server retrieves only the configured
existing Runtime, verifies its expected display name and `google-adk` framework,
then sends the fixed synthetic prompt. The response exposes only model,
location, tool/final-response flags, private-data status, and a billing warning.
It never exposes the Runtime resource name, staging bucket, credentials, or
model response text.

Runtime creation remains on `agentplatform.Client`. With the pinned SDK, its
streaming path may omit events, so hosted verification temporarily retrieves
the existing Runtime through the deprecated-compatible `vertexai.Client` path.
The compatibility client must be created before starting the asynchronous
stream so its internal session stays alive. Verification is bounded to two
attempts and succeeds only when the same attempt contains both the tool call and
final response.

## Verification

Wrapper construction, safe Runtime-reference validation, bounded verification,
and the empty-POST web boundary are covered by the automated tests. The test
suite creates no remote resource. Run the local checks with:

```text
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
```

## Official references

- Google Cloud, [Develop and deploy agents on Agent Runtime with ADK](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/quickstart-adk)
- Google Cloud, [Deploy an agent](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/deploy-an-agent)
- Google Cloud, [Supported locations for agents](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/agent-locations)
