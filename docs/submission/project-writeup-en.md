# Ride Storyteller — English project write-up draft

> Local working draft. It has not been copied to Devpost. The official form and
> track wording were audited on 2026-08-17; registration and user answers remain
> pending.

## Inspiration

Motorcycle tours produce hours of beautiful footage, but the emotional shape of
the ride is often hidden inside timestamps, GPS logs, and many nearly identical
video files. Ride Storyteller explores whether an agent can turn that material
into an evidence-based travel film without inventing what the camera captured.

## What it does

Ride Storyteller converts a GPS route into explainable story events, such as a
departure, elevation change, turn, stop, and arrival. A Story Agent decides when
GPS context is insufficient and requests video evidence. A media tool resolves
the relevant source interval, Gemini analyzes only that interval, and the Story
Agent accepts, rejects, or escalates the candidate. The edit remains blocked
until every selected clip is timestamp-matched and its visual evidence is
explicitly confirmed.

The intended film is five to ten minutes long, has no voice narration, and uses
existing copyright-free music. Japanese and English presentation layers share
the same stable internal contracts.

## How we built it

- Python frozen dataclasses define validated contracts for routes, events,
  story plans, media assets, video analysis, evidence decisions, and render plans.
- Deterministic GPS parsing and event extraction remain auditable before an LLM
  is introduced.
- Google ADK runs a synthetic evidence-decision agent with Gemini 2.5 Flash.
- One synthetic-only Google Cloud Agent Platform Runtime has been verified in
  Tokyo. It cannot access GPX, coordinates, video, Box, credentials, or arbitrary
  user input.
- A Vertex AI Gemini video transport is implemented for an already-approved
  `gs://` object. It never uploads local media and constrains output with a JSON
  schema.
- The local web demonstration supports Japanese and English and exposes only
  safe synthetic or aggregate results. Its deterministic Story Plan generates
  native English titles and rationales while preserving the same internal event
  and chapter identifiers as Japanese. The synthetic Story Agent likewise
  generates native English evidence reasons for all four safe demo outcomes
  without changing its decision status. Candidate-plan review reasons are also
  generated from structural evidence fields rather than translated by sentence
  matching.
- A lean production container runs the public demo through Gunicorn
  as a non-root user. Its build context allowlists application code and excludes
  environment files, private GPS/media formats, tests, and local documentation.
  The verified `linux/amd64` image contains no Google SDK; a credential-free
  Cloud Run plan keeps resource creation and public IAM as separate approvals.
- An optional Gemini Story copy adapter rewrites only a fixed synthetic plan.
  JSON Schema and local checks preserve chapter IDs, count, and order, while the
  outbound payload excludes event IDs, coordinates, and media references.
- The FFmpeg layer produces an inspectable command plan but never executes it
  automatically.

## Safety and privacy

Real GPX logs and GoPro footage are private and excluded from the public source
tree. Real-media cloud transfer is not authorized. Local inventory and metadata
tools do not upload footage. Cloud probes use fixed synthetic inputs and retain
only safe completion metadata.

## Challenges

The main challenge is separating route evidence from visual evidence. A sharp
turn or elevation change can identify where to look, but it cannot prove that a
clip is beautiful, usable, or even available. We therefore built explicit
evidence states and fail-closed quality gates rather than allowing the agent to
silently produce an edit.

Cloud regions also have different purposes: Gemini inference uses the global
endpoint, while the deployed Agent Runtime and staging bucket are in Tokyo.
Keeping those boundaries explicit prevented configuration from being mistaken
for a successful hosted deployment.

## Accomplishments

- A deterministic GPS-to-story-to-candidate pipeline with stable identifiers.
- Explicit confirmed/rejected video-evidence transitions with attribution.
- A tested multi-clip FFmpeg plan that blocks unresolved evidence.
- Local and hosted Google ADK synthetic verification without private data.
- A bilingual UI and deterministic bilingual Story Plan with invariant
  structural identifiers, a bilingual synthetic evidence-decision Agent, and a
  terminal-free local media-inventory workflow.
- A live synthetic English Story copy response from Gemini 2.5 Flash, validated
  without retaining model text or private data.
- A locally built and health-checked public-demo container that rejects the
  private and Google execution endpoints and exposes no cloud-call controls.
- IBM Bob was used to review the codebase and identify gaps that were then
  implemented and covered by focused tests.

## What remains before submission

- Complete Devpost registration, explicit eligibility/rules agreement, and
  final IBM-track confirmation.
- Select an OSI-approved license and add it at the repository root.
- Re-capture a sanitized IBM Bob screenshot showing a project-specific finding.
- Create and validate the local inventory when the real footage is accessible.
- Obtain explicit approval before any real-video cloud transfer.
- Run real-video analysis, complete human visual review, and record the final
  English demo.
- Align and human-review the English subtitle draft against the final recording.
- Publish a reviewed public repository and hosted application without private
  data or secrets.
