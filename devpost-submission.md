# Ride Storyteller — Devpost submission working draft

> Draft only. Nothing in this file has been submitted. Values marked `PENDING`
> require user input, public verification, or a later real-media gate.

## Project identity

- **Project name:** Ride Storyteller
- **Tagline:** Turn motorcycle telemetry into questions, video into evidence,
  and evidence into a travel story.
- **Submitter type:** PENDING — Individual / Team / Organization
- **Organization name:** PENDING — use `N/A` if applicable
- **Country of residence:** PENDING
- **Canadian province:** PENDING — use `N/A` if applicable
- **Government employee:** PENDING — Yes / No
- **New or existing before July 27, 2026:** New; repository history begins
  2026-08-17. User must confirm no earlier pre-contest implementation is being entered.
- **Team size:** PENDING — maximum four
- **Partner track:** IBM — recommended working selection; final user confirmation required

## Project links

- **Hosted project URL:** PENDING — the verified Cloud Run service is private
- **Public repository URL:** PENDING — no remote is configured
- **Public demo video URL:** PENDING — must be YouTube or Vimeo and no longer than three minutes
- **OSI license:** PENDING — no root license has been selected

## What it does

Ride Storyteller converts motorcycle-route GPS data into explainable candidate
story events. A Story Agent asks for video evidence when telemetry alone cannot
support a visual claim. The system resolves the relevant source interval,
constrains Gemini to structured clip analysis, and updates the story decision.
Every edit candidate remains blocked until source matching and visual evidence
are explicitly confirmed.

The final output is a five-to-ten-minute, no-narration travel film using existing
copyright-free music. The public three-minute hackathon video demonstrates the
agent workflow rather than replacing the film.

## Technologies used

- Python 3.11+
- Google ADK
- Google Cloud Agent Platform / object-style `AdkApp`
- Vertex AI Gemini 2.5 Flash
- Cloud Run and Artifact Registry
- IBM Bob during development
- FFmpeg command planning (human-reviewed; no automatic execution)
- Optional future Box MCP media search; not used as the Partner track

## Google Cloud products used

- Vertex AI / Gemini
- Google ADK
- Google Cloud Agent Platform Runtime
- Cloud Run
- Artifact Registry
- Cloud Storage staging bucket for the synthetic Runtime

The final wording must use the Devpost form's accepted product names and must not
claim real-media analysis until that gate is actually completed.

## Other tools and products

- IBM Bob
- Garmin Connect GPX export (private, local input)
- GoPro source footage (private, excluded from the public repository)
- FFmpeg / ffprobe
- Existing copyright-free music, with final track attribution still pending

## IBM track evidence

IBM Bob reviewed the codebase and identified missing ADK wiring, missing
evidence transitions, the lack of a concrete Gemini video transport, and focused
boundary-test gaps. Those findings were implemented and mapped to tests in:

- `docs/submission/ibm-bob-review-sanitized.md`
- `docs/submission/ibm-bob-evidence.md`

A sanitized IBM Bob screenshot must still be captured. Confluent is not used;
the IBM rule describes it as optional.

## Safety and privacy

Real GPX logs and GoPro footage are private. The public tree excludes those
formats, environment files, credentials, and private paths. Synthetic cloud
probes accept only fixed non-private input. The public demo container contains no
Google SDK and blocks every private or cloud-execution endpoint. Real-media cloud
transfer requires separate explicit approval.

## Findings and learnings

GPS can explain where to look, but it cannot prove what the camera saw. The
central product decision was therefore to model visual evidence as an explicit,
attributed state transition and to fail closed. Cloud deployment was also split
into a synthetic agent proof and a public-safe deterministic demo so that private
media access is never implied by a successful hosted request.

## Required form answers still pending

- participant identity, company, job title, experience levels, and primary goals;
- explicit eligibility and official-rules agreement;
- submitter/country/government/team fields above;
- whether this is the participant's first use of IBM;
- optional IBM contact-sharing consent;
- final license, repository, hosted URL, video URL, and music attribution;
- final confirmation of the IBM track and real-media demonstration claims.
