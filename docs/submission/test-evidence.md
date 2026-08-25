# Test evidence

This page records reproducible local checks without environment values, cloud
resource names, private paths, GPX contents, or video file names.

## Commands

```text
.venv/bin/python -m pytest
.venv/bin/python -m ruff check app tests
.venv/bin/python -m pip check
.venv/bin/python -m app.submission
```

## Latest result

2026-08-25: **243 pytest tests passed**, Ruff was clean, `pip check` found no
broken requirements, and the dependency-free Day 1 checks passed. The submission
preflight now passes the document, required Devpost-draft headings,
AGPL-3.0-license, private-ignore, private-file, and secret checks and reports
`offline_preparation_complete=true`. External publication, hosted-app, video,
and real-media gates remain separate and are not claimed by the offline result.

The canonical repository `LICENSE` SHA-256 exactly matched the file fetched from
GNU at `https://www.gnu.org/licenses/agpl-3.0.txt`. The readiness recognizer now
reports `recognized license: AGPL-3.0`; a focused regression test keeps MIT
recognition as a supported generic preflight case without selecting it for this
project. The installed direct dependencies were inspected separately and no
blocking conflict was identified among their Apache-2.0 and MIT-family licenses.
Seven third-party SDK deprecation warnings remain non-fatal and unchanged in
character.

The Source-link publication gate adds focused coverage for accepted HTTPS
GitHub/GitLab/Bitbucket repository-root URLs; rejected HTTP, unsupported-host,
credential-bearing, query, fragment, subpage, trailing-slash, and traversal
forms; bilingual link rendering; the missing-link public warning; and the
Cloud Run refusal to generate unauthenticated-access arguments without a
validated repository URL. The related Web, deployment, i18n, and Cloud Run
subset passed **63 tests**. A local public-demo browser check with a synthetic
placeholder URL confirmed the English AGPL Source link was visible at the page
footer and the layout remained intact. The temporary server and tab were then
closed; the placeholder was not recorded as a real repository.

The sanitized IBM Bob image was inspected at full resolution and matched against
the current render-gate source and focused test. A new regression test removes
the image from a prepared fixture and verifies that the submission-document
check fails with its exact file name.

Two additional focused tests verify that the preflight reads only the local
rules-acknowledgment flag, never treats it as live registration proof, and fails
safely when the local state is unreadable. The existing focused test removes one
required Devpost heading and verifies the exact missing section. The preflight also requires the
registration worksheet, IBM Bob capture checklist and evidence image, and recording runbook, so
those handoff documents cannot silently disappear from a public candidate.

On 2026-08-20, the English `public_demo` UI was opened in a browser and exercised
through the accepted decision, missing-asset decision, Story Plan, and
candidate-plan views. The IBM Bob development-evidence section rendered in
English, cloud/private controls were disabled, the deterministic demo returned
its five-step flow, and the candidate plan remained blocked for insufficient
duration and unconfirmed evidence. Five synthetic-only screenshots were saved
under `docs/submission/assets/` and manually inspected at full resolution. The
temporary loopback server and test tab were closed after inspection. These
captures do not claim hosted execution, public availability, Bob usage, or
real-media completion.

The suite includes Japanese/English Story Plan API coverage and verifies that
changing the output language does not change selected event IDs, chapter IDs,
event links, or narrative roles.

The four synthetic Story Agent outcomes are also compared across Japanese and
English. Event ID, video-evidence requirement, asset hint, and decision status
must remain identical while labels, reasons, story roles, and flow steps change
language.

The candidate-plan API comparison removes only the localized story title and
review-reason prose, then requires every remaining plan and review field to be
equal across Japanese and English.

The loopback-only GPX fixture is also compared in both languages. Route summary,
event counts, and structural chapter roles must match, and neither response may
contain latitude or longitude fields.

Gemini Story copy tests cover synthetic-only enforcement, outbound-field
minimization, exact chapter IDs/count/order, empty/extra/malformed output,
JSON-Schema transport configuration, JSON fallback, and provider-detail
redaction. A live fixed-synthetic request returned a valid three-chapter English
response; generated text was not displayed or saved.

The English SRT draft is verified for sequential numbering, non-overlapping
timestamps, a precise 180-second end, bounded cue duration, ASCII-only public
text, secret/path absence, and an explicit real-media gate.

Production-container tests verify the public-mode default, non-root user,
allowlisted copy operations, private-data build exclusions, health check,
Gunicorn entry point, bounded workers/threads, disabled control socket, and the
pinned Gunicorn 26 dependency range. A real local Docker build also completed.
The resulting container became healthy, returned HTTP 200 from `/healthz`,
served the English synthetic demo, and returned HTTP 403 for the private GPX
summary endpoint.

The Cloud Run plan tests also verify the fixed Tokyo target, 1 CPU / 512 MiB,
minimum zero / maximum one instance, concurrency four, non-secret environment,
and the independent resource-creation and unauthenticated-access gates. A real
`linux/amd64` image build produced a 44,497,520-byte image with no Google SDK.
The emulated container was healthy, served the synthetic demo, and returned 403
for all private and Google execution endpoints.

An additional subprocess check removes the optional cloud package boundary and
verifies that local cloud-only endpoints return a safe 503 without exposing the
underlying import error. Public mode continues to return 403 before any import.

After explicit approval, management-plane verification confirmed that the Cloud
Run Admin and Artifact Registry APIs are enabled. A second explicit approval
created a standard Docker repository in Tokyo using Google-managed encryption;
it reported 0.000 MB and no images. The dedicated runtime service account has
no direct project role and no user-managed key. Cloud Run service list remains
empty and Cloud Build remains disabled.

After a third explicit approval, Docker authentication was configured for only
the Tokyo registry host and one candidate tag was pushed. Remote inspection
matched OCI index digest
`sha256:353ca0f87c281ee9d852ae997570fe21491640dda16bb20570e41c6cfd3112af`,
reported an executable `linux/amd64` manifest plus its attestation manifest,
and showed repository usage of 44.500 MB. The push itself did not create a
workload or public endpoint.

After a fourth explicit approval of one private service and its cost, one Tokyo
revision became Ready and received 100% of traffic with the reviewed 1 CPU /
512 MiB, minimum zero / maximum one instance, concurrency four, and 30-second
timeout. There is no unauthenticated IAM binding. Using the authenticated Cloud
Run proxy, the English synthetic demo returned HTTP 200 and all five
private/Google execution routes returned HTTP 403. Cloud Run logs recorded the
same results and no application startup error. The hosted `/healthz` path
returned a Google-generated HTTP 404, so hosted health is recorded as unresolved
rather than passed.

After approval of the health correction and replacement revision, Google's
documented reserved-path warning was applied: `/health` became canonical while
`/healthz` remained a local compatibility alias. The replacement `linux/amd64`
image was 44,513,334 bytes and its remote OCI index digest matched
`sha256:22fd60d9067c678e878c1d11c08de71dfa1d065f36a72062365afcc0350d2fe3`.
The executable manifest digest was
`sha256:0c5842d77ac53c90644951b60a3cfa15b4561b3ffa8a9473311f1a82777c4163`.

The second private revision became Ready, received 100% of traffic, and reported
`ContainerHealthy` after its HTTP startup probe called `/health` successfully.
Through the authenticated Cloud Run proxy, `/health` and the English synthetic
demo returned 200; all five private/Google execution routes returned 403. The
health response included every required security header. A direct
unauthenticated `/health` request returned 403, and no `allUsers` IAM binding was
present. Revision logs recorded the startup-probe 200, authenticated 200/403
results, and no application startup error.

A later read-only management audit reconfirmed Ready status and no anonymous
project IAM grant. Cloud Run reports service-level maximum one and revision-level
maximum 20; Google's current rule uses the lower value, so the effective maximum
is one. Minimum instances remains zero. The Cloud Billing Budget API is disabled;
the automatic enable prompt was declined, so no budget or API change was made.

The run reported seven non-fatal Python 3.14 deprecation warnings from external
Google SDK dependencies. They are not test failures or project-code warnings.

Expected external SDK deprecation warnings are recorded separately from test
failures. The tests do not create, modify, or delete a cloud Runtime and do not
upload media or GPX data.
