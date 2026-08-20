# Ride Storyteller

> Devpost working draft only. Nothing in this file has been submitted. `PENDING`
> values require participant input, public verification, or the real-media gate.

## One-line Summary

Turn motorcycle telemetry into questions, video into evidence, and evidence into
an explainable travel story.

## Problem

A motorcycle trip can produce hundreds of gigabytes of footage. The memorable
story is buried across long video files, camera timestamps, and a separate GPS
record. Manually finding the useful moments is slow, while treating GPS events as
visual facts would invent evidence that the camera may never have captured.

## Solution

Ride Storyteller converts a GPS route into explainable candidate events. A Story
Agent decides when route context is insufficient and requests video evidence. A
media-search boundary resolves the relevant source interval, Gemini analyzes only
that interval, and the Story Agent accepts, rejects, or escalates the candidate.
The edit remains blocked until every selected clip is timestamp-matched and its
visual evidence is explicitly confirmed with an attributed source.

The intended output is a five-to-ten-minute travel film with no voice narration
and existing copyright-free music. The public three-minute hackathon video will
demonstrate the functioning agent workflow rather than substitute a cinematic
trailer for the product demo.

## Why This Matters

Motorcycle riders and travel creators often have far more footage than editing
time. Ride Storyteller reduces the search space while keeping the human in control
of the final visual claim. GPS says where to look; the camera evidence determines
what can honestly enter the story.

## How We Used AI

- A Google ADK agent receives one fixed synthetic event, invokes a typed evidence
  tool, and produces a structured final response with Gemini 2.5 Flash.
- A synthetic-only Google Cloud Agent Platform Runtime in Tokyo verifies the
  hosted ADK tool/final-response loop without accepting GPX, coordinates, video,
  Box data, credentials, or arbitrary prompts.
- A Vertex AI Gemini video transport prepares schema-constrained analysis for an
  already-approved `gs://` clip. It does not upload local media.
- The Story Agent treats malformed output, missing media, model unavailability,
  and rejected visual evidence as human-review states instead of inventing a
  successful edit.
- An optional Gemini Story-copy boundary rewrites only fixed synthetic chapter
  copy while preserving chapter IDs, order, and count.

## How We Used Codex

Codex was used as the primary implementation and verification partner. It turned
the product constraints into frozen data contracts, deterministic GPS and story
planning, explicit evidence-state transitions, Google ADK and Agent Platform
adapters, the bilingual local/public-safe UI, Cloud Run deployment safeguards,
tests, and submission documentation. It also ran regression and secret/private-
media checks, exercised the browser demo, and kept the Japanese Notion design,
ADR, history, and test records synchronized with the repository.

IBM Bob was used separately during development to review the earlier codebase.
Its findings about missing ADK wiring, evidence transitions, video transport, and
boundary tests were then implemented and mapped to focused regression tests.

## Key Features

- Explainable GPS event extraction and stable story identifiers.
- Agentic evidence loop: decide, search, analyze, update, or escalate.
- Explicit `awaiting`, `confirmed`, and `rejected` evidence states with source
  attribution.
- Half-open source intervals and camera/GPS clock correction.
- Inspectable multi-clip FFmpeg command planning that never auto-executes.
- Japanese/English UI with invariant status and domain contracts.
- Synthetic-only Google cloud path separated from private local media workflows.
- Public-demo mode that removes cloud, GPX, Maps, and private-media controls.
- Root-license, secret, ignored-file, and private-media submission preflight.

## Architecture

```text
private/local route or synthetic event
  -> GPS parser and explainable event extraction
  -> Story Planner
  -> Story Agent decides whether evidence is needed
  -> media-search tool boundary
  -> Gemini video-analysis boundary
  -> attributed evidence decision
  -> candidate edit quality gate
  -> inspectable FFmpeg render plan
```

Google ADK exposes the safe synthetic decision loop as an agent/tool workflow.
The deployed Agent Platform Runtime accepts only a fixed non-private event. The
public Cloud Run image is a separate lean web demonstration and contains no
Google SDK or credentials. IBM Bob is evidenced as a development-process tool,
not falsely presented as a runtime integration.

## Testing Instructions

Python 3.11 or later is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
ruff check .
python -m tests.run_day1_checks
python -m app.submission
```

Start the credential-free public-safe demonstration:

```bash
RIDE_WEB_MODE=public_demo RIDE_UI_DEFAULT_LANGUAGE=en \
  python -m app.web.server
```

Open `http://127.0.0.1:8765/?lang=en`, run the synthetic decision scenarios,
and inspect the candidate-plan evidence gate. Public mode intentionally rejects
private GPX and Google execution endpoints. Until the participant selects an
OSI-approved root license, `python -m app.submission` intentionally reports only
the license check as incomplete.

## Public Demo Link

`PENDING` — the verified Cloud Run service remains private. Do not publish it
until IAM, abuse/cost controls, and live browser behavior have been approved and
re-verified.

## Public Repository Link

`PENDING` — no Git remote is configured. A reviewed public repository must include
all public source and instructions while excluding `.env`, credentials, GPX,
route JSON, video, private catalogs, and private file paths.

## Demo Video

`PENDING` — publish a maximum three-minute YouTube or Vimeo demonstration in
English or with complete English subtitles. The timing-matched draft is in
`docs/submission/demo-script-en.md` and `docs/submission/demo-subtitles-en.srt`.

## Screenshot Shot List

Captured local synthetic-only candidates:

1. [English home screen](docs/submission/assets/01-home-en-public-safe.jpg) with
   synthetic-data and public-safe-mode labels.
2. [Accepted evidence-decision flow](docs/submission/assets/02-agent-accepted-en.jpg),
   including the tool-call step.
3. [Missing-asset flow](docs/submission/assets/03-agent-missing-asset-en.jpg)
   showing fail-closed escalation.
4. [Candidate plan blocked by unresolved evidence](docs/submission/assets/04-candidate-evidence-blocked-en.jpg).
5. [Synthetic Story Plan](docs/submission/assets/05-story-plan-synthetic-en.jpg).

Still required as distinct evidence:

6. Synthetic-only hosted ADK result with `private_data_used=false` and no model
   response text.
7. IBM Bob product-identifying screen with a project-specific finding, sanitized
   of account data, secrets, resource names, and private paths.
8. Architecture and automated-test evidence.
9. One real source-to-confirmed-output sequence only after explicit real-media
   approval and successful human review.

## Submission Readiness Notes

- The live Devpost surfaces were rechecked on 2026-08-20.
- The official dates endpoint and legal rules now agree on
  **2026-09-09 21:00 UTC / 2026-09-10 06:00 JST**. The earlier two-day
  discrepancy is resolved; final validation should finish at least 24 hours
  before the official deadline.
- Working partner track: `IBM`; final participant confirmation is required.
- IBM Bob review transcript and finding-to-fix mapping exist. A new sanitized Bob
  screenshot is still required because earlier image paths no longer exist.
- Google Cloud synthetic agent use is verified. Real-media cloud use is not.
- Local automated checks pass, except the intentionally incomplete root-license
  gate.
- Devpost registration and explicit eligibility/rules agreement are incomplete.
- Nothing has been sent to Devpost.

## Known Limitations

- No real GPX or GoPro footage has been sent to Google; real-video end-to-end
  evidence is not yet available.
- The public Cloud Run service, public source repository, and public video do not
  yet exist.
- The FFmpeg layer creates a human-inspectable command plan but does not render
  automatically.
- Final music selection, rights attribution, English subtitle alignment, and
  visual quality review remain pending.
- Box is optional future media infrastructure and is not a valid contest track.

## TODO Official Form Fields

### Project identity

- **Project name:** Ride Storyteller
- **Tagline:** Turn motorcycle telemetry into questions, video into evidence,
  and evidence into a travel story.
- **Submitter Type:** `PENDING` — Individual / Team / Organization
- **Organization name:** `PENDING` — use `N/A` if applicable
- **Country of residence:** `PENDING`
- **Canadian province:** `PENDING` — use `N/A` if applicable
- **Government employee:** `PENDING` — Yes / No
- **New or existing before July 27, 2026:** working answer `New`; participant must
  confirm that no pre-contest implementation is being entered
- **Partner track:** working answer `IBM`; participant confirmation required
- **Team size:** `PENDING` — maximum four
- **First time using IBM tools:** `PENDING`
- **First time using other-track tools:** use the exact `N/A` choices after IBM is
  confirmed
- **Optional IBM contact sharing:** `PENDING`; never opt in without the
  participant's explicit choice

### Links and assets

- **Open-source repository URL:** `PENDING`
- **Hosted project URL:** `PENDING`
- **Public YouTube/Vimeo demo URL:** `PENDING`
- **OSI-approved root license:** `PENDING`
- **Music title, creator, license, and source URL:** `PENDING`

### Product lists

- **Google Cloud products:** Vertex AI / Gemini, Google ADK, Google Cloud Agent
  Platform Runtime, Cloud Run, Artifact Registry, and Cloud Storage staging.
- **Other tools/products:** IBM Bob, Python, Gunicorn, FFmpeg/ffprobe planning,
  Garmin Connect GPX export, and GoPro source footage.

### Registration profile and agreements

- Team preference, company, job title, AI experience, Google Cloud Agent Builder
  experience, and primary goals: `PENDING` participant answers.
- Age-of-majority, territory/sanctions, employment/conflict, and official-rules
  eligibility: `PENDING` explicit participant confirmation.
- Devpost official rules and terms: `PENDING` explicit participant agreement.
