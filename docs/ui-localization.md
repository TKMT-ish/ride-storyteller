# Local UI language boundary

Ride Storyteller development remains Japanese-first, while the hackathon demo
can use an English presentation layer without changing domain contracts.

## Current behavior

- `http://127.0.0.1:8765/?lang=ja` renders Japanese.
- `http://127.0.0.1:8765/?lang=en` renders English.
- `RIDE_UI_DEFAULT_LANGUAGE=ja|en` selects the local default when the query
  parameter is absent. Japanese is the safe fallback for missing or invalid
  values.
- The main demo and isolated video-inventory page preserve the selected language
  in their links.
- `/api/story-plan?lang=ja|en` generates the deterministic synthetic Story Plan
  title, chapter titles, rationales, and notice in the requested language.
- `/api/demo?scenario=...&lang=ja|en` generates the deterministic synthetic
  Story Agent label, decision reason, accepted story role, and flow steps in the
  requested language.
- `/api/candidate-edit-plan?lang=ja|en` localizes its synthetic story title,
  notice, and quality-review reasons from structural fields. Clip IDs, event
  IDs, durations, evidence states, and readiness values remain unchanged.
- The loopback-only `/api/private-gpx-summary?lang=ja|en` localizes its in-memory
  privacy notice, deterministic story title, and review reasons. Aggregate route
  and event values stay equal and coordinates remain absent from both variants.
- Translation dictionaries use the same semantic keys and are checked for
  missing or empty values at import time and in tests.

## Boundary

Stable internal values such as `accepted`, `rejected`,
`awaiting_video_evidence`, event types, and API field names remain English and
are not translated. The UI translates their surrounding labels and derives
candidate-review messages from structural review fields rather than matching
Japanese prose.

The deterministic rule-based planner receives a validated output-language enum.
Japanese and English plans select the same events and retain the same event IDs,
chapter IDs, narrative roles, durations, status values, and planning provider;
only user-facing title and rationale text changes. Tests compare both variants
to prevent translation from changing story structure.

The deterministic Story Agent applies the same rule to its evidence loop. All
four synthetic outcomes change only user-facing text; event ID, evidence flag,
asset hint, and decision status must remain equal. The main page displays these
API-generated values rather than replacing Japanese agent output in the
browser.

Candidate-review prose is derived in the API presentation layer from
`missing_duration_s`, awaiting event IDs, and rejected event IDs. The underlying
fail-closed review object remains language-neutral except for its legacy local
reason tuple, and the API never uses Japanese sentence matching to decide state.

This does not broaden GPX access: the endpoint remains unavailable in
`public_demo`, and language selection does not persist or externally transmit
the uploaded GPX.

An optional Gemini Story copy adapter separately accepts only an explicitly
synthetic Story Plan. Its schema-validated Japanese/English prose cannot change
chapter IDs, count, or order, and its outbound payload excludes event IDs,
coordinates, media references, and paths. Real route- or media-derived model
copy is still rejected and requires a separate approval and human review.

Real LLM-generated story copy still needs its own explicit output-language
input, prompt contract, structured response validation, and human review before
submission. The deterministic bilingual plan does not prove that future model
output is submission-ready in both languages.

No private GPX, video, Box content, credentials, or cloud calls are involved in
language switching.
