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

2026-08-30: **325 pytest tests passed**, Ruff was clean, and
`git diff --check` passed. Seven warnings came from external Google／Vertex／Agent
Platform SDK deprecations and were not project-code failures. The run did not
upload media or GPX and did not create or modify a cloud resource.

The earlier 2026-08-25 submission-preflight run passed the document, required
Devpost-draft headings, AGPL-3.0-license, private-ignore, private-file, and secret
checks and reported `offline_preparation_complete=true`. That historical offline
result does not prove the current hosted app, video, Devpost form, or real-media
quality gates.

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
subset passed **66 tests**. A local public-demo browser check with a synthetic
placeholder URL confirmed the English AGPL Source link was visible at the page
footer and the layout remained intact. The temporary server and tab were then
closed; the placeholder was not recorded as a real repository.

The public abuse-baseline update adds deterministic coverage for fixed-window
reset/retry timing, invalid limits, body-free GET enforcement, HTTP 405/413/429,
`Retry-After`, health-probe exemption, unchanged local mode, at-most-two
Gunicorn workers/threads, and commit-derived immutable image tags. Docker's
static check returned no warnings. The 44,271,065-byte `linux/amd64` image ran
healthy as user `ride`; the live container returned 200 for health and the
five-step demo, displayed the exact AGPL Source link, returned 403 for all five
private/Google routes, returned 405/413 for disallowed public request shapes,
and produced 429 with `Retry-After: 60` under a rapid local request sequence.
The temporary containers were stopped and auto-removed. This proves the local
image only; the current hosted revision predates the limiter.

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
is one. Minimum instances remains zero. On 2026-08-27, billing currency JPY, the
enabled Budget API, and exactly one project-only monthly JPY 1,000 budget were
re-read successfully. The verified thresholds are actual 50/80/100% and
forecast 100%, with default IAM recipients and Project Owners enabled, and no
Pub/Sub or Monitoring notification channel. It is not a hard spending cap.

The run reported seven non-fatal Python 3.14 deprecation warnings from external
Google SDK dependencies. They are not test failures or project-code warnings.

Expected external SDK deprecation warnings are recorded separately from test
failures. The tests do not create, modify, or delete a cloud Runtime and do not
upload media or GPX data.

On 2026-08-28, Homebrew FFmpeg 9.0.1 was installed for local-only media work.
An actual FFmpeg integration check generated a temporary synthetic 1280x720
source with audio, read its container metadata, built a one-entry clock-confirmed
catalog, timestamp-matched a synthetic GPX event, and created one 720p review
clip. The unified `app.local_pipeline` stopped at
`human_visual_evidence_review`, reported no external transfer and no coordinates
in its summary, and did not invoke Gemini, Google, Box, Maps, or Cloud Run. A
second synthetic integration run matched two candidates, generated two review
clips, recorded explicit synthetic-only evidence confirmations, and rendered a
60-second silent local draft film. Awaiting, rejected, unmatched, or incomplete
review states remain fail-closed before FFmpeg rendering.

After the user confirmed a local camera-to-GPS correction of -46,800 seconds,
the private real-media run cataloged 35/35 MP4 sources with no metadata issues.
The first run exposed a planning limitation: only 2 of 6 type-representative
events had timestamp coverage. The local pipeline was then changed to select
only timestamp-covered events, preserve one strong event per available type,
and fill the requested duration with additional covered events without making
visual claims. The second run matched 10/10 candidates, produced ten 1280x720
review clips totaling about 300 seconds, left all ten evidence decisions in
`awaiting_video_evidence`, and sent no data externally. Private file names,
timestamps, coordinates, paths, and video contents are not recorded here.

The first real-media highlights experiment analyzed 626 twelve-second windows
from 35 local LRV/MP4 pairs. A stricter second pass replaced cumulative GPS
bearing jitter with a first-half/second-half heading delta and added a visual
motion floor. It reduced eligible windows from 91 to 41 and extracted 30 local
comparison clips: three candidates for each of ten independent ranking methods.
All 30 clips passed `ffprobe`, were 1280x720, totaled about 361 seconds, and were
kept outside Git. The contact sheet still showed that several single-metric
methods retain visually mild road segments; these are experiments, not evidence
confirmations, and the result motivates human-label calibration or a separately
approved semantic-vision stage.

The full repository suite then passed **295 tests**. Ruff passed for `app` and
`tests`, and `pip check` reported no broken requirements. Seven warnings came
from external Google SDK deprecations and were not project-code failures.

On 2026-08-28, the local highlight selector was rebuilt after human review found
the v2 candidates too straight or stationary-looking. The v3h pass analyzed
1,858 local windows, retained 93 at the GPS/FFmpeg gate, obtained complete local
GPMF and Apple Vision evidence for all 93, and retained 15 at the centered-turn
and road-context gate. It produced four eight-clip review sets. Every set was
8/8 unique, had zero hard-gate violations and zero Apple utility frames. The
recommended balanced set had zero Feature Print duplicate pairs and a minimum
pair distance of 0.371. A same-scale check of the v2 30-frame set found 21
duplicate pairs and only 17 unique source intervals. Generic Apple aesthetic
mean decreased from 0.478 to 0.417, which is recorded as a real tradeoff: the
new hard gates optimize the user's turn/non-stop requirement rather than generic
blue-sky-road aesthetics. Human viewing of the eight source clips is still
required before evidence confirmation.

After these changes, the full repository suite passed **322 tests** with the
same seven external Google SDK deprecation warnings. Ruff passed for `app` and
`tests`, `pip check` found no broken requirements, `git diff --check` passed,
and Git confirmed that the real GPX, v3h contact sheet, and extracted clips are
ignored. No private-media file is tracked.

On 2026-08-30, the complete new source set was processed as 14 physical MP4
files and 10 logical recordings. Four later GoPro chapters received cumulative
duration start-time correction; no catalog issue remained. The confirmed
camera-to-GPS correction was -46,800 seconds. The source covered about 85 minutes
inside an approximately 224-minute time span, so the system recorded roughly
38% coverage and did not invent media for the gaps.

The v4a real-media run analyzed 2,385 twelve-second windows, retained 202 at the
strict GPS／FFmpeg gate, obtained complete GPMF and on-device Apple Vision
evidence for all 202, retained 21 at the final evidence gate, and extracted four
sets of eight 720p review clips. All 32 outputs existed; hashes showed 15 unique
clip contents. The run reported `external_data_sent=false` and did not confirm
visual evidence.

The first Apple Vision attempt failed only inside the restricted tool sandbox
with a local pixel-buffer creation error. `ffprobe` verified the 606 JPEG inputs.
The same three inputs succeeded with native macOS Vision access, followed by a
606-input run that calculated 183,315 Feature Print distances in about 4.48
seconds. Re-running the whole pipeline with the same native local access then
completed. This is local platform evidence, not a cloud call.

The four methods all selected eight unique windows with zero hard-gate
violations. `balanced-diverse` had the highest mean pair distance (0.554) and
covered two route buckets, but three-timepoint storyboard review still found
several gentle straight-looking roads. The result is therefore recorded as
technical E2E **PASS**, automatic candidate quality **PARTIAL**, user approval
**NOT YET**, and confirmed visual evidence **0**.

The 15 distinct outputs were reviewed at 2, 6, and 10 seconds. Eight examples
with a visible turn, merge, intersection, or nearby-vehicle change were copied
to a separate private manual-review set. They are candidate labels for the next
design iteration, not a claim that the automatic selector produced a final edit.
Real file names, paths, timestamps, coordinates, GPX contents, and frames are not
recorded here and remain outside Git.
